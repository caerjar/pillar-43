"""run_catalog: coordinator for the three-pass ingest pipeline
(scan, chunk, embed).

The summary, thread, wikilink, structural and completeness passes were
removed with the personal app; Ask retrieves from `file_chunks` and
`chunk_vectors`, which only these three passes write.

Test patches `services.catalog.get_db` -- we route through the
`services.catalog` package via `_pkg()` so the swap takes effect.
"""

from __future__ import annotations

import ctypes
import logging
from typing import Any

import services.job_store as job_store
from config import settings

from .chunk import _pass_chunking
from .embed import _pass_embedding
from .reports import generate_extraction_skipped_report
from .scan import _pass_file_scan

log = logging.getLogger(__name__)


def _pkg():
    # Deferred for test-patch resolution. Tests patch services.catalog.get_db
    # and other names via the package namespace; we look them up through the
    # package at call time so the patch takes effect. Do not "fix" by
    # hoisting — it will silently break tests.
    from services import catalog as _cat

    return _cat


def run_catalog(
    force_rescan: bool = False,
    mounts: list[str] | None = None,
    progress_callback=None,
    job_id: str | None = None,
    skip_ai: bool = False,
) -> dict[str, Any]:
    """Walk the given mounts and index every file.

    Three passes:
      Pass 1   -- file scan: stat, hash, text extraction, DB upsert
      Pass 1.5 -- split extracted text into passages (`file_chunks`)
      Pass 2   -- embed the passages into the vector store (a no-op under
                  `skip_ai`; the caller embeds afterwards)
    """
    if mounts is None:
        all_keys = list(settings.all_mounts.keys())
        priority = ["notes", "generated", "library"]
        extras = [k for k in all_keys if k not in priority]
        mounts = [k for k in priority if k in all_keys] + extras

    mount_roots = settings.all_mounts
    cat = _pkg()  # for get_db patchability
    conn = cat.get_db()
    errors: list[str] = []

    def _is_cancelled() -> bool:
        if not job_id:
            return False
        return job_store.is_cancelled(job_id)

    def _early_exit(files_scanned, errors):
        """Return early exit result structure when cancelled."""
        if progress_callback:
            progress_callback(
                "-- Stopped by user -- remaining phases cancelled",
                files_scanned,
                level="warning",
            )
        return {
            "files_scanned": files_scanned,
            "errors": errors,
            "cancelled": True,
        }

    try:
        p1 = _pass_file_scan(
            conn,
            mounts,
            mount_roots,
            force_rescan,
            progress_callback,
            job_id,
        )
        errors.extend(p1["errors"])
        files_scanned: int = p1["files_scanned"]
        skipped_extractions: list = p1.get("skipped_extractions", [])

        # Best-effort: surface which files were *attempted* but didn't land
        # in the index (size cap or empty extraction). Failure here must not
        # crash the run — the report is auxiliary.
        try:
            rep = generate_extraction_skipped_report(skipped_extractions)
            if progress_callback and rep["skipped_count"] > 0:
                progress_callback(
                    f"Skipped {rep['skipped_count']} files for text "
                    f"extraction — see generated/extraction-skipped.md",
                    files_scanned,
                    phase="scan",
                    level="info",
                )
        except Exception as e:
            log.warning("extraction-skipped report failed: %s", e, exc_info=True)

        if _is_cancelled():
            return _early_exit(files_scanned, errors)

        # Pass 1.5 — split extracted text into passages before embedding.
        # Pure CPU, no AI, so it runs even under skip_ai: the chunks are what
        # a later embedding run consumes.
        p15 = _pass_chunking(conn, job_id, progress_callback, files_scanned)
        errors.extend(p15["errors"])

        if _is_cancelled():
            return _early_exit(files_scanned, errors)

        p2 = _pass_embedding(conn, job_id, progress_callback, files_scanned, skip_ai)
        errors.extend(p2["errors"])
    finally:
        conn.close()

    try:
        ctypes.cdll.LoadLibrary("libc.so.6").malloc_trim(0)
    except Exception:
        log.debug("malloc_trim unavailable on this platform; skipping", exc_info=True)

    return {
        "files_scanned": files_scanned,
        "errors": errors,
    }
