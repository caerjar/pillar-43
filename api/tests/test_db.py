"""Tests for api/services/db.py — journal mode, schema init, connection management."""

import os
import sqlite3
from pathlib import Path


os.environ.setdefault("TESTING", "1")


def _make_db(tmp_path: Path) -> sqlite3.Connection:
    """Open a fresh test database using get_db() pointed at tmp_path."""
    from services import db as db_module

    # Override db_path for this test by monkeypatching settings.db_path.
    # We use a direct connect + init_schema pattern here to avoid mutating
    # global _initialized_paths across tests.
    db_path = tmp_path / "test_wal.db"
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    db_module.init_schema(conn)
    return conn


# ── Journal mode ─────────────────────────────────────────────────────────────


def test_get_db_enables_wal_journal_mode(tmp_path, monkeypatch):
    """The first get_db() call must configure WAL journal mode. Subsequent
    connections inherit it from the file header.

    WAL is the correct mode for our workload (many concurrent readers + one
    long-lived writer). It works correctly because the production DB lives in
    a Docker named volume now (config.py: `data_path`), not a bind mount.
    See services/db.py:get_db for the full reasoning.
    """
    from services import db as db_module

    monkeypatch.setattr(db_module, "get_db_path", lambda: tmp_path / "pillar43.db")
    db_module._initialized_paths.clear()

    conn = db_module.get_db()
    try:
        row = conn.execute("PRAGMA journal_mode").fetchone()
        assert row[0] == "wal", f"Expected WAL mode, got: {row[0]}"
    finally:
        conn.close()
        db_module._initialized_paths.clear()


def test_get_db_succeeds_while_writer_holds_lock(tmp_path, monkeypatch):
    """Regression test for the bug where every per-file _is_cancelled() call
    crashed the catalog scan with `sqlite3.OperationalError: database is
    locked`. Root cause: PRAGMA journal_mode was being re-run on every new
    connection, and that PRAGMA requires an exclusive lock — which conflicts
    with the scan thread's open write transaction.

    The fix: PRAGMA journal_mode runs only on the first get_db() call per
    process per DB. New connections inherit the mode from the file header.
    """
    from services import db as db_module

    monkeypatch.setattr(db_module, "get_db_path", lambda: tmp_path / "writer_lock.db")
    db_module._initialized_paths.clear()

    # First connection sets journal_mode + runs schema init.
    conn1 = db_module.get_db()
    try:
        # Take a write lock that would block any PRAGMA journal_mode change.
        conn1.execute("BEGIN IMMEDIATE")
        try:
            # Second connection: under the bug, this raised OperationalError.
            # Under the fix, it succeeds because the PRAGMA isn't re-run.
            conn2 = db_module.get_db()
            try:
                assert conn2.execute("SELECT 1").fetchone()[0] == 1
            finally:
                conn2.close()
        finally:
            conn1.rollback()
    finally:
        conn1.close()
        db_module._initialized_paths.clear()


def test_get_db_sets_synchronous_normal(tmp_path, monkeypatch):
    """get_db() must set synchronous=NORMAL for reduced fsync overhead."""
    from services import db as db_module

    monkeypatch.setattr(db_module, "get_db_path", lambda: tmp_path / "pillar432.db")
    db_module._initialized_paths.clear()

    conn = db_module.get_db()
    try:
        row = conn.execute("PRAGMA synchronous").fetchone()
        # NORMAL = 1
        assert row[0] == 1, f"Expected synchronous=NORMAL (1), got: {row[0]}"
    finally:
        conn.close()
        db_module._initialized_paths.clear()


# ── Schema init ───────────────────────────────────────────────────────────────


def test_init_schema_creates_files_table(tmp_path):
    """init_schema() must create the files table with the expected columns."""
    conn = _make_db(tmp_path)
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(files)")}
        assert "rel_path" in cols
        assert "sha256" in cols
        assert "extracted_text" in cols
        assert "inbox_suggested_path" in cols
    finally:
        conn.close()


def test_init_schema_creates_threads_table(tmp_path):
    """init_schema() must create the threads table."""
    conn = _make_db(tmp_path)
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(threads)")}
        assert "name" in cols
        assert "status" in cols
        assert "files_json" in cols
    finally:
        conn.close()


def test_init_schema_idempotent(tmp_path):
    """Calling init_schema() twice must not raise an error."""
    from services.db import init_schema

    conn = sqlite3.connect(str(tmp_path / "idem.db"), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        init_schema(conn)
        init_schema(conn)  # second call must be safe
    finally:
        conn.close()


# ── Migrations must not touch host logging ────────────────────────────────────


def test_init_schema_leaves_root_logging_untouched(tmp_path):
    """A programmatic `alembic upgrade` must not reconfigure the root logger.

    alembic.ini declares `[logger_root] level = WARN, handlers = console`, and
    env.py's fileConfig applies that to the ROOT logger of whatever process
    calls it. So the first init_schema() dropped the host process to WARN and
    swapped its handler — every app INFO line vanished for the life of the
    process. The api papered over it with a _reconfigure_logging() repair pass;
    the worker had none, so its logs died ~30s after boot and a mute Commons
    bot became undiagnosable. env.py now honours the `configure_logging`
    attribute set by services.db._alembic_config.
    """
    import logging

    from services.db import init_schema

    root = logging.getLogger()
    prev_level, prev_handlers = root.level, root.handlers[:]
    sentinel = logging.StreamHandler()
    root.handlers = [sentinel]
    root.setLevel(logging.INFO)

    conn = sqlite3.connect(str(tmp_path / "logging.db"), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        init_schema(conn)
        assert root.level == logging.INFO, (
            f"migrations changed the root log level to "
            f"{logging.getLevelName(root.level)}"
        )
        assert root.handlers == [sentinel], "migrations replaced the root handlers"
    finally:
        conn.close()
        root.handlers = prev_handlers
        root.setLevel(prev_level)


# ── get_db path guard ─────────────────────────────────────────────────────────


def test_get_db_creates_parent_directory(tmp_path, monkeypatch):
    """get_db() must create missing parent directories."""
    from services import db as db_module

    nested = tmp_path / "deep" / "nested" / "pillar43.db"
    monkeypatch.setattr(db_module, "get_db_path", lambda: nested)
    db_module._initialized_paths.clear()

    conn = db_module.get_db()
    try:
        assert nested.exists()
    finally:
        conn.close()
        db_module._initialized_paths.clear()
