"""hot-query indexes: ensure files.cataloged_at, tasks.due_date, tasks.completed_at

Revision ID: 0004_hot_query_indexes
Revises: 0003_snapshot_content
Create Date: 2026-04-28

The baseline schema (0001) declares these three indexes via
`CREATE INDEX IF NOT EXISTS`, so any catalog DB initialized from the
canonical baseline already has them. Older databases initialized via
the legacy `_migrate_*` helpers (pre-Alembic) may be missing them.
This migration is idempotent and safe to run on any prior state.

Indexes added:
  idx_files_cataloged_at   — speeds the `ORDER BY cataloged_at` sort
                              used by the AI-run summarization scheduler.
  idx_tasks_due_date       — speeds TaskBoard's "due soon" query.
  idx_tasks_completed_at   — speeds TaskBoard's "completed within N days"
                              filter and dashboard rollups.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op


revision: str = "0004_hot_query_indexes"
down_revision: Union[str, None] = "0003_snapshot_content"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(raw, name: str) -> bool:
    row = raw.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone()
    return row is not None


def upgrade() -> None:
    """Idempotent. CREATE INDEX IF NOT EXISTS is safe even if the index
    already exists; we still gate on table presence so test fixtures that
    seed a partial schema don't fail with `no such table`."""
    bind = op.get_bind()
    raw = bind.connection.driver_connection

    statements: list[str] = []
    if _table_exists(raw, "files"):
        statements.append(
            "CREATE INDEX IF NOT EXISTS idx_files_cataloged_at ON files(cataloged_at);"
        )
    if _table_exists(raw, "tasks"):
        statements.append(
            "CREATE INDEX IF NOT EXISTS idx_tasks_due_date ON tasks(due_date);"
        )
        statements.append(
            "CREATE INDEX IF NOT EXISTS idx_tasks_completed_at ON tasks(completed_at);"
        )

    if statements:
        raw.executescript("\n".join(statements))


def downgrade() -> None:
    bind = op.get_bind()
    raw = bind.connection.driver_connection
    raw.executescript(
        "DROP INDEX IF EXISTS idx_files_cataloged_at;\n"
        "DROP INDEX IF EXISTS idx_tasks_due_date;\n"
        "DROP INDEX IF EXISTS idx_tasks_completed_at;\n"
    )
