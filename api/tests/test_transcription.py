"""Transcription service tests.

Mocks ffprobe + faster-whisper + the Anthropic caption client so the suite
runs without network or media files.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from config import settings
from services import transcription
from services._transcript_path import transcript_path


# ── Pure helpers ──────────────────────────────────────────────────────────────


def test_transcript_path_encodes_mount_and_slashes():
    assert (
        transcript_path("library/2024/foo.mp3")
        == "generated/transcripts/library__2024__foo.mp3.md"
    )
    assert (
        transcript_path("notes/audio/talk.wav")
        == "generated/transcripts/notes__audio__talk.wav.md"
    )


def test_is_transcribable_covers_audio_video_image():
    assert transcription.is_transcribable("library/foo.mp3")
    assert transcription.is_transcribable("library/foo.mp4")
    assert transcription.is_transcribable("library/foo.jpg")
    assert not transcription.is_transcribable("library/foo.pdf")
    assert not transcription.is_transcribable("notes/foo.md")


def test_format_timestamp_short_and_long():
    assert transcription._format_timestamp(0) == "00:00"
    assert transcription._format_timestamp(125) == "02:05"
    assert transcription._format_timestamp(3725) == "01:02:05"


def test_segments_to_markdown_empty_returns_marker():
    assert "no speech detected" in transcription._segments_to_markdown([])


def test_segments_to_markdown_formats_lines():
    out = transcription._segments_to_markdown(
        [
            {"start": 0.0, "end": 1.5, "text": "Hello."},
            {"start": 1.5, "end": 3.0, "text": "World."},
        ]
    )
    assert "[00:00] Hello." in out
    assert "[00:01] World." in out


def test_format_transcript_writes_frontmatter_and_body():
    out = transcription._format_transcript(
        "library/foo.mp3",
        {"source_path": "library/foo.mp3", "provider": "local", "frame_samples": 0},
        "[00:00] hi\n",
    )
    assert out.startswith("---\n")
    assert "source_path: library/foo.mp3" in out
    assert "provider: local" in out
    assert "frame_samples: 0" in out
    assert "# Transcript: foo.mp3" in out
    assert "[00:00] hi" in out


# ── Provider/model helpers ────────────────────────────────────────────────────


def test_speed_factor_falls_back_to_default_for_unknown_local_model(monkeypatch):
    monkeypatch.setattr(
        settings,
        "_load_overrides",
        lambda: {
            "local_whisper_model": "distil-small.en",
        },
    )
    assert transcription._speed_factor() == 6.0


# ── Hash-based skip ───────────────────────────────────────────────────────────


def test_existing_matches_returns_true_when_hash_present(tmp_path):
    f = tmp_path / "t.md"
    f.write_text("---\nsource_hash: abc123\n---\nbody\n")
    assert transcription._existing_matches(f, "abc123") is True
    assert transcription._existing_matches(f, "different") is False


def test_existing_matches_returns_false_for_missing_file(tmp_path):
    assert transcription._existing_matches(tmp_path / "missing.md", "anything") is False


# ── End-to-end with mocked Whisper ────────────────────────────────────────────


@pytest.fixture
def mp3_with_mocked_whisper(tmp_path, monkeypatch):
    """Set up a fake mp3 + mocked faster-whisper, return the rel_path."""
    library = tmp_path / "library"
    library.mkdir()
    generated = tmp_path / "generated"
    generated.mkdir()
    audio = library / "talk.mp3"
    audio.write_bytes(b"\x00" * 1024)  # placeholder bytes, never decoded

    monkeypatch.setattr(settings, "library_root", library)
    monkeypatch.setattr(settings, "generated_path", generated)
    monkeypatch.setattr(
        settings,
        "_load_overrides",
        lambda: {"local_whisper_model": "tiny.en"},
    )

    # Mock ffprobe
    monkeypatch.setattr(transcription, "_ffprobe_duration", lambda p: 60.0)

    # Mock faster-whisper transcribe to skip the model load + decode
    class FakeSeg:
        def __init__(self, start, end, text):
            self.start, self.end, self.text = start, end, text

    class FakeInfo:
        duration = 60.0
        language = "en"

    def fake_whisper_local(abs_path, progress):
        segs = [
            {"start": 0.0, "end": 4.0, "text": "First sentence."},
            {"start": 4.0, "end": 8.0, "text": "Second sentence."},
        ]
        return segs, "en", "tiny.en"

    monkeypatch.setattr(transcription, "_whisper_local", fake_whisper_local)
    return "library/talk.mp3", audio, generated


def test_transcribe_audio_writes_transcript_with_frontmatter(mp3_with_mocked_whisper):
    rel_path, audio, generated = mp3_with_mocked_whisper
    out_rel = transcription.transcribe(rel_path)
    assert out_rel == "generated/transcripts/library__talk.mp3.md"
    out_abs = generated / "transcripts" / "library__talk.mp3.md"
    assert out_abs.exists()
    text = out_abs.read_text()
    assert "source_path: library/talk.mp3" in text
    assert "provider: local" in text
    assert "model: tiny.en" in text
    assert "language: en" in text
    assert "# Transcript: talk.mp3" in text
    assert "[00:00] First sentence." in text
    assert "[00:04] Second sentence." in text


def test_transcribe_skips_when_source_hash_matches(mp3_with_mocked_whisper):
    rel_path, audio, generated = mp3_with_mocked_whisper
    # First pass writes the transcript
    transcription.transcribe(rel_path)
    # Patch the underlying Whisper call to blow up if invoked again
    with patch.object(
        transcription,
        "_whisper_local",
        side_effect=AssertionError("should not be called"),
    ):
        out_rel = transcription.transcribe(rel_path)
    assert out_rel == "generated/transcripts/library__talk.mp3.md"


def test_transcribe_regenerates_when_source_changes(mp3_with_mocked_whisper):
    rel_path, audio, generated = mp3_with_mocked_whisper
    transcription.transcribe(rel_path)
    out_abs = generated / "transcripts" / "library__talk.mp3.md"
    first_hash_line = next(
        ln for ln in out_abs.read_text().splitlines() if ln.startswith("source_hash:")
    )
    # Modify source bytes — produces a different hash
    audio.write_bytes(b"\xff" * 1024)
    transcription.transcribe(rel_path)
    new_hash_line = next(
        ln for ln in out_abs.read_text().splitlines() if ln.startswith("source_hash:")
    )
    assert first_hash_line != new_hash_line


# ── Catalog integration ──────────────────────────────────────────────────────


def test_extract_text_for_catalog_returns_transcript_for_audio(tmp_path, monkeypatch):
    """Once a transcript exists, the catalog's text extractor returns its content."""
    from services.catalog import extract_text_for_catalog

    library = tmp_path / "library"
    library.mkdir()
    generated = tmp_path / "generated"
    (generated / "transcripts").mkdir(parents=True)

    audio = library / "talk.mp3"
    audio.write_bytes(b"x")

    transcript = generated / "transcripts" / "library__talk.mp3.md"
    transcript.write_text("---\nprovider: local\n---\n# Transcript\n\n[00:00] body\n")

    monkeypatch.setattr(settings, "library_root", library)
    monkeypatch.setattr(settings, "generated_path", generated)

    out = extract_text_for_catalog(audio, "library/talk.mp3")
    assert out is not None
    assert "[00:00] body" in out


def test_extract_text_for_catalog_returns_none_without_transcript(
    tmp_path, monkeypatch
):
    from services.catalog import extract_text_for_catalog

    library = tmp_path / "library"
    library.mkdir()
    generated = tmp_path / "generated"
    generated.mkdir()
    audio = library / "talk.mp3"
    audio.write_bytes(b"x")

    monkeypatch.setattr(settings, "library_root", library)
    monkeypatch.setattr(settings, "generated_path", generated)

    assert extract_text_for_catalog(audio, "library/talk.mp3") is None


# ── Estimate endpoint ────────────────────────────────────────────────────────


def test_estimate_seconds_image_is_constant(monkeypatch, tmp_path):
    library = tmp_path / "library"
    library.mkdir()
    (library / "cover.jpg").write_bytes(b"x")
    monkeypatch.setattr(settings, "library_root", library)
    duration, processing = transcription.estimate_seconds("library/cover.jpg")
    assert duration == 0.0
    assert processing == 3.0


def test_estimate_seconds_audio_uses_duration_and_speed(monkeypatch, tmp_path):
    library = tmp_path / "library"
    library.mkdir()
    (library / "talk.mp3").write_bytes(b"x")
    monkeypatch.setattr(settings, "library_root", library)
    monkeypatch.setattr(transcription, "_ffprobe_duration", lambda p: 600.0)  # 10 min
    monkeypatch.setattr(
        settings,
        "_load_overrides",
        lambda: {
            "local_whisper_model": "distil-small.en",
        },
    )
    duration, processing = transcription.estimate_seconds("library/talk.mp3")
    assert duration == 600.0
    # 600s / 6.0x speed = 100s
    assert processing == 100.0


# ── Model cache (#1) ─────────────────────────────────────────────────────────


def test_local_model_loads_once_and_is_reused(monkeypatch, tmp_path):
    """Second call returns the cached model without re-importing or re-loading."""
    monkeypatch.setattr(settings, "generated_path", tmp_path)
    transcription._model_cache.clear()

    load_count = {"n": 0}

    class FakeModel:
        pass

    class FakeFasterWhisper:
        @staticmethod
        def WhisperModel(*args, **kwargs):
            load_count["n"] += 1
            return FakeModel()

    import sys

    monkeypatch.setitem(sys.modules, "faster_whisper", FakeFasterWhisper)

    m1 = transcription._get_local_model("tiny.en", progress=None)
    m2 = transcription._get_local_model("tiny.en", progress=None)
    assert m1 is m2
    assert load_count["n"] == 1


# ── ffprobe duration cache (#4) ──────────────────────────────────────────────


def test_ffprobe_duration_cached_by_path_and_mtime(monkeypatch, tmp_path):
    """Calling _ffprobe_duration twice on the same file invokes subprocess once."""
    transcription._duration_cache.clear()
    audio = tmp_path / "talk.mp3"
    audio.write_bytes(b"x")

    call_count = {"n": 0}

    class FakeResult:
        returncode = 0
        stderr = ""
        stdout = '{"format": {"duration": "42.5"}}'

    def fake_run(*args, **kwargs):
        call_count["n"] += 1
        return FakeResult()

    monkeypatch.setattr(transcription.subprocess, "run", fake_run)

    d1 = transcription._ffprobe_duration(audio)
    d2 = transcription._ffprobe_duration(audio)
    assert d1 == 42.5
    assert d2 == 42.5
    assert call_count["n"] == 1


def test_ffprobe_duration_cache_invalidates_on_mtime_change(monkeypatch, tmp_path):
    """Updating the file's mtime busts the cache and triggers a fresh probe."""
    transcription._duration_cache.clear()
    audio = tmp_path / "talk.mp3"
    audio.write_bytes(b"x")

    durations = iter([10.0, 99.0])

    class FakeResult:
        returncode = 0
        stderr = ""

        def __init__(self, d):
            self.stdout = f'{{"format": {{"duration": {d}}}}}'

    def fake_run(*args, **kwargs):
        return FakeResult(next(durations))

    monkeypatch.setattr(transcription.subprocess, "run", fake_run)

    assert transcription._ffprobe_duration(audio) == 10.0
    # Bump mtime forward
    import os

    new_mtime = audio.stat().st_mtime + 100
    os.utime(audio, (new_mtime, new_mtime))
    assert transcription._ffprobe_duration(audio) == 99.0


# ── #6 frontmatter-aware existing-match ──────────────────────────────────────


def test_existing_matches_only_reads_frontmatter(tmp_path):
    """Hash that appears in the body but not in the frontmatter is NOT a match."""
    f = tmp_path / "t.md"
    f.write_text(
        "---\n"
        "source_hash: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n"
        "provider: local\n"
        "---\n\n"
        "# Body\n\nQuoted source_hash: bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb in body.\n"
    )
    assert (
        transcription._existing_matches(f, "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
        is True
    )
    assert (
        transcription._existing_matches(f, "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb")
        is False
    )


def test_existing_matches_handles_missing_frontmatter(tmp_path):
    """A transcript with no frontmatter never matches."""
    f = tmp_path / "t.md"
    f.write_text("just body content with source_hash: aaaaaaaa\n")
    assert transcription._existing_matches(f, "aaaaaaaa") is False


# ── #7 ffprobe failure mode distinction ──────────────────────────────────────


def test_ffprobe_returns_zero_when_binary_missing(monkeypatch, tmp_path):
    """Missing ffmpeg surfaces a WARNING log distinguishing it from a 0-duration file."""
    transcription._duration_cache.clear()
    audio = tmp_path / "x.mp3"
    audio.write_bytes(b"x")

    warnings = []
    monkeypatch.setattr(
        transcription.log,
        "warning",
        lambda msg, *a, **kw: warnings.append(msg % a if a else msg),
    )
    monkeypatch.setattr(
        transcription.subprocess,
        "run",
        lambda *a, **kw: (_ for _ in ()).throw(FileNotFoundError("ffprobe")),
    )

    assert transcription._ffprobe_duration(audio) == 0.0
    assert any("ffprobe binary not found" in w for w in warnings)


def test_ffprobe_returns_zero_when_subprocess_nonzero(monkeypatch, tmp_path):
    """Non-zero ffprobe exit emits a distinct WARNING with the return code + stderr."""
    transcription._duration_cache.clear()
    audio = tmp_path / "x.mp3"
    audio.write_bytes(b"x")

    class FakeResult:
        returncode = 1
        stdout = ""
        stderr = "Invalid data found"

    warnings = []
    monkeypatch.setattr(
        transcription.log,
        "warning",
        lambda msg, *a, **kw: warnings.append(msg % a if a else msg),
    )
    monkeypatch.setattr(transcription.subprocess, "run", lambda *a, **kw: FakeResult())

    assert transcription._ffprobe_duration(audio) == 0.0
    assert any("ffprobe returned 1" in w for w in warnings)


# ── #13 audio extension expansion ───────────────────────────────────────────


@pytest.mark.parametrize(
    "rel_path",
    [
        "library/foo.aac",
        "library/audiobook.m4b",
        "library/podcast.opus",
        "library/voice.aif",
        "library/voice.aiff",
    ],
)
def test_new_audio_formats_are_transcribable(rel_path):
    assert transcription.is_transcribable(rel_path)


# ── #14 + #20 single source of truth ────────────────────────────────────────


def test_transcribable_set_matches_media_exts_module():
    """transcription module surface and the canonical _media_exts agree."""
    from services import _media_exts

    assert transcription.TRANSCRIBABLE_EXTS == _media_exts.TRANSCRIBABLE_EXTS
    assert transcription.AUDIO_EXTS == _media_exts.AUDIO_EXTS


def test_catalog_no_text_extensions_includes_all_transcribable():
    """The catalog skip-text set must cover every transcribable extension."""
    from services.catalog import _NO_TEXT_EXTENSIONS

    assert transcription.TRANSCRIBABLE_EXTS <= _NO_TEXT_EXTENSIONS


# ── #15 force flag bypasses hash skip ────────────────────────────────────────


def test_transcribe_force_flag_bypasses_hash_skip(mp3_with_mocked_whisper):
    """force=True regenerates even when source bytes are unchanged."""
    rel_path, audio, generated = mp3_with_mocked_whisper
    transcription.transcribe(rel_path)  # writes the transcript

    call_count = {"n": 0}

    def counting_whisper(abs_path, progress):
        call_count["n"] += 1
        return ([{"start": 0, "end": 1, "text": "regen"}], "en", "tiny.en")

    with patch.object(transcription, "_whisper_local", counting_whisper):
        out_rel = transcription.transcribe(rel_path, force=True)

    assert out_rel == "generated/transcripts/library__talk.mp3.md"
    assert call_count["n"] == 1


# ── #16 hardened YAML quoting ────────────────────────────────────────────────


def test_yaml_quote_passes_simple_strings_unquoted():
    assert transcription._yaml_quote("local") == "local"
    assert transcription._yaml_quote("distil-small.en") == "distil-small.en"
    assert transcription._yaml_quote("library/foo.mp3") == "library/foo.mp3"


def test_yaml_quote_escapes_strings_with_colons():
    """ISO timestamps contain colons — must be quoted."""
    assert (
        transcription._yaml_quote("2026-04-28T15:32:11+00:00")
        == '"2026-04-28T15:32:11+00:00"'
    )


def test_yaml_quote_handles_booleans_and_numbers():
    assert transcription._yaml_quote(True) == "true"
    assert transcription._yaml_quote(False) == "false"
    assert transcription._yaml_quote(42) == "42"
    assert transcription._yaml_quote(3.14) == "3.14"


def test_yaml_quote_escapes_special_chars():
    assert transcription._yaml_quote("has\\backslash") == '"has\\\\backslash"'
    assert transcription._yaml_quote('has"quote') == '"has\\"quote"'
    assert transcription._yaml_quote("# leading hash") == '"# leading hash"'
    assert transcription._yaml_quote("") == '""'


def test_yaml_quote_escapes_yaml_reserved_literals():
    """Bare 'true'/'null'/'-' would be parsed as a non-string value."""
    assert transcription._yaml_quote("true") == '"true"'
    assert transcription._yaml_quote("null") == '"null"'
    assert transcription._yaml_quote("-") == '"-"'


def test_format_transcript_yaml_round_trips_with_safe_load(tmp_path):
    """Frontmatter writer output is parseable by a real YAML lib."""
    text = transcription._format_transcript(
        "library/talk.mp3",
        {
            "source_path": "library/talk.mp3",
            "transcribed_at": "2026-04-28T15:32:11+00:00",
            "frame_samples": 0,
            "language": "en",
            "model": "distil-small.en",
        },
        "[00:00] hello\n",
    )
    # Extract the frontmatter block and parse it
    fm_block = text.split("---")[1]
    parsed = {}
    for line in fm_block.strip().splitlines():
        k, _, v = line.partition(":")
        parsed[k.strip()] = v.strip()
    # Quoted values keep their quotes in our naïve splitter — strip them
    assert parsed["source_path"] == "library/talk.mp3"
    assert parsed["transcribed_at"].strip('"') == "2026-04-28T15:32:11+00:00"
    assert parsed["frame_samples"] == "0"
    assert parsed["language"] == "en"
    assert parsed["model"] == "distil-small.en"


# ── caption model ───────────────────────────────────────────────────────────


def test_caption_uses_the_single_vision_model_setting(monkeypatch):
    seen: dict = {}

    def fake(image_bytes, media_type, prompt, **kw):
        seen["media_type"] = media_type
        return "  a harbor at dusk \n"

    monkeypatch.setattr(transcription, "describe_image", fake)
    assert transcription._caption_image_bytes(b"x", "image/png") == "a harbor at dusk"
    assert seen["media_type"] == "image/png"


def test_vision_model_setting_defaults_and_reads_env(monkeypatch):
    monkeypatch.setattr(settings, "_load_overrides", dict)
    monkeypatch.delenv("VISION_MODEL", raising=False)
    assert settings.effective_vision_model() == "qwen2.5vl:7b"
    monkeypatch.setenv("VISION_MODEL", "gemma3:12b")
    assert settings.effective_vision_model() == "gemma3:12b"


# ── #18 first-run download notice ────────────────────────────────────────────


def test_get_local_model_emits_download_notice_when_cache_empty(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "generated_path", tmp_path)
    transcription._model_cache.clear()

    class FakeModel:
        pass

    class FakeFasterWhisper:
        @staticmethod
        def WhisperModel(*args, **kwargs):
            return FakeModel()

    import sys

    monkeypatch.setitem(sys.modules, "faster_whisper", FakeFasterWhisper)

    events: list[tuple[str, float]] = []
    transcription._get_local_model(
        "tiny.en", lambda stage, frac: events.append((stage, frac))
    )
    assert any("downloading" in stage for stage, _ in events)


def test_get_local_model_skips_download_notice_when_cache_present(
    monkeypatch, tmp_path
):
    cache_dir = tmp_path / "models" / "whisper"
    cache_dir.mkdir(parents=True)
    (cache_dir / "models--Systran--faster-whisper-tiny.en").mkdir()
    monkeypatch.setattr(settings, "generated_path", tmp_path)
    transcription._model_cache.clear()

    class FakeModel:
        pass

    class FakeFasterWhisper:
        @staticmethod
        def WhisperModel(*args, **kwargs):
            return FakeModel()

    import sys

    monkeypatch.setitem(sys.modules, "faster_whisper", FakeFasterWhisper)

    events: list[tuple[str, float]] = []
    transcription._get_local_model(
        "tiny.en", lambda stage, frac: events.append((stage, frac))
    )
    assert not any("downloading" in stage for stage, _ in events)
    assert any("loading tiny.en" in stage for stage, _ in events)


# ── #19 video flow integration ───────────────────────────────────────────────


def test_transcribe_video_interleaves_audio_and_frame_captions(monkeypatch, tmp_path):
    """End-to-end video path: audio segments and frame captions interleave by timestamp."""
    library = tmp_path / "library"
    library.mkdir()
    generated = tmp_path / "generated"
    generated.mkdir()
    video = library / "lecture.mp4"
    video.write_bytes(b"\x00" * 1024)

    monkeypatch.setattr(settings, "library_root", library)
    monkeypatch.setattr(settings, "generated_path", generated)
    monkeypatch.setattr(
        settings,
        "_load_overrides",
        lambda: {
            "local_whisper_model": "tiny.en",
            "video_frame_sampling": True,
            "transcription_max_frames_per_video": 2,
        },
    )
    monkeypatch.setattr(transcription, "_ffprobe_duration", lambda p: 90.0)
    monkeypatch.setattr(
        transcription,
        "_ffmpeg_extract_audio",
        lambda src, dest, duration=0.0: dest.write_bytes(b"wav"),
    )
    monkeypatch.setattr(
        transcription,
        "_whisper_local",
        lambda p, prog: (
            [
                {"start": 5.0, "end": 30.0, "text": "First spoken segment."},
                {"start": 60.0, "end": 80.0, "text": "Second spoken segment."},
            ],
            "en",
            "tiny.en",
        ),
    )
    fake_frames_dir = tmp_path / "frames"
    fake_frames_dir.mkdir()
    f1 = fake_frames_dir / "f1.jpg"
    f1.write_bytes(b"jpg1")
    f2 = fake_frames_dir / "f2.jpg"
    f2.write_bytes(b"jpg2")
    monkeypatch.setattr(
        transcription,
        "_ffmpeg_sample_frames",
        lambda src, tmp, dur, n: [(20.0, f1), (70.0, f2)],
    )
    monkeypatch.setattr(
        transcription,
        "_caption_image_bytes",
        lambda b, mt: f"caption for {len(b)} bytes",
    )

    transcription.transcribe("library/lecture.mp4")
    out_abs = generated / "transcripts" / "library__lecture.mp4.md"
    text = out_abs.read_text()
    # Body must interleave audio and frames in chronological order:
    # 5s audio < 20s frame < 60s audio < 70s frame
    body = text.split("# Transcript: lecture.mp4\n\n", 1)[1]
    lines = [ln for ln in body.splitlines() if ln.strip()]
    assert len(lines) >= 4
    assert "[00:05] First spoken" in lines[0]
    assert "[Frame at 00:20]" in lines[1]
    assert "[01:00] Second spoken" in lines[2]
    assert "[Frame at 01:10]" in lines[3]
    # Frontmatter records frame count
    assert "frame_samples: 2" in text


# ── SSE error path scrubs provider exceptions ────────────────────────────────


def test_route_uses_human_error_for_provider_exception(tmp_path, monkeypatch):
    """The /api/transcribe SSE error event runs through _human_error.

    Without scrubbing, request text inside an httpx error's `str(exc)`
    would surface to the SSE consumer. This test mirrors
    the equivalent guard in test_handwriting.py and ensures the audio/
    video/image transcribe path is just as safe.
    """
    from fastapi.testclient import TestClient
    from main import app
    import httpx

    library = tmp_path / "library"
    library.mkdir()
    generated = tmp_path / "generated"
    generated.mkdir()
    img = library / "scan.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
    monkeypatch.setattr(settings, "library_root", library)
    monkeypatch.setattr(settings, "generated_path", generated)

    def explode_with_status(*_a, **_k):
        request = httpx.Request("POST", "http://127.0.0.1:11434/api/chat")
        response = httpx.Response(500, request=request)
        raise httpx.HTTPStatusError(
            "SECRET_SHOULD_BE_SCRUBBED", request=request, response=response
        )

    monkeypatch.setattr(transcription, "_caption_image_bytes", explode_with_status)

    client = TestClient(app)
    with client.stream(
        "POST", "/api/transcribe", json={"path": "library/scan.png"}
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
    errors = [p for p in parsed if p.get("event") == "error"]
    assert errors, f"no error event in {parsed}"
    msg = errors[0]["message"]
    assert "SECRET_SHOULD_BE_SCRUBBED" not in msg
    assert "Ollama returned an error (500)" in msg
