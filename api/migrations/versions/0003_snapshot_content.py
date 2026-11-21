"""snapshot content: store full md content in file_checkpoints

Revision ID: 0003_snapshot_content
Revises: 0002_jobs_table
Create Date: 2026-04-28

Until now, file_checkpoints stored only (path, sha, content_hash, saved_at)
and content was retrieved via `git show <sha>:<rel>` from the notes/ git repo.
That made history retrieval impossible for any mount without a git repo
(library/, generated/, extra libraries).

Adding a `content TEXT NOT NULL DEFAULT ''` column lets the snapshot table
serve as the single source of truth for the History panel across every
mount. Pre-existing rows (notes/) keep their git-backed retrieval path
because their `sha` still resolves; new rows include the content inline
and are retrievable purely from SQLite.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op


revision: str = "0003_snapshot_content"
down_revision: Union[str, None] = "0002_jobs_table"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Idempotent. Several test fixtures seed partial schemas and stamp at
    baseline before running upgrades — this migration must work whether
    file_checkpoints exists or not, and whether the content column is
    already present."""
    bind = op.get_bind()
    raw = bind.connection.driver_connection

    table_exists = raw.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='file_checkpoints'"
    ).fetchone()

    if not table_exists:
        # Test fixtures sometimes seed a partial schema without file_checkpoints.
        # Create it fresh, with the new column included.
        raw.executescript("""
            CREATE TABLE file_checkpoints (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                path         TEXT    NOT NULL,
                sha          TEXT    NOT NULL,
                content_hash TEXT    NOT NULL,
                content      TEXT    NOT NULL DEFAULT '',
                saved_at     REAL    NOT NULL DEFAULT (unixepoch('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_checkpoints_path
                ON file_checkpoints(path, saved_at DESC);
        """)
        return

    cols = [r[1] for r in raw.execute("PRAGMA table_info(file_checkpoints)").fetchall()]
    if "content" not in cols:
        raw.executescript(
            "ALTER TABLE file_checkpoints ADD COLUMN content TEXT NOT NULL DEFAULT '';"
        )


def downgrade() -> None:
    # SQLite ALTER TABLE DROP COLUMN requires recreation. Skip — this migration
    # only adds a default-empty column, no data is lost by leaving it.
    pass
