"""Withdraw an item: the writer takes it back.

One transaction-shaped sequence: tombstone the bytes' hash (so intake refuses
them under any path), close the item (consent -> private, `withdrawn_at`),
and forget the catalog rows, chunks and vectors so neither semantic nor
lexical search can find it. Every other item with the same bytes goes too.
Earlier answers that cited it are reported, and flagged by `answer_view`.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from services.archive import ledger
from services.catalog.forget import forget_file


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def withdraw(conn: sqlite3.Connection, rel_path: str, *, by: str) -> dict:
    """Raises KeyError if `rel_path` is not an item. Idempotent."""
    row = conn.execute("SELECT sha256 FROM item WHERE path = ?", (rel_path,)).fetchone()
    if row is None:
        raise KeyError(rel_path)
    sha = row[0]
    paths = [
        r[0] for r in conn.execute("SELECT path FROM item WHERE sha256 = ?", (sha,))
    ]
    at = _now()
    with conn:
        conn.execute(
            "INSERT OR IGNORE INTO tombstone (sha256, withdrawn_by, at) VALUES (?,?,?)",
            (sha, by, at),
        )
        conn.execute(
            "UPDATE item SET consent='private', consent_by=?, consent_at=?, "
            "withdrawn_at=COALESCE(withdrawn_at, ?) WHERE sha256 = ?",
            (by, at, at, sha),
        )
    for p in paths:
        forget_file(conn, p)
    ledger.append(conn, "withdraw", by, rel_path, {"sha256": sha, "paths": paths})
    marked = [
        r[0]
        for r in conn.execute(
            "SELECT DISTINCT answer_id FROM answer_citation WHERE sha256 = ? ORDER BY 1",
            (sha,),
        )
    ]
    return {"path": rel_path, "sha256": sha, "paths": paths, "answers_marked": marked}


def forget_withdrawn(conn: sqlite3.Connection) -> int:
    """Drop catalog rows of withdrawn items that a re-scan brought back."""
    n = 0
    for (p,) in conn.execute(
        "SELECT path FROM item WHERE withdrawn_at IS NOT NULL"
    ).fetchall():
        n += forget_file(conn, p)
    return n
