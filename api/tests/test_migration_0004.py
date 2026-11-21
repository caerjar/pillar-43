"""Regression: migration 0004 (hot-query indexes) must be idempotent.

The migration uses CREATE INDEX IF NOT EXISTS so this is safe by
construction; this test documents the contract so a future schema sweep
that drops the IF NOT EXISTS doesn't silently break upgrade-on-warm-DB.
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


def _index_names() -> set[str]:
    from services.db import get_db

    conn = get_db()
    try:
        return {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%'"
            )
        }
    finally:
        conn.close()


def test_0004_indexes_present_after_init(tmp_path, monkeypatch):
    _make_settings(tmp_path, monkeypatch)
    indexes = _index_names()
    assert "idx_files_cataloged_at" in indexes
    assert "idx_tasks_due_date" in indexes
    assert "idx_tasks_completed_at" in indexes


def test_0004_idempotent_on_warm_db(tmp_path, monkeypatch):
    _make_settings(tmp_path, monkeypatch)
    first = _index_names()
    # Re-open: schema-init / alembic upgrade head should be a no-op
    second = _index_names()
    assert first == second
    assert "idx_files_cataloged_at" in second
