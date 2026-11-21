"""wikilinks: directional source→target index with line numbers

Revision ID: 0009_wikilinks
Revises: 0008_saved_searches
Create Date: 2026-04-29

Adds the `wikilinks` table backing the Sprint 92 backlinks endpoint
and Day 4 graph view.

Why a new table instead of reusing file_connections:
  - file_connections is intentionally symmetric (UNIQUE on file_a_id,
    file_b_id, kind), modeling undirected topic-overlap edges.
    Wikilinks are directional — `[[A]] in B` means B → A, not the
    same as A → B.
  - Wikilinks need a `source_line` per edge; file_connections has no
    column for that. Adding one would inflate every topic-overlap row.
  - Distinct table keeps the schemas honest. Joining wikilinks +
    file_connections in the global graph view is one UNION away.

Idempotent. Safe to run on a fresh DB or one that already has 0008.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op


revision: str = "0009_wikilinks"
down_revision: Union[str, None] = "0008_saved_searches"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    raw = bind.connection.driver_connection
    raw.executescript(
        """
        CREATE TABLE IF NOT EXISTS wikilinks (
          id          INTEGER PRIMARY KEY AUTOINCREMENT,
          source_id   INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
          target_id   INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
          source_line INTEGER NOT NULL,
          scanned_at  REAL    NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_wikilinks_source
          ON wikilinks(source_id);
        CREATE INDEX IF NOT EXISTS idx_wikilinks_target
          ON wikilinks(target_id);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_wikilinks_dedup
          ON wikilinks(source_id, target_id, source_line);
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    raw = bind.connection.driver_connection
    raw.executescript(
        """
        DROP INDEX IF EXISTS idx_wikilinks_dedup;
        DROP INDEX IF EXISTS idx_wikilinks_target;
        DROP INDEX IF EXISTS idx_wikilinks_source;
        DROP TABLE IF EXISTS wikilinks;
        """
    )
