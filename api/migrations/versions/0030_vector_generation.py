"""vector generation — a counter the API process can poll to see CLI writes

Revision ID: 0030_vector_generation
Revises: 0029_archive_correspondents
Create Date: 2026-11-21

`vector_store` caches the whole vector matrix in memory. Index, intake and
withdraw run as a second process (`archive_cli.py`), so the API process never
saw their writes until restart. `vector_generation` is one row holding a
counter; triggers bump it in the same transaction as every insert, update or
delete on `chunk_vectors` (and when a file's path or mount changes, since the
cache carries those). Triggers rather than Python calls so no writer, including
the raw SQL in `catalog/forget.py`, can forget to bump it.

Idempotent.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0030_vector_generation"
down_revision: Union[str, None] = "0029_archive_correspondents"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_BUMP = "UPDATE vector_generation SET generation = generation + 1 WHERE id = 1"


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS vector_generation (
            id         INTEGER PRIMARY KEY CHECK (id = 1),
            generation INTEGER NOT NULL DEFAULT 0
        )
    """)
    op.execute("INSERT OR IGNORE INTO vector_generation (id, generation) VALUES (1, 0)")
    for name, event in (
        ("vector_generation_ins", "AFTER INSERT ON chunk_vectors"),
        ("vector_generation_upd", "AFTER UPDATE ON chunk_vectors"),
        ("vector_generation_del", "AFTER DELETE ON chunk_vectors"),
        ("vector_generation_file", "AFTER UPDATE OF rel_path, mount ON files"),
    ):
        op.execute(f"CREATE TRIGGER IF NOT EXISTS {name} {event} BEGIN {_BUMP}; END")


def downgrade() -> None:
    for name in (
        "vector_generation_ins",
        "vector_generation_upd",
        "vector_generation_del",
        "vector_generation_file",
    ):
        op.execute(f"DROP TRIGGER IF EXISTS {name}")
    op.execute("DROP TABLE IF EXISTS vector_generation")
