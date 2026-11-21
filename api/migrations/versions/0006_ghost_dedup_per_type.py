"""ghost dedup: include erasure_type in the unique index

Revision ID: 0006_ghost_dedup_per_type
Revises: 0005_counter_archive_phase_2
Create Date: 2026-04-29

Migration 0005's dedup index `UNIQUE(source_path, source_line,
paragraph_hash)` is too strict. A single paragraph legitimately produces
multiple ghosts of DIFFERENT erasure_types — e.g., "Today she came back.
We did not speak about [redacted]" has both `unnamed_actor` and
`redacted`. The original index blocked the second insert.

This migration drops the original unique index and rebuilds it with
erasure_type included. Behavior preserved: a re-scan of an unchanged
paragraph still gets its same-typed ghosts blocked (the rerun-skip
invariant Pass 6 depends on).

Idempotent. Safe to run on a fresh DB or one that already has 0005.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op


revision: str = "0006_ghost_dedup_per_type"
down_revision: Union[str, None] = "0005_counter_archive_phase_2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    raw = bind.connection.driver_connection
    raw.executescript(
        """
        DROP INDEX IF EXISTS idx_ca_ghosts_dedup;
        CREATE UNIQUE INDEX IF NOT EXISTS idx_ca_ghosts_dedup
          ON ca_ghosts(source_path, source_line, paragraph_hash, erasure_type);
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    raw = bind.connection.driver_connection
    raw.executescript(
        """
        DROP INDEX IF EXISTS idx_ca_ghosts_dedup;
        CREATE UNIQUE INDEX IF NOT EXISTS idx_ca_ghosts_dedup
          ON ca_ghosts(source_path, source_line, paragraph_hash);
        """
    )
