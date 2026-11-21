"""Sprint 50 — Security audit tests.

Covers:
  1. Generic 500 handler does not leak internals
"""

import pytest
from httpx import AsyncClient, ASGITransport

from main import app


@pytest.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


# ── Generic 500 handler does not leak internals ────────────────────────────


@pytest.mark.asyncio
async def test_500_handler_returns_generic_message(monkeypatch):
    """A route that raises an unhandled exception must return a safe 500 body."""
    from routes import files as files_module

    def _boom():
        raise RuntimeError("ANTHROPIC_API_KEY=sk-secret; internal details here")

    monkeypatch.setattr(files_module, "get_tree", _boom)
    # raise_app_exceptions=False lets FastAPI's exception_handler intercept the error
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as c:
        resp = await c.get("/api/tree")

    assert resp.status_code == 500
    body = resp.json()
    assert body == {"detail": "Internal server error"}
    # Must not leak the exception message
    assert "secret" not in resp.text
    assert "ANTHROPIC" not in resp.text
