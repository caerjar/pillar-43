"""Local vision: one image + one prompt -> text, via Ollama `/api/chat`.

The only place the api reads images with a model. Handwriting transcription and
image / video-frame captions both call `describe_image`. Requests go to the
configured Ollama host and nowhere else (Pillar-43 runs on local open-weight
models; there is no hosted provider to fall back to).

The model comes from `settings.effective_vision_model()` (`VISION_MODEL`). It
must already be pulled in Ollama; this module never pulls or loads anything
itself beyond what Ollama does on the first request.
"""

from __future__ import annotations

import base64
import logging

import httpx

from config import settings

log = logging.getLogger(__name__)

# Vision models on a laptop are slow on a full page; generous, but bounded.
DEFAULT_TIMEOUT_S = 300.0


def ollama_host_url() -> str:
    """Ollama's root URL (no `/v1`), from the same setting chat uses."""
    base = settings.effective_ollama_base_url().rstrip("/")
    if base.endswith("/v1"):
        base = base[: -len("/v1")]
    return base


def describe_image(
    image_bytes: bytes,
    media_type: str,
    prompt: str,
    *,
    system: str | None = None,
    schema: dict | None = None,
    max_tokens: int = 1024,
    timeout: float = DEFAULT_TIMEOUT_S,
) -> str:
    """Send one image and prompt to the local vision model; return its text.

    `schema` (a JSON schema) constrains the reply to JSON via Ollama's
    `format` field; the caller parses the returned string. `media_type` is
    kept for callers and logs; Ollama sniffs the format from the bytes.

    Raises `httpx.HTTPError` on connection, timeout or HTTP-status failures
    (`services.ai_errors._human_error` turns those into user-facing text) and
    `RuntimeError` if Ollama answers without any message content.
    """
    messages: list[dict] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append(
        {
            "role": "user",
            "content": prompt,
            "images": [base64.standard_b64encode(image_bytes).decode("ascii")],
        }
    )
    body: dict = {
        "model": settings.effective_vision_model(),
        "messages": messages,
        "stream": False,
        "think": False,
        "options": {"temperature": 0, "num_predict": max_tokens},
    }
    if schema is not None:
        body["format"] = schema
    resp = httpx.post(ollama_host_url() + "/api/chat", json=body, timeout=timeout)
    resp.raise_for_status()
    content = (resp.json().get("message") or {}).get("content")
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError(
            f"vision model {body['model']!r} returned no content for {media_type}"
        )
    return content
