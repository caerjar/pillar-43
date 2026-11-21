"""services/vision.describe_image: one image + prompt to local Ollama /api/chat."""

from __future__ import annotations

import base64
import json

import httpx
import pytest

from config import settings
from services import vision


@pytest.fixture
def sent(monkeypatch):
    """Capture every outgoing httpx request; reply per `reply` (mutable)."""
    state: dict = {"requests": [], "reply": (200, {"message": {"content": "ok"}})}

    def fake_send(self, request, **kwargs):
        state["requests"].append(request)
        status, payload = state["reply"]
        return httpx.Response(status, json=payload, request=request)

    monkeypatch.setattr(httpx.Client, "send", fake_send)
    monkeypatch.setattr(settings, "_load_overrides", dict)
    monkeypatch.setenv("OLLAMA_URL", "http://127.0.0.1:11434")
    monkeypatch.delenv("VISION_MODEL", raising=False)
    return state


def test_request_shape(sent):
    out = vision.describe_image(b"imgbytes", "image/png", "what is this?")
    assert out == "ok"
    (req,) = sent["requests"]
    assert str(req.url) == "http://127.0.0.1:11434/api/chat"
    body = json.loads(req.content)
    assert body["model"] == settings.effective_vision_model() == "qwen2.5vl:7b"
    assert body["stream"] is False
    assert "format" not in body
    (msg,) = body["messages"]
    assert msg["role"] == "user" and msg["content"] == "what is this?"
    assert msg["images"] == [base64.b64encode(b"imgbytes").decode()]


def test_system_prompt_schema_and_token_limit(sent):
    schema = {"type": "object", "properties": {"a": {"type": "string"}}}
    vision.describe_image(
        b"x", "image/jpeg", "p", system="be terse", schema=schema, max_tokens=77
    )
    body = json.loads(sent["requests"][0].content)
    assert body["messages"][0] == {"role": "system", "content": "be terse"}
    assert body["format"] == schema
    assert body["options"]["num_predict"] == 77


def test_model_comes_from_the_vision_model_setting(sent, monkeypatch):
    monkeypatch.setenv("VISION_MODEL", "gemma3:12b")
    vision.describe_image(b"x", "image/png", "p")
    assert json.loads(sent["requests"][0].content)["model"] == "gemma3:12b"


def test_http_error_status_propagates(sent):
    sent["reply"] = (404, {"error": "model not found"})
    with pytest.raises(httpx.HTTPStatusError):
        vision.describe_image(b"x", "image/png", "p")


def test_empty_content_is_an_error(sent):
    sent["reply"] = (200, {"message": {"content": "  "}})
    with pytest.raises(RuntimeError, match="no content"):
        vision.describe_image(b"x", "image/png", "p")


def test_connection_failure_reads_as_ollama_not_running():
    from services.ai_errors import _human_error

    msg = _human_error(httpx.ConnectError("refused"))
    assert "Ollama" in msg and "running" in msg
