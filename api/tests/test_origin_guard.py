"""Cross-origin state-changing requests are refused (code audit 2026-11-20 H1).

CORS only hides the response; a page on another origin can still make the
browser send a POST whose body has no Content-Type, and FastAPI parses that
as JSON. The guard refuses unsafe methods whose Origin is present and is not
the app itself.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    import config as cfg

    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "_trash").mkdir()
    monkeypatch.setattr(cfg.settings, "notes_path", notes)
    from main import app

    return TestClient(app, base_url="http://127.0.0.1:8000"), notes


EVIL = {"Origin": "https://evil.example"}


def test_cross_origin_post_without_content_type_is_refused(client):
    c, notes = client
    (notes / "victim.md").write_text("my note")
    r = c.post("/api/file/trash", content=b'{"path":"notes/victim.md"}', headers=EVIL)
    assert r.status_code == 403
    assert (notes / "victim.md").exists()


def test_cross_origin_bodyless_post_is_refused(client):
    c, notes = client
    (notes / "_trash" / "precious.md").write_text("keep")
    r = c.post("/api/trash/empty", headers={**EVIL, "Content-Type": "text/plain"})
    assert r.status_code == 403
    assert (notes / "_trash" / "precious.md").exists()


@pytest.mark.parametrize("method", ["PUT", "PATCH", "DELETE"])
def test_other_unsafe_methods_are_refused(client, method):
    c, _ = client
    r = c.request(method, "/api/file", headers=EVIL)
    assert r.status_code == 403


def test_opaque_null_origin_is_refused(client):
    c, _ = client
    r = c.post("/api/trash/empty", headers={"Origin": "null"})
    assert r.status_code == 403


def test_cross_site_fetch_metadata_is_refused_even_with_allowed_origin_absent(client):
    c, _ = client
    r = c.post(
        "/api/trash/empty",
        headers={"Origin": "https://evil.example", "Sec-Fetch-Site": "cross-site"},
    )
    assert r.status_code == 403


def test_safe_methods_with_foreign_origin_are_not_blocked(client):
    c, _ = client
    r = c.get("/health", headers=EVIL)
    assert r.status_code == 200


@pytest.mark.parametrize(
    "headers",
    [
        {},  # curl / CLI: no Origin
        {"Origin": "http://127.0.0.1:5173"},  # vite dev
        {"Origin": "http://localhost:4173"},  # vite preview
        {"Origin": "http://127.0.0.1:8000"},  # same origin as Host (desktop shell)
        {"Origin": "http://127.0.0.1:5221", "Sec-Fetch-Site": "same-origin"},  # nginx
    ],
)
def test_app_origins_and_cli_still_work(client, headers):
    c, notes = client
    # The guard sits in front of routing: anything but its 403 means it let
    # the request through (the route itself answers 404 outside org).
    r = c.post("/api/archive/ask", json={"question": "x"}, headers=headers)
    assert r.status_code != 403, r.text
