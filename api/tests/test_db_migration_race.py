"""Guards for the concurrent-migration corruption.

`_alembic_lock` was a threading.Lock, which serialises threads inside one
interpreter and nothing else. Two processes migrate the same database
routinely — pytest-xdist runs `-n auto` workers against a shared DB, and the
api and worker containers both mount pillar43_data and both call get_db() on
startup.

When that raced, each process inserted its own row into `alembic_version`.
Alembic reads multiple rows as multiple heads, so a real database ended up
holding 0001_baseline, 0004_hot_query_indexes and 0015_post_feedback at once.
Those all lie on one linear chain, so they "overlap" and every subsequent
`upgrade head` raises RevisionError. The database is wedged permanently — not
flaky, broken.

That is exactly how it presented: intermittent xdist failures that looked like
test flake, until the shared test DB stayed broken between runs.
"""

from __future__ import annotations

import sqlite3

import pytest

from services.db import (
    _alembic_config,
    _repair_multi_head_alembic_version,
    init_schema,
)


@pytest.fixture
def migrated_db(tmp_path, monkeypatch):
    """A real, fully-migrated database on disk."""
    generated = tmp_path / "generated"
    generated.mkdir()
    monkeypatch.setenv("GENERATED_PATH", str(generated))
    import config

    monkeypatch.setattr(config.settings, "generated_path", generated)

    db_path = generated / "pillar43.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    init_schema(conn)
    yield db_path, conn
    conn.close()


def _versions(conn) -> set[str]:
    return {r[0] for r in conn.execute("SELECT version_num FROM alembic_version")}


def test_a_healthy_db_has_exactly_one_revision(migrated_db):
    _db_path, conn = migrated_db
    assert len(_versions(conn)) == 1


def test_repair_collapses_ancestors_to_the_furthest_revision(migrated_db):
    """The corruption seen in the wild, reproduced and repaired."""
    db_path, conn = migrated_db
    head = next(iter(_versions(conn)))

    # Reproduce what the race produced: several revisions from one chain.
    conn.execute("DELETE FROM alembic_version")
    for rev in ("0001_baseline", "0004_hot_query_indexes", head):
        conn.execute("INSERT INTO alembic_version (version_num) VALUES (?)", (rev,))
    conn.commit()
    assert len(_versions(conn)) == 3

    _repair_multi_head_alembic_version(conn, _alembic_config(db_path))

    # Keeps the one furthest along and drops the ancestors it supersedes.
    assert _versions(conn) == {head}


def test_repair_is_a_noop_on_a_healthy_db(migrated_db):
    db_path, conn = migrated_db
    before = _versions(conn)
    _repair_multi_head_alembic_version(conn, _alembic_config(db_path))
    assert _versions(conn) == before


def test_corrupted_db_can_be_upgraded_again_after_repair(migrated_db):
    """The actual symptom: `upgrade head` refused to run at all."""
    db_path, conn = migrated_db
    head = next(iter(_versions(conn)))
    conn.execute("DELETE FROM alembic_version")
    for rev in ("0001_baseline", "0004_hot_query_indexes", head):
        conn.execute("INSERT INTO alembic_version (version_num) VALUES (?)", (rev,))
    conn.commit()

    from alembic import command

    cfg = _alembic_config(db_path)

    # Before the repair this is the RevisionError that wedged the database.
    with pytest.raises(Exception, match=r"overlaps|revision"):
        command.upgrade(cfg, "head")

    _repair_multi_head_alembic_version(conn, cfg)
    command.upgrade(cfg, "head")  # must not raise
    assert len(_versions(conn)) == 1


def test_repair_refuses_to_touch_unknown_revisions(migrated_db, caplog):
    """A revision we don't recognise means "do not guess" — leave it alone."""
    db_path, conn = migrated_db
    conn.execute(
        "INSERT INTO alembic_version (version_num) VALUES ('9999_from_the_future')"
    )
    conn.commit()
    before = _versions(conn)

    with caplog.at_level("ERROR"):
        _repair_multi_head_alembic_version(conn, _alembic_config(db_path))

    assert _versions(conn) == before, "must not silently drop an unknown revision"
    assert "not in the script directory" in caplog.text


def test_migration_lock_is_held_across_processes(tmp_path):
    """flock, not threading.Lock — the distinction the bug turned on."""
    import fcntl
    import os

    from services.db import _migration_lock

    db_path = tmp_path / "pillar43.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = db_path.parent / f".{db_path.name}.migrate.lock"

    with _migration_lock(db_path):
        assert lock_path.exists()
        # A second, independent file descriptor — the moral equivalent of
        # another process — must not be able to take the lock.
        fd = os.open(lock_path, os.O_WRONLY)
        try:
            with pytest.raises(BlockingIOError):
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            os.close(fd)

    # Released on exit, so the next process can migrate.
    fd = os.open(lock_path, os.O_WRONLY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)
