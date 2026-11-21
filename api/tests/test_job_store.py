"""Tests for job_store.py — SQLite-backed job registry.

Critical coverage:
- Job CRUD operations (create, get, update, list)
- Status transitions (running → done/error/cancelled)
- Cancellation flag handling
- Cleanup logic (old jobs, orphaned jobs)
- Edge cases (non-existent jobs, unknown fields)
"""

import sqlite3
import threading
import time
from unittest.mock import patch

import pytest

from services.job_store import (
    HEARTBEAT_STALE_SEC,
    _row_to_job,
    cancel_job,
    cleanup_old_jobs,
    create_job,
    fail_job,
    finish_job,
    get_job,
    heartbeat,
    is_cancelled,
    list_jobs,
    reclassify_running_jobs_as_interrupted,
    retry_cancel_in_background,
    try_update_job,
    update_job,
)


@pytest.fixture
def test_db():
    """Create a shared in-memory SQLite database with jobs schema for testing.

    Uses URI with shared cache so multiple connections see the same data.
    This matches production behavior where each job_store function opens and
    closes its own connection to the same database file.
    """
    # Use shared cache so multiple connections see same data
    db_uri = "file::memory:?cache=shared"

    # Create schema on initial connection
    init_conn = sqlite3.connect(db_uri, uri=True)
    init_conn.row_factory = sqlite3.Row
    init_conn.execute("""
        CREATE TABLE jobs (
            id TEXT PRIMARY KEY,
            label TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'running',
            progress TEXT,
            started_at REAL NOT NULL,
            finished_at REAL,
            cancel_requested INTEGER NOT NULL DEFAULT 0,
            last_heartbeat REAL
        )
    """)
    init_conn.commit()

    # Return a factory function that creates new connections to the same DB
    def get_test_conn():
        conn = sqlite3.connect(db_uri, uri=True)
        conn.row_factory = sqlite3.Row
        return conn

    # Store connections for cleanup
    connections = [init_conn]
    get_test_conn._connections = connections

    yield get_test_conn

    # Cleanup all connections
    for conn in connections:
        try:
            conn.close()
        except Exception:
            pass


# ── Row conversion tests ──────────────────────────────────────────────────────


def test_row_to_job_conversion(test_db):
    """_row_to_job converts SQLite row to BackgroundJob dataclass."""
    conn = test_db()
    try:
        conn.execute(
            "INSERT INTO jobs (id, label, status, progress, started_at, finished_at, cancel_requested) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("test-123", "Test job", "running", "50%", 1234567890.0, None, 0),
        )
        conn.commit()

        row = conn.execute("SELECT * FROM jobs WHERE id = 'test-123'").fetchone()
        job = _row_to_job(row)

        assert job.id == "test-123"
        assert job.label == "Test job"
        assert job.status == "running"
        assert job.progress == "50%"
        assert job.started_at == 1234567890.0
        assert job.finished_at is None
        assert job.cancel_requested is False
    finally:
        conn.close()


def test_row_to_job_with_cancel_flag(test_db):
    """_row_to_job correctly converts cancel_requested integer to bool."""
    conn = test_db()
    try:
        conn.execute(
            "INSERT INTO jobs (id, label, status, started_at, cancel_requested) "
            "VALUES (?, ?, ?, ?, ?)",
            ("test-456", "Cancelled job", "cancelled", 1234567890.0, 1),
        )
        conn.commit()

        row = conn.execute("SELECT * FROM jobs WHERE id = 'test-456'").fetchone()
        job = _row_to_job(row)

        assert job.cancel_requested is True
    finally:
        conn.close()


# ── create_job tests ──────────────────────────────────────────────────────────


def test_create_job_basic(test_db):
    """create_job inserts new job with generated UUID."""
    with patch("services.db.get_db", side_effect=test_db):
        job = create_job("Test operation")

    assert job.label == "Test operation"
    assert job.status == "running"
    assert job.progress is None
    assert job.cancel_requested is False
    assert job.started_at > 0

    # Verify persisted to database
    conn = test_db()
    try:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job.id,)).fetchone()
        assert row is not None
        assert row["label"] == "Test operation"
        assert row["status"] == "running"
    finally:
        conn.close()


def test_create_multiple_jobs(test_db):
    """Multiple create_job calls create distinct jobs."""
    with patch("services.db.get_db", side_effect=test_db):
        job1 = create_job("Job 1")
        job2 = create_job("Job 2")

    assert job1.id != job2.id

    # Both persisted
    conn = test_db()
    try:
        count = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        assert count == 2
    finally:
        conn.close()


# ── get_job tests ─────────────────────────────────────────────────────────────


def test_get_job_exists(test_db):
    """get_job retrieves existing job by ID."""
    conn = test_db()
    try:
        conn.execute(
            "INSERT INTO jobs (id, label, status, started_at, cancel_requested) "
            "VALUES (?, ?, ?, ?, ?)",
            ("job-123", "Existing job", "running", time.time(), 0),
        )
        conn.commit()
    finally:
        conn.close()

    with patch("services.db.get_db", side_effect=test_db):
        job = get_job("job-123")

    assert job is not None
    assert job.id == "job-123"
    assert job.label == "Existing job"


def test_get_job_not_exists(test_db):
    """get_job returns None for non-existent job ID."""
    with patch("services.db.get_db", side_effect=test_db):
        job = get_job("non-existent")

    assert job is None


# ── list_jobs tests ───────────────────────────────────────────────────────────


def test_list_jobs_empty(test_db):
    """list_jobs returns empty list when no jobs exist."""
    with patch("services.db.get_db", side_effect=test_db):
        jobs = list_jobs()

    assert jobs == []


def test_list_jobs_ordered_by_started_at(test_db):
    """list_jobs returns jobs ordered by started_at DESC (most recent first)."""
    # Insert jobs with different start times
    conn = test_db()
    try:
        conn.execute(
            "INSERT INTO jobs (id, label, status, started_at, cancel_requested) VALUES "
            "('job-1', 'First', 'done', 1000.0, 0), "
            "('job-2', 'Second', 'running', 2000.0, 0), "
            "('job-3', 'Third', 'error', 1500.0, 0)"
        )
        conn.commit()
    finally:
        conn.close()

    with patch("services.db.get_db", side_effect=test_db):
        jobs = list_jobs()

    assert len(jobs) == 3
    assert jobs[0].id == "job-2"  # Most recent (2000.0)
    assert jobs[1].id == "job-3"  # Middle (1500.0)
    assert jobs[2].id == "job-1"  # Oldest (1000.0)


# ── update_job tests ──────────────────────────────────────────────────────────


def test_update_job_progress(test_db):
    """update_job modifies progress field."""
    conn = test_db()
    try:
        conn.execute(
            "INSERT INTO jobs (id, label, status, started_at, cancel_requested) "
            "VALUES (?, ?, ?, ?, ?)",
            ("job-123", "Test", "running", time.time(), 0),
        )
        conn.commit()
    finally:
        conn.close()

    with patch("services.db.get_db", side_effect=test_db):
        update_job("job-123", progress="Processing file 5/10")

    conn = test_db()
    try:
        row = conn.execute("SELECT progress FROM jobs WHERE id = 'job-123'").fetchone()
        assert row["progress"] == "Processing file 5/10"
    finally:
        conn.close()


def test_update_job_status(test_db):
    """update_job modifies status field."""
    conn = test_db()
    try:
        conn.execute(
            "INSERT INTO jobs (id, label, status, started_at, cancel_requested) "
            "VALUES (?, ?, ?, ?, ?)",
            ("job-456", "Test", "running", time.time(), 0),
        )
        conn.commit()
    finally:
        conn.close()

    with patch("services.db.get_db", side_effect=test_db):
        update_job("job-456", status="done")

    conn = test_db()
    try:
        row = conn.execute("SELECT status FROM jobs WHERE id = 'job-456'").fetchone()
        assert row["status"] == "done"
    finally:
        conn.close()


def test_update_job_cancel_requested_bool_to_int(test_db):
    """update_job converts cancel_requested bool to integer for SQLite."""
    conn = test_db()
    try:
        conn.execute(
            "INSERT INTO jobs (id, label, status, started_at, cancel_requested) "
            "VALUES (?, ?, ?, ?, ?)",
            ("job-789", "Test", "running", time.time(), 0),
        )
        conn.commit()
    finally:
        conn.close()

    with patch("services.db.get_db", side_effect=test_db):
        update_job("job-789", cancel_requested=True)

    conn = test_db()
    try:
        row = conn.execute(
            "SELECT cancel_requested FROM jobs WHERE id = 'job-789'"
        ).fetchone()
        assert row["cancel_requested"] == 1
    finally:
        conn.close()


def test_update_job_ignores_unknown_fields(test_db):
    """update_job silently ignores unknown fields."""
    conn = test_db()
    try:
        conn.execute(
            "INSERT INTO jobs (id, label, status, started_at, cancel_requested) "
            "VALUES (?, ?, ?, ?, ?)",
            ("job-999", "Test", "running", time.time(), 0),
        )
        conn.commit()
    finally:
        conn.close()

    # Should not raise
    with patch("services.db.get_db", side_effect=test_db):
        update_job("job-999", unknown_field="value", progress="valid")

    conn = test_db()
    try:
        row = conn.execute("SELECT progress FROM jobs WHERE id = 'job-999'").fetchone()
        assert row["progress"] == "valid"
    finally:
        conn.close()


def test_update_job_no_kwargs(test_db):
    """update_job with no kwargs is a no-op."""
    with patch("services.db.get_db", side_effect=test_db):
        # Should not raise, should not touch database
        update_job("any-id")


def test_update_job_multiple_fields(test_db):
    """update_job can modify multiple fields at once."""
    conn = test_db()
    try:
        conn.execute(
            "INSERT INTO jobs (id, label, status, started_at, cancel_requested) "
            "VALUES (?, ?, ?, ?, ?)",
            ("job-multi", "Test", "running", 1000.0, 0),
        )
        conn.commit()
    finally:
        conn.close()

    with patch("services.db.get_db", side_effect=test_db):
        update_job(
            "job-multi",
            status="done",
            progress="Complete",
            finished_at=2000.0,
        )

    conn = test_db()
    try:
        row = conn.execute("SELECT * FROM jobs WHERE id = 'job-multi'").fetchone()
        assert row["status"] == "done"
        assert row["progress"] == "Complete"
        assert row["finished_at"] == 2000.0
    finally:
        conn.close()


# ── finish_job tests ──────────────────────────────────────────────────────────


def test_finish_job_sets_status_and_timestamp(test_db):
    """finish_job marks job as done with finished_at timestamp."""
    conn = test_db()
    try:
        conn.execute(
            "INSERT INTO jobs (id, label, status, started_at, cancel_requested) "
            "VALUES (?, ?, ?, ?, ?)",
            ("job-finish", "Test", "running", time.time(), 0),
        )
        conn.commit()
    finally:
        conn.close()

    before = time.time()
    with patch("services.db.get_db", side_effect=test_db):
        finish_job("job-finish", progress="All done")
    after = time.time()

    conn = test_db()
    try:
        row = conn.execute("SELECT * FROM jobs WHERE id = 'job-finish'").fetchone()
        assert row["status"] == "done"
        assert row["progress"] == "All done"
        assert before <= row["finished_at"] <= after
    finally:
        conn.close()


# ── fail_job tests ────────────────────────────────────────────────────────────


def test_fail_job_sets_error_status(test_db):
    """fail_job marks job as error with error message."""
    conn = test_db()
    try:
        conn.execute(
            "INSERT INTO jobs (id, label, status, started_at, cancel_requested) "
            "VALUES (?, ?, ?, ?, ?)",
            ("job-fail", "Test", "running", time.time(), 0),
        )
        conn.commit()
    finally:
        conn.close()

    before = time.time()
    with patch("services.db.get_db", side_effect=test_db):
        fail_job("job-fail", error="Something went wrong")
    after = time.time()

    conn = test_db()
    try:
        row = conn.execute("SELECT * FROM jobs WHERE id = 'job-fail'").fetchone()
        assert row["status"] == "error"
        assert row["progress"] == "Something went wrong"
        assert before <= row["finished_at"] <= after
    finally:
        conn.close()


# ── cancel_job tests ──────────────────────────────────────────────────────────


def test_cancel_job_sets_flag_not_status(test_db):
    """cancel_job sets cancel_requested flag but does NOT change status."""
    conn = test_db()
    try:
        conn.execute(
            "INSERT INTO jobs (id, label, status, started_at, cancel_requested) "
            "VALUES (?, ?, ?, ?, ?)",
            ("job-cancel", "Test", "running", time.time(), 0),
        )
        conn.commit()
    finally:
        conn.close()

    with patch("services.db.get_db", side_effect=test_db):
        cancel_job("job-cancel", reason="User clicked stop")

    conn = test_db()
    try:
        row = conn.execute("SELECT * FROM jobs WHERE id = 'job-cancel'").fetchone()
        assert row["status"] == "running"  # Status unchanged
        assert row["cancel_requested"] == 1
        assert row["progress"] == "User clicked stop"
    finally:
        conn.close()


# ── is_cancelled tests ────────────────────────────────────────────────────────


def test_is_cancelled_true(test_db):
    """is_cancelled returns True when cancel_requested flag is set."""
    conn = test_db()
    try:
        conn.execute(
            "INSERT INTO jobs (id, label, status, started_at, cancel_requested) "
            "VALUES (?, ?, ?, ?, ?)",
            ("job-123", "Test", "running", time.time(), 1),
        )
        conn.commit()
    finally:
        conn.close()

    with patch("services.db.get_db", side_effect=test_db):
        result = is_cancelled("job-123")

    assert result is True


def test_is_cancelled_false(test_db):
    """is_cancelled returns False when cancel_requested flag is not set."""
    conn = test_db()
    try:
        conn.execute(
            "INSERT INTO jobs (id, label, status, started_at, cancel_requested) "
            "VALUES (?, ?, ?, ?, ?)",
            ("job-456", "Test", "running", time.time(), 0),
        )
        conn.commit()
    finally:
        conn.close()

    with patch("services.db.get_db", side_effect=test_db):
        result = is_cancelled("job-456")

    assert result is False


def test_is_cancelled_non_existent_job(test_db):
    """is_cancelled returns False for non-existent job."""
    with patch("services.db.get_db", side_effect=test_db):
        result = is_cancelled("non-existent")

    assert result is False


# ── cleanup_old_jobs tests ────────────────────────────────────────────────────


def test_cleanup_old_jobs_deletes_finished_jobs(test_db):
    """cleanup_old_jobs removes finished jobs older than 1 hour."""
    now = time.time()
    old_time = now - 7200  # 2 hours ago
    recent_time = now - 1800  # 30 minutes ago

    conn = test_db()
    try:
        conn.execute(
            "INSERT INTO jobs (id, label, status, started_at, finished_at, cancel_requested) VALUES "
            "('old-done', 'Old done', 'done', ?, ?, 0), "
            "('old-error', 'Old error', 'error', ?, ?, 0), "
            "('recent-done', 'Recent done', 'done', ?, ?, 0)",
            (old_time, old_time, old_time, old_time, recent_time, recent_time),
        )
        conn.commit()
    finally:
        conn.close()

    with patch("services.db.get_db", side_effect=test_db):
        cleanup_old_jobs()

    conn = test_db()
    try:
        remaining = conn.execute("SELECT id FROM jobs").fetchall()
        remaining_ids = [r["id"] for r in remaining]

        # Old jobs should be deleted
        assert "old-done" not in remaining_ids
        assert "old-error" not in remaining_ids

        # Recent job should remain
        assert "recent-done" in remaining_ids
    finally:
        conn.close()


def test_cleanup_old_jobs_keeps_running_jobs(test_db):
    """cleanup_old_jobs does not delete running jobs (even old ones)."""
    now = time.time()
    old_time = now - 7200  # 2 hours ago

    conn = test_db()
    try:
        conn.execute(
            "INSERT INTO jobs (id, label, status, started_at, finished_at, cancel_requested) VALUES "
            "('old-running', 'Old running', 'running', ?, NULL, 0)",
            (old_time,),
        )
        conn.commit()
    finally:
        conn.close()

    with patch("services.db.get_db", side_effect=test_db):
        cleanup_old_jobs()

    # Running job should remain (will be marked orphaned separately)
    conn = test_db()
    try:
        row = conn.execute("SELECT * FROM jobs WHERE id = 'old-running'").fetchone()
        assert row is not None
    finally:
        conn.close()


def test_cleanup_orphaned_catalog_jobs(test_db):
    """cleanup_old_jobs marks catalog jobs running >15min as cancelled."""
    now = time.time()
    orphan_time = now - (16 * 60)  # 16 minutes ago
    recent_time = now - (10 * 60)  # 10 minutes ago

    conn = test_db()
    try:
        conn.execute(
            "INSERT INTO jobs (id, label, status, started_at, finished_at, cancel_requested) VALUES "
            "('orphan-index', 'Indexing vault', 'running', ?, NULL, 0), "
            "('orphan-reindex', 'Reindex vault', 'running', ?, NULL, 0), "
            "('recent-index', 'Indexing vault', 'running', ?, NULL, 0)",
            (orphan_time, orphan_time, recent_time),
        )
        conn.commit()
    finally:
        conn.close()

    with patch("services.db.get_db", side_effect=test_db):
        cleanup_old_jobs()

    conn = test_db()
    try:
        # Orphaned jobs should be marked cancelled
        orphan1 = conn.execute(
            "SELECT * FROM jobs WHERE id = 'orphan-index'"
        ).fetchone()
        assert orphan1["status"] == "cancelled"
        assert "orphaned" in orphan1["progress"]
        assert orphan1["finished_at"] is not None

        orphan2 = conn.execute(
            "SELECT * FROM jobs WHERE id = 'orphan-reindex'"
        ).fetchone()
        assert orphan2["status"] == "cancelled"

        # Recent job should remain running
        recent = conn.execute("SELECT * FROM jobs WHERE id = 'recent-index'").fetchone()
        assert recent["status"] == "running"
    finally:
        conn.close()


def test_cleanup_orphaned_other_jobs(test_db):
    """cleanup_old_jobs marks non-catalog jobs running >30min as cancelled."""
    now = time.time()
    orphan_time = now - (35 * 60)  # 35 minutes ago
    recent_time = now - (25 * 60)  # 25 minutes ago

    conn = test_db()
    try:
        conn.execute(
            "INSERT INTO jobs (id, label, status, started_at, finished_at, cancel_requested) VALUES "
            "('orphan-other', 'Some other job', 'running', ?, NULL, 0), "
            "('recent-other', 'Another job', 'running', ?, NULL, 0)",
            (orphan_time, recent_time),
        )
        conn.commit()
    finally:
        conn.close()

    with patch("services.db.get_db", side_effect=test_db):
        cleanup_old_jobs()

    conn = test_db()
    try:
        # Orphaned job should be marked cancelled
        orphan = conn.execute("SELECT * FROM jobs WHERE id = 'orphan-other'").fetchone()
        assert orphan["status"] == "cancelled"
        assert "30min" in orphan["progress"]

        # Recent job should remain running
        recent = conn.execute("SELECT * FROM jobs WHERE id = 'recent-other'").fetchone()
        assert recent["status"] == "running"
    finally:
        conn.close()


def test_cleanup_combined_logic(test_db):
    """cleanup_old_jobs handles old finished + orphaned running jobs together."""
    now = time.time()
    very_old = now - 7200  # 2 hours ago
    orphan_time = now - (20 * 60)  # 20 minutes ago
    recent_time = now - 1800  # 30 minutes ago

    conn = test_db()
    try:
        conn.execute(
            "INSERT INTO jobs (id, label, status, started_at, finished_at, cancel_requested) VALUES "
            "('old-done', 'Old', 'done', ?, ?, 0), "
            "('orphan-catalog', 'Indexing vault', 'running', ?, NULL, 0), "
            "('recent-done', 'Recent', 'done', ?, ?, 0)",
            (very_old, very_old, orphan_time, recent_time, recent_time),
        )
        conn.commit()
    finally:
        conn.close()

    with patch("services.db.get_db", side_effect=test_db):
        cleanup_old_jobs()

    conn = test_db()
    try:
        remaining = conn.execute("SELECT id, status FROM jobs").fetchall()
        remaining_dict = {r["id"]: r["status"] for r in remaining}

        # Old finished job should be deleted
        assert "old-done" not in remaining_dict

        # Orphaned catalog job should be marked cancelled
        assert remaining_dict.get("orphan-catalog") == "cancelled"

        # Recent finished job should remain
        assert "recent-done" in remaining_dict
    finally:
        conn.close()


# ── Integration tests ─────────────────────────────────────────────────────────


def test_full_job_lifecycle(test_db):
    """Test complete job lifecycle: create → update → finish."""
    with patch("services.db.get_db", side_effect=test_db):
        # Create
        job = create_job("Full lifecycle test")
        assert job.status == "running"

        # Update progress
        update_job(job.id, progress="Processing...")
        updated = get_job(job.id)
        assert updated.progress == "Processing..."

        # Finish
        finish_job(job.id, progress="Complete")
        finished = get_job(job.id)
        assert finished.status == "done"
        assert finished.progress == "Complete"
        assert finished.finished_at is not None


def test_cancellation_workflow(test_db):
    """Test cancellation workflow: create → cancel → check → finish as cancelled."""
    with patch("services.db.get_db", side_effect=test_db):
        # Create job
        job = create_job("Cancellable job")

        # Request cancellation
        cancel_job(job.id, reason="User stopped")

        # Worker checks if cancelled
        assert is_cancelled(job.id) is True

        # Worker finishes gracefully with cancelled status
        update_job(job.id, status="cancelled", finished_at=time.time())

        # Verify final state
        final = get_job(job.id)
        assert final.status == "cancelled"
        assert final.cancel_requested is True
        assert "stopped" in final.progress.lower()


# ── Heartbeat tests ───────────────────────────────────────────────────────────


def test_heartbeat_updates_last_heartbeat(test_db):
    with patch("services.db.get_db", side_effect=test_db):
        job = create_job("Heartbeating job")

        before = get_job(job.id)
        assert before.last_heartbeat is None

        t0 = time.time()
        heartbeat(job.id)
        after = get_job(job.id)
        assert after.last_heartbeat is not None
        assert after.last_heartbeat >= t0


def test_cleanup_uses_heartbeat_threshold(test_db):
    """A catalog job whose heartbeat is stale is reaped — even if started_at
    is recent — so the user doesn't have to wait 15 minutes for recovery."""
    with patch("services.db.get_db", side_effect=test_db):
        job = create_job("Indexing vault")
        # started_at = now (recent), but heartbeat is stale
        stale_at = time.time() - (HEARTBEAT_STALE_SEC + 30)
        update_job(job.id, last_heartbeat=stale_at)

        cleanup_old_jobs()

        reaped = get_job(job.id)
        assert reaped.status == "cancelled"
        assert reaped.cancel_requested is True


def test_cleanup_keeps_fresh_heartbeat_jobs(test_db):
    """A catalog job with a recent heartbeat is not reaped by cleanup."""
    with patch("services.db.get_db", side_effect=test_db):
        job = create_job("Indexing vault")
        update_job(job.id, last_heartbeat=time.time())

        cleanup_old_jobs()

        kept = get_job(job.id)
        assert kept.status == "running"


# ── try_update_job + write-lock concurrency tests ─────────────────────────────


def test_try_update_job_returns_true_on_success(test_db):
    """try_update_job returns True when the write succeeds, and applies the patch."""
    conn = test_db()
    try:
        conn.execute(
            "INSERT INTO jobs (id, label, status, started_at, cancel_requested) "
            "VALUES (?, ?, ?, ?, ?)",
            ("job-try-ok", "Test", "running", time.time(), 0),
        )
        conn.commit()
    finally:
        conn.close()

    with patch("services.db.get_db", side_effect=test_db):
        ok = try_update_job("job-try-ok", progress="patched")

    assert ok is True

    conn = test_db()
    try:
        row = conn.execute(
            "SELECT progress FROM jobs WHERE id = 'job-try-ok'"
        ).fetchone()
        assert row["progress"] == "patched"
    finally:
        conn.close()


class _LockingConn:
    """Wraps a real sqlite3.Connection and raises OperationalError on writes.

    Used to simulate the production lock-contention scenario where some other
    writer (catalog scan thread) is holding the SQLite write slot.
    """

    def __init__(
        self,
        real_conn,
        fail_on: str = "UPDATE",
        err_cls=sqlite3.OperationalError,
        message: str = "database is locked",
    ):
        self._real = real_conn
        self._fail_on = fail_on
        self._err_cls = err_cls
        self._message = message

    def execute(self, sql, params=()):
        if sql.lstrip().upper().startswith(self._fail_on):
            raise self._err_cls(self._message)
        return self._real.execute(sql, params)

    def commit(self):
        return self._real.commit()

    def close(self):
        return self._real.close()

    def __getattr__(self, name):
        return getattr(self._real, name)


def test_try_update_job_returns_false_on_db_locked(test_db):
    """try_update_job swallows sqlite3.OperationalError('database is locked')
    and returns False — this is the recovery path used by /catalog/run when a
    prior scan thread holds the writer slot."""
    conn = test_db()
    try:
        conn.execute(
            "INSERT INTO jobs (id, label, status, started_at, cancel_requested) "
            "VALUES (?, ?, ?, ?, ?)",
            ("job-locked", "Test", "running", time.time(), 0),
        )
        conn.commit()
    finally:
        conn.close()

    def get_db_that_locks():
        return _LockingConn(test_db(), fail_on="UPDATE")

    with patch("services.db.get_db", side_effect=get_db_that_locks):
        ok = try_update_job(
            "job-locked",
            cancel_requested=True,
            status="error",
            progress="replaced by new run",
        )

    assert ok is False  # Did not raise; signalled failure to caller.


def test_try_update_job_does_not_swallow_other_errors(test_db):
    """try_update_job only catches OperationalError. Programmer errors
    (column mismatch, integrity violations) still propagate so they're
    visible during development."""

    def get_db_that_errors():
        return _LockingConn(
            test_db(),
            fail_on="UPDATE",
            err_cls=sqlite3.IntegrityError,
            message="foreign key violation",
        )

    with patch("services.db.get_db", side_effect=get_db_that_errors):
        with pytest.raises(sqlite3.IntegrityError):
            try_update_job("some-job", progress="x")


def test_concurrent_update_jobs_serialize_cleanly(test_db):
    """Many threads calling update_job at once should all succeed, with no
    crashes from the Python-level write lock. Each thread's patch must end up
    persisted (last-write-wins for the same field is OK; the test just asserts
    no exceptions and that the row exists with the final value of one writer).

    The patch is applied once at the test level — `unittest.mock.patch`
    mutates a global attribute and is NOT thread-safe, so 20 concurrent
    `with patch(...)` blocks would leave services.db.get_db in a broken state
    that contaminates the rest of the suite.
    """
    conn = test_db()
    try:
        conn.execute(
            "INSERT INTO jobs (id, label, status, started_at, cancel_requested) "
            "VALUES (?, ?, ?, ?, ?)",
            ("job-race", "Test", "running", time.time(), 0),
        )
        conn.commit()
    finally:
        conn.close()

    errors: list[Exception] = []

    def writer(n: int):
        try:
            update_job("job-race", progress=f"writer-{n}")
        except Exception as e:  # pragma: no cover - the assertion catches it
            errors.append(e)

    with patch("services.db.get_db", side_effect=test_db):
        threads = [threading.Thread(target=writer, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    assert errors == [], f"Concurrent update_job calls raised: {errors}"

    conn = test_db()
    try:
        row = conn.execute("SELECT progress FROM jobs WHERE id = 'job-race'").fetchone()
        # Whichever writer landed last wins — we don't care which one, only
        # that some valid value is there.
        assert row["progress"].startswith("writer-")
    finally:
        conn.close()


# ── reclassify_running_jobs_as_interrupted tests ──────────────────────────────


def test_reclassify_marks_all_running_jobs_cancelled(test_db):
    """Every row with status='running' becomes status='cancelled' with the
    'interrupted by API restart' progress message — regardless of age, heartbeat
    freshness, or label. This is the startup-time orphan sweep that catches
    fresh-heartbeat runs that died with the container."""
    conn = test_db()
    try:
        now = time.time()
        conn.execute(
            "INSERT INTO jobs (id, label, status, started_at, last_heartbeat, cancel_requested) VALUES "
            "('fresh', 'Indexing vault', 'running', ?, ?, 0), "
            "('old',   'Dispatch',       'running', ?, ?, 0), "
            "('done',  'Old finished',   'done',    ?, NULL, 0)",
            (now - 30, now - 5, now - 7200, now - 7000, now - 1000),
        )
        conn.commit()
    finally:
        conn.close()

    with patch("services.db.get_db", side_effect=test_db):
        count = reclassify_running_jobs_as_interrupted()

    assert count == 2, f"expected 2 jobs reclassified, got {count}"

    conn = test_db()
    try:
        rows = {
            r["id"]: r
            for r in conn.execute(
                "SELECT id, status, cancel_requested, progress FROM jobs"
            ).fetchall()
        }
        for jid in ("fresh", "old"):
            assert rows[jid]["status"] == "cancelled", f"{jid} should be cancelled"
            assert rows[jid]["cancel_requested"] == 1
            assert "interrupted" in rows[jid]["progress"].lower()
        # The finished row is untouched.
        assert rows["done"]["status"] == "done"
    finally:
        conn.close()


def test_reclassify_returns_zero_when_no_running_jobs(test_db):
    """No-op case: clean startup with nothing in 'running' state."""
    conn = test_db()
    try:
        conn.execute(
            "INSERT INTO jobs (id, label, status, started_at, cancel_requested) "
            "VALUES ('d', 'Done', 'done', ?, 0)",
            (time.time(),),
        )
        conn.commit()
    finally:
        conn.close()

    with patch("services.db.get_db", side_effect=test_db):
        count = reclassify_running_jobs_as_interrupted()
    assert count == 0


# ── retry_cancel_in_background tests ──────────────────────────────────────────


def test_retry_cancel_background_succeeds_when_lock_clears(test_db):
    """The background thread keeps retrying cancel_job until the writer lock
    clears, then writes cancel_requested=1. User-perceived recovery: under 1s
    in the typical case where the writer holds the slot only briefly.
    """
    import services.job_store as js

    conn = test_db()
    try:
        conn.execute(
            "INSERT INTO jobs (id, label, status, started_at, cancel_requested) "
            "VALUES (?, ?, ?, ?, ?)",
            ("job-retry", "Test", "running", time.time(), 0),
        )
        conn.commit()
    finally:
        conn.close()

    # Simulate a writer slot that's locked for the first 2 attempts, then
    # clears. retry_cancel_in_background should win on attempt 3.
    locked_attempts = {"n": 0}
    real_update = js.update_job

    def flaky_update(job_id, **kwargs):
        if locked_attempts["n"] < 2:
            locked_attempts["n"] += 1
            raise sqlite3.OperationalError("database is locked")
        return real_update(job_id, **kwargs)

    with (
        patch("services.db.get_db", side_effect=test_db),
        patch.object(js, "update_job", flaky_update),
    ):
        t = retry_cancel_in_background(
            "job-retry",
            "Stopped by user",
            initial_backoff=0.05,  # speed up tests
            max_backoff=0.1,
            max_total_seconds=2.0,
        )
        t.join(timeout=3.0)
        assert not t.is_alive(), "retry thread should have exited within budget"

    assert locked_attempts["n"] == 2, (
        f"expected the simulated lock to clear after 2 attempts, got {locked_attempts['n']}"
    )

    conn = test_db()
    try:
        row = conn.execute(
            "SELECT cancel_requested, progress FROM jobs WHERE id = 'job-retry'"
        ).fetchone()
        assert row["cancel_requested"] == 1, "cancel_requested should land after retry"
        assert row["progress"] == "Stopped by user"
    finally:
        conn.close()


def test_retry_cancel_background_gives_up_after_budget(test_db):
    """If the lock never clears within the budget, the thread exits cleanly.
    Heartbeat-stale sweep (cleanup_old_jobs) is the next backstop.
    """
    import services.job_store as js

    conn = test_db()
    try:
        conn.execute(
            "INSERT INTO jobs (id, label, status, started_at, cancel_requested) "
            "VALUES (?, ?, ?, ?, ?)",
            ("job-stuck", "Test", "running", time.time(), 0),
        )
        conn.commit()
    finally:
        conn.close()

    attempts = {"n": 0}

    def always_locked(job_id, **kwargs):
        attempts["n"] += 1
        raise sqlite3.OperationalError("database is locked")

    with (
        patch("services.db.get_db", side_effect=test_db),
        patch.object(js, "update_job", always_locked),
    ):
        t = retry_cancel_in_background(
            "job-stuck",
            initial_backoff=0.05,
            max_backoff=0.1,
            max_total_seconds=0.3,  # short budget for fast test
        )
        t.join(timeout=2.0)
        assert not t.is_alive(), "retry thread should have exited within budget"

    assert attempts["n"] >= 2, f"expected ≥2 attempts, got {attempts['n']}"

    # Row was not mutated — cancel never landed. Heartbeat sweep will catch it.
    conn = test_db()
    try:
        row = conn.execute(
            "SELECT cancel_requested FROM jobs WHERE id = 'job-stuck'"
        ).fetchone()
        assert row["cancel_requested"] == 0
    finally:
        conn.close()


def test_retry_cancel_background_succeeds_on_first_attempt(test_db):
    """No-contention case: lock is free, first attempt lands, thread exits
    almost immediately. Smoke test that the helper isn't accidentally
    slow when there's no contention.
    """
    conn = test_db()
    try:
        conn.execute(
            "INSERT INTO jobs (id, label, status, started_at, cancel_requested) "
            "VALUES (?, ?, ?, ?, ?)",
            ("job-fast", "Test", "running", time.time(), 0),
        )
        conn.commit()
    finally:
        conn.close()

    with patch("services.db.get_db", side_effect=test_db):
        start = time.time()
        t = retry_cancel_in_background(
            "job-fast",
            "Stopped",
            initial_backoff=1.0,  # would block 1s if we hit a retry
            max_total_seconds=5.0,
        )
        t.join(timeout=2.0)
        elapsed = time.time() - start

    assert not t.is_alive()
    assert elapsed < 0.5, (
        f"un-contended retry took {elapsed:.2f}s — should be near-instant"
    )

    conn = test_db()
    try:
        row = conn.execute(
            "SELECT cancel_requested FROM jobs WHERE id = 'job-fast'"
        ).fetchone()
        assert row["cancel_requested"] == 1
    finally:
        conn.close()


def test_cleanup_legacy_job_without_heartbeat(test_db):
    """Pre-heartbeat-instrumented jobs (last_heartbeat IS NULL) still get the
    legacy 15-minute started_at fallback so we don't strand them."""
    with patch("services.db.get_db", side_effect=test_db):
        job = create_job("Indexing vault")
        # Backdate started_at to 16 minutes ago, leave heartbeat NULL.
        update_job(job.id, started_at=time.time() - (16 * 60))

        cleanup_old_jobs()

        reaped = get_job(job.id)
        assert reaped.status == "cancelled"


def test_cleanup_deletes_finished_rows_with_no_finished_at_immediately(
    test_db, monkeypatch
):
    """A landmine, pinned so the first caller that trips it fails loudly.

    cleanup_old_jobs deletes with:

        WHERE status != 'running' AND COALESCE(finished_at, 0) < cutoff

    `COALESCE(finished_at, 0)` makes a NULL `finished_at` compare as 0, and 0
    is always below the cutoff — so a row moved to a terminal status WITHOUT
    setting finished_at is deleted on the very next cleanup, not after the
    intended hour.

    No production path does that today (every terminal update passes
    finished_at), which is why this has never bitten. It is one forgotten
    keyword away from silently losing job rows, so the behaviour is pinned
    here rather than left to be rediscovered.
    """
    import services.job_store as js

    job = js.create_job("terminal but undated")
    # Terminal status, finished_at deliberately left NULL.
    js.update_job(job.id, status="error")
    assert js.get_job(job.id) is not None

    js.cleanup_old_jobs()

    assert js.get_job(job.id) is None, (
        "a terminal row with NULL finished_at is deleted immediately — if this "
        "now survives, the COALESCE default was changed and that is an "
        "improvement worth updating this test for"
    )


def test_cleanup_keeps_a_recently_finished_row(test_db):
    """The intended behaviour, for contrast: with finished_at set, the
    one-hour grace period applies."""
    import time
    import services.job_store as js

    job = js.create_job("finished just now")
    js.update_job(job.id, status="done", finished_at=time.time())

    js.cleanup_old_jobs()

    assert js.get_job(job.id) is not None, "a just-finished job must survive cleanup"
