"""The personal-practice routers are gone, not hidden.

A 404 alone would also be what the allowlist gate answers, so each path is
also checked against `app.routes`: no mounted route may carry the prefix.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.real_gate

# (method, request path, route prefix that must not exist in app.routes)
REMOVED = [
    ("GET", "/api/commons", "/api/commons"),
    ("GET", "/api/commons/items", "/api/commons"),
    ("GET", "/api/dispatch", "/api/dispatch"),
    ("GET", "/api/tasks", "/api/tasks"),
    ("GET", "/api/graph/stats", "/api/graph"),
    ("POST", "/api/ai/chat", "/api/ai/chat"),
    ("GET", "/api/sources", "/api/sources"),
    ("GET", "/api/sources/google-drive/status", "/api/sources"),
    ("GET", "/api/ai/meridian/soul", "/api/ai/meridian"),
    ("GET", "/api/history", "/api/history"),
    ("GET", "/api/history/some/file.md", "/api/history"),
    ("POST", "/api/catalog/run", "/api/catalog/run"),
]


@pytest.fixture
def client():
    from main import app

    return TestClient(app, base_url="http://localhost")


@pytest.mark.parametrize("method,path,prefix", REMOVED)
def test_removed_route_answers_404(client, method, path, prefix):
    assert client.request(method, path, json={}).status_code == 404


@pytest.mark.parametrize("prefix", sorted({p for _, _, p in REMOVED}))
def test_no_route_is_mounted_under_a_removed_prefix(prefix):
    from main import app

    mounted = [r.path for r in app.routes if getattr(r, "path", "").startswith(prefix)]
    assert mounted == []
