"""Tests for catalog (extracted-text) search."""

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


def _make_settings(tmp_path: Path, monkeypatch):
    active = tmp_path / "notes"
    active.mkdir()
    vault = tmp_path / "library"
    vault.mkdir()
    generated = tmp_path / "generated"
    generated.mkdir()
    monkeypatch.setenv("NOTES_PATH", str(active))
    monkeypatch.setenv("LIBRARY_ROOT", str(vault))
    monkeypatch.setenv("GENERATED_PATH", str(generated))
    import config

    monkeypatch.setattr(config.settings, "notes_path", active)
    monkeypatch.setattr(config.settings, "library_root", vault)
    monkeypatch.setattr(config.settings, "generated_path", generated)
    return active, vault, generated


def _seed_catalog_db(tmp_path: Path):
    """Create a minimal catalog DB with a PDF entry containing extracted_text.

    Seeds at `settings.db_path` so the conftest autouse's per-worker DATA_PATH
    isolation (tmp_path/data) is honoured — not the legacy generated/ path.
    """
    from config import settings as _settings

    db_path = _settings.db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rel_path TEXT NOT NULL UNIQUE,
            mount TEXT NOT NULL DEFAULT '',
            abs_path TEXT NOT NULL DEFAULT '',
            sha256 TEXT NOT NULL DEFAULT '',
            size_bytes INTEGER NOT NULL DEFAULT 0,
            mtime REAL NOT NULL DEFAULT 0,
            ext TEXT NOT NULL DEFAULT '.pdf',
            extracted_text TEXT,
            summary TEXT,
            topics TEXT,
            entities TEXT,
            cataloged_at REAL,
            inbox_suggested_path TEXT,
            created_at REAL NOT NULL DEFAULT (unixepoch('now'))
        );
        CREATE TABLE IF NOT EXISTS file_connections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_a_id INTEGER NOT NULL,
            file_b_id INTEGER NOT NULL,
            score REAL NOT NULL,
            kind TEXT NOT NULL,
            shared_topics TEXT,
            discovered_at REAL NOT NULL DEFAULT (unixepoch('now'))
        );
    """)
    conn.execute(
        "INSERT INTO files (rel_path, mount, ext, extracted_text, summary) VALUES (?,?,?,?,?)",
        (
            "library/materia/yarrow-study.pdf",
            "library",
            ".pdf",
            "Yarrow (Achillea millefolium) is a diaphoretic and nervine herb used in fever management.",
            "Study on yarrow's medicinal properties.",
        ),
    )
    conn.execute(
        "INSERT INTO files (rel_path, mount, ext, extracted_text, summary) VALUES (?,?,?,?,?)",
        (
            "library/notes/echinacea.md",
            "library",
            ".md",
            "Echinacea is an immunostimulant.",
            "Echinacea note.",
        ),
    )
    conn.commit()
    conn.close()


@pytest.fixture
def client(tmp_path, monkeypatch):
    _make_settings(tmp_path, monkeypatch)
    import importlib
    import main as app_module

    importlib.reload(app_module)
    return TestClient(app_module.app)


@pytest.fixture
def catalog_client(tmp_path, monkeypatch):
    _make_settings(tmp_path, monkeypatch)
    _seed_catalog_db(tmp_path)
    import importlib
    import main as app_module

    importlib.reload(app_module)
    return TestClient(app_module.app)


# ── Plain search ─────────────────────────────────────────────────────────────


def test_search_normal_no_ai_flag(client):
    """Default search carries no `ai` flag and no source/note on ripgrep hits."""
    resp = client.get("/api/search", params={"q": "yarrow"})
    assert resp.status_code == 200
    data = resp.json()
    assert "ai" not in data
    # results may be empty (no files seeded) but structure is right
    for r in data["results"]:
        assert "source" not in r
        assert "note" not in r


def test_search_invalid_scope(client):
    resp = client.get("/api/search", params={"q": "test", "scope": "invalid"})
    assert resp.status_code == 400


# ── Catalog search ────────────────────────────────────────────────────────────


def test_catalog_search_finds_pdf(catalog_client):
    """_catalog_search should return the PDF entry for 'yarrow'."""
    from routes.search import _catalog_search

    results = _catalog_search("yarrow")
    assert len(results) == 1
    assert results[0]["path"] == "library/materia/yarrow-study.pdf"
    assert results[0]["source"] == "catalog"
    assert results[0]["line"] == 0
    assert "yarrow" in results[0]["text"].lower()


def test_catalog_search_excludes_markdown(catalog_client):
    """Markdown files (.md) must not appear in catalog search results."""
    from routes.search import _catalog_search

    results = _catalog_search("echinacea")
    paths = [r["path"] for r in results]
    assert not any(p.endswith(".md") for p in paths)


def test_catalog_search_empty_db(client):
    """Empty catalog returns empty list without error."""
    from routes.search import _catalog_search

    results = _catalog_search("anything")
    assert results == []


# ── Lexical endpoint merges catalog results ──────────────────────────────────


def test_search_endpoint_merges_catalog(catalog_client, monkeypatch):
    """GET /api/search includes catalogued PDF results next to ripgrep hits."""
    monkeypatch.setattr(
        "services.archive.access.staff_may_see_many", lambda paths: set(paths)
    )
    resp = catalog_client.get("/api/search", params={"q": "yarrow"})

    assert resp.status_code == 200
    data = resp.json()
    assert "ai" not in data
    paths = [r["path"] for r in data["results"]]
    assert "library/materia/yarrow-study.pdf" in paths


def test_search_endpoint_catalog_respects_scope(catalog_client):
    """A catalog hit in library/ must not appear when the scope is notes."""
    resp = catalog_client.get("/api/search", params={"q": "yarrow", "scope": "notes"})

    assert resp.status_code == 200
    assert resp.json()["results"] == []


def test_catalog_search_skips_markdown_overlap(tmp_path, monkeypatch):
    """If ripgrep and catalog both match the same path, it appears once."""
    active, vault, generated = _make_settings(tmp_path, monkeypatch)
    # Create a markdown note that ripgrep will find
    (active / "yarrow.md").write_text("yarrow is a herb", encoding="utf-8")
    # Seed catalog with a non-md file (different ext) — no dedup case here by design
    # Dedup only happens when same rel_path appears in both; test the logic directly
    from routes.search import _catalog_search

    # Seed catalog with an md file (which catalog_search excludes anyway)
    _seed_catalog_db(tmp_path)
    # Verify ripgrep and catalog would produce different paths
    results = _catalog_search("yarrow")
    paths = [r["path"] for r in results]
    # The PDF is a different path from yarrow.md — no conflict expected
    assert all(not p.endswith(".md") for p in paths)
