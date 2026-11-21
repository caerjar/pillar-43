"""Pass 1.5: split extracted_text into file_chunks rows.

Runs between extraction and embedding. No network, no AI — pure CPU, so it's
cheap to re-run and safe to cancel at any point.

Skip-rerun contract: a file's chunk set is identified by the ordered list of
its chunk hashes. Identical means no-op with `embedded_at` preserved, so a
catalog re-run on a stable vault costs one hash comparison per file and zero
embeddings. Different means the whole file's chunks are replaced in one
transaction and marked pending.

This moves re-embed authority off `files.qdrant_synced_at < mtime`, which
re-embedded whenever a file was merely touched.
"""

from __future__ import annotations

import logging

import services.job_store as job_store

from .chunking import chunk_text
from .scan import _heartbeat_in_band

log = logging.getLogger(__name__)

# How many files to process between progress heartbeats.
_HEARTBEAT_EVERY = 50


def _current_hashes(conn, file_id: int) -> list[str]:
    rows = conn.execute(
        "SELECT chunk_hash FROM file_chunks WHERE file_id = ? ORDER BY ordinal",
        (file_id,),
    ).fetchall()
    return [r["chunk_hash"] for r in rows]


def rechunk_file(conn, file_id: int, text: str, ext: str) -> int:
    """Recompute chunks for one file. Returns the number of chunks now stored.

    Returns early (preserving `embedded_at`) when the content is unchanged.
    The delete+reinsert is one transaction so a crash can't leave a file with
    a half-replaced chunk set.
    """
    chunks = chunk_text(text or "", ext=ext or "")
    new_hashes = [c.chunk_hash for c in chunks]

    if new_hashes and new_hashes == _current_hashes(conn, file_id):
        return len(new_hashes)

    with conn:
        # Explicit delete: PRAGMA foreign_keys is off, so ON DELETE CASCADE
        # on file_chunks.file_id does not fire.
        conn.execute("DELETE FROM file_chunks WHERE file_id = ?", (file_id,))
        for c in chunks:
            conn.execute(
                "INSERT INTO file_chunks "
                "(file_id, ordinal, text, char_start, char_end, heading, "
                " chunk_hash, embedded_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, NULL)",
                (
                    file_id,
                    c.ordinal,
                    c.text,
                    c.char_start,
                    c.char_end,
                    c.heading,
                    c.chunk_hash,
                ),
            )
    return len(chunks)


def _pass_chunking(
    conn,
    job_id: str | None,
    progress_callback,
    files_scanned: int,
) -> dict:
    """Pass 1.5: chunk every file whose passages are missing or stale."""

    def _is_cancelled() -> bool:
        return bool(job_id and job_store.is_cancelled(job_id))

    if progress_callback:
        progress_callback("── Pass 1.5: Chunking", files_scanned, phase="chunk")

    rows = conn.execute(
        "SELECT id, ext, extracted_text FROM files "
        "WHERE extracted_text IS NOT NULL AND extracted_text != ''"
    ).fetchall()

    total = len(rows)
    files_chunked = 0
    chunks_written = 0
    errors: list[str] = []

    for i, r in enumerate(rows):
        if _is_cancelled():
            log.info("[catalog] chunking cancelled after %d files", i)
            break
        try:
            n = rechunk_file(conn, r["id"], r["extracted_text"], r["ext"])
            if n:
                files_chunked += 1
                chunks_written += n
        except Exception as exc:  # one bad file must not kill the pass
            log.warning(
                "[catalog] chunking failed for file %s: %s", r["id"], exc, exc_info=True
            )
            errors.append(f"chunking failed for file {r['id']}: {exc}")

        if i and i % _HEARTBEAT_EVERY == 0:
            if progress_callback:
                progress_callback(
                    f"Chunking… {i}/{total} files, {chunks_written} passages",
                    files_scanned,
                    total,
                    phase="chunk",
                )
            with conn:
                _heartbeat_in_band(conn, job_id, f"Chunking: {i}/{total} files…")

    if progress_callback:
        progress_callback(
            f"✓ Chunking: {chunks_written} passages across {files_chunked} files",
            files_scanned,
            phase="chunk",
        )

    return {
        "files_chunked": files_chunked,
        "chunks_written": chunks_written,
        "errors": errors,
    }
