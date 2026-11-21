"""Pass 1: filesystem walk + per-file upsert.

Test patches like `patch("services.catalog.hash_file", ...)` and
`patch("services.job_store.is_cancelled", ...)` only affect attribute lookups
on the named module — so we resolve those names through the source module at
call time. `_pkg()` returns the catalog package; `job_store.is_cancelled` is
called as `job_store.is_cancelled(...)` so monkeypatches stick.
"""

from __future__ import annotations

import ctypes
import errno as _errno
import gc
import logging
import sqlite3 as _sqlite3
import time
from functools import partial
from pathlib import Path
from typing import Any

import services.job_store as job_store
from config import settings

from .code_projects import _find_code_dirs
from .forget import forget_missing_files
from .constants import (
    CATALOG_BATCH_SIZE,
    CODE_CONFIG_EXTENSIONS,
    EXCLUDE_DIRS,
    EXCLUDE_FILES,
    MAX_TEXT_EXTRACT_BYTES,
    README_NAMES,
)
from .state import FileRecord

log = logging.getLogger(__name__)

# In-band heartbeat cadence — every N scanned files we patch the jobs row on
# the scan thread's OWN connection. Single-writer pattern: no separate
# connection, no writer-vs-writer contention. ~10s cadence on fast scans;
# faster on slow ones (where each file takes longer).
HEARTBEAT_EVERY_N_FILES = 50


def _pkg():
    """Return the services.catalog package module so name lookups respect
    `unittest.mock.patch('services.catalog.X', ...)` swaps used by tests.
    """
    # Deferred for test-patch resolution, NOT for circularity. Tests patch
    # services.catalog.hash_file / extract_text_for_catalog via the package
    # namespace; we look them up through the package at call time so monkeypatch
    # takes effect. Do not "fix" by hoisting — it will silently break tests.
    from services import catalog as _cat

    return _cat


def _retry_on_locked(fn, *, attempts: int = 4, base_delay: float = 0.25):
    """Run `fn`, retrying on SQLite 'database is locked' with backoff.

    Even with WAL + a 10s busy_timeout, a concurrent writer (the worker's
    periodic jobs, a parallel pass) can hold the write lock long enough that
    a per-file scan write loses the race and `database is locked` surfaces.
    Previously that dropped the file silently. A few short retries recover
    the transient case; a genuinely stuck lock still raises after the last
    attempt (caller logs + skips, as before).
    """
    for i in range(attempts):
        try:
            return fn()
        except _sqlite3.OperationalError as e:
            if "locked" not in str(e).lower() or i == attempts - 1:
                raise
            time.sleep(base_delay * (2**i))
    return None


def _heartbeat_in_band(conn, job_id: str | None, msg: str) -> None:
    """Patch the jobs row using the scan thread's own SQLite connection.

    Replaces the previous `update_job(job_id, progress=..., last_heartbeat=...)`
    call that ran on a fresh connection from the SSE thread. That pattern
    fought the scan thread's batched commits and triggered
    `database is locked`. Routing the UPDATE through the existing `conn`
    means only one writer touches the file — single-writer invariant.

    The UPDATE joins whatever transaction `conn` already has open and
    persists when the next `conn.commit()` fires (batch boundary in
    `_pass_file_scan`, or autocommit in passes that own their own txns).
    Lost heartbeats on rollback don't matter; JobStatusBar simply shows
    the previous value briefly.
    """
    if not job_id:
        return
    try:
        conn.execute(
            "UPDATE jobs SET progress = ?, last_heartbeat = ? WHERE id = ?",
            (msg[:200] if msg else None, time.time(), job_id),
        )
    except Exception as e:
        # Heartbeats are best-effort; never let a stale-jobs UPDATE crash the scan.
        log.debug("in-band heartbeat skipped: %s", e, exc_info=True)


def _emit_scan_progress(
    *,
    progress_callback,
    conn,
    job_id: str | None,
    mount: str,
    rel_path: str,
    files_scanned: int,
    mount_scanned: int,
) -> None:
    """Per-file progress + the in-band job heartbeat.

    This block was duplicated verbatim in the unchanged-file and changed-file
    arms of the scan loop, contributing its branches twice. The two cadences
    are deliberately different: the SSE progress event every 10 files is for
    the UI, the heartbeat every HEARTBEAT_EVERY_N_FILES is what stops the
    stale-job sweep cancelling a healthy long scan.
    """
    msg = f"Indexing {mount}/: {mount_scanned:,} files…"
    if progress_callback and files_scanned % 10 == 0:
        progress_callback(msg, files_scanned, phase="scan", current_file=rel_path)
    if files_scanned % HEARTBEAT_EVERY_N_FILES == 0:
        _heartbeat_in_band(conn, job_id, msg)


def _skip_reason(
    abs_path: Path,
    *,
    mount: str,
    rel_parts: tuple[str, ...],
) -> str | None:
    """Why this path should not be catalogued, or None to scan it.

    Pure and total — no I/O, no settings mutation — so the scan loop's skip
    policy can be tested directly instead of only through a full catalog run.
    Returning the *reason* rather than a bool means a future "why was my file
    skipped?" surface has something to report.

    Order matters only for which reason wins; every branch is a skip.
    """
    # Commons wire logs + downloaded attachments (generated/commons/**) are
    # untrusted remote content. Never scan/extract/embed them, so an attacker's
    # document is never fed to a parser and never poisons the user's search
    # index. See the Commons security model in the maintainer notes.
    if mount == "generated" and rel_parts and rel_parts[0] == "commons":
        return "untrusted-commons-content"
    if any(p.startswith(".") or p in EXCLUDE_DIRS for p in rel_parts[:-1]):
        return "excluded-directory"
    if abs_path.name.startswith(".") or abs_path.name in EXCLUDE_FILES:
        return "excluded-file"
    if abs_path.suffix.lower() in CODE_CONFIG_EXTENSIONS:
        return "code-config-extension"
    if abs_path.suffix.lower() in settings.effective_excluded_extensions():
        return "user-excluded-extension"
    return None


def _extract_text_for_file(
    cat, abs_path: Path, rel_path: str, ext: str, stat
) -> tuple[str | None, list[dict]]:
    """Extract a file's text, or decline to.

    Returns (text, skip-records). Two ways to decline, and the report
    distinguishes them: `over_size` means we never tried, `empty_extraction`
    means the extractor ran and produced nothing usable — a binary without a
    transcript, an image-only PDF, a parse failure, a timeout.

    A markdown note with no body is NOT flagged: the extractor returns file
    content verbatim, so an empty .md legitimately yields an empty string.
    """
    skipped: list[dict] = []
    if stat.st_size > MAX_TEXT_EXTRACT_BYTES:
        log.info(
            "[catalog] skipping text extraction: %s (%.0f MB)",
            rel_path,
            stat.st_size / (1024 * 1024),
        )
        text = None
        skipped.append(
            {
                "rel_path": rel_path,
                "size_bytes": stat.st_size,
                "ext": ext,
                "reason": "over_size",
            }
        )
    else:
        text = cat.extract_text_for_catalog(abs_path, rel_path)
        # Empty extraction result: extractor ran but produced
        # nothing usable for the index. Catches binary types
        # without transcripts, image-only PDFs, parse failures,
        # and extraction timeouts. Markdown notes with no body
        # are NOT flagged — extractor returns the file content
        # verbatim (possibly empty string for truly empty .md),
        # which is a degenerate but legitimate state we leave
        # to the user to notice.
        if text is None or text == "":
            skipped.append(
                {
                    "rel_path": rel_path,
                    "size_bytes": stat.st_size,
                    "ext": ext,
                    "reason": "empty_extraction",
                }
            )
    return text, skipped


def _scan_iter_for(root: Path, path_filter: str | None) -> Any:
    """What this mount's walk should yield.

    Whole-mount scans rglob. A single-file scan resolves through
    `settings.resolve()` rather than joining lexically: `root / tail` keeps
    `..` segments intact, and routes/catalog/run.py's docstring has always
    claimed "path traversal is prevented by settings.resolve() in the scan
    pass" while no line in this module called it. It does now.

    A rejected filter yields nothing instead of raising — the caller is a
    background job, and files_scanned=0 is an outcome the surrounding code
    already handles.
    """
    if not path_filter:
        return root.rglob("*")
    try:
        return [settings.resolve(path_filter)]
    except (ValueError, KeyError):
        log.warning("[catalog] refusing out-of-mount path filter: %r", path_filter)
        return []


def _prune_mount(conn, mount: str, progress_callback, files_scanned: int) -> None:
    """Drop catalog rows for files that have left this mount.

    Scoped to the mount just walked — a scan of notes/ must never drop
    library/ rows because that volume happens to be unmounted. Deleting a
    user's whole library catalog because a disk did not mount is a worse
    failure than the staleness this fixes.

    Extracted rather than inlined into `_pass_file_scan`, which is already
    at the C901 ceiling: three more branches there push it over, and raising
    the threshold to fit a prune step is how the ceiling stops meaning
    anything.

    Never raises. A prune failure must not fail a scan that has already
    indexed everything it walked.
    """
    try:
        pruned = forget_missing_files(conn, mount=mount)
    except Exception as e:
        log.warning("[catalog] prune failed for %s: %s", mount, e, exc_info=True)
        return
    if pruned and progress_callback:
        progress_callback(
            f"{mount}/ — removed {pruned:,} entries for deleted files",
            files_scanned,
            phase="scan",
        )


def _pass_file_scan(
    conn,
    mounts: list[str],
    mount_roots: dict,
    force_rescan: bool,
    progress_callback,
    job_id: str | None,
    path_filter: str | None = None,
) -> dict:
    """Pass 1: walk filesystem, extract text, upsert file records.

    When `path_filter` is set (mount-prefixed rel_path), only that single
    file is processed instead of every file in every mount. Used by the
    Editor's "Re-summarize this file" button.
    """

    # Cache the cancel-check result for CANCEL_CHECK_TTL_SEC. is_cancelled()
    # opens a fresh sqlite3 connection and SELECTs from `jobs`. The scan loop
    # iterates tens of thousands of files; hitting the DB per file collides
    # with the scan thread's own batched commits under TRUNCATE journal mode
    # and triggers `sqlite3.OperationalError: database is locked` even with
    # busy_timeout. Caching means we query at most ~10×/sec instead of
    # 1×/file. Stop latency stays sub-second; DB contention disappears.
    #
    # OperationalError from a transient lock is swallowed — we keep the prior
    # cached value and re-query on the next tick. Safer than crashing the
    # whole scan over a recoverable race.
    import sqlite3 as _sqlite3

    CANCEL_CHECK_TTL_SEC = 0.1
    _cancel_state = {"checked_at": 0.0, "cancelled": False}

    def _is_cancelled() -> bool:
        if not job_id:
            return False
        now = time.time()
        if now - _cancel_state["checked_at"] < CANCEL_CHECK_TTL_SEC:
            return _cancel_state["cancelled"]  # type: ignore[return-value]
        try:
            _cancel_state["cancelled"] = job_store.is_cancelled(job_id)
            _cancel_state["checked_at"] = now
        except _sqlite3.OperationalError as e:
            log.debug("is_cancelled transient error (kept prior value): %s", e)
            _cancel_state["checked_at"] = now  # backoff: don't retry for TTL
        return _cancel_state["cancelled"]  # type: ignore[return-value]

    cat = _pkg()  # resolve hash_file / extract_text_for_catalog through package

    errors: list[str] = []
    files_scanned = 0
    # Tracks files that were *attempted* but did not land text in the index.
    # Two reasons reported; unchanged-hash skips are intentionally excluded
    # (most files most runs — would explode the report). See
    # reports.generate_extraction_skipped_report.
    skipped_extractions: list[dict] = []

    if progress_callback:
        progress_callback("── Pass 1: Indexing files", 0, phase="scan")
    _heartbeat_in_band(conn, job_id, "Pass 1: Indexing files")

    existing_map: dict[str, dict] = {
        row["rel_path"]: dict(row)
        for row in conn.execute(
            "SELECT id, rel_path, sha256, mtime, size_bytes FROM files"
        )
    }

    pending_writes = 0

    for mount in mounts:
        if _is_cancelled():
            if progress_callback:
                progress_callback("── Cancelled by user", files_scanned)
            break
        # Single-file mode: skip mounts that don't own the target path. The
        # filter is mount-prefixed (e.g. "notes/foo.md") so we match by prefix.
        if path_filter and not path_filter.startswith(mount + "/"):
            continue
        root = mount_roots.get(mount)
        if not root or not root.exists():
            continue
        mount_scanned = 0

        if progress_callback:
            progress_callback(
                f"Indexing {mount}/ — scanning…",
                files_scanned,
                phase="scan",
            )

        code_dirs = _find_code_dirs(root)

        scan_iter: Any = _scan_iter_for(root, path_filter)

        for abs_path in scan_iter:
            if _is_cancelled():
                if progress_callback:
                    progress_callback("── Cancelled by user", files_scanned)
                break
            # Symlinks are refused before is_file(), which FOLLOWS them.
            #
            # This is the one containment check the scan has. `_skip_reason`
            # is pure by contract and `relative_to` is lexical, so neither
            # can see that a clean-looking rel_path resolves outside the
            # mount. Without this, a link in notes/ has its target read,
            # embedded, and returned by search —
            # and notes/ is git-tracked and cloud-synced, both of which
            # preserve symlinks, so it is a delivery channel, not a
            # hypothetical.
            #
            # Refuse rather than resolve-and-contain: a link pointing back
            # inside the vault just duplicates a file the walk already
            # yields, so there is nothing to lose by skipping all of them.
            # Symlink check FIRST — is_file() follows links, so the reverse
            # order lets a link's target through with a clean-looking
            # rel_path. Refusing rather than resolving is deliberate: a link
            # pointing back inside the vault only duplicates a file the walk
            # already yields.
            if abs_path.is_symlink() or not abs_path.is_file():
                continue
            rel_parts = abs_path.relative_to(root).parts
            if _skip_reason(abs_path, mount=mount, rel_parts=rel_parts):
                continue

            containing_code_dir = next(
                (cd for cd in code_dirs if abs_path == cd or cd in abs_path.parents),
                None,
            )
            if containing_code_dir is not None:
                if abs_path.name.lower() not in README_NAMES:
                    continue
                _readme_language: str | None = code_dirs[containing_code_dir]
            else:
                _readme_language = None

            rel_path = mount + "/" + str(abs_path.relative_to(root))
            ext = abs_path.suffix.lower()
            try:
                stat = abs_path.stat()
                ex = existing_map.get(rel_path)

                unchanged = (
                    ex is not None
                    and not force_rescan
                    and ex["mtime"] == stat.st_mtime
                    and ex["size_bytes"] == stat.st_size
                )

                if unchanged:
                    files_scanned += 1
                    mount_scanned += 1
                    _emit_scan_progress(
                        progress_callback=progress_callback,
                        conn=conn,
                        job_id=job_id,
                        mount=mount,
                        rel_path=rel_path,
                        files_scanned=files_scanned,
                        mount_scanned=mount_scanned,
                    )
                else:
                    sha = cat.hash_file(abs_path)
                    text, _skips = _extract_text_for_file(
                        cat, abs_path, rel_path, ext, stat
                    )
                    skipped_extractions.extend(_skips)
                    if _readme_language is not None and text is not None:
                        project_name = containing_code_dir.name  # type: ignore[union-attr]
                        prefix = (
                            f"[Code project — {_readme_language}: {project_name}]\n\n"
                        )
                        text = prefix + text
                    fm = cat._parse_frontmatter(text or "")
                    authorship = cat._infer_authorship(rel_path, ext, mount, fm)
                    # partial(), not lambda: it binds these arguments eagerly, so
                    # the retry callable closes over nothing from the loop. The
                    # lambda this replaces was equally safe in practice —
                    # _retry_on_locked invokes it synchronously, before the loop
                    # advances — but "safe because of what the callee does" is a
                    # property a reader has to go verify. This has no late
                    # binding to reason about at all.
                    record = FileRecord(
                        rel_path=rel_path,
                        mount=mount,
                        abs_path=str(abs_path),
                        sha256=sha,
                        size_bytes=stat.st_size,
                        mtime=stat.st_mtime,
                        ext=ext,
                        extracted_text=text,
                        authorship=authorship,
                    )
                    _retry_on_locked(
                        partial(
                            cat.upsert_file_record,
                            conn,
                            record,
                            existing_map=existing_map,  # bound at L163; ruff mis-reads the later `del`
                            commit=False,
                        )
                    )
                    pending_writes += 1
                    if pending_writes >= CATALOG_BATCH_SIZE:
                        _retry_on_locked(conn.commit)
                        pending_writes = 0

                    files_scanned += 1
                    mount_scanned += 1
                    _emit_scan_progress(
                        progress_callback=progress_callback,
                        conn=conn,
                        job_id=job_id,
                        mount=mount,
                        rel_path=rel_path,
                        files_scanned=files_scanned,
                        mount_scanned=mount_scanned,
                    )
                    if files_scanned % 500 == 0:
                        gc.collect()
                        try:
                            ctypes.cdll.LoadLibrary("libc.so.6").malloc_trim(0)
                        except Exception as e:
                            log.debug("malloc_trim skipped: %s", e)

            except OSError as e:
                if e.errno == _errno.EDEADLK:
                    log.debug("Skipping locked file %s (iCloud/NFS lock)", abs_path)
                else:
                    log.warning("Catalog error for %s: %s", abs_path, e)
                    errors.append(f"{abs_path}: {e}")
            except Exception as e:
                # Full traceback for lock errors so the exact contended write
                # is identifiable (the bare message hid where it's raised).
                log.warning(
                    "Catalog error for %s: %s",
                    abs_path,
                    e,
                    exc_info="locked" in str(e).lower(),
                )
                errors.append(f"{abs_path}: {e}")
            time.sleep(0.002)

        if pending_writes:
            _retry_on_locked(conn.commit)
            pending_writes = 0

        if not path_filter:
            _prune_mount(conn, mount, progress_callback, files_scanned)

        if progress_callback and mount_scanned > 0:
            progress_callback(
                f"{mount}/ done — {mount_scanned:,} files indexed ✓",
                files_scanned,
                phase="scan",
            )
        _heartbeat_in_band(
            conn,
            job_id,
            f"{mount}/ done — {mount_scanned:,} files indexed",
        )

    del existing_map
    gc.collect()

    # Ensure the trailing heartbeat persists even if no per-mount commit ran
    # (e.g. all mounts empty or every file unchanged).
    try:
        _retry_on_locked(conn.commit)
    except Exception as e:
        log.debug("trailing heartbeat commit skipped: %s", e, exc_info=True)

    return {
        "files_scanned": files_scanned,
        "errors": errors,
        "skipped_extractions": skipped_extractions,
    }
