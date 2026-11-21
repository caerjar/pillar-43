"""answer passages — which passage each stored citation number meant

Revision ID: 0031_answer_passage
Revises: 0030_vector_generation
Create Date: 2026-11-21

`answer.answer_json` stores `cites` and `quote.passage` as the numbers 1..n of
the passage list the model was shown, and `answer_citation` keeps only the item
path and sha256. The numbered list itself was never kept, so a stored quote
could not be walked back to the document it came from.

`answer_passage`: one row per passage in the prompt of one answer — its
number, the item path and sha256 the text came from, the chunk it was cut from
(id, ordinal, and the character span in the item's extracted text), and the
sha256 of the passage text the model read. No passage text is stored; the
text stays in the item, where consent and withdrawal govern it.

Idempotent.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0031_answer_passage"
down_revision: Union[str, None] = "0030_vector_generation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS answer_passage (
            answer_id      INTEGER NOT NULL,
            n              INTEGER NOT NULL,
            path           TEXT    NOT NULL,
            sha256         TEXT    NOT NULL DEFAULT '',
            chunk_id       INTEGER,
            ordinal        INTEGER,
            char_start     INTEGER,
            char_end       INTEGER,
            passage_sha256 TEXT    NOT NULL DEFAULT '',
            PRIMARY KEY (answer_id, n)
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_answer_passage_path ON answer_passage(path)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS answer_passage")
