import json
import urllib.parse
import urllib.request

from fastapi import APIRouter
from pydantic import BaseModel

from config import settings

router = APIRouter()


class LocalModelsResponse(BaseModel):
    models: list[str]
    error: str | None = None


@router.get("/local-models", response_model=LocalModelsResponse)
async def local_models():
    """Discover the models installed in the configured Ollama server.

    Returns {"models": [...], "error": null} on success, or {"models": [], "error": "..."} on failure.
    """
    import asyncio

    def _discover():
        base_url = settings.effective_ollama_base_url().rstrip("/")

        # SSRF guard: only allow connections to hosts that are part of this
        # deployment. Two kinds qualify, and each earned its place:
        #
        # - Loopback literals: the user's own machine, the common case.
        # - `host.docker.internal`, because under Docker it IS this machine.
        #   `OLLAMA_URL` points at it in the compose file, since the
        #   container's loopback is not the host's; omitting it would mean
        #   rejecting the address the deployment itself configured.
        #
        # Neither can be a public host: both are definitionally local. Widening
        # this further needs the same argument made again, per host.
        _parsed_url = urllib.parse.urlparse(base_url)
        _host = _parsed_url.hostname or ""
        _allowed = {
            "localhost",
            "127.0.0.1",
            "::1",
            "0.0.0.0",
            "host.docker.internal",
        }
        if _host not in _allowed:
            raise ValueError(
                f"Remote base URLs are not permitted for local model discovery: {_host!r}"
            )

        # Ollama API root is one level up from the /v1 base_url
        ollama_root = f"{_parsed_url.scheme}://{_parsed_url.netloc}"
        req = urllib.request.Request(f"{ollama_root}/api/tags")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
        return [m["name"] for m in data.get("models", [])]

    try:
        models_list = await asyncio.to_thread(_discover)
        return {"models": models_list, "error": None}
    except Exception as e:
        from services.ai_errors import _human_error

        return {"models": [], "error": _human_error(e)}
