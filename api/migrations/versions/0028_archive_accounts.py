"""archive accounts — local accounts, sessions, and who owns which item

Revision ID: 0028_archive_accounts
Revises: 0027_archive_silences
Create Date: 2026-11-18

  - `account`: name, role (admin, staff, writer), scrypt password hash.
  - `session`: SHA-256 of a login token (the token itself is never stored).
  - `item_owner`: the items a writer controls, linked by an admin.

Idempotent.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0028_archive_accounts"
down_revision: Union[str, None] = "0027_archive_silences"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS account (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            name          TEXT NOT NULL UNIQUE,
            role          TEXT NOT NULL CHECK (role IN ('admin', 'staff', 'writer')),
            password_hash TEXT NOT NULL,
            created_at    TEXT NOT NULL,
            disabled_at   TEXT
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS session (
            token_sha256 TEXT PRIMARY KEY,
            account_id   INTEGER NOT NULL,
            created_at   TEXT NOT NULL
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS item_owner (
            path       TEXT NOT NULL,
            account_id INTEGER NOT NULL,
            PRIMARY KEY (path, account_id)
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS item_owner")
    op.execute("DROP TABLE IF EXISTS session")
    op.execute("DROP TABLE IF EXISTS account")
