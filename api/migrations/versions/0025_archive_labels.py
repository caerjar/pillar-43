"""archive labels — item.labels, a JSON list of label ids from org.yaml

Revision ID: 0025_archive_labels
Revises: 0024_archive_ledger
Create Date: 2026-11-18

Idempotent.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0025_archive_labels"
down_revision: Union[str, None] = "0024_archive_ledger"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    cols = {r[1] for r in conn.exec_driver_sql("PRAGMA table_info(item)").fetchall()}
    if "labels" not in cols:
        op.execute("ALTER TABLE item ADD COLUMN labels TEXT NOT NULL DEFAULT '[]'")


def downgrade() -> None:
    pass  # SQLite cannot drop a column portably; the column is harmless
