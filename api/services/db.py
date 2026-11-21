"""SQLite database initialization and connection management.

The catalog database lives at generated/pillar43.db (settings.db_path).
Both the API (reads) and the worker (writes) share this file via the
shared Docker volume. WAL mode allows concurrent readers with one writer.

Schema lifecycle:
    Migrations are managed by Alembic (see api/migrations/). On first open
    in a process, init_schema() runs `alembic upgrade head` against the DB.

    Three startup states are handled:
      1. New DB                 → upgrade head (creates everything)
      2. DB pre-dating Alembic  → stamp 0001_baseline, then upgrade head
      3. DB already versioned   → upgrade head (no-op if already at head)
"""

from __future__ import annotations

import fcntl
import logging
import os
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

from config import settings

log = logging.getLogger(__name__)


# Locate alembic.ini and the migrations/ directory relative to this file
_API_DIR = Path(__file__).resolve().parent.parent
_ALEMBIC_INI = _API_DIR / "alembic.ini"


def get_db_path() -> Path:
    return settings.db_path


def _alembic_config(db_path: Path):
    """Build a runtime Alembic Config pointing at the given DB path.

    Importing alembic at function scope keeps cold-import cost off the
    hot path for processes that never touch the schema.
    """
    from alembic.config import Config

    cfg = Config(str(_ALEMBIC_INI))
    cfg.set_main_option("script_location", str(_API_DIR / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    # Never let a programmatic migration reconfigure the host process's
    # logging. alembic.ini declares `[logger_root] level = WARN`, and env.py's
    # fileConfig applies it to the ROOT logger — so the first init_schema()
    # silently dropped every app INFO line for the life of the process. The
    # api patched that back up for years; the worker didn't, and its logs died
    # ~30s after boot. env.py honours this attribute; the alembic CLI (which
    # doesn't set it) still gets the ini's logging config.
    cfg.attributes["configure_logging"] = False
    return cfg


def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone()
    return row is not None


def _backfill_fts(conn: sqlite3.Connection) -> None:
    """Populate files_fts for any rows not yet indexed.

    The FTS triggers keep new writes in sync. Pre-existing rows or
    test fixtures that seed `files` directly need the one-off rebuild.
    """
    try:
        conn.execute("INSERT INTO files_fts(files_fts) VALUES('rebuild')")
        conn.commit()
    except sqlite3.OperationalError as e:
        log.warning("FTS5 rebuild failed (FTS5 may not be compiled in): %s", e)


# Alembic invocations are not safe to run in parallel against the same DB.
# This lock covers threads within ONE process; _migration_lock() below covers
# the cross-PROCESS case, which is the one that actually corrupted databases.
_alembic_lock = threading.Lock()


@contextmanager
def _migration_lock(db_path: Path):
    """Serialise `alembic upgrade` across processes, not just threads.

    The threading.Lock above is per-interpreter, so nothing stopped two
    processes migrating the same database at once — and two do it routinely:
    pytest-xdist runs `-n auto` workers against a shared DB, and the api and
    worker containers both mount pillar43_data and both call get_db() on
    startup.

    When that raced, each process inserted its own row into `alembic_version`.
    Alembic reads multiple rows as multiple heads, so a DB could end up
    holding 0001_baseline, 0004_hot_query_indexes and 0015_post_feedback at
    once. Because those all lie on one linear chain they "overlap", and every
    subsequent `upgrade head` fails with a RevisionError — the database is
    wedged permanently, not just for that run.

    An flock on a sidecar file is enough: it is advisory but every writer here
    is this same code path, it releases automatically if a process dies, and
    it works across containers when the DB directory is a shared volume.
    """
    lock_path = db_path.parent / f".{db_path.name}.migrate.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "w") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def _repair_multi_head_alembic_version(conn: sqlite3.Connection, cfg) -> None:
    """Collapse a multi-row `alembic_version` back to a single revision.

    Repairs databases already corrupted by the race described in
    _migration_lock. Keeps whichever present revision is furthest along the
    chain — walking the real script directory rather than trusting the
    ``NNNN_`` filename prefixes — and drops the ancestors it supersedes.

    Only ever collapses revisions that lie on ONE line. If a future branching
    migration graph produces genuinely divergent heads, this leaves them alone
    and lets alembic complain, because merging those is a human decision.
    """
    if not _has_table(conn, "alembic_version"):
        return
    present = {r[0] for r in conn.execute("SELECT version_num FROM alembic_version")}
    if len(present) <= 1:
        return

    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(cfg)
    # walk_revisions yields head → base, so the first match is furthest along.
    ordered = [s.revision for s in script.walk_revisions()]
    known = [r for r in ordered if r in present]
    if len(known) != len(present):
        log.error(
            "alembic_version holds revisions not in the script directory (%s) — "
            "leaving it alone",
            sorted(present - set(ordered)),
        )
        return

    keep = known[0]
    superseded = sorted(present - {keep})
    # Every other present revision must be an ancestor of `keep`, otherwise
    # these are real branches and collapsing them would skip a migration.
    ancestors = {s.revision for s in script.iterate_revisions(keep, "base")}
    if not set(superseded).issubset(ancestors):
        log.error(
            "alembic_version holds divergent heads %s — not collapsing; this "
            "needs an alembic merge",
            sorted(present),
        )
        return

    log.warning(
        "Repairing alembic_version: %d rows found (%s); keeping %s and dropping "
        "the ancestors it supersedes. Caused by concurrent migration before "
        "the cross-process lock existed.",
        len(present),
        sorted(present),
        keep,
    )
    conn.execute("DELETE FROM alembic_version")
    conn.execute("INSERT INTO alembic_version (version_num) VALUES (?)", (keep,))
    conn.commit()


def init_schema(conn: sqlite3.Connection) -> None:
    """Bring the database to the latest migration revision.

    Idempotent — calling on an already-migrated DB is a no-op.

    For in-memory databases (`:memory:`), Alembic can't be used because it
    opens its own connection by URL. We apply the baseline schema directly
    against the provided `conn`. Subsequent migrations beyond the baseline
    are NOT applied to in-memory DBs — they're for tests with frozen schema.
    """
    raw_path = conn.execute("PRAGMA database_list").fetchone()[2] or ""

    # In-memory DBs: apply baseline directly, no Alembic.
    #
    # ⚠ KNOWN LIMITATION ⚠
    # Migrations beyond 0001_baseline are NOT applied to in-memory DBs.
    # Alembic can't open `:memory:` connections by URL — it would have to
    # share the existing connection, which it doesn't support cleanly.
    #
    # When you write migration 0002+, audit `:memory:` callers in tests/
    # (search for `sqlite3.connect(":memory:")`) and convert them to
    # `tmp_path / "test.db"` so they go through Alembic naturally. Otherwise
    # those tests silently run against the frozen baseline schema and either
    # fail or pass spuriously without exercising the new column.
    if not raw_path:
        from services._schema_baseline import BASELINE_SQL

        conn.executescript(BASELINE_SQL)
        _backfill_fts(conn)
        conn.commit()
        return

    db_path = Path(raw_path).resolve()

    with _alembic_lock, _migration_lock(db_path):
        from alembic import command

        cfg = _alembic_config(db_path)

        # Repair before upgrading: a DB corrupted by the pre-lock race cannot
        # be upgraded at all until alembic_version holds a single revision.
        _repair_multi_head_alembic_version(conn, cfg)

        # State detection: if the DB has our tables but no alembic_version,
        # it's a pre-Alembic database from an earlier sprint. Stamp it as
        # being at the baseline so `upgrade head` skips re-creating tables.
        has_alembic = _has_table(conn, "alembic_version")
        has_files = _has_table(conn, "files")

        if has_files and not has_alembic:
            log.info(
                "Pre-Alembic database detected at %s — stamping at baseline",
                db_path,
            )
            command.stamp(cfg, "0001_baseline")

        command.upgrade(cfg, "head")

    _backfill_fts(conn)
    conn.commit()


# Track which database files have been schema-initialized in this process.
# Keyed by resolved path string — handles multiple tmp databases in tests.
_initialized_paths: set[str] = set()


def _migrate_db_from_bind_mount(target: Path) -> None:
    """One-time copy of the SQLite DB from the legacy bind-mount location
    (GENERATED_PATH/pillar43.db) to the new named-volume location
    (DATA_PATH/pillar43.db). Runs at most once per fresh volume.

    Only fires in production-like environments where DATA_PATH is explicitly
    set (i.e. inside the api container with the pillar43_data volume mounted).
    Tests don't set DATA_PATH, so this is a no-op for them — their fixtures
    point db_path at tmp_path/pillar43.db via monkeypatched generated_path.

    No-op when: target already exists, DATA_PATH unset, settings.testing
    True, or legacy file absent.
    """
    if target.exists():
        return
    if settings.testing:
        return  # tests use per-worker tmp DBs — never copy the legacy fixture
    if not os.getenv("DATA_PATH"):
        return  # not production — skip
    try:
        from config import settings as _settings

        legacy = _settings.generated_path / "pillar43.db"
    except Exception:
        return
    if not legacy.exists():
        return
    import shutil

    log.info("[db] migrating SQLite DB from %s → %s (one-time)", legacy, target)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(legacy), str(target))
        # Copy any sibling WAL/SHM/journal files too — harmless if absent.
        for suffix in ("-wal", "-shm", "-journal"):
            src = legacy.parent / f"{legacy.name}{suffix}"
            if src.exists():
                shutil.copy2(str(src), str(target.parent / src.name))
        log.info("[db] migration complete (%d bytes)", target.stat().st_size)
    except Exception as e:
        log.warning("[db] migration failed (will start fresh at %s): %s", target, e)


def get_db() -> sqlite3.Connection:
    """Open (or create) the catalog database. Caller is responsible for closing.

    Schema migrations run once per database file per process. WAL mode is
    enabled on every connection for safe concurrent read/write.
    """
    db_path = get_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    _migrate_db_from_bind_mount(db_path)
    # Pass timeout to sqlite3.connect so busy_timeout is active from the very
    # first statement on the connection — important because the *first* PRAGMA
    # is the one most likely to hit a lock contention with a concurrent writer
    # holding a transaction, and we need busy_timeout in place before then.
    conn = sqlite3.connect(str(db_path), timeout=10.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    # busy_timeout PRAGMA is redundant with the timeout=10.0 above but kept for
    # explicit documentation. Both write to the same sqlite3_busy_timeout slot.
    conn.execute("PRAGMA busy_timeout = 10000")

    key = str(db_path.resolve())
    if key not in _initialized_paths:
        # journal_mode and synchronous are set ONCE per process per DB.
        #
        # - journal_mode is a database-file-level setting (persisted in the
        #   file header). Running it on every connection takes an exclusive
        #   lock and crashes under concurrent writers. Subsequent connections
        #   inherit the mode from the file.
        # - synchronous is technically per-connection, but the first time a
        #   PRAGMA touches the file it requires brief locking that can collide
        #   with a long-held writer transaction. We accept the SQLite default
        #   (FULL) on short-lived check connections; the long-lived scan
        #   thread is among the first connections and gets NORMAL.
        #
        # WAL is now safe because the DB lives in a Docker named volume
        # (config.py: `data_path`, mapped from compose volume `pillar43_data`)
        # instead of a bind mount. WAL's SHM file requires shared mmap across
        # connections, which Docker's bind-mount filesystem bridge on macOS
        # (VirtioFS / gRPC FUSE) doesn't reliably support — that produced the
        # `disk I/O error` / `database is locked` / `malformed` bugs we spent
        # this sprint chasing. Named volumes use Docker's native storage layer
        # and the entire class of bugs disappears.
        #
        # WAL is the right journal mode for this workload: many concurrent
        # readers (HTTP handlers, heartbeat updates) + a single long-lived
        # writer (catalog scan thread). With rollback modes (TRUNCATE, DELETE)
        # readers block on writers and vice versa; with WAL they don't.
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        init_schema(conn)
        _initialized_paths.add(key)
    return conn
