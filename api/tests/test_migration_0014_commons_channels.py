"""Migration 0014 — commons_channels + roundtable_sessions.commons_channel_id.

Same shape as test_migration_0005.py / test_migration_0011 — assert
schema after init + idempotency.
"""

from __future__ import annotations

from pathlib import Path


def _make_settings(tmp_path: Path, monkeypatch):
    notes = tmp_path / "notes"
    notes.mkdir()
    library = tmp_path / "library"
    library.mkdir()
    generated = tmp_path / "generated"
    generated.mkdir()
    monkeypatch.setenv("NOTES_PATH", str(notes))
    monkeypatch.setenv("LIBRARY_ROOT", str(library))
    monkeypatch.setenv("GENERATED_PATH", str(generated))
    import config

    monkeypatch.setattr(config.settings, "notes_path", notes)
    monkeypatch.setattr(config.settings, "library_root", library)
    monkeypatch.setattr(config.settings, "generated_path", generated)


def _table_names() -> set[str]:
    from services.db import get_db

    conn = get_db()
    try:
        return {
            r["name"]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    finally:
        conn.close()


def _column_names(table: str) -> set[str]:
    from services.db import get_db

    conn = get_db()
    try:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    finally:
        conn.close()


def test_0014_commons_channels_table_present(tmp_path, monkeypatch):
    _make_settings(tmp_path, monkeypatch)
    tables = _table_names()
    assert "commons_channels" in tables


def test_0014_commons_channels_columns(tmp_path, monkeypatch):
    _make_settings(tmp_path, monkeypatch)
    cols = _column_names("commons_channels")
    expected = {
        "id",
        "slug",
        "mattermost_url",
        "mattermost_channel_id",
        "polling_interval_sec",
        "enabled",
        "last_polled_at",
        "created_at",
    }
    assert expected.issubset(cols), f"missing: {expected - cols}"


# `test_0014_roundtable_sessions_gained_commons_channel_id` was removed with
# migration 0018: it asserted a column on `roundtable_sessions`, a table that
# no longer exists. The column it checked for existed to bind a Roundtable
# session to a Commons channel, and Roundtables were removed in `682931a`.


def test_0014_idempotent_when_already_applied(tmp_path, monkeypatch):
    """Re-running migrations against an already-migrated DB must not error."""
    from services.db import get_db

    _make_settings(tmp_path, monkeypatch)
    # First init via _make_settings already ran migrations. Open the DB a
    # second time — services.db.get_db() triggers init if needed; the
    # idempotency guards in 0014 mean a second invocation is harmless.
    conn = get_db()
    try:
        conn.execute("SELECT COUNT(*) FROM commons_channels").fetchone()
    finally:
        conn.close()
    # Asserting we got here without an exception is the test.


def test_0014_slug_uniqueness_enforced(tmp_path, monkeypatch):
    """slug column has UNIQUE; two rows with the same slug must fail."""
    import sqlite3

    from services.db import get_db

    _make_settings(tmp_path, monkeypatch)
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO commons_channels "
            "(id, slug, mattermost_url, mattermost_channel_id, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("a", "research-room", "http://x", "ch1", 1700000000.0),
        )
        conn.commit()
        try:
            conn.execute(
                "INSERT INTO commons_channels "
                "(id, slug, mattermost_url, mattermost_channel_id, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                ("b", "research-room", "http://y", "ch2", 1700000000.0),
            )
            conn.commit()
            raise AssertionError("expected UNIQUE constraint to fail")
        except sqlite3.IntegrityError:
            pass
    finally:
        conn.close()
