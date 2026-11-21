"""chunk_vectors — embeddings in SQLite, replacing Qdrant

Revision ID: 0021_chunk_vectors
Revises: 0020_commons_ambient
Create Date: 2026-08-18

Qdrant was the last daemon in the stack, and a double-clickable desktop app
cannot ship one. This is where the vectors go instead.

`0017_file_chunks` anticipated this exactly. Its header says chunk text lives
in SQLite rather than as vector-store payload precisely so it "survives that
cutover untouched", and that `file_chunks.id` "is INTEGER AUTOINCREMENT
because it doubles as the vector-store point ID … a monotone integer maps
directly onto Phase 1a's planned `chunk_vectors(chunk_id PK, embedding
FLOAT[dims])`." So this table stores *only* the vector. `path`, `mount` and
`ordinal` are already reachable by joining `file_chunks → files`, and
duplicating them here would be a second copy to keep in step.

Schema decisions:

  - **BLOB of float32, not sqlite-vec.** An extension would mean one more
    dlopen'd .dylib to bundle, ad-hoc sign, and keep loadable inside a frozen
    app — in exchange for an ANN index this does not need. The live vault is
    22,624 chunks at 384 dims: a 34.7MB float32 matrix, one dot product,
    single-digit milliseconds. sqlite-vec stays available later behind the
    same facade — it would be this migration plus one module.

  - **Vectors are stored L2-normalised**, which is what fastembed returns
    (measured norm exactly 1.0). That is what lets cosine similarity be a
    plain dot product rather than a division per row.

  - **`dims` per row, not per table.** The embedding model is a user setting
    and models differ (384 … 1536). Storing width alongside the vector makes a
    model switch detectable rather than a silent buffer misread —
    `ensure_collection` compares it and truncates when it moves.

  - **No backfill from Qdrant.** A fresh install starts empty and indexes from
    scratch, which is the case that has to work; writing migration machinery
    for a store being deleted would be code with one user and no future. An
    existing vault re-embeds — local, no API cost, a few minutes.

NOTE: `ON DELETE CASCADE` is declared but does NOT fire — `PRAGMA foreign_keys`
is never enabled on this connection, the same caveat `0017` records for
`file_chunks`. Deletes must remove rows here explicitly; the constraint is
documentation of intent and correctness if foreign keys are ever turned on.

Idempotent. Safe on a fresh DB or one already at 0020.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0021_chunk_vectors"
down_revision: Union[str, None] = "0020_commons_ambient"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS chunk_vectors (
            chunk_id INTEGER PRIMARY KEY
                     REFERENCES file_chunks(id) ON DELETE CASCADE,
            dims     INTEGER NOT NULL,
            vector   BLOB    NOT NULL
        )
    """)
    # The hot query filters by mount, which lives on `files`, so the join runs
    # chunk_vectors → file_chunks → files. file_chunks already indexes file_id
    # (idx_file_chunks_file, 0017); this covers the other direction.
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_chunk_vectors_dims ON chunk_vectors(dims)"
    )

    # Retire the embed markers, because the vectors they refer to are gone.
    #
    # This is the upgrade's one genuine hazard and it fails silently. An
    # existing vault has `file_chunks.embedded_at` and `files.qdrant_synced_at`
    # set from the Qdrant era — 22,372 chunks on the dev vault — while the new
    # table is empty. The embed pass selects `WHERE embedded_at IS NULL`, so it
    # would consider every chunk already done, embed nothing, and leave
    # semantic search returning no hits forever. Nothing raises; the catalog
    # run reports success.
    #
    # `ensure_collection` cannot rescue this: it compares *stored* dims, and an
    # empty store correctly reports "nothing to invalidate" — which is the
    # right answer for a fresh install and the wrong one here. The migration is
    # the only place that knows vectors just ceased to exist.
    #
    # Cost is a local re-embed on next index: no API calls, a few minutes.
    #
    # Both columns are probed rather than assumed, because this project has two
    # schema paths that do not agree: `services/_schema_baseline.py` (used at
    # runtime) declares `files.qdrant_synced_at`, and the Alembic chain never
    # adds it. Writing to it unconditionally passes against a real vault and
    # fails every test that migrates from scratch — which is exactly what
    # happened when this was first written.
    bind = op.get_bind()

    def _has_column(table: str, column: str) -> bool:
        rows = bind.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()
        return any(r[1] == column for r in rows)

    if _has_column("file_chunks", "embedded_at"):
        op.execute("UPDATE file_chunks SET embedded_at = NULL")
    if _has_column("files", "qdrant_synced_at"):
        op.execute("UPDATE files SET qdrant_synced_at = NULL")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_chunk_vectors_dims")
    op.execute("DROP TABLE IF EXISTS chunk_vectors")
