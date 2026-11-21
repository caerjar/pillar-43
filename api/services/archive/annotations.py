"""Annotations: the right of reply.

A person (a writer, a translator, an estate) attaches a note to an item or to
one passage. It is shown beside the passage in every answer that retrieves it,
signed and dated, so a reading of a work is never presented without the reply
of the person it concerns. Append-only: retract, never edit. Never sent to a
model.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from services.archive import ledger


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def add_annotation(
    conn: sqlite3.Connection,
    path: str,
    body: str,
    *,
    by: str,
    ordinal: int | None = None,
    role: str | None = None,
) -> int:
    body = body.strip()
    if not body:
        raise ValueError("annotation is empty")
    if conn.execute("SELECT 1 FROM item WHERE path = ?", (path,)).fetchone() is None:
        raise KeyError(path)
    with conn:
        cur = conn.execute(
            "INSERT INTO annotation (path, ordinal, body, author, role, at) VALUES (?,?,?,?,?,?)",
            (path, ordinal, body, by, role, _now()),
        )
    aid = int(cur.lastrowid or 0)
    ledger.append(
        conn,
        "annotation",
        by,
        path,
        {"annotation_id": aid, "ordinal": ordinal, "role": role},
    )
    return aid


def retract_annotation(
    conn: sqlite3.Connection, annotation_id: int, *, by: str
) -> None:
    with conn:
        cur = conn.execute(
            "UPDATE annotation SET retracted_at = ? WHERE id = ? AND retracted_at IS NULL",
            (_now(), annotation_id),
        )
    if cur.rowcount == 0:
        raise KeyError(annotation_id)
    ledger.append(conn, "annotation_retract", by, "", {"annotation_id": annotation_id})


def list_annotations(conn: sqlite3.Connection, path: str) -> list[dict]:
    rows = conn.execute(
        "SELECT id, path, ordinal, body, author, role, at FROM annotation "
        "WHERE path = ? AND retracted_at IS NULL ORDER BY id",
        (path,),
    )
    return [
        {
            "id": r[0],
            "path": r[1],
            "ordinal": r[2],
            "body": r[3],
            "by": r[4],
            "role": r[5],
            "at": r[6],
        }
        for r in rows
    ]


def attach_to_passages(conn: sqlite3.Connection, passages: list[dict]) -> None:
    """Add `annotations` to each passage dict: notes on its item as a whole and
    notes on its own ordinal."""
    for p in passages:
        p["annotations"] = [
            a
            for a in list_annotations(conn, p["path"])
            if a["ordinal"] is None or a["ordinal"] == p.get("ordinal")
        ]
