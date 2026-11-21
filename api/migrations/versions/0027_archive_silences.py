"""archive silences — item.year, and the silences logged with each answer

Revision ID: 0027_archive_silences
Revises: 0026_archive_annotations
Create Date: 2026-11-18

  - `item.year`: the year the item is from (read from its path at intake, 19xx
    or 20xx; a person can set it). NULL when unknown. Years in a question's
    scope with no item are reported as silences.
  - `answer.silences`: the silences computed for that answer, as JSON, so the
    Gaps view can aggregate them across questions.

Idempotent.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0027_archive_silences"
down_revision: Union[str, None] = "0026_archive_annotations"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _cols(table: str) -> set[str]:
    conn = op.get_bind()
    return {
        r[1] for r in conn.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()
    }


def upgrade() -> None:
    if "year" not in _cols("item"):
        op.execute("ALTER TABLE item ADD COLUMN year INTEGER")
    if "silences" not in _cols("answer"):
        op.execute("ALTER TABLE answer ADD COLUMN silences TEXT")


def downgrade() -> None:
    pass  # SQLite cannot drop a column portably; the columns are harmless
