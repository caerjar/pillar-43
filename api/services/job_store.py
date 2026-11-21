"""Background job registry — SQLite-backed.

Jobs are created by long-running endpoints that return immediately. The
frontend polls GET /api/jobs/{id} until the job reaches a terminal state
(done | error | cancelled).

Persistence rationale (Day 4 — replaces the previous in-memory `_jobs` dict):
  - API restarts no longer forget about in-flight jobs
  - Multiple uvicorn workers see consistent state (was per-process before)
  - Job history survives across sessions — recent runs become a UI feature

Public surface is unchanged from the in-memory version: `create_job`,
`update_job`, `get_job`, `list_jobs`, `finish_job`, `fail_job`,
`cancel_job`, `is_cancelled`, `cleanup_old_jobs`.

Schema lives in Alembic migration 0002_jobs_table.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass

log = logging.getLogger(__name__)

_CLEANUP_AGE = 3600  # seconds
HEARTBEAT_STALE_SEC = 120  # catalog job is stuck if no heartbeat in 2 min

# Module-level write lock: serializes Python-side writes from job_store so
# create_job + update_job + cleanup_old_jobs can't be in flight simultaneously
# on different threads racing SQLite's writer slot. Does NOT protect against
# cross-table contention (e.g. catalog scan thread writing to `files` while
# we try to UPDATE jobs) — for that, the route handler uses try_update_job to
# fail gracefully instead of crashing.
_write_lock = threading.Lock()


@dataclass
class BackgroundJob:
    """Public-shape dataclass — callers destructure `.id`, `.status`, etc.

    Constructed from a SQLite row by `_row_to_job()`. Mutating fields here
    does NOT persist; use `update_job()` for that.
    """

    id: str
    label: str
    status: str = "running"  # 'running' | 'done' | 'error' | 'cancelled'
    progress: str | None = None
    started_at: float = 0.0
    finished_at: float | None = None
    cancel_requested: bool = False
    last_heartbeat: float | None = None


def _row_to_job(row) -> BackgroundJob:
    """Materialise a SQLite Row into the public dataclass."""
    keys = row.keys() if hasattr(row, "keys") else ()
    return BackgroundJob(
        id=row["id"],
        label=row["label"],
        status=row["status"],
        progress=row["progress"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        cancel_requested=bool(row["cancel_requested"]),
        last_heartbeat=row["last_heartbeat"] if "last_heartbeat" in keys else None,
    )


def create_job(label: str) -> BackgroundJob:
    """Insert a new running job and return its dataclass form."""
    from services.db import get_db

    job_id = str(uuid.uuid4())
    now = time.time()
    with _write_lock:
        conn = get_db()
        try:
            conn.execute(
                "INSERT INTO jobs (id, label, status, progress, started_at, "
                "                  finished_at, cancel_requested) "
                "VALUES (?, ?, 'running', NULL, ?, NULL, 0)",
                (job_id, label, now),
            )
            conn.commit()
        finally:
            conn.close()
    return BackgroundJob(id=job_id, label=label, status="running", started_at=now)


def update_job(job_id: str, **kwargs) -> None:
    """Patch arbitrary BackgroundJob fields.

    Accepts the same keyword arguments the dataclass takes. Unknown fields
    are silently ignored to match the previous setattr-loop behaviour.
    """
    if not kwargs:
        return

    allowed = {
        "label",
        "status",
        "progress",
        "started_at",
        "finished_at",
        "cancel_requested",
        "last_heartbeat",
    }
    cleaned: dict = {}
    for k, v in kwargs.items():
        if k not in allowed:
            continue
        if k == "cancel_requested":
            v = 1 if v else 0
        cleaned[k] = v
    if not cleaned:
        return

    columns = ", ".join(f"{k} = ?" for k in cleaned)
    params = [*list(cleaned.values()), job_id]

    from services.db import get_db

    with _write_lock:
        conn = get_db()
        try:
            conn.execute(f"UPDATE jobs SET {columns} WHERE id = ?", params)
            conn.commit()
        finally:
            conn.close()


def try_update_job(job_id: str, **kwargs) -> bool:
    """Opportunistic `update_job`. Returns True on success, False if the write
    failed because the DB was locked.

    Use this from route handlers where a wedged DB must NOT crash the request
    — for example, the "replace prior running job" auto-recover in
    POST /catalog/run, which is only an optimization. When this returns False
    the next pass of `cleanup_old_jobs` (heartbeat-stale sweep) will reclassify
    any orphaned row, so the recovery still happens — just lazily.

    Only `sqlite3.OperationalError` (lock contention) is swallowed; programmer
    errors (unknown column, type mismatch) still propagate.
    """
    try:
        update_job(job_id, **kwargs)
        return True
    except sqlite3.OperationalError as e:
        log.warning(
            "[job_store] try_update_job(%s) failed — DB locked, will rely on "
            "heartbeat-stale sweep: %s",
            job_id,
            e,
        )
        return False


def get_job(job_id: str) -> BackgroundJob | None:
    from services.db import get_db

    conn = get_db()
    try:
        row = conn.execute(
            "SELECT id, label, status, progress, started_at, finished_at, "
            "       cancel_requested, last_heartbeat "
            "FROM jobs WHERE id = ?",
            (job_id,),
        ).fetchone()
    finally:
        conn.close()
    return _row_to_job(row) if row else None


def list_jobs() -> list[BackgroundJob]:
    """Return all known jobs, most recent first."""
    from services.db import get_db

    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT id, label, status, progress, started_at, finished_at, "
            "       cancel_requested, last_heartbeat "
            "FROM jobs ORDER BY started_at DESC"
        ).fetchall()
    finally:
        conn.close()
    return [_row_to_job(r) for r in rows]


def heartbeat(job_id: str) -> None:
    """Refresh last_heartbeat to now. Call frequently from long-running tasks
    (every progress message). cleanup_old_jobs uses this to detect wedged
    catalog jobs within HEARTBEAT_STALE_SEC instead of waiting for the
    started_at-based 15-minute threshold.
    """
    update_job(job_id, last_heartbeat=time.time())


def finish_job(job_id: str, progress: str | None = None) -> None:
    update_job(job_id, status="done", finished_at=time.time(), progress=progress)


def fail_job(job_id: str, error: str) -> None:
    update_job(job_id, status="error", finished_at=time.time(), progress=error)


def cancel_job(job_id: str, reason: str = "Cancelled by user.") -> None:
    """Request cancellation of a running job.

    Only sets cancel_requested flag — does NOT change status. The running
    process checks is_cancelled() and exits gracefully, then marks itself
    as cancelled when it actually stops.
    """
    update_job(
        job_id,
        cancel_requested=True,
        progress=reason,
    )


def retry_cancel_in_background(
    job_id: str,
    reason: str = "Cancelled by user.",
    *,
    max_total_seconds: float = 10.0,
    initial_backoff: float = 0.5,
    max_backoff: float = 2.0,
) -> threading.Thread:
    """Spawn a daemon thread that retries `cancel_job` with exponential backoff.

    Called by the cancel route when the synchronous `cancel_job` raised
    `sqlite3.OperationalError` (DB locked). The first synchronous attempt
    runs at request time so the common (un-contended) case lands a single
    quick write. This background thread is the recovery path for the
    contended case — typically wins within 0.5–2 s once the wedged writer
    releases its slot.

    If all retries within the budget fail, falls back to
    `cleanup_old_jobs`'s heartbeat-stale sweep (2 min) — so the user is
    never permanently stranded with a stuck "running" row. See
    MAINTAIN_PANEL_PLAN.md §1.7.5.

    Returns the thread handle for tests; production callers ignore it.
    """

    def _retry_loop() -> None:
        deadline = time.time() + max_total_seconds
        backoff = initial_backoff
        attempt = 0
        while time.time() < deadline:
            attempt += 1
            try:
                cancel_job(job_id, reason)
                log.info(
                    "[job_store] background cancel landed for %s on attempt %d",
                    job_id,
                    attempt,
                )
                return
            except sqlite3.OperationalError as e:
                remaining = deadline - time.time()
                if remaining <= 0:
                    break
                sleep_for = min(backoff, remaining)
                log.debug(
                    "[job_store] background cancel attempt %d for %s failed (%s); "
                    "retrying in %.2fs",
                    attempt,
                    job_id,
                    e,
                    sleep_for,
                )
                time.sleep(sleep_for)
                backoff = min(backoff * 1.5, max_backoff)
        log.warning(
            "[job_store] background cancel exhausted %.1fs budget for %s after %d "
            "attempts; heartbeat-stale sweep will catch it within %ds",
            max_total_seconds,
            job_id,
            attempt,
            HEARTBEAT_STALE_SEC,
        )

    t = threading.Thread(
        target=_retry_loop,
        daemon=True,
        name=f"cancel-retry-{job_id[:8]}",
    )
    t.start()
    return t


def is_cancelled(job_id: str) -> bool:
    """Return True if cancellation was requested. Long-running tasks check this
    periodically to exit cleanly."""
    from services.db import get_db

    conn = get_db()
    try:
        row = conn.execute(
            "SELECT cancel_requested FROM jobs WHERE id = ?", (job_id,)
        ).fetchone()
    finally:
        conn.close()
    return bool(row and row["cancel_requested"])


def reclassify_running_jobs_as_interrupted() -> int:
    """Mark all rows with status='running' as cancelled with an 'interrupted'
    message. Returns the count.

    Called once on API startup. Any job still in 'running' state at startup
    is by definition orphaned — its owning thread died with the previous
    container. cleanup_old_jobs's threshold-based sweep is the right tool for
    DURING-runtime orphan detection (catches jobs that wedged mid-run); this
    function is the right tool for the process-boundary case, where age
    thresholds aren't relevant. A user who restarts `./pillar43 stop && start`
    within 120s of a still-running scan would otherwise see Run buttons stuck
    disabled until cleanup_old_jobs's heartbeat-stale threshold elapses. See
    MAINTAIN_PANEL_PLAN.md §1.8.
    """
    from services.db import get_db

    with _write_lock:
        conn = get_db()
        try:
            rows = conn.execute(
                "SELECT id, label FROM jobs WHERE status = 'running'"
            ).fetchall()
            for row in rows:
                conn.execute(
                    "UPDATE jobs SET status = 'cancelled', finished_at = ?, "
                    "cancel_requested = 1, "
                    "progress = 'Interrupted by API restart — start a new run' "
                    "WHERE id = ?",
                    (time.time(), row["id"]),
                )
                log.info(
                    "[job_store] reclassified orphan running job at startup: %s (%s)",
                    row["id"][:8],
                    row["label"],
                )
            conn.commit()
            return len(rows)
        finally:
            conn.close()


def cleanup_old_jobs() -> None:
    """Remove finished jobs older than _CLEANUP_AGE seconds.

    Also marks orphaned running jobs as cancelled:
    - Catalog/Reindex jobs: heartbeat stale > HEARTBEAT_STALE_SEC (default 2 min),
      OR (no heartbeat ever AND started > 15 min ago) for jobs that pre-date the
      heartbeat column.
    - Other jobs: running > 30 minutes (no heartbeat instrumentation)
    """
    cutoff = time.time() - _CLEANUP_AGE
    now = time.time()
    heartbeat_cutoff = now - HEARTBEAT_STALE_SEC
    legacy_started_cutoff = now - (15 * 60)  # fallback for pre-heartbeat jobs
    general_orphan_cutoff = now - (30 * 60)  # 30 min for non-catalog jobs

    from services.db import get_db
    import logging

    logger = logging.getLogger(__name__)

    with _write_lock:
        conn = get_db()
        try:
            # Mark orphaned catalog jobs (heartbeat-based; 15min started_at fallback
            # for jobs that never sent one — e.g. created on an older API build).
            cur = conn.execute(
                "SELECT id, label FROM jobs "
                "WHERE status = 'running' "
                "AND label IN ('Indexing vault', 'Reindex vault') "
                "AND ( "
                "  (last_heartbeat IS NOT NULL AND last_heartbeat < ?) "
                "  OR (last_heartbeat IS NULL AND started_at < ?) "
                ")",
                (heartbeat_cutoff, legacy_started_cutoff),
            )
            orphaned_catalog = cur.fetchall()
            for job_id, label in orphaned_catalog:
                conn.execute(
                    "UPDATE jobs SET status = 'cancelled', finished_at = ?, "
                    "cancel_requested = 1, "
                    "progress = 'Cancelled (orphaned — heartbeat stale)' WHERE id = ?",
                    (time.time(), job_id),
                )
                logger.warning(
                    "Marked orphaned catalog job as cancelled: %s (id=%s)",
                    label,
                    job_id,
                )

            # Mark other orphaned jobs (30 min threshold)
            cur = conn.execute(
                "SELECT id, label FROM jobs "
                "WHERE status = 'running' "
                "AND label NOT IN ('Indexing vault', 'Reindex vault') "
                "AND started_at < ?",
                (general_orphan_cutoff,),
            )
            orphaned_other = cur.fetchall()
            for job_id, label in orphaned_other:
                conn.execute(
                    "UPDATE jobs SET status = 'cancelled', finished_at = ?, "
                    "progress = 'Cancelled (orphaned - exceeded 30min)' WHERE id = ?",
                    (time.time(), job_id),
                )
                logger.warning(
                    "Marked orphaned job as cancelled: %s (id=%s)", label, job_id
                )

            # Delete old finished jobs
            conn.execute(
                "DELETE FROM jobs "
                "WHERE status != 'running' AND COALESCE(finished_at, 0) < ?",
                (cutoff,),
            )
            conn.commit()
        finally:
            conn.close()
