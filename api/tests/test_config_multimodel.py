"""Tests for multi-model config accessors."""

import json
import pytest


@pytest.fixture
def tmp_config(tmp_path, monkeypatch):
    """Config pointing at a tmp_path generated dir with no pre-existing overrides."""
    monkeypatch.setattr("config.settings.generated_path", tmp_path)
    monkeypatch.setattr("config.settings.notes_path", tmp_path / "notes")
    return tmp_path


# ── Embedding model ────────────────────────────────────────────────────────────


def test_embedding_model_default(tmp_config):
    from config import settings

    assert settings.effective_embedding_model() == "BAAI/bge-small-en-v1.5"


def test_embedding_model_override(tmp_config):
    from config import settings

    cfg = tmp_config / "pillar43.config.json"
    cfg.write_text(json.dumps({"embedding_model": "BAAI/bge-base-en-v1.5"}))
    assert settings.effective_embedding_model() == "BAAI/bge-base-en-v1.5"


# ── Ollama endpoint ────────────────────────────────────────────────────────────


def test_ollama_base_url_comes_from_ollama_url(tmp_config, monkeypatch):
    """The address is the install's (OLLAMA_URL), never a saved setting."""
    from config import settings

    monkeypatch.delenv("OLLAMA_URL", raising=False)
    assert settings.effective_ollama_base_url() == "http://127.0.0.1:11434/v1"

    monkeypatch.setenv("OLLAMA_URL", "http://host.docker.internal:11434/")
    cfg = tmp_config / "pillar43.config.json"
    cfg.write_text(json.dumps({"ollama_base_url": "http://lmstudio:1234/v1"}))
    assert (
        settings.effective_ollama_base_url() == "http://host.docker.internal:11434/v1"
    )


# ── Settings API GET/POST ──────────────────────────────────────────────────────


@pytest.fixture
async def client(tmp_config):
    from httpx import AsyncClient, ASGITransport
    from main import app

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


@pytest.mark.anyio
async def test_get_settings_includes_model_fields(client):
    resp = await client.get("/api/settings")
    assert resp.status_code == 200
    data = resp.json()
    assert "ollama_base_url" in data
    for removed in ("chat_provider", "openai_base_url", "ai_model", "local_model"):
        assert removed not in data
    assert "available_embedding_models" in data


@pytest.mark.anyio
async def test_post_settings_embedding_model(client, tmp_config):
    resp = await client.post(
        "/api/settings", json={"embedding_model": "BAAI/bge-base-en-v1.5"}
    )
    assert resp.status_code == 200
    assert resp.json()["embedding_model"] == "BAAI/bge-base-en-v1.5"


@pytest.mark.anyio
async def test_post_settings_invalid_embedding_model(client):
    resp = await client.post(
        "/api/settings", json={"embedding_model": "not-a-real-model"}
    )
    assert resp.status_code == 400


@pytest.mark.anyio
async def test_post_settings_ollama_fields(client, tmp_config):
    resp = await client.post(
        "/api/settings",
        json={"ollama_base_url": "http://ollama:11434/v1", "ollama_model": "qwen3"},
    )
    assert resp.status_code == 200
    data = resp.json()
    # The address is not settable: the posted value is not stored.
    assert data["ollama_base_url"] != "http://ollama:11434/v1"
    assert data["ollama_model"] == "qwen3"
