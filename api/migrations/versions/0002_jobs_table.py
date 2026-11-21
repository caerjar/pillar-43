"""jobs: persist BackgroundJob state in SQLite

Revision ID: 0002_jobs_table
Revises: 0001_baseline
Create Date: 2026-04-27

Replaces the in-memory `_jobs: dict` in services/job_store.py with a SQLite
table so that:
  - API restarts don't forget about in-flight jobs
  - Multiple uvicorn workers see consistent state
  - Job history survives across sessions (free "recent runs" feature)
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op


revision: str = "0002_jobs_table"
down_revision: Union[str, None] = "0001_baseline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_JOBS_SQL = """
CREATE TABLE IF NOT EXISTS jobs (
    id                TEXT    PRIMARY KEY,
    label             TEXT    NOT NULL,
    status            TEXT    NOT NULL DEFAULT 'running',
    progress          TEXT,
    started_at        REAL    NOT NULL,
    finished_at       REAL,
    cancel_requested  INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_jobs_status      ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_started_at  ON jobs(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_jobs_finished_at ON jobs(finished_at DESC);
"""


def upgrade() -> None:
    bind = op.get_bind()
    raw = bind.connection.driver_connection
    raw.executescript(_JOBS_SQL)


def downgrade() -> None:
    bind = op.get_bind()
    raw = bind.connection.driver_connection
    raw.executescript("DROP TABLE IF EXISTS jobs;")
