"""Items and their consent levels — the one place consent is decided.

Two audiences read the archive:
  - `staff`: a person at the organization. Sees items at `staff` or `model`.
  - `model`: anything that goes into a model prompt. Sees `model` only.

`private` items are visible to neither. An item with no row here (the catalog
has a file that intake never registered) is treated as private: in the org
profile the archive fails closed, never open.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import re
from datetime import datetime, timezone
from pathlib import Path

from services.archive import ledger
from services.archive.org import CONSENT_LEVELS, load_org

AUDIENCE_LEVELS: dict[str, frozenset[str]] = {
    "staff": frozenset({"staff", "model"}),
    "model": frozenset({"model"}),
}


class TombstonedError(Exception):
    """Intake refused a file whose hash was withdrawn."""


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


_YEAR_IN_PATH = re.compile(r"(?<!\d)((?:19|20)\d\d)(?!\d)")


def year_from_path(rel_path: str) -> int | None:
    m = _YEAR_IN_PATH.search(rel_path)
    return int(m.group(1)) if m else None


def is_tombstoned(conn: sqlite3.Connection, sha256: str) -> bool:
    return (
        conn.execute("SELECT 1 FROM tombstone WHERE sha256 = ?", (sha256,)).fetchone()
        is not None
    )


def register_item(
    conn: sqlite3.Connection,
    rel_path: str,
    abs_path: Path,
    *,
    by: str = "intake",
) -> dict:
    """Add (or refresh) the item row for a file. Kind and default consent come
    from org.yaml. An existing row keeps its consent: re-running intake must
    never reopen something a writer closed. Raises TombstonedError if the
    file's bytes were withdrawn, under any path."""
    sha = sha256_file(abs_path)
    if is_tombstoned(conn, sha):
        raise TombstonedError(rel_path)
    org = load_org()
    rule = org.classify(rel_path)
    kind = rule.kind if rule else "document"
    default = rule.default if rule else "private"
    existing = conn.execute(
        "SELECT id, consent FROM item WHERE path = ?", (rel_path,)
    ).fetchone()
    with conn:
        if existing:
            conn.execute(
                "UPDATE item SET sha256 = ?, kind = ? WHERE id = ?",
                (sha, kind, existing[0]),
            )
            return {
                "path": rel_path,
                "sha256": sha,
                "kind": kind,
                "consent": existing[1],
                "new": False,
            }
        conn.execute(
            "INSERT INTO item (path, sha256, kind, consent, consent_by, consent_at, year) VALUES (?,?,?,?,?,?,?)",
            (rel_path, sha, kind, default, by, _now(), year_from_path(rel_path)),
        )
    seq = ledger.append(
        conn,
        "intake",
        by,
        rel_path,
        {"sha256": sha, "kind": kind, "consent": default},
    )
    with conn:
        conn.execute("UPDATE item SET ledger_seq = ? WHERE path = ?", (seq, rel_path))
    return {
        "path": rel_path,
        "sha256": sha,
        "kind": kind,
        "consent": default,
        "new": True,
    }


def register_virtual(
    conn: sqlite3.Connection,
    rel_path: str,
    sha256: str,
    kind: str,
    *,
    people: list[dict] | None = None,
    consent: str = "private",
    by: str = "intake",
) -> dict | None:
    """An item that is part of a file, not a file: one email in a mailbox, one
    attachment. `rel_path` is the container's path plus a `#fragment`
    (services/archive/mail.py). Same rules as `register_item`: an existing row
    keeps its consent; a withdrawn hash is refused (returns None)."""
    if is_tombstoned(conn, sha256):
        return None
    pj = json.dumps(people or [])
    existing = conn.execute(
        "SELECT id, consent FROM item WHERE path = ?", (rel_path,)
    ).fetchone()
    with conn:
        if existing:
            conn.execute(
                "UPDATE item SET sha256 = ?, kind = ?, people = ? WHERE id = ?",
                (sha256, kind, pj, existing[0]),
            )
            return {"path": rel_path, "consent": existing[1], "new": False}
        conn.execute(
            "INSERT INTO item (path, sha256, kind, people, consent, consent_by, consent_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (rel_path, sha256, kind, pj, consent, by, _now()),
        )
    return {"path": rel_path, "consent": consent, "new": True}


class ItemWithdrawn(Exception):
    """The item was withdrawn by its writer. Withdrawal is final: consent on it
    cannot be changed, so its bytes are never served again."""


def set_consent(
    conn: sqlite3.Connection, rel_path: str, level: str, *, by: str
) -> None:
    if level not in CONSENT_LEVELS:
        raise ValueError(f"unknown consent level {level!r}")
    old = conn.execute(
        "SELECT consent, withdrawn_at FROM item WHERE path = ?", (rel_path,)
    ).fetchone()
    if old is not None and old[1] is not None:
        raise ItemWithdrawn(rel_path)
    with conn:
        cur = conn.execute(
            "UPDATE item SET consent = ?, consent_by = ?, consent_at = ? WHERE path = ?",
            (level, by, _now(), rel_path),
        )
    if cur.rowcount == 0:
        raise KeyError(rel_path)
    ledger.append(
        conn, "consent", by, rel_path, {"from": old[0] if old else None, "to": level}
    )


def item_meta(conn: sqlite3.Connection, rel_paths: list[str]) -> dict[str, dict]:
    if not rel_paths:
        return {}
    ph = ",".join("?" * len(rel_paths))
    rows = conn.execute(
        f"SELECT path, sha256, kind, consent, people, title_isbn, labels FROM item WHERE path IN ({ph})",
        rel_paths,
    ).fetchall()
    return {
        r[0]: {
            "sha256": r[1],
            "kind": r[2],
            "consent": r[3],
            "people": json.loads(r[4] or "[]"),
            "title_isbn": r[5],
            "labels": json.loads(r[6] or "[]"),
        }
        for r in rows
    }


def allowed_paths(
    conn: sqlite3.Connection,
    rel_paths: list[str],
    audience: str,
    purpose: str | None = None,
    role: str | None = None,
) -> set[str]:
    """The subset of `rel_paths` the audience may see. Unknown audience → none.

    For the `model` audience the item's labels apply too: the AI may use it
    only for a purpose every label permits (default purpose: `ask`)."""
    levels = AUDIENCE_LEVELS.get(audience, frozenset())
    meta = item_meta(conn, rel_paths)
    ok = {p for p, m in meta.items() if m["consent"] in levels}
    if audience == "model":
        from services.archive.labels import labels_permit

        ok = {p for p in ok if labels_permit(meta[p]["labels"], purpose or "ask", role)}
    return ok


def open_counts(conn: sqlite3.Connection) -> dict[str, int]:
    """Items the AI may read for a question, by kind, most first. Withdrawn
    items are not counted."""
    rows = conn.execute(
        "SELECT path, kind FROM item WHERE withdrawn_at IS NULL"
    ).fetchall()
    ok = allowed_paths(conn, [r[0] for r in rows], "model")
    out: dict[str, int] = {}
    for path, kind in rows:
        if path in ok:
            out[kind or "document"] = out.get(kind or "document", 0) + 1
    return dict(sorted(out.items(), key=lambda kv: (-kv[1], kv[0])))
