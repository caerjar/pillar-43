"""A2 — TrustedHostMiddleware anti-DNS-rebinding guard.

A web page the user visits must not be able to rebind a hostname to
127.0.0.1 and drive the local API. The middleware rejects any request whose
Host header isn't in the loopback-only (extensible) allowlist.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from config import settings


def test_allowlist_is_loopback_plus_proxy_host_by_default(monkeypatch):
    monkeypatch.delenv("ALLOWED_HOSTS", raising=False)
    monkeypatch.setattr(settings, "testing", False)
    hosts = settings.effective_allowed_hosts()
    # Loopback + the `api` docker service name (the Vite proxy rewrites Host to
    # it via changeOrigin; without it every proxied request 400s).
    assert hosts == ["127.0.0.1", "localhost", "api"]
    assert "*" not in hosts


def test_allowlist_extends_via_env(monkeypatch):
    monkeypatch.setenv("ALLOWED_HOSTS", "pillar43.local, 10.0.0.5 , *")
    monkeypatch.setattr(settings, "testing", False)
    hosts = settings.effective_allowed_hosts()
    assert "pillar43.local" in hosts and "10.0.0.5" in hosts
    assert "127.0.0.1" in hosts  # loopback always kept
    assert "*" not in hosts  # wildcard is stripped


@pytest.mark.asyncio
async def test_disallowed_host_is_rejected():
    from main import app

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://evil.example.com"
    ) as c:
        res = await c.get("/health")
    assert res.status_code == 400  # "Invalid host header"


@pytest.mark.asyncio
async def test_loopback_host_is_allowed():
    from main import app

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://127.0.0.1"
    ) as c:
        res = await c.get("/health")
    assert res.status_code == 200
