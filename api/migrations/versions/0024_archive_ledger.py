"""archive ledger — an append-only, hash-chained record of what happened

Revision ID: 0024_archive_ledger
Revises: 0023_archive_withdraw
Create Date: 2026-11-18

One line per intake, consent change, withdrawal and model call. Each line's
`hash` covers its own fields and the previous line's hash, so an edit or a
deleted line breaks every hash after it (`services/archive/ledger.verify`).
`item.ledger_seq` (from 0022) points at the item's intake line.

Idempotent.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0024_archive_ledger"
down_revision: Union[str, None] = "0023_archive_withdraw"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS ledger (
            seq       INTEGER PRIMARY KEY,
            at        TEXT NOT NULL,
            kind      TEXT NOT NULL,
            actor     TEXT NOT NULL,
            subject   TEXT NOT NULL DEFAULT '',
            data      TEXT NOT NULL DEFAULT '{}',
            prev_hash TEXT NOT NULL,
            hash      TEXT NOT NULL
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_ledger_kind ON ledger(kind)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ledger")
