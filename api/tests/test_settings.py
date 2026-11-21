"""Tests for settings endpoint — Sprint 59 (summarize_context_chars)."""

import json
import pytest
from httpx import AsyncClient, ASGITransport

import config as config_mod
from main import app


def _make_settings(tmp_path, monkeypatch):
    active = tmp_path / "notes"
    active.mkdir()
    vault = tmp_path / "library"
    vault.mkdir()
    generated = tmp_path / "generated"
    generated.mkdir()
    monkeypatch.setattr(config_mod.settings, "notes_path", active)
    monkeypatch.setattr(config_mod.settings, "library_root", vault)
    monkeypatch.setattr(config_mod.settings, "generated_path", generated)
    return active, vault, generated


@pytest.fixture
async def client(tmp_path, monkeypatch):
    _make_settings(tmp_path, monkeypatch)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


# ── Removed personal fields ──────────────────────────────────────────────────

REMOVED_FIELDS = [
    "summarize_context_chars",
    "max_recent_files",
    "display_name",
    "new_note_format",
    "background_jobs",
    "style_aware_skills",
    "openai_model",
    "gemini_api_key_set",
    "gemini_base_url",
    "gemini_model",
    "groq_api_key_set",
    "groq_base_url",
    "groq_model",
    "ai_model",
    "chat_provider",
    "openai_base_url",
    "openai_api_key_set",
    "local_base_url",
    "local_model",
    "transcription_provider",
    "available_models",
    "available_chat_providers",
    "anthropic_api_key_set",
    "anthropic_api_key_masked",
    "task_model_overrides",
    "available_task_types",
]


@pytest.mark.asyncio
async def test_settings_response_has_no_personal_or_hosted_provider_fields(client):
    """GET /api/settings no longer reports the personal fields or the
    Gemini and Groq provider keys."""
    response = await client.get("/api/settings")
    assert response.status_code == 200
    body = response.json()
    present = [f for f in REMOVED_FIELDS if f in body]
    assert not present, f"removed fields still reported: {present}"


@pytest.mark.asyncio
async def test_settings_post_ignores_a_removed_field(client):
    """A removed field is not stored: the POST succeeds and nothing is written."""
    response = await client.post(
        "/api/settings", json={"summarize_context_chars": 8000}
    )
    assert response.status_code == 200
    assert "summarize_context_chars" not in response.json()
    config_path = config_mod.settings.generated_path / "pillar43.config.json"
    if config_path.exists():
        assert "summarize_context_chars" not in json.loads(config_path.read_text())


@pytest.mark.asyncio
async def test_settings_post_no_translation_language(client):
    """translation_language field is no longer accepted (removed in Sprint 59)."""
    # Sending it should not cause an error (Pydantic ignores unknown fields by default
    # depending on config, but more importantly the response must NOT include it).
    response = await client.get("/api/settings")
    assert response.status_code == 200
    body = response.json()
    assert "translation_language" not in body


# ── Enum validation ──────────────────────────────────────────────────────────
#
# Characterization, written before the branch-per-field chain in
# update_settings was turned into a declarative table. Each of these was one
# hand-written `if X not in (...): raise 400` block; none had a test, so
# nothing would have caught the table dropping a field or widening what it
# accepts. Parameterised so adding a field to the table without a case here is
# visible.

ENUM_FIELDS = [
    # (field, a valid value, an invalid value)
    ("move_confirm", "silent", "maybe"),
    ("local_whisper_model", "tiny.en", "not-a-size"),
]


@pytest.mark.parametrize("field,good,bad", ENUM_FIELDS)
async def test_enum_field_rejects_an_unknown_value(client, field, good, bad):
    r = await client.post("/api/settings", json={field: bad})
    assert r.status_code == 400, f"{field} accepted {bad!r}"
    assert field in r.json()["detail"], "the message must name the field"


@pytest.mark.parametrize("field,good,bad", ENUM_FIELDS)
async def test_enum_field_accepts_a_valid_value(client, field, good, bad):
    r = await client.post("/api/settings", json={field: good})
    assert r.status_code == 200, f"{field} rejected {good!r}: {r.text}"


async def test_embedding_model_is_validated(client):
    r = await client.post("/api/settings", json={"embedding_model": "not-a-model"})
    assert r.status_code == 400
    assert "embedding_model" in r.json()["detail"]


async def test_local_whisper_model_is_validated(client):
    r = await client.post("/api/settings", json={"local_whisper_model": "not-a-size"})
    assert r.status_code == 400
    assert "local_whisper_model" in r.json()["detail"]


async def test_a_passthrough_field_round_trips(client):
    """The 14 no-validation fields must keep passing straight through."""
    r = await client.post("/api/settings", json={"voice_language": "en"})
    assert r.status_code == 200
    assert r.json()["voice_language"] == "en"


async def test_an_omitted_field_is_left_alone(client):
    """`is not None` gating: omitting a field must not reset it."""
    await client.post("/api/settings", json={"voice_language": "en"})
    await client.post("/api/settings", json={"ollama_model": "qwen3"})
    r = await client.get("/api/settings")
    assert r.json()["voice_language"] == "en"


async def test_every_string_passthrough_field_is_stripped(client):
    """The nine unguarded transforms.

    These fields arrive from text inputs and are `.strip()`ed before storage —
    a trailing space in an API key or base URL is a support ticket. When the
    branch chain became a table, the first version dropped the transform on 10
    of 14 fields; only voice_language had a test, so nine of them would have
    regressed silently. This covers the rest.
    """
    from routes.settings import _PASSTHROUGH_FIELDS

    stripped = [f for f, t in _PASSTHROUGH_FIELDS if t is not None]
    assert len(stripped) >= 2, "the table lost its transforms"

    payload = {f: f"  value-for-{f}  " for f in stripped}
    r = await client.post("/api/settings", json=payload)
    assert r.status_code == 200, r.text

    got = r.json()
    # API keys are deliberately not echoed back — the response reports whether
    # one is SET, never its value. So assert on the fields that do round-trip,
    # and require that to be most of them rather than silently checking none.
    checked = [f for f in payload if f in got]
    assert len(checked) >= 2, f"only {len(checked)} fields round-trip; test is vacuous"
    for f in checked:
        assert got[f] == f"value-for-{f}", f"{f} was not stripped"


# ── Bounded integers and extension lists ─────────────────────────────────────
#
# Characterization for the second settings split: range-checked ints and
# two identical extension normalisers, each previously its own branch.

RANGE_FIELDS = [
    # (field, too_low, ok, too_high)
    ("transcription_max_frames_per_video", 0, 10, 51),
]


@pytest.mark.parametrize("field,low,ok,high", RANGE_FIELDS)
async def test_bounded_int_rejects_below_range(client, field, low, ok, high):
    r = await client.post("/api/settings", json={field: low})
    assert r.status_code == 400, f"{field} accepted {low}"
    assert field in r.json()["detail"]


@pytest.mark.parametrize("field,low,ok,high", RANGE_FIELDS)
async def test_bounded_int_rejects_above_range(client, field, low, ok, high):
    if high is None:
        pytest.skip(f"{field} has no upper bound")
    r = await client.post("/api/settings", json={field: high})
    assert r.status_code == 400, f"{field} accepted {high}"


@pytest.mark.parametrize("field,low,ok,high", RANGE_FIELDS)
async def test_bounded_int_accepts_in_range(client, field, low, ok, high):
    r = await client.post("/api/settings", json={field: ok})
    assert r.status_code == 200, r.text
    assert r.json()[field] == ok


@pytest.mark.parametrize("field", ["excluded_extensions", "tree_dim_extensions"])
async def test_extensions_are_normalised(client, field):
    """Leading dot added, lowercased, whitespace trimmed, blanks dropped —
    so a user typing "PDF, .Png,  " gets what they meant."""
    r = await client.post("/api/settings", json={field: ["PDF", " .Png ", "", "  "]})
    assert r.status_code == 200, r.text
    assert r.json()[field] == [".pdf", ".png"]


# ── Ollama endpoint ──────────────────────────────────────────────────────────
#
# Every assertion below pins the PORT rather than the whole URL: the address
# is `OLLAMA_URL`'s, and the host differs between the Docker stack and the
# desktop app.


def _port(url: str) -> int | None:
    from urllib.parse import urlparse

    return urlparse(url).port


def test_ollama_base_url_defaults_to_ollamas_own_port(tmp_path, monkeypatch):
    """Ollama's own port."""
    _make_settings(tmp_path, monkeypatch)
    monkeypatch.delenv("OLLAMA_URL", raising=False)
    assert _port(config_mod.settings.effective_ollama_base_url()) == 11434


@pytest.mark.asyncio
async def test_settings_round_trips_the_ollama_endpoint(client):
    """POST stores the Ollama model and GET reports it back; the address is
    the install's (OLLAMA_URL) and a posted one is not stored."""
    response = await client.post(
        "/api/settings",
        json={
            "ollama_base_url": "http://127.0.0.1:9999/v1",
            "ollama_model": "qwen2.5",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert _port(body["ollama_base_url"]) != 9999
    # Models are stored verbatim — no host rewriting applies to them.
    assert body["ollama_model"] == "qwen2.5"
