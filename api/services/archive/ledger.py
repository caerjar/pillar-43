"""The ledger: an append-only, hash-chained record, in the archive's DB.

Each line is {seq, at, kind, actor, subject, data}. Its hash is
sha256(canonical JSON of those fields + the previous line's hash); the first
line chains to GENESIS. Editing a line changes its hash and so breaks the next
line's `prev_hash`; deleting a line breaks the line after it. `verify` walks
the chain and names the first line that does not hold.

Kinds: intake, consent, withdraw, model_call.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone

GENESIS = "0" * 64


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _hash(
    seq: int, at: str, kind: str, actor: str, subject: str, data: str, prev: str
) -> str:
    body = json.dumps(
        [seq, at, kind, actor, subject, data, prev],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def append(
    conn: sqlite3.Connection,
    kind: str,
    actor: str,
    subject: str = "",
    data: dict | None = None,
) -> int:
    """Add a line; returns its seq. Writers serialise on the DB write lock."""
    payload = json.dumps(data or {}, ensure_ascii=False, sort_keys=True)
    for attempt in range(5):
        last = conn.execute(
            "SELECT seq, hash FROM ledger ORDER BY seq DESC LIMIT 1"
        ).fetchone()
        seq = (last[0] + 1) if last else 1
        prev = last[1] if last else GENESIS
        at = _now()
        h = _hash(seq, at, kind, actor, subject, payload, prev)
        try:
            with conn:
                conn.execute(
                    "INSERT INTO ledger (seq, at, kind, actor, subject, data, prev_hash, hash) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (seq, at, kind, actor, subject, payload, prev, h),
                )
            return seq
        except sqlite3.IntegrityError:
            # another writer took this seq between our read and write
            if attempt == 4:
                raise
    raise RuntimeError("unreachable")


def verify(conn: sqlite3.Connection) -> dict:
    """Walk the chain. `first_bad_seq` is the first line that does not hold."""
    prev = GENESIS
    expected = 1
    n = 0
    for seq, at, kind, actor, subject, data, prev_hash, h in conn.execute(
        "SELECT seq, at, kind, actor, subject, data, prev_hash, hash "
        "FROM ledger ORDER BY seq"
    ):
        if (
            seq != expected
            or prev_hash != prev
            or h != _hash(seq, at, kind, actor, subject, data, prev_hash)
        ):
            return {"ok": False, "entries": n, "first_bad_seq": seq}
        prev = h
        expected = seq + 1
        n += 1
    return {"ok": True, "entries": n, "first_bad_seq": None}


def entry(conn: sqlite3.Connection, seq: int) -> dict | None:
    r = conn.execute(
        "SELECT seq, at, kind, actor, subject, data, prev_hash, hash FROM ledger WHERE seq=?",
        (seq,),
    ).fetchone()
    if r is None:
        return None
    return {
        "seq": r[0],
        "at": r[1],
        "kind": r[2],
        "actor": r[3],
        "subject": r[4],
        "data": json.loads(r[5]),
        "prev_hash": r[6],
        "hash": r[7],
    }


def reads_by_sha(conn: sqlite3.Connection) -> dict[str, int]:
    """How many model calls had each item's bytes in the prompt."""
    rows = conn.execute(
        "SELECT json_extract(j.value, '$.sha256'), COUNT(DISTINCT l.seq) "
        "FROM ledger l, json_each(l.data, '$.items') j "
        "WHERE l.kind = 'model_call' GROUP BY 1"
    ).fetchall()
    return {r[0]: r[1] for r in rows if r[0]}
