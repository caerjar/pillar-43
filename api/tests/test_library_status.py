"""Tests for GET /api/library/status — the first-run wizard gate.

The frontend renders FirstRunWizard iff `notes.git_ready` is False. So the
truth table here is load-bearing:

  notes/.git exists | catalog has rows | git_ready
  ------------------|------------------|----------
  yes               | any              | True
  no                | yes              | True   ← regression-prone
  no                | no               | False  (genuine fresh setup)

Bug B specifically: pre-fix `_indexed_count` read from `generated_path /
"pillar43.db"`. The DB was migrated to a Docker named volume; that path
no longer exists in production, so the second row of the table was dead
code. `test_git_ready_true_when_catalog_populated_but_no_git` would have
caught it.
"""

import os
import sqlite3

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("TESTING", "1")


@pytest.fixture()
def isolated(tmp_path, monkeypatch):
    """Isolate notes_path, generated_path, library_root; reset DB init cache."""
    import config as cfg
    import services.db as db_mod

    notes = tmp_path / "notes"
    notes.mkdir()
    generated = tmp_path / "generated"
    generated.mkdir()
    library = tmp_path / "library"
    library.mkdir()

    monkeypatch.setattr(cfg.settings, "notes_path", notes)
    monkeypatch.setattr(cfg.settings, "generated_path", generated)
    monkeypatch.setattr(cfg.settings, "library_root", library)

    # The conftest autouse `_isolate_db_per_test` has already pointed db_path
    # at tmp_path/data/pillar43.db via DATA_PATH. Discard its init-cache entry
    # so the next get_db() call applies the schema.
    db_mod._initialized_paths.discard(str(cfg.settings.db_path.resolve()))

    return {"tmp_path": tmp_path, "notes": notes, "generated": generated}


@pytest.fixture()
def client(isolated):
    from main import app

    return TestClient(app)


def _seed_catalog(notes_count: int = 0, library_count: int = 0) -> None:
    """Initialize schema and insert N rows for each mount."""
    import services.db as db_mod

    conn = db_mod.get_db()
    try:
        rows = []
        for i in range(notes_count):
            rows.append(
                (f"notes/n{i}.md", "notes", f"/n{i}.md", f"sha-n{i}", 100, 1.0, ".md")
            )
        for i in range(library_count):
            rows.append(
                (
                    f"library/l{i}.pdf",
                    "library",
                    f"/l{i}.pdf",
                    f"sha-l{i}",
                    100,
                    1.0,
                    ".pdf",
                )
            )
        if rows:
            conn.executemany(
                "INSERT INTO files (rel_path, mount, abs_path, sha256, size_bytes, mtime, ext) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
            conn.commit()
    finally:
        conn.close()


def test_git_ready_true_when_notes_git_exists(client, isolated):
    """The original signal: vault-init ran, notes/.git exists, wizard skipped."""
    (isolated["notes"] / ".git").mkdir()

    res = client.get("/api/library/status")
    assert res.status_code == 200
    body = res.json()
    assert body["notes"]["git_ready"] is True
    assert body["notes"]["git_actual"] is True


def test_git_ready_true_when_catalog_populated_but_no_git(client, isolated):
    """Bug B regression: a populated catalog alone should skip the wizard,
    even if notes/.git is missing. Pre-fix `_indexed_count` read from the
    wrong DB path and always returned 0, so this case fell through to the
    wizard despite an indexed library."""
    _seed_catalog(notes_count=2, library_count=3)

    res = client.get("/api/library/status")
    assert res.status_code == 200
    body = res.json()
    assert body["notes"]["git_ready"] is True
    assert body["notes"]["git_actual"] is False
    assert body["library"]["file_count"] == 3


def test_git_ready_false_on_fresh_setup(client):
    """No notes/.git, no DB rows — genuine first-run, wizard must appear."""
    res = client.get("/api/library/status")
    assert res.status_code == 200
    body = res.json()
    assert body["notes"]["git_ready"] is False
    assert body["notes"]["git_actual"] is False


def test_indexed_count_reads_from_db_path_not_generated(isolated, monkeypatch):
    """Bug B lock-in: when DATA_PATH points to a distinct location, the count
    must read from there, not from generated_path. This is the production
    layout (catalog DB in a Docker named volume, generated/ a bind mount)."""
    import config as cfg
    import services.db as db_mod
    from routes.vault import _indexed_count

    # The conftest autouse already placed `data` under tmp_path. exist_ok=True
    # keeps this test independent of whether the autouse created it.
    data_dir = isolated["tmp_path"] / "data"
    data_dir.mkdir(exist_ok=True)
    monkeypatch.setenv("DATA_PATH", str(data_dir))
    monkeypatch.setattr(cfg.settings, "data_path", data_dir)
    db_mod._initialized_paths.discard(str((data_dir / "pillar43.db").resolve()))

    # Seed under the new db_path (not generated_path).
    conn = sqlite3.connect(str(data_dir / "pillar43.db"))
    try:
        from services.db import init_schema

        init_schema(conn)
        conn.execute(
            "INSERT INTO files (rel_path, mount, abs_path, sha256, size_bytes, mtime, ext) "
            "VALUES ('notes/a.md', 'notes', '/a.md', 'sha-a', 100, 1.0, '.md')"
        )
        conn.commit()
    finally:
        conn.close()

    assert _indexed_count("notes") == 1
    assert _indexed_count("library") == 0

    # Sanity check: the generated_path location is empty, so without the fix
    # _indexed_count would return 0 for both.
    assert not (isolated["generated"] / "pillar43.db").exists()
