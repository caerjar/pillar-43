"""file_chunks — passage-level storage for chunked retrieval

Revision ID: 0017_file_chunks
Revises: 0016_commons_consent
Create Date: 2026-07-21

Until now every file was represented by ONE embedding vector computed from its
first 2000 characters (`catalog/embed.py`), so nothing past a document's
opening was retrievable. A 200-page PDF was its title page. This table is what
lets retrieval reach page 40.

Schema decisions:

  - Chunks live in SQLite rather than only as vector-store payload. Two
    reasons. Retrieval must return passage TEXT for injection into prompts,
    and the desktop plan (plans/MACOS_DMG_RUST_REPACKAGING_PLAN.md Phase 1a)
    replaces Qdrant with sqlite-vec — text in a Qdrant payload would be thrown
    away at that cutover, text here survives it untouched. Second, a chunk
    FTS5 table gives passage-level lexical search over PDFs for free;
    retrieval's ripgrep leg is markdown-only.

  - `id` is INTEGER AUTOINCREMENT because it doubles as the vector-store point
    ID. Point IDs used to equal files.id; chunking makes that one-to-many, and
    a monotone integer maps directly onto Phase 1a's planned
    `chunk_vectors(chunk_id PK, embedding FLOAT[dims])`.

  - `chunk_hash` (sha256 of the passage text) is the skip-rerun key. Rechunk
    compares the ordered hash list for a file; identical means no-op with
    `embedded_at` preserved. This moves re-embed authority off
    `files.qdrant_synced_at < mtime`, which re-embedded on a mere touch.

  - `char_start` / `char_end` are deliberate insurance. `text` duplicates
    `extracted_text` at ~1.2x (overlap) plus an FTS index. If that storage
    cost bites on a large vault, `text` can be dropped in a later migration
    and reconstructed via substr(extracted_text, ...). Keeping the offsets
    from day one is what keeps that option open.

  - `embedded_at` is per-chunk, not per-file, so the embedding pass is
    resumable mid-file and self-heals: a crashed run leaves its un-upserted
    chunks pending rather than marking a whole file done.

NOTE: ON DELETE CASCADE is declared but does NOT fire — `PRAGMA foreign_keys`
is never enabled on this connection (see services/db.py). Chunk rows must be
deleted explicitly. The constraint is kept as documentation of intent and so
the schema is correct if foreign keys are ever turned on.

Idempotent. Safe on a fresh DB or one already at 0016.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0017_file_chunks"
down_revision: Union[str, None] = "0016_commons_consent"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS file_chunks (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            file_id     INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
            ordinal     INTEGER NOT NULL,
            text        TEXT    NOT NULL,
            char_start  INTEGER NOT NULL,
            char_end    INTEGER NOT NULL,
            heading     TEXT,
            chunk_hash  TEXT    NOT NULL,
            embedded_at REAL,
            UNIQUE(file_id, ordinal)
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_file_chunks_file ON file_chunks(file_id)"
    )
    # Partial-ish index for the embedding pass's "what's pending" scan.
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_file_chunks_pending ON file_chunks(embedded_at)"
    )

    # External-content FTS5, mirroring files_fts in services/_schema_baseline.py.
    op.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS file_chunks_fts
            USING fts5(text, content=file_chunks, content_rowid=id)
    """)
    op.execute("""
        CREATE TRIGGER IF NOT EXISTS file_chunks_fts_insert
            AFTER INSERT ON file_chunks BEGIN
                INSERT INTO file_chunks_fts(rowid, text)
                VALUES (new.id, new.text);
            END
    """)
    op.execute("""
        CREATE TRIGGER IF NOT EXISTS file_chunks_fts_update
            AFTER UPDATE OF text ON file_chunks BEGIN
                INSERT INTO file_chunks_fts(file_chunks_fts, rowid, text)
                VALUES ('delete', old.id, old.text);
                INSERT INTO file_chunks_fts(rowid, text)
                VALUES (new.id, new.text);
            END
    """)
    op.execute("""
        CREATE TRIGGER IF NOT EXISTS file_chunks_fts_delete
            AFTER DELETE ON file_chunks BEGIN
                INSERT INTO file_chunks_fts(file_chunks_fts, rowid, text)
                VALUES ('delete', old.id, old.text);
            END
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS file_chunks_fts_delete")
    op.execute("DROP TRIGGER IF EXISTS file_chunks_fts_update")
    op.execute("DROP TRIGGER IF EXISTS file_chunks_fts_insert")
    op.execute("DROP TABLE IF EXISTS file_chunks_fts")
    op.execute("DROP INDEX IF EXISTS idx_file_chunks_pending")
    op.execute("DROP INDEX IF EXISTS idx_file_chunks_file")
    op.execute("DROP TABLE IF EXISTS file_chunks")
