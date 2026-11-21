"""Tests for the handwriting transcription route + supporting helpers.

Built incrementally alongside the implementation. Mirrors the pattern
in tests/test_transcription.py: tmp_path-based vault fixture, mocked
local vision call, parsed output assertions.
"""

from __future__ import annotations

import json

import pytest
from unittest.mock import patch

from fastapi.testclient import TestClient

from config import settings
from main import app
from services import handwriting
from services._diagram_path import diagram_path


# ── Pure helpers ─────────────────────────────────────────────────────────────


def test_diagram_path_encodes_mount_and_index() -> None:
    assert (
        diagram_path("library/scans/note.png", 1)
        == "generated/diagrams/library__scans__note.png.1.svg"
    )
    # Multi-page docs get globally-numbered diagrams — same source can
    # produce >1 SVG; the index keeps them distinct.
    assert (
        diagram_path("notes/journal.pdf", 7)
        == "generated/diagrams/notes__journal.pdf.7.svg"
    )


def test_diagram_path_is_pure() -> None:
    a = diagram_path("a/b/c.png", 3)
    b = diagram_path("a/b/c.png", 3)
    assert a == b


def test_is_handwriting_transcribable_accepts_images() -> None:
    assert handwriting.is_handwriting_transcribable("library/scan.png")
    assert handwriting.is_handwriting_transcribable("library/scan.JPG")
    assert handwriting.is_handwriting_transcribable("notes/diagram.gif")
    assert handwriting.is_handwriting_transcribable("photos/IMG_0042.HEIC")
    assert handwriting.is_handwriting_transcribable("library/journal.pdf")
    assert not handwriting.is_handwriting_transcribable("library/talk.mp3")
    assert not handwriting.is_handwriting_transcribable("notes/foo.md")


def test_sanitize_svg_strips_scripts_and_event_handlers() -> None:
    """Write-time SVG sanitizer must remove every script-execution vector."""
    hostile = (
        '<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)">'
        "<script>steal(document.cookie)</script>"
        '<rect onclick="alert(2)" />'
        # Multi-attribute jam: no whitespace before `onload`. The previous
        # `\\s+on[a-z]+` regex missed this and the handler reached disk.
        # The new `(^|[\\s/\\'"])on[a-z]+` form catches it via the `"`
        # boundary character. r="5" must survive.
        '<circle r="5"onload="alert(3)" />'
        '<a href="javascript:alert(4)">link</a>'
        '<foreignObject><iframe src="x"></iframe></foreignObject>'
        "</svg>"
    )
    cleaned = handwriting._sanitize_svg(hostile)
    assert "<script" not in cleaned.lower()
    assert "onload=" not in cleaned.lower(), (
        f"onload leaked through sanitizer: {cleaned!r}"
    )
    assert "onclick=" not in cleaned.lower()
    assert "javascript:" not in cleaned.lower()
    assert "<foreignobject" not in cleaned.lower()
    assert "<iframe" not in cleaned.lower()
    # Surface structure should survive.
    assert "<svg" in cleaned.lower()
    assert "<rect" in cleaned.lower()
    # The benign `r="5"` next to the jammed `onload=` must still be present
    # — the new regex preserves the captured boundary character via `\\1`.
    assert 'r="5"' in cleaned


def test_sanitize_svg_preserves_benign_content() -> None:
    benign = '<svg viewBox="0 0 100 100"><circle cx="50" cy="50" r="40" /></svg>'
    assert handwriting._sanitize_svg(benign) == benign


def test_write_diagrams_sanitizes_before_write(tmp_path, monkeypatch) -> None:
    """Hostile model output never reaches disk verbatim."""
    library = tmp_path / "library"
    library.mkdir()
    generated = tmp_path / "generated"
    generated.mkdir()
    monkeypatch.setattr(settings, "library_root", library)
    monkeypatch.setattr(settings, "generated_path", generated)
    handwriting._write_diagrams(
        "library/scan.png",
        [{"caption": "evil", "svg": "<svg><script>alert(1)</script></svg>"}],
        start_index=1,
    )
    written = (generated / "diagrams" / "library__scan.png.1.svg").read_text()
    assert "<script" not in written.lower()


def test_transcribe_rejects_oversized_source(tmp_path, monkeypatch) -> None:
    """Files above the size cap fail fast, never reach the vision call."""
    library = tmp_path / "library"
    library.mkdir()
    huge = library / "huge.png"
    huge.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * (26 * 1024 * 1024))
    monkeypatch.setattr(settings, "library_root", library)
    monkeypatch.setattr(settings, "generated_path", tmp_path / "generated")
    (tmp_path / "generated").mkdir()

    def explode(*_a, **_k):
        raise AssertionError("vision call should not happen for oversized source")

    monkeypatch.setattr(handwriting, "_call_vision", explode)

    with pytest.raises(ValueError, match="max is 25 MB"):
        handwriting.transcribe("library/huge.png")


def test_transcribe_rejects_oversized_pdf(tmp_path, monkeypatch) -> None:
    """PDFs above the page cap fail fast at the route layer (before render)."""
    from services.vault import pdf as vault_pdf

    library = tmp_path / "library"
    library.mkdir()
    pdf = library / "doorstop.pdf"
    pdf.write_bytes(b"%PDF-1.4\nfake")
    monkeypatch.setattr(settings, "library_root", library)
    monkeypatch.setattr(settings, "generated_path", tmp_path / "generated")
    (tmp_path / "generated").mkdir()
    monkeypatch.setattr(vault_pdf, "get_pdf_page_count", lambda p: 51)

    def explode(*_a, **_k):
        raise AssertionError("page-rendering should not happen for oversized PDF")

    monkeypatch.setattr(vault_pdf, "render_pdf_page", explode)

    with pytest.raises(ValueError, match="51 pages; max is 50"):
        handwriting.transcribe("library/doorstop.pdf")


def test_route_uses_human_error_for_exception(tmp_path, monkeypatch) -> None:
    """SSE error event carries _human_error(e), not raw str(e).

    Concretely: an httpx error from Ollama carrying request-payload text
    must be turned into a canned message before reaching the SSE consumer.
    """
    library = tmp_path / "library"
    library.mkdir()
    generated = tmp_path / "generated"
    generated.mkdir()
    img = library / "scan.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)
    monkeypatch.setattr(settings, "library_root", library)
    monkeypatch.setattr(settings, "generated_path", generated)

    import httpx

    def explode_with_status(image_bytes, media_type):
        request = httpx.Request("POST", "http://127.0.0.1:11434/api/chat")
        response = httpx.Response(404, request=request)
        raise httpx.HTTPStatusError(
            "model SECRET_SHOULD_BE_SCRUBBED not found",
            request=request,
            response=response,
        )

    monkeypatch.setattr(handwriting, "_call_vision", explode_with_status)

    client = TestClient(app)
    with client.stream(
        "POST",
        "/api/handwriting/transcribe",
        json={"path": "library/scan.png"},
    ) as resp:
        events = []
        for line in resp.iter_lines():
            if line.startswith("data: "):
                payload = line[6:]
                if payload == "[DONE]":
                    break
                events.append(payload)

    import json as _json

    parsed = [_json.loads(e) for e in events]
    errors = [p for p in parsed if p["event"] == "error"]
    assert len(errors) == 1, parsed
    msg = errors[0]["message"]
    assert "SECRET_SHOULD_BE_SCRUBBED" not in msg
    assert "Model not found in Ollama" in msg


def test_transcribe_handles_malformed_model_output(
    png_with_mocked_vision, monkeypatch
) -> None:
    """A reply missing required keys raises a clean RuntimeError.

    Guards against the model omitting a required field on adversarial
    inputs: the previous behaviour was a bare KeyError leaking from
    _transcribe_image, surfaced as a confusing stack trace in the UI.
    """
    rel_path, _scan, _generated = png_with_mocked_vision
    monkeypatch.undo()  # drop the stubbed _call_vision from the fixture
    library = png_with_mocked_vision[1].parent.parent
    generated = png_with_mocked_vision[2]
    monkeypatch.setattr(settings, "library_root", library)
    monkeypatch.setattr(settings, "generated_path", generated)
    monkeypatch.setattr(
        handwriting,
        "describe_image",
        lambda *_a, **_k: json.dumps({"markdown": "only this key"}),
    )

    with pytest.raises(RuntimeError, match="malformed output: missing"):
        handwriting.transcribe(rel_path)


def test_call_vision_rejects_non_json_reply(monkeypatch) -> None:
    monkeypatch.setattr(handwriting, "describe_image", lambda *_a, **_k: "{cut off")
    with pytest.raises(RuntimeError, match="invalid JSON"):
        handwriting._call_vision(b"\x89PNG", "image/png")


def test_call_vision_sends_schema_and_returns_parsed_object(monkeypatch) -> None:
    seen: dict = {}

    def fake(image_bytes, media_type, prompt, **kw):
        seen.update(kw)
        return json.dumps({"markdown": "hi", "diagrams": [], "page_kind": "text-only"})

    monkeypatch.setattr(handwriting, "describe_image", fake)
    out = handwriting._call_vision(b"\x89PNG", "image/png")
    assert out["page_kind"] == "text-only"
    assert seen["schema"] is handwriting._TRANSCRIBE_SCHEMA
    assert seen["system"] == handwriting._SYSTEM_PROMPT


def test_route_rejects_path_traversal() -> None:
    """POST with a traversal payload must not read /etc/passwd.

    settings.resolve() raises ValueError on traversal. The route's
    worker thread catches it and surfaces via _human_error which falls
    through to str(e). What matters is that no file outside the mounts
    is read — verified indirectly by ensuring no `done` event with a
    transcript_path is emitted.
    """
    client = TestClient(app)
    with client.stream(
        "POST",
        "/api/handwriting/transcribe",
        json={"path": "../../etc/passwd.png"},
    ) as resp:
        # The path has .png so is_handwriting_transcribable returns True
        # and we get past the 400-guard. The worker then fails on resolve.
        assert resp.status_code == 200
        events = []
        for line in resp.iter_lines():
            if line.startswith("data: "):
                payload = line[6:]
                if payload == "[DONE]":
                    break
                events.append(payload)
    import json as _json

    parsed = [_json.loads(e) for e in events]
    assert not [p for p in parsed if p["event"] == "done"], (
        f"traversal payload produced a done event: {parsed}"
    )
    assert [p for p in parsed if p["event"] == "error"], (
        f"traversal payload should produce an error event: {parsed}"
    )


def test_force_regenerate_clears_orphan_svgs(
    png_with_mocked_vision, monkeypatch
) -> None:
    """Force-regenerate purges <encoded>.*.svg from the previous run."""
    rel_path, _scan, generated = png_with_mocked_vision

    # First run: produces 3 diagrams.
    def fake_three(image_bytes, media_type):
        return {
            "markdown": "{{DIAGRAM:1}}{{DIAGRAM:2}}{{DIAGRAM:3}}",
            "diagrams": [
                {"caption": "a", "svg": "<svg id='a'/>"},
                {"caption": "b", "svg": "<svg id='b'/>"},
                {"caption": "c", "svg": "<svg id='c'/>"},
            ],
            "page_kind": "diagram-only",
        }

    monkeypatch.setattr(handwriting, "_call_vision", fake_three)
    handwriting.transcribe(rel_path)
    for n in (1, 2, 3):
        assert (generated / "diagrams" / f"library__scans__note.png.{n}.svg").exists()

    # Second run with force: only 1 diagram. Orphans must be gone.
    def fake_one(image_bytes, media_type):
        return {
            "markdown": "{{DIAGRAM:1}}",
            "diagrams": [{"caption": "fresh", "svg": "<svg id='fresh'/>"}],
            "page_kind": "diagram-only",
        }

    monkeypatch.setattr(handwriting, "_call_vision", fake_one)
    handwriting.transcribe(rel_path, force=True)

    assert (generated / "diagrams" / "library__scans__note.png.1.svg").exists()
    assert not (generated / "diagrams" / "library__scans__note.png.2.svg").exists()
    assert not (generated / "diagrams" / "library__scans__note.png.3.svg").exists()


def test_summarize_kinds() -> None:
    assert handwriting._summarize_kinds([]) == "blank"
    assert handwriting._summarize_kinds(["blank", "blank"]) == "blank"
    assert handwriting._summarize_kinds(["text-only", "text-only"]) == "text-only"
    assert (
        handwriting._summarize_kinds(["diagram-only", "diagram-only"]) == "diagram-only"
    )
    assert handwriting._summarize_kinds(["text-only", "diagram-only"]) == "mixed"
    assert handwriting._summarize_kinds(["text-only", "blank", "mixed"]) == "mixed"


# ── Image transcription (mocked Anthropic) ───────────────────────────────────


@pytest.fixture
def png_with_mocked_vision(tmp_path, monkeypatch):
    """Vault layout with a PNG; vision call replaced by a tool-use stub.

    Returns (rel_path, source_abs_path, generated_root).
    """
    library = tmp_path / "library"
    library.mkdir()
    generated = tmp_path / "generated"
    generated.mkdir()
    scan = library / "scans" / "note.png"
    scan.parent.mkdir(parents=True)
    scan.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)

    monkeypatch.setattr(settings, "library_root", library)
    monkeypatch.setattr(settings, "generated_path", generated)

    def fake_call_vision(image_bytes, media_type):
        assert image_bytes.startswith(b"\x89PNG"), (
            "vision call should receive raw PNG bytes"
        )
        assert media_type == "image/png", "media type should match extension"
        return {
            "markdown": "# Meeting notes\n\n- first point\n- second point\n",
            "diagrams": [],
            "page_kind": "text-only",
        }

    monkeypatch.setattr(handwriting, "_call_vision", fake_call_vision)
    return "library/scans/note.png", scan, generated


def test_transcribe_image_writes_markdown(png_with_mocked_vision) -> None:
    rel_path, _scan, generated = png_with_mocked_vision
    result = handwriting.transcribe(rel_path)

    assert (
        result["transcript_path"] == "generated/transcripts/library__scans__note.png.md"
    )
    assert result["diagrams_found"] == 0
    assert result["diagram_paths"] == []
    assert result["pages_processed"] == 1

    out_abs = generated / "transcripts" / "library__scans__note.png.md"
    text = out_abs.read_text()
    assert "source_path: library/scans/note.png" in text
    assert "page_kind: text-only" in text
    assert "diagrams_found: 0" in text
    assert "provider: ollama" in text
    # a ":" in the tag makes the YAML writer quote the value
    assert f'model: "{settings.effective_vision_model()}"' in text
    assert "# Transcript: note.png" in text
    assert "# Meeting notes" in text
    assert "- first point" in text


def test_transcribe_writes_svg_and_substitutes_placeholder(
    png_with_mocked_vision, monkeypatch
) -> None:
    """Mixed page: SVG file lands at generated/diagrams/...; markdown gets the link."""
    rel_path, _scan, generated = png_with_mocked_vision

    def fake_with_diagram(image_bytes, media_type):
        return {
            "markdown": "Intro paragraph.\n\n{{DIAGRAM:1}}\n\nAfter the diagram.\n",
            "diagrams": [
                {
                    "caption": "Forces on a block on an incline",
                    "svg": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"></svg>',
                }
            ],
            "page_kind": "mixed",
        }

    monkeypatch.setattr(handwriting, "_call_vision", fake_with_diagram)
    result = handwriting.transcribe(rel_path)

    assert result["diagrams_found"] == 1
    assert result["diagram_paths"] == [
        "generated/diagrams/library__scans__note.png.1.svg"
    ]

    svg_abs = generated / "diagrams" / "library__scans__note.png.1.svg"
    assert svg_abs.exists()
    assert "<svg" in svg_abs.read_text()

    out_abs = generated / "transcripts" / "library__scans__note.png.md"
    text = out_abs.read_text()
    assert "{{DIAGRAM:" not in text
    assert (
        "![Forces on a block on an incline](../diagrams/library__scans__note.png.1.svg)"
        in text
    )
    assert "Intro paragraph." in text
    assert "After the diagram." in text


def test_transcribe_pure_diagram_page_writes_stub_md(
    png_with_mocked_vision, monkeypatch
) -> None:
    """page_kind=diagram-only still produces a markdown stub linking the SVG.

    Locked decision from the plan: always emit a markdown entry point so
    the file tree shows context, not an orphan SVG.
    """
    rel_path, _scan, generated = png_with_mocked_vision

    def fake_pure_diagram(image_bytes, media_type):
        return {
            "markdown": "{{DIAGRAM:1}}\n",
            "diagrams": [
                {
                    "caption": "Flowchart of the request lifecycle",
                    "svg": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 100"><rect /></svg>',
                }
            ],
            "page_kind": "diagram-only",
        }

    monkeypatch.setattr(handwriting, "_call_vision", fake_pure_diagram)
    result = handwriting.transcribe(rel_path)

    assert result["diagrams_found"] == 1
    out_text = (generated / "transcripts" / "library__scans__note.png.md").read_text()
    assert "page_kind: diagram-only" in out_text
    assert (
        "![Flowchart of the request lifecycle](../diagrams/library__scans__note.png.1.svg)"
        in out_text
    )


def test_substitute_handles_missing_placeholder_entry(monkeypatch) -> None:
    """{{DIAGRAM:3}} referenced but only 2 diagrams: don't crash, leave a marker."""
    result = handwriting._substitute_diagram_placeholders(
        "before {{DIAGRAM:3}} after",
        diagrams=[
            {"caption": "a", "svg": "<svg/>"},
            {"caption": "b", "svg": "<svg/>"},
        ],
        diagram_paths=[
            "generated/diagrams/x.1.svg",
            "generated/diagrams/x.2.svg",
        ],
    )
    assert "_[diagram 3 missing]_" in result


# ── PDF multi-page ───────────────────────────────────────────────────────────


@pytest.fixture
def pdf_with_mocked_render(tmp_path, monkeypatch):
    """Vault layout with a fake PDF; pdf rendering + page count mocked.

    Lets tests script per-page vision responses without needing a real
    PDF (and without invoking the real PDFium renderer during unit tests).
    Returns (rel_path, source_abs, generated_root).
    """
    from services.vault import pdf as vault_pdf

    library = tmp_path / "library"
    library.mkdir()
    generated = tmp_path / "generated"
    generated.mkdir()
    pdf_path = library / "journal.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\nfake")

    monkeypatch.setattr(settings, "library_root", library)
    monkeypatch.setattr(settings, "generated_path", generated)

    # We patch where the service consumes them (consumer-side patching,
    # per feedback-patch-where-used) — imports happen inside _transcribe_pdf.
    return "library/journal.pdf", pdf_path, generated, vault_pdf


def test_transcribe_pdf_iterates_pages_and_assembles(
    pdf_with_mocked_render, monkeypatch
) -> None:
    rel_path, _pdf, generated, vault_pdf = pdf_with_mocked_render
    monkeypatch.setattr(vault_pdf, "get_pdf_page_count", lambda p: 3)
    monkeypatch.setattr(
        vault_pdf, "render_pdf_page", lambda p, page, dpi: f"page{page}-bytes".encode()
    )

    per_page_responses = {
        1: {"markdown": "intro text.\n", "diagrams": [], "page_kind": "text-only"},
        2: {
            "markdown": "before {{DIAGRAM:1}} after\n",
            "diagrams": [{"caption": "diagram A", "svg": "<svg/>"}],
            "page_kind": "mixed",
        },
        3: {
            "markdown": "two diagrams: {{DIAGRAM:1}} and {{DIAGRAM:2}}\n",
            "diagrams": [
                {"caption": "diagram B", "svg": "<svg id='b'/>"},
                {"caption": "diagram C", "svg": "<svg id='c'/>"},
            ],
            "page_kind": "mixed",
        },
    }
    seq = iter([per_page_responses[1], per_page_responses[2], per_page_responses[3]])
    monkeypatch.setattr(handwriting, "_call_vision", lambda b, m: next(seq))

    result = handwriting.transcribe(rel_path)

    assert result["pages_processed"] == 3
    assert result["diagrams_found"] == 3
    assert result["diagram_paths"] == [
        "generated/diagrams/library__journal.pdf.1.svg",
        "generated/diagrams/library__journal.pdf.2.svg",
        "generated/diagrams/library__journal.pdf.3.svg",
    ]

    md = (generated / "transcripts" / "library__journal.pdf.md").read_text()
    assert "## Page 1" in md
    assert "## Page 2" in md
    assert "## Page 3" in md
    assert "intro text." in md
    # Page-2 placeholder resolves to diagram 1 (first globally).
    assert "![diagram A](../diagrams/library__journal.pdf.1.svg)" in md
    # Page-3 placeholders resolve to globally numbered diagrams 2 and 3.
    assert "![diagram B](../diagrams/library__journal.pdf.2.svg)" in md
    assert "![diagram C](../diagrams/library__journal.pdf.3.svg)" in md
    assert "page_kind: mixed" in md

    for n in (1, 2, 3):
        assert (generated / "diagrams" / f"library__journal.pdf.{n}.svg").exists()


def test_transcribe_pdf_continues_on_per_page_failure(
    pdf_with_mocked_render, monkeypatch
) -> None:
    """A vision-call failure on one page emits a marker and continues."""
    rel_path, _pdf, generated, vault_pdf = pdf_with_mocked_render
    monkeypatch.setattr(vault_pdf, "get_pdf_page_count", lambda p: 3)
    monkeypatch.setattr(vault_pdf, "render_pdf_page", lambda p, page, dpi: b"png-bytes")

    call_seq = {"n": 0}

    def flaky_call(image_bytes, media_type):
        call_seq["n"] += 1
        if call_seq["n"] == 2:
            raise RuntimeError("vision blew up on page 2")
        return {"markdown": "page text\n", "diagrams": [], "page_kind": "text-only"}

    monkeypatch.setattr(handwriting, "_call_vision", flaky_call)
    result = handwriting.transcribe(rel_path)

    assert result["pages_processed"] == 3, "still counts pages even when one fails"
    md = (generated / "transcripts" / "library__journal.pdf.md").read_text()
    assert "## Page 1" in md
    assert "## Page 2" in md
    assert "_[page 2 — extraction failed: vision blew up on page 2]_" in md
    assert "## Page 3" in md


def test_transcribe_pdf_render_failure_records_page_marker(
    pdf_with_mocked_render, monkeypatch
) -> None:
    rel_path, _pdf, generated, vault_pdf = pdf_with_mocked_render
    monkeypatch.setattr(vault_pdf, "get_pdf_page_count", lambda p: 2)

    def flaky_render(p, page, dpi):
        if page == 1:
            raise RuntimeError("renderer exploded")
        return b"png-bytes"

    monkeypatch.setattr(vault_pdf, "render_pdf_page", flaky_render)
    monkeypatch.setattr(
        handwriting,
        "_call_vision",
        lambda b, m: {
            "markdown": "real content\n",
            "diagrams": [],
            "page_kind": "text-only",
        },
    )

    handwriting.transcribe(rel_path)
    md = (generated / "transcripts" / "library__journal.pdf.md").read_text()
    assert "_[page 1 — render failed: renderer exploded]_" in md
    assert "real content" in md


def test_single_page_pdf_omits_page_header(pdf_with_mocked_render, monkeypatch) -> None:
    rel_path, _pdf, generated, vault_pdf = pdf_with_mocked_render
    monkeypatch.setattr(vault_pdf, "get_pdf_page_count", lambda p: 1)
    monkeypatch.setattr(vault_pdf, "render_pdf_page", lambda p, page, dpi: b"png")
    monkeypatch.setattr(
        handwriting,
        "_call_vision",
        lambda b, m: {
            "markdown": "lone page\n",
            "diagrams": [],
            "page_kind": "text-only",
        },
    )
    handwriting.transcribe(rel_path)
    md = (generated / "transcripts" / "library__journal.pdf.md").read_text()
    assert "## Page" not in md
    assert "lone page" in md


# ── HEIC handling ────────────────────────────────────────────────────────────


def test_heic_inputs_transcoded_to_jpeg_before_vision_call(
    tmp_path, monkeypatch
) -> None:
    """Source has .heic extension → vision call receives JPEG bytes + jpeg media_type.

    Generates a real HEIC fixture in-test via Pillow + pillow-heif so the
    transcode path is exercised end-to-end, not just mocked.
    """
    pytest.importorskip("pillow_heif")
    # The opener must be registered before Pillow can WRITE a HEIC fixture
    # below — Pillow can't sniff HEIF without the plugin. The service has
    # its own registration call inside _heic_to_jpeg_bytes, so this isn't
    # masking a regression in the service path.
    import pillow_heif

    pillow_heif.register_heif_opener()
    from PIL import Image

    library = tmp_path / "library"
    library.mkdir()
    generated = tmp_path / "generated"
    generated.mkdir()
    heic_path = library / "photo.heic"
    Image.new("RGB", (16, 16), color=(200, 100, 50)).save(heic_path, format="HEIF")

    monkeypatch.setattr(settings, "library_root", library)
    monkeypatch.setattr(settings, "generated_path", generated)

    seen: dict = {}

    def capture_call(image_bytes, media_type):
        seen["bytes"] = image_bytes
        seen["media_type"] = media_type
        return {"markdown": "hello\n", "diagrams": [], "page_kind": "text-only"}

    monkeypatch.setattr(handwriting, "_call_vision", capture_call)
    handwriting.transcribe("library/photo.heic")

    assert seen["media_type"] == "image/jpeg"
    # JPEG magic: FF D8 FF
    assert seen["bytes"][:3] == b"\xff\xd8\xff"


def test_route_accepts_heic_extension() -> None:
    """Route guard accepts .heic now that HEIC is in HANDWRITING_EXTS."""
    # Negative control — .mp3 still rejected — already covered above; this
    # asserts the positive side: handler isn't called yet (will 500 because
    # no file exists), but the 400 extension guard does NOT fire.
    client = TestClient(app)
    res = client.post(
        "/api/handwriting/transcribe",
        json={"path": "library/does-not-exist.heic"},
    )
    # The extension check passes (no 400); the missing file surfaces later.
    assert res.status_code != 400


def test_write_diagrams_skips_empty_svg(tmp_path, monkeypatch) -> None:
    library = tmp_path / "library"
    library.mkdir()
    generated = tmp_path / "generated"
    generated.mkdir()
    monkeypatch.setattr(settings, "library_root", library)
    monkeypatch.setattr(settings, "generated_path", generated)

    paths = handwriting._write_diagrams(
        "library/scan.png",
        [
            {"caption": "real", "svg": "<svg/>"},
            {"caption": "empty", "svg": ""},
            {"caption": "whitespace", "svg": "   \n"},
        ],
        start_index=1,
    )
    assert paths == [
        "generated/diagrams/library__scan.png.1.svg",
        "",
        "",
    ]
    assert (generated / "diagrams" / "library__scan.png.1.svg").exists()
    assert not (generated / "diagrams" / "library__scan.png.2.svg").exists()


def test_transcribe_skips_when_source_hash_matches(png_with_mocked_vision) -> None:
    """Second pass on unchanged source short-circuits — no vision call."""
    rel_path, _scan, _generated = png_with_mocked_vision
    handwriting.transcribe(rel_path)
    with patch.object(
        handwriting,
        "_call_vision",
        side_effect=AssertionError("should not call vision on unchanged source"),
    ):
        result = handwriting.transcribe(rel_path)
    assert (
        result["transcript_path"] == "generated/transcripts/library__scans__note.png.md"
    )


def test_transcribe_force_flag_bypasses_skip(
    png_with_mocked_vision, monkeypatch
) -> None:
    """force=True regenerates even if the transcript already matches the hash."""
    rel_path, _scan, _generated = png_with_mocked_vision
    handwriting.transcribe(rel_path)

    call_count = {"n": 0}

    def counting_call(image_bytes, media_type):
        call_count["n"] += 1
        return {"markdown": "fresh content\n", "diagrams": [], "page_kind": "text-only"}

    monkeypatch.setattr(handwriting, "_call_vision", counting_call)
    handwriting.transcribe(rel_path, force=True)
    assert call_count["n"] == 1


def test_transcribe_regenerates_when_source_changes(png_with_mocked_vision) -> None:
    rel_path, scan, generated = png_with_mocked_vision
    handwriting.transcribe(rel_path)
    out_abs = generated / "transcripts" / "library__scans__note.png.md"
    first_hash_line = next(
        line
        for line in out_abs.read_text().splitlines()
        if line.startswith("source_hash:")
    )
    scan.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\xff" * 64)
    handwriting.transcribe(rel_path)
    new_hash_line = next(
        line
        for line in out_abs.read_text().splitlines()
        if line.startswith("source_hash:")
    )
    assert first_hash_line != new_hash_line


def test_transcribe_rejects_unsupported_extension(tmp_path, monkeypatch) -> None:
    library = tmp_path / "library"
    library.mkdir()
    (library / "talk.mp3").write_bytes(b"x")
    monkeypatch.setattr(settings, "library_root", library)
    with pytest.raises(ValueError, match="Not a handwriting-transcribable"):
        handwriting.transcribe("library/talk.mp3")


# ── Route ────────────────────────────────────────────────────────────────────


def test_route_rejects_non_image_extension() -> None:
    """The HTTP layer guards the same set the service does (400, not 500)."""
    client = TestClient(app)
    res = client.post(
        "/api/handwriting/transcribe",
        json={"path": "library/talk.mp3"},
    )
    assert res.status_code == 400
    assert "handwriting-transcribable" in res.json()["detail"]


def test_route_streams_progress_and_done(png_with_mocked_vision) -> None:
    """SSE happy path: at least one progress event, then a done event with the result."""
    rel_path, _scan, _generated = png_with_mocked_vision
    client = TestClient(app)
    with client.stream(
        "POST",
        "/api/handwriting/transcribe",
        json={"path": rel_path},
    ) as resp:
        assert resp.status_code == 200
        events = []
        for line in resp.iter_lines():
            if not line:
                continue
            if line.startswith("data: "):
                payload = line[6:]
                if payload == "[DONE]":
                    break
                events.append(payload)

    import json as _json

    parsed = [_json.loads(e) for e in events]
    assert any(p["event"] == "progress" for p in parsed)
    done = [p for p in parsed if p["event"] == "done"]
    assert len(done) == 1
    result = done[0]["result"]
    assert (
        result["transcript_path"] == "generated/transcripts/library__scans__note.png.md"
    )
    assert result["diagrams_found"] == 0
    assert result["pages_processed"] == 1
