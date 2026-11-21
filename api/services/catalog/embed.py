"""Pass 2: write embeddings to Qdrant, one vector per PASSAGE.

Consumes `file_chunks` (written by Pass 1.5, `chunk.py`) rather than reading
`files.extracted_text` directly. Before chunking this pass embedded each
file's first 2000 characters as a single vector, so nothing past a
document's opening was retrievable.

Splits the work into batches of EMBED_BATCH_SIZE so memory stays bounded for
very large vaults. Pending work is tracked per-chunk via
`file_chunks.embedded_at`, which makes the pass resumable mid-file and
self-healing: a crashed run leaves its un-upserted chunks pending rather than
marking a whole file done.

Test patches `services.job_store.is_cancelled` — we keep the top-level module
import and dispatch through it at call time so the monkeypatch sticks. (This
also named `httpx.get`, for a Qdrant health probe that no longer exists; no
test ever patched it, and `test_catalog_embed_retry.py` goes through
`embed_texts`.)
"""

from __future__ import annotations

import ctypes
import gc
import logging
import time

import services.job_store as job_store
from services.embeddings import embed_texts, release_model
from services.vector_store import ensure_collection, get_client, upsert_points

from .constants import EMBED_BATCH_SIZE
from .scan import _heartbeat_in_band

log = logging.getLogger(__name__)

# Per-batch retry so a *transient* embeddings-service slowdown (CPU spike under
# a big re-embed) doesn't abort the whole pass. Without this, one timed-out
# batch propagated up and silently skipped every remaining passage — a full
# vault re-embed stalled at ~12%. Backoff: 2,4,8,16,30s ≈ 60s before giving up;
# a genuinely-down service still aborts (chunks stay embedded_at=NULL, resume
# next run — the pass is per-chunk resumable).
_EMBED_RETRY_ATTEMPTS = 5
_EMBED_RETRY_BASE_DELAY = 2.0
_EMBED_RETRY_MAX_DELAY = 30.0


def _embed_batch_with_retry(texts: "list[str]") -> "list[list[float]]":
    delay = _EMBED_RETRY_BASE_DELAY
    for attempt in range(1, _EMBED_RETRY_ATTEMPTS + 1):
        try:
            return embed_texts(texts)
        except RuntimeError as e:
            if attempt == _EMBED_RETRY_ATTEMPTS:
                raise
            log.warning(
                "[catalog] embed batch failed (attempt %d/%d) — retrying in %.0fs: %s",
                attempt,
                _EMBED_RETRY_ATTEMPTS,
                delay,
                e,
            )
            time.sleep(delay)
            delay = min(delay * 2, _EMBED_RETRY_MAX_DELAY)
    # Unreachable (loop either returns or raises), but keeps type-checkers happy.
    raise RuntimeError("embed batch exhausted retries")


def _pass_embedding(
    conn,
    job_id: str | None,
    progress_callback,
    files_scanned: int,
    skip_ai: bool,
) -> dict:
    """Pass 2: embed files to Qdrant + truncate extracted_text post-embed."""

    def _is_cancelled() -> bool:
        return bool(job_id and job_store.is_cancelled(job_id))

    errors: list[str] = []

    if progress_callback:
        progress_callback("── Pass 2: Semantic embedding", files_scanned, phase="embed")

    # No reachability preflight any more: the vector store is a table in the
    # same SQLite file this pass is already writing to. The old code pinged
    # Qdrant's /healthz and skipped the whole pass on failure — there is
    # nothing left to be unreachable.
    qdrant_ok = not skip_ai

    try:
        vstore = None
        if qdrant_ok:
            vstore = get_client()
            # Honour the return value. This was previously discarded, so
            # changing the embedding model dropped the collection without
            # clearing the synced markers — nothing re-embedded, and semantic
            # search silently stayed empty forever.
            if ensure_collection(vstore):
                log.info("[catalog] collection (re)created — clearing embed markers")
                with conn:
                    conn.execute("UPDATE file_chunks SET embedded_at = NULL")
                    conn.execute("UPDATE files SET qdrant_synced_at = NULL")

        all_embed_ids: list[int] = [
            r["id"]
            for r in conn.execute(
                "SELECT id FROM file_chunks WHERE embedded_at IS NULL ORDER BY file_id, ordinal"
            )
        ]
        total_to_embed = len(all_embed_ids)

        if all_embed_ids and vstore is not None:
            total_embedded = 0
            now = time.time()

            for batch_start in range(0, total_to_embed, EMBED_BATCH_SIZE):
                if _is_cancelled():
                    break
                batch_ids = all_embed_ids[batch_start : batch_start + EMBED_BATCH_SIZE]
                placeholders = ",".join("?" * len(batch_ids))
                batch = conn.execute(
                    f"SELECT c.id, c.file_id, c.ordinal, c.text, c.heading, "
                    f"       f.rel_path, f.mount "
                    f"FROM file_chunks c JOIN files f ON f.id = c.file_id "
                    f"WHERE c.id IN ({placeholders})",
                    batch_ids,
                ).fetchall()
                # Prepend the heading breadcrumb: a passage under "Dosage"
                # should be findable by "how much", and the bare passage
                # often doesn't contain the word. Mirrors Chunk.embed_text.
                texts = [
                    f"{r['heading']}\n\n{r['text']}" if r["heading"] else r["text"]
                    for r in batch
                ]
                if _is_cancelled():
                    break
                vectors = _embed_batch_with_retry(texts)
                points = [
                    {
                        "id": r["id"],
                        "vector": vec,
                        "payload": {
                            "rel_path": r["rel_path"],
                            "mount": r["mount"],
                            "file_id": r["file_id"],
                            "ordinal": r["ordinal"],
                        },
                    }
                    # strict=False preserves today's behaviour exactly. Note what
                    # that behaviour is, though: if the embedder ever returns
                    # fewer vectors than texts, this silently drops the tail
                    # rather than mispairing them. strict=True is the better
                    # answer, but it turns a silent skip into a raised pass —
                    # a behaviour change that needs its own test.
                    for r, vec in zip(batch, vectors, strict=False)
                ]
                upsert_points(vstore, points)
                with conn:
                    for r in batch:
                        conn.execute(
                            "UPDATE file_chunks SET embedded_at=? WHERE id=?",
                            (now, r["id"]),
                        )
                    # A file counts as synced once none of its chunks are
                    # pending. Kept current because read paths and the
                    # connections features still gate on it.
                    touched_files = {r["file_id"] for r in batch}
                    for fid in touched_files:
                        conn.execute(
                            "UPDATE files SET qdrant_synced_at=? WHERE id=? AND NOT EXISTS "
                            "(SELECT 1 FROM file_chunks WHERE file_id=? AND embedded_at IS NULL)",
                            (now, fid, fid),
                        )
                    # In-band heartbeat — joins this batch's transaction.
                    _heartbeat_in_band(
                        conn,
                        job_id,
                        f"Embedding: {total_embedded + len(batch)}/{total_to_embed} passages…",
                    )
                total_embedded += len(batch)
                time.sleep(0.05)
                del batch, texts, vectors, points
                if progress_callback:
                    progress_callback(
                        f"Embedding: {total_embedded}/{total_to_embed} passages…",
                        files_scanned,
                        total_to_embed,
                        phase="embed",
                    )

            log.info("[catalog] Qdrant: embedded %d passages", total_embedded)

        del all_embed_ids
        gc.collect()
        try:
            release_model()
            gc.collect()
            ctypes.cdll.LoadLibrary("libc.so.6").malloc_trim(0)
        except Exception as e:
            log.debug("malloc_trim skipped: %s", e)
    except Exception as e:
        log.warning("[catalog] Qdrant embedding pass skipped: %s", e)

    return {"qdrant_ok": qdrant_ok, "errors": errors}
