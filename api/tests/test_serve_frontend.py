"""Tests for optionally serving the built SPA from the API process.

This exists for the desktop build, which has no nginx. Serving the frontend
from the API makes the page's origin the API's origin, which is what lets the
build-time-baked `BASE` in `web/src/lib/api/_fetch.ts` keep working against a
port that is only chosen at launch.

The invariant worth protecting is the ordering one: the static mount is a
catch-all at "/", so it must be registered after every real route. If that
inverts, `/health` and every `/api/*` endpoint start returning index.html and
the failure looks like "the backend is up but nothing works".
"""

import importlib
import os

import pytest
from httpx import AsyncClient, ASGITransport


@pytest.fixture
def built_dist(tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>pillar43</title>")
    (dist / "assets" / "app.js").write_text("console.log('hi')")
    return dist


def _app_with(monkeypatch, web_dist_value):
    """Re-import main with WEB_DIST_PATH set — the mount happens at import."""
    monkeypatch.setenv("WEB_DIST_PATH", str(web_dist_value))
    import main

    return importlib.reload(main).app


@pytest.fixture
def restore_main():
    """Undo the module reload so later tests get the unmounted app back."""
    yield
    os.environ.pop("WEB_DIST_PATH", None)
    import main

    importlib.reload(main)


async def _get(app, path):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        return await c.get(path)


async def test_frontend_not_served_without_the_env_var(restore_main, monkeypatch):
    """The Docker stack must be untouched — nginx serves the SPA there."""
    monkeypatch.delenv("WEB_DIST_PATH", raising=False)
    import main

    app = importlib.reload(main).app
    r = await _get(app, "/")
    assert r.status_code == 404


async def test_serves_index_at_root(restore_main, monkeypatch, built_dist):
    app = _app_with(monkeypatch, built_dist)
    r = await _get(app, "/")
    assert r.status_code == 200
    assert "pillar43" in r.text


async def test_serves_hashed_assets(restore_main, monkeypatch, built_dist):
    app = _app_with(monkeypatch, built_dist)
    r = await _get(app, "/assets/app.js")
    assert r.status_code == 200
    assert "console.log" in r.text


async def test_health_still_wins_over_the_catch_all(
    restore_main, monkeypatch, built_dist
):
    """The regression that would make the desktop app look totally broken."""
    app = _app_with(monkeypatch, built_dist)
    r = await _get(app, "/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


async def test_api_routes_still_win_over_the_catch_all(
    restore_main, monkeypatch, built_dist
):
    app = _app_with(monkeypatch, built_dist)
    r = await _get(app, "/api/library/status")
    assert r.status_code == 200
    assert "notes" in r.json()


async def test_unknown_path_is_404_not_a_blank_shell(
    restore_main, monkeypatch, built_dist
):
    """No SPA catch-all: the frontend has no client-side router, so a typo
    should 404 rather than silently render an empty app."""
    app = _app_with(monkeypatch, built_dist)
    r = await _get(app, "/no/such/thing")
    assert r.status_code == 404


async def test_bad_dist_path_does_not_break_the_api(
    restore_main, monkeypatch, tmp_path
):
    """A misconfigured path must not take the backend down with it."""
    app = _app_with(monkeypatch, tmp_path / "nope")
    r = await _get(app, "/health")
    assert r.status_code == 200
