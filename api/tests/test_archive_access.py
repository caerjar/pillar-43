"""Organization edition: the HTTP API serves nothing consent closes to staff.

`test_archive_ask.py` proves the model never reads a closed item. These prove
a person at the machine can't open, list or search one either (UI audit
2026-11-18: `/api/file/raw` returned the private mail export).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import config

OPEN = "library/letters/open-letter.md"
STAFF = "library/minutes/staff-minutes.md"
PRIVATE = "library/correspondence/private-mail.md"
UNREGISTERED = "library/loose/never-registered.md"


@pytest.fixture
def vault(tmp_path, monkeypatch):
    for name in ("notes", "library", "generated"):
        (tmp_path / name).mkdir()
    monkeypatch.setattr(config.settings, "notes_path", tmp_path / "notes")
    monkeypatch.setattr(config.settings, "library_root", tmp_path / "library")
    monkeypatch.setattr(config.settings, "generated_path", tmp_path / "generated")
    files = {
        OPEN: "the orchard contract was signed in june",
        STAFF: "the board approved the reprint budget",
        PRIVATE: "zebracorn secret only in the private mail",
        UNREGISTERED: "zebracorn appears in an unregistered file too",
        "notes/misc/scratch.md": "zebracorn in notes",
        "generated/catalog_summary.md": "zebracorn summarised from private mail",
    }
    for rel, text in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)

    from services.db import get_db

    conn = get_db()
    try:
        for rel, consent in ((OPEN, "model"), (STAFF, "staff"), (PRIVATE, "private")):
            conn.execute(
                "INSERT INTO item (path, sha256, kind, consent) VALUES (?,?,?,?)",
                (rel, "sha-" + rel, "letter", consent),
            )
        conn.commit()
    finally:
        conn.close()
    return tmp_path


@pytest.fixture
def client():
    from main import app

    return TestClient(app, base_url="http://localhost")


def test_private_item_cannot_be_opened(vault, client):
    for path in (
        PRIVATE,
        UNREGISTERED,
        "generated/catalog_summary.md",
        "notes/misc/scratch.md",
    ):
        for route in ("/api/file/raw", "/api/file", "/api/file/text"):
            r = client.get(route, params={"path": path})
            assert r.status_code == 404, (route, path, r.status_code)


def test_staff_and_model_items_can_be_opened(vault, client):
    for path in (OPEN, STAFF):
        r = client.get("/api/file/raw", params={"path": path})
        assert r.status_code == 200, (path, r.status_code)


def test_tree_lists_only_what_staff_may_see(vault, client):
    body = client.get("/api/tree").json()

    def files(nodes):
        for n in nodes:
            if n.get("type") == "file":
                yield n["path"]
            yield from files(n.get("children") or [])

    seen = set(files(body))
    roots = {n["path"].split("/")[0] for n in body}
    assert roots == {"library"}
    assert PRIVATE not in seen and UNREGISTERED not in seen
    for d in ("library/correspondence", "library/loose"):
        listed = client.get("/api/tree/dir", params={"path": d}).json()["children"]
        assert listed == [], (d, listed)
    assert client.get("/api/tree/dir", params={"path": "notes"}).status_code == 404


def test_search_never_returns_a_closed_item(vault, client):
    r = client.get("/api/search", params={"q": "zebracorn"})
    assert r.status_code == 200
    assert r.json()["results"] == []
    hits = client.get("/api/search", params={"q": "orchard"}).json()["results"]
    assert [h["path"] for h in hits] == [OPEN]


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/api/connections"),
        ("GET", "/api/catalog/summary"),
        ("GET", "/api/history/log"),
        ("POST", "/api/file"),
        ("POST", "/api/file/trash"),
    ],
)
def test_routes_the_org_screens_dont_use_are_404(vault, client, method, path):
    assert client.request(method, path, json={}).status_code == 404
