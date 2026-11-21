"""file_connections.dismissed: formalize the lazy-added archivist column

Revision ID: 0013_file_connections_dismissed
Revises: 0012_jobs_last_heartbeat
Create Date: 2026-05-12

`services.archivist._ensure_schema` has been lazily adding `dismissed`
to `file_connections` via ALTER TABLE since the dismiss-suggestion feature
shipped. That worked for users who hit Archivist but left the column
missing for anyone who hadn't — including fresh test DBs, which is how
the Load-Bearing SQL regression slipped past PR review (the production
DB had `dismissed`, the test schema didn't).

This migration moves the schema mutation into the migration chain. Once
all DBs are at revision 0013, `_ensure_schema` is a no-op and can be
removed in a later cleanup.

Idempotent: skips the ADD COLUMN if the column already exists.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op


revision: str = "0013_file_connections_dismissed"
down_revision: Union[str, None] = "0012_jobs_last_heartbeat"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    raw = bind.connection.driver_connection
    cols = {
        row[1] for row in raw.execute("PRAGMA table_info(file_connections)").fetchall()
    }
    if "dismissed" not in cols:
        raw.executescript(
            "ALTER TABLE file_connections ADD COLUMN dismissed INTEGER DEFAULT 0;"
        )


def downgrade() -> None:
    bind = op.get_bind()
    raw = bind.connection.driver_connection
    cols = {
        row[1] for row in raw.execute("PRAGMA table_info(file_connections)").fetchall()
    }
    if "dismissed" in cols:
        try:
            raw.executescript("ALTER TABLE file_connections DROP COLUMN dismissed;")
        except Exception:
            # Older SQLite — leave the column in place; it's nullable + has a default.
            pass
