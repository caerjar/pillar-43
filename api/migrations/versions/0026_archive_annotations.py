"""archive annotations — the right of reply

Revision ID: 0026_archive_annotations
Revises: 0025_archive_labels
Create Date: 2026-11-18

A signed, dated note attached to an item (`ordinal` NULL) or to one passage of
it (`ordinal` = the chunk's ordinal). Append-only: a note is retracted
(`retracted_at`), never edited or deleted. The model never reads these.

Idempotent.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0026_archive_annotations"
down_revision: Union[str, None] = "0025_archive_labels"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS annotation (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            path         TEXT NOT NULL,
            ordinal      INTEGER,
            body         TEXT NOT NULL,
            author       TEXT NOT NULL,
            role         TEXT,
            at           TEXT NOT NULL,
            retracted_at TEXT
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_annotation_path ON annotation(path)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS annotation")
