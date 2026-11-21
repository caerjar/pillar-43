"""archive correspondents — a person's recorded consent, by address

Revision ID: 0029_archive_correspondents
Revises: 0028_archive_accounts
Create Date: 2026-11-19

`correspondent`: one row per email address that has had consent recorded.
Messages are still items with their own consent; this row is what a message
*ingested later* inherits, and what a withdrawal remembers. `consent` is the
level recorded; `withdrawn_at` is set when the person withdrew everything.

Idempotent.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0029_archive_correspondents"
down_revision: Union[str, None] = "0028_archive_accounts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS correspondent (
            address      TEXT PRIMARY KEY,
            consent      TEXT NOT NULL DEFAULT 'private'
                         CHECK (consent IN ('private', 'staff', 'model')),
            consent_by   TEXT,
            consent_at   TEXT,
            withdrawn_at TEXT
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS correspondent")
