"""No hosted key anywhere, and Ollama pinned to the host."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def hostile_env(monkeypatch):
    # Everything a hosted setup would set, from the environment:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-should-never-be-used")
    monkeypatch.setenv("OLLAMA_BASE_URL", "https://llm.example.com/v1")
    monkeypatch.setenv("OLLAMA_URL", "http://host.docker.internal:11434")


@pytest.fixture
def client():
    from main import app

    return TestClient(app, base_url="http://localhost")


def test_archive_cannot_reach_a_hosted_model(hostile_env, monkeypatch):
    from config import settings

    # Hostile saved Settings overrides, the third source of config.
    monkeypatch.setattr(
        settings,
        "_load_overrides",
        lambda: {
            "anthropic_api_key": "sk-ant-should-never-be-used",
            "ollama_base_url": "https://api.groq.com/openai/v1",
        },
    )
    assert (
        settings.effective_ollama_base_url() == "http://host.docker.internal:11434/v1"
    )


def test_no_hosted_provider_key_or_setting_exists(hostile_env, client):
    """The api has no hosted-provider key: no getter, and no field in the
    settings response or the update body (a key POSTed is not stored)."""
    from config import Settings, settings

    assert not [n for n in dir(Settings) if "api_key" in n.lower()]
    body = client.get("/api/settings").json()
    assert not [k for k in body if "api_key" in k or "anthropic" in k]
    r = client.post("/api/settings", json={"anthropic_api_key": "sk-ant-x"})
    assert r.status_code == 200
    saved = settings._load_overrides()
    assert "anthropic_api_key" not in saved


def test_vision_calls_go_only_to_the_configured_ollama(hostile_env, monkeypatch):
    """Whatever the environment and saved Settings say, an image read reaches
    exactly one place: the host's Ollama at OLLAMA_URL, with no credentials."""
    import httpx

    from config import settings
    from services import vision

    monkeypatch.setattr(
        settings,
        "_load_overrides",
        lambda: {"ollama_base_url": "https://api.groq.com/openai/v1"},
    )
    seen: list[httpx.Request] = []

    def fake_send(self, request, **kwargs):
        seen.append(request)
        return httpx.Response(
            200, json={"message": {"content": "a page"}}, request=request
        )

    monkeypatch.setattr(httpx.Client, "send", fake_send)

    assert vision.describe_image(b"\x89PNG", "image/png", "describe") == "a page"
    assert len(seen) == 1
    req = seen[0]
    assert (req.url.host, req.url.port) == ("host.docker.internal", 11434)
    assert req.url.path == "/api/chat"
    assert "authorization" not in req.headers
    assert "x-api-key" not in req.headers


def test_profile_endpoint_names_the_press(client):
    body = client.get("/api/archive/profile").json()
    assert "profile" not in body
    assert body["title"] == "Pillar-43 - Local Archive"
    assert body["org_name"] == "Lantern Wharf Editions"
    # Only views that exist; unbuilt ones (titles, people, ledger...) arrive with their screens.
    assert body["nav"] == ["ask", "files", "settings"]
    assert "profile" not in client.get("/health").json()
