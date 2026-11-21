"""archive withdraw — item.withdrawn_at, and a record of every answer

Revision ID: 0023_archive_withdraw
Revises: 0022_archive_items
Create Date: 2026-11-18

  - `item.withdrawn_at`: set when a writer withdraws an item. The row stays
    (so the path still fails closed and the ledger can name it) but its
    consent is forced to `private` and its sha256 is in `tombstone`.
  - `answer`: one row per answer Ask gave. `answer_citation` lists the items
    each answer cited, by path and sha256, so a later withdrawal can mark
    every answer that rested on the withdrawn item.

Idempotent.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0023_archive_withdraw"
down_revision: Union[str, None] = "0022_archive_items"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    cols = {r[1] for r in conn.exec_driver_sql("PRAGMA table_info(item)").fetchall()}
    if "withdrawn_at" not in cols:
        op.execute("ALTER TABLE item ADD COLUMN withdrawn_at TEXT")
    op.execute("""
        CREATE TABLE IF NOT EXISTS answer (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            asked_at      TEXT NOT NULL,
            question      TEXT NOT NULL,
            answer_json   TEXT NOT NULL DEFAULT '[]',
            prompt_sha256 TEXT,
            model         TEXT
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS answer_citation (
            answer_id INTEGER NOT NULL,
            path      TEXT    NOT NULL,
            sha256    TEXT    NOT NULL DEFAULT '',
            PRIMARY KEY (answer_id, path)
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_answer_citation_sha ON answer_citation(sha256)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS answer_citation")
    op.execute("DROP TABLE IF EXISTS answer")
