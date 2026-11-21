"""counterfactuals: ca_potentials table for Azoulay-grounded drafts

Revision ID: 0010_counterfactuals
Revises: 0009_wikilinks
Create Date: 2026-04-30

Sprint 93. The Counterfactual engine drafts potential notes — records
that COULD have existed in the archive if its silences had been
written. Grounded in Ariella Azoulay's "potential history": not
biography, not user-mimicking — third-person scholarly remove.

Schema decisions worth flagging:

  - source_gap_id is FK to ca_gaps but ca_gaps is truncated every
    catalog run. We denormalize source_gap_type + source_evidence so
    the potential stays intelligible after the prompting gap row
    disappears. The FK is for joinability when fresh, not durability.

  - draft_path is UNIQUE. Slugs collide; the writer increments
    (<slug>-2.md, etc.) and retries on UNIQUE violation. The unique
    index makes collision detection a SQL constraint, not a race.

  - promoted_at IS NULL while the draft sits in
    notes/counter-archive/potentials/. On user-promote: file moves
    out, frontmatter rewrites (potential: false + promoted: true),
    promoted_at + promoted_path persist the trail.

  - Partial index on unpromoted rows because that's the hot query
    (UI lists "drafts awaiting decision"); promoted ones are history.

Idempotent. Safe to run on a fresh DB or one that already has 0009.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op


revision: str = "0010_counterfactuals"
down_revision: Union[str, None] = "0009_wikilinks"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    raw = bind.connection.driver_connection
    raw.executescript(
        """
        CREATE TABLE IF NOT EXISTS ca_potentials (
          id              INTEGER PRIMARY KEY AUTOINCREMENT,
          source_gap_id   INTEGER REFERENCES ca_gaps(id) ON DELETE SET NULL,
          source_gap_type TEXT    NOT NULL,
          source_evidence TEXT    NOT NULL,
          draft_path      TEXT    NOT NULL UNIQUE,
          draft_text      TEXT    NOT NULL,
          prompt_version  TEXT    NOT NULL,
          model           TEXT    NOT NULL,
          generated_at    REAL    NOT NULL,
          promoted_at     REAL,
          promoted_path   TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_ca_potentials_gap
          ON ca_potentials(source_gap_id);
        CREATE INDEX IF NOT EXISTS idx_ca_potentials_unpromoted
          ON ca_potentials(generated_at) WHERE promoted_at IS NULL;
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    raw = bind.connection.driver_connection
    raw.executescript(
        """
        DROP INDEX IF EXISTS idx_ca_potentials_unpromoted;
        DROP INDEX IF EXISTS idx_ca_potentials_gap;
        DROP TABLE IF EXISTS ca_potentials;
        """
    )
