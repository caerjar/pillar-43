"""archive items — consent per item, and tombstones for withdrawn files

Revision ID: 0022_archive_items
Revises: 0021_chunk_vectors
Create Date: 2026-11-17

The press archive puts a consent level on
every item an organization holds. Consent lives in its own table, never in a
file path, so moving a folder cannot open or close anything.

  - `item`: one row per file the archive took in. `consent` is one of
    `private` (held, never searchable), `staff` (searchable and cited to staff,
    never sent to a model) or `model` (a model may read it at question time).
    `people` is a JSON list of `{name, role}`; roles come from `org.yaml`.
  - `tombstone`: the sha256 of every withdrawn file. Intake refuses a file
    whose hash is here, which is what keeps a withdrawn work from slipping
    back in under a new name or path.

The personal profile never writes these tables, so an existing vault gains two
empty tables and nothing else.

Idempotent.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0022_archive_items"
down_revision: Union[str, None] = "0021_chunk_vectors"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS item (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            path        TEXT    NOT NULL UNIQUE,
            sha256      TEXT    NOT NULL,
            kind        TEXT    NOT NULL,
            title_isbn  TEXT,
            people      TEXT    NOT NULL DEFAULT '[]',
            consent     TEXT    NOT NULL DEFAULT 'private'
                        CHECK (consent IN ('private', 'staff', 'model')),
            consent_by  TEXT,
            consent_at  TEXT,
            ledger_seq  INTEGER
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_item_sha ON item(sha256)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_item_consent ON item(consent)")
    op.execute("""
        CREATE TABLE IF NOT EXISTS tombstone (
            sha256       TEXT PRIMARY KEY,
            withdrawn_by TEXT NOT NULL,
            at           TEXT NOT NULL
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS tombstone")
    op.execute("DROP TABLE IF EXISTS item")
