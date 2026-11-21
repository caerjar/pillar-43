"""Tests for the Alembic-driven init_schema state detection.

Especially the trickiest path: a database created by the OLD `_SCHEMA +
_migrate_*` code (no `alembic_version` table, but tables already exist).
init_schema must detect that and stamp it at baseline rather than try to
re-create everything.
"""

from __future__ import annotations

import sqlite3


def _alembic_head() -> str:
    """Look up the current head revision from Alembic config — avoids hardcoding."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from pathlib import Path

    api_dir = Path(__file__).resolve().parent.parent
    cfg = Config(str(api_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(api_dir / "migrations"))
    return ScriptDirectory.from_config(cfg).get_current_head()


def test_init_schema_stamps_pre_alembic_db(tmp_path, monkeypatch):
    """A DB created by the old code path (tables exist, no alembic_version)
    must be stamped — and then upgraded to head. Critical for the production
    migration from sprint 12 to sprint 13."""
    db_path = tmp_path / "pillar43.db"

    # Simulate a DB built by the old _SCHEMA + _migrate_* code: tables
    # exist, but no alembic_version table.
    raw = sqlite3.connect(str(db_path))
    from services._schema_baseline import BASELINE_SQL

    raw.executescript(BASELINE_SQL)
    raw.commit()
    raw.close()

    # Confirm precondition: no alembic_version yet
    raw = sqlite3.connect(str(db_path))
    pre = raw.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='alembic_version'"
    ).fetchone()
    raw.close()
    assert pre is None, "test setup should produce a pre-Alembic DB"

    # Now run init_schema — should stamp baseline then upgrade to head
    import config
    import services.db as db_mod

    monkeypatch.setattr(config.settings, "generated_path", tmp_path)
    db_mod._initialized_paths.discard(str(db_path.resolve()))

    conn = db_mod.get_db()
    try:
        version = conn.execute("SELECT version_num FROM alembic_version").fetchone()
        assert version is not None, (
            "alembic_version table should exist after init_schema"
        )
        assert version[0] == _alembic_head(), (
            f"DB should be migrated to head; got {version[0]!r}"
        )

        # Original tables preserved
        files_table = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='files'"
        ).fetchone()
        assert files_table is not None, "files table should be preserved"
    finally:
        conn.close()


def test_init_schema_idempotent_on_already_stamped_db(tmp_path, monkeypatch):
    """Calling init_schema twice must produce the same head version both times."""
    import config
    import services.db as db_mod

    monkeypatch.setattr(config.settings, "generated_path", tmp_path)
    db_path = tmp_path / "pillar43.db"
    db_mod._initialized_paths.discard(str(db_path.resolve()))

    # First call
    conn1 = db_mod.get_db()
    v1 = conn1.execute("SELECT version_num FROM alembic_version").fetchone()[0]
    conn1.close()

    # Drop the in-process cache so init_schema runs again
    db_mod._initialized_paths.discard(str(db_path.resolve()))

    # Second call must be a no-op
    conn2 = db_mod.get_db()
    v2 = conn2.execute("SELECT version_num FROM alembic_version").fetchone()[0]
    conn2.close()

    assert v1 == v2 == _alembic_head()


def test_init_schema_fresh_db_creates_alembic_version(tmp_path, monkeypatch):
    """A brand-new DB must end up at the latest head after init_schema."""
    import config
    import services.db as db_mod

    monkeypatch.setattr(config.settings, "generated_path", tmp_path)
    db_mod._initialized_paths.discard(str((tmp_path / "pillar43.db").resolve()))

    conn = db_mod.get_db()
    try:
        version = conn.execute("SELECT version_num FROM alembic_version").fetchone()
        assert version is not None
        assert version[0] == _alembic_head()

        # Baseline tables present
        for name in ("files", "threads", "tasks", "topic_aliases", "ca_opacity"):
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (name,),
            ).fetchone()
            assert row is not None, f"{name} table missing"
    finally:
        conn.close()


def test_in_memory_db_applies_baseline_directly():
    """`:memory:` databases bypass Alembic and apply BASELINE_SQL directly.
    Documented limitation — see init_schema() comment."""
    from services.db import init_schema

    conn = sqlite3.connect(":memory:", check_same_thread=False)
    init_schema(conn)
    try:
        # Has the baseline tables
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='files'"
        ).fetchone()
        assert row is not None

        # But NO alembic_version table — that's the documented limitation
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='alembic_version'"
        ).fetchone()
        assert row is None, (
            "in-memory DBs should NOT have alembic_version — "
            "the fallback path bypasses Alembic"
        )
    finally:
        conn.close()
