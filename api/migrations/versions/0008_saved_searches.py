"""saved searches: per-vault named queries

Revision ID: 0008_saved_searches
Revises: 0007_counter_archive_phase_3
Create Date: 2026-04-29

Adds the `saved_searches` table backing the Sprint 92 saved-searches
surface. Single table, no relations — saved searches are per-vault and
self-contained. UPSERT semantics on `name` (UNIQUE index) so the user
can rename via overwrite.

Idempotent. Safe to run on a fresh DB or one that already has 0007.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op


revision: str = "0008_saved_searches"
down_revision: Union[str, None] = "0007_counter_archive_phase_3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    raw = bind.connection.driver_connection
    raw.executescript(
        """
        CREATE TABLE IF NOT EXISTS saved_searches (
          id            INTEGER PRIMARY KEY AUTOINCREMENT,
          name          TEXT    NOT NULL,
          query         TEXT    NOT NULL,
          scope         TEXT    NOT NULL DEFAULT 'all',
          ai            INTEGER NOT NULL DEFAULT 0,
          semantic      INTEGER NOT NULL DEFAULT 0,
          created_at    REAL    NOT NULL,
          last_used_at  REAL,
          use_count     INTEGER NOT NULL DEFAULT 0
        );

        CREATE UNIQUE INDEX IF NOT EXISTS idx_saved_searches_name
          ON saved_searches(name);
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    raw = bind.connection.driver_connection
    raw.executescript(
        """
        DROP INDEX IF EXISTS idx_saved_searches_name;
        DROP TABLE IF EXISTS saved_searches;
        """
    )
