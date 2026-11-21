"""AI provider error classification.

The only model provider is the local Ollama server, reached over httpx
(`services/vision.py`) or urllib (`routes/ai/_provider.py`, `services/archive`).
`_human_error` maps whatever those raise to text safe to show a user.

Request payloads can ride inside exception text, so recognised exceptions are
mapped to canned strings and unrecognised httpx errors degrade to the class
name only. Errors raised by our own code pass through: they are written to be
read.
"""

from __future__ import annotations

import httpx


def _classify_ollama(exc: Exception) -> str | None:
    """Canned text for httpx errors from the local Ollama server, else None."""
    if isinstance(exc, httpx.TimeoutException):
        return (
            "The local model timed out - it may still be loading. "
            "Try again in a minute."
        )
    if isinstance(exc, httpx.ConnectError):
        return "Could not connect to Ollama - is it running?"
    if isinstance(exc, httpx.HTTPStatusError):
        if exc.response.status_code == 404:
            return (
                "Model not found in Ollama - check the model name in Settings "
                "and that it has been pulled."
            )
        return f"Ollama returned an error ({exc.response.status_code})."
    if isinstance(exc, httpx.HTTPError):
        return f"AI provider error ({type(exc).__name__})"
    return None


def _human_error(exc: Exception) -> str:
    """Map provider exceptions to human-readable messages."""
    hit = _classify_ollama(exc)
    if hit is not None:
        return hit

    msg = str(exc)
    if "connection" in msg.lower() or "refused" in msg.lower():
        return "Could not connect to the AI provider - is it running?"
    return msg
