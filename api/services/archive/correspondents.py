"""A correspondent's consent, by email address, applied to their messages.

Consent is still per item (`item.consent`, decided in `items.py`). This module
is the bulk handle on it: recording consent for an address sets every message
*sent by* that address (and its attachments), and is remembered in
`correspondent` so a message ingested later starts at the same level.
Withdrawing an address withdraws each of their messages through the ordinary
item withdrawal (tombstone, close, forget), so intake refuses them again.

Only the sender is the consenting party. A recipient's consent is not implied
by a message addressed to them, and a reply that quotes someone else is still
the sender's message.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from services.archive import ledger
from services.archive.items import ItemWithdrawn, set_consent
from services.archive.org import CONSENT_LEVELS


def norm(address: str) -> str:
    return address.strip().lower()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sender_of(people_json: str | None) -> str | None:
    try:
        people = json.loads(people_json or "[]")
    except json.JSONDecodeError:
        return None
    for p in people:
        if isinstance(p, dict) and p.get("sender") and p.get("address"):
            return norm(p["address"])
    return None


def consent_for(conn: sqlite3.Connection, address: str) -> str | None:
    """The level recorded for `address`, or None (never recorded, or withdrawn)."""
    row = conn.execute(
        "SELECT consent FROM correspondent WHERE address = ? AND withdrawn_at IS NULL",
        (norm(address),),
    ).fetchone()
    return row[0] if row else None


def messages_from(conn: sqlite3.Connection, address: str) -> list[str]:
    a = norm(address)
    return sorted(
        p
        for p, raw in conn.execute(
            "SELECT path, people FROM item WHERE kind = 'email' AND withdrawn_at IS NULL"
        ).fetchall()
        if sender_of(raw) == a
    )


def _attachments(conn: sqlite3.Connection, message: str) -> list[tuple[str, str]]:
    return [
        (p, c)
        for p, c in conn.execute(
            "SELECT path, consent FROM item "
            "WHERE kind = 'attachment' AND withdrawn_at IS NULL"
        ).fetchall()
        if p.startswith(message + "/")
    ]


def record_consent(
    conn: sqlite3.Connection, address: str, level: str, *, by: str
) -> list[str]:
    """Set `level` on every message from `address`, and on the attachments that
    still carry their message's old level (one someone set separately keeps its
    own). Returns the message paths."""
    if level not in CONSENT_LEVELS:
        raise ValueError(f"unknown consent level {level!r}")
    a = norm(address)
    msgs = messages_from(conn, a)
    for m in msgs:
        old = conn.execute("SELECT consent FROM item WHERE path = ?", (m,)).fetchone()[
            0
        ]
        kids = [p for p, c in _attachments(conn, m) if c == old]
        for p in (m, *kids):
            try:
                set_consent(conn, p, level, by=by)
            except ItemWithdrawn:
                continue  # withdrawal is final; a bulk rule does not reopen it
    with conn:
        conn.execute(
            "INSERT INTO correspondent (address, consent, consent_by, consent_at, withdrawn_at) "
            "VALUES (?,?,?,?,NULL) ON CONFLICT(address) DO UPDATE SET "
            "consent=excluded.consent, consent_by=excluded.consent_by, "
            "consent_at=excluded.consent_at, withdrawn_at=NULL",
            (a, level, by, _now()),
        )
    ledger.append(
        conn, "consent", by, f"person:{a}", {"to": level, "messages": len(msgs)}
    )
    return msgs


def withdraw_person(conn: sqlite3.Connection, address: str, *, by: str) -> dict:
    """Withdraw every message from `address` and its attachments, and forget
    the recorded consent."""
    from services.archive.withdraw import withdraw

    a = norm(address)
    msgs = messages_from(conn, a)
    for m in msgs:
        for kid, _c in _attachments(conn, m):
            withdraw(conn, kid, by=by)
        withdraw(conn, m, by=by)
    at = _now()
    with conn:
        conn.execute(
            "INSERT INTO correspondent (address, consent, consent_by, consent_at, withdrawn_at) "
            "VALUES (?,'private',?,?,?) ON CONFLICT(address) DO UPDATE SET "
            "consent='private', consent_by=excluded.consent_by, "
            "consent_at=excluded.consent_at, withdrawn_at=excluded.withdrawn_at",
            (a, by, at, at),
        )
    return {"address": a, "withdrawn": len(msgs), "paths": msgs}
