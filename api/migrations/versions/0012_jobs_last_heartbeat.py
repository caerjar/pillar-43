"""jobs.last_heartbeat: per-job liveness signal

Revision ID: 0012_jobs_last_heartbeat
Revises: 0011_agent_harness
Create Date: 2026-05-10

Adds a nullable REAL `last_heartbeat` column. Long-running endpoints
update it on every progress message; cleanup_old_jobs uses it to detect
wedged catalog jobs within ~2 minutes instead of the 15-minute
started_at threshold.

Idempotent: skips the ADD COLUMN if the column already exists.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op


revision: str = "0012_jobs_last_heartbeat"
down_revision: Union[str, None] = "0011_agent_harness"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    raw = bind.connection.driver_connection
    cols = {row[1] for row in raw.execute("PRAGMA table_info(jobs)").fetchall()}
    if "last_heartbeat" not in cols:
        raw.executescript("ALTER TABLE jobs ADD COLUMN last_heartbeat REAL;")


def downgrade() -> None:
    # SQLite ALTER TABLE DROP COLUMN exists since 3.35 (2021). Production
    # containers ship a recent SQLite, but guard anyway.
    bind = op.get_bind()
    raw = bind.connection.driver_connection
    cols = {row[1] for row in raw.execute("PRAGMA table_info(jobs)").fetchall()}
    if "last_heartbeat" in cols:
        try:
            raw.executescript("ALTER TABLE jobs DROP COLUMN last_heartbeat;")
        except Exception:
            # Older SQLite — leave the column in place; it's nullable so harmless.
            pass
