"""Multimedia → markdown transcription service.

Audio (mp3, wav, ogg) and video (mp4, mov) get transcribed via faster-whisper
(local, the only provider). Images (jpg, jpeg, png) get a single
caption from the local vision model (Ollama, `VISION_MODEL`). The result is a markdown file with frontmatter
written to generated/transcripts/<encoded>.md.

The transcript file participates in the existing catalog/threads/summarization
pipeline as a regular .md file — no parallel indexer.

Hash-based dedup: a re-run on an unchanged source short-circuits.
"""

from __future__ import annotations

import logging
import json
import re
import subprocess
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from config import settings
from services._media_exts import (
    AUDIO_EXTS,
    IMAGE_EXTS,
    TRANSCRIBABLE_EXTS,
    VIDEO_EXTS,
)
from services._transcript_path import transcript_path
from services.catalog import hash_file
from services import vault
from services.vision import describe_image

log = logging.getLogger(__name__)

# Whisper model construction is expensive (~1-3s + ~150-500MB RAM allocation).
# A module-level cache keyed by model name keeps the model loaded for the
# process's lifetime so back-to-back transcriptions don't re-load.
_model_cache: dict = {}
_model_lock = threading.Lock()

# Transcription is CPU-bound (or rate-limited on the API path). Running multiple
# at once doesn't help and risks OOM with concurrent model loads. One semaphore
# guards both the per-file route and the auto-sweep so they coexist safely.
_transcribe_semaphore = threading.Semaphore(1)

# In-process cache for ffprobe-derived durations, keyed by (abs_path_str, mtime).
# Cheap protection against repeating ffprobe calls in the same auto-sweep run.
# Persistence across restarts is intentionally out of scope for now.
_duration_cache: dict[tuple[str, float], float] = {}
_duration_cache_lock = threading.Lock()

# Matches `source_hash: <hex>` *only* inside a YAML frontmatter block at
# the top of the file (between two `---` fences). Avoids the false-positive
# substring search that would match the same hex anywhere in the body.
_FRONTMATTER_SOURCE_HASH_RE = re.compile(
    r"\A---\s*\n(.*?)\n---\s*(?:\n|$)",
    re.DOTALL,
)
_SOURCE_HASH_LINE_RE = re.compile(r"^source_hash:\s*(\S+)\s*$", re.MULTILINE)


# Speed factor: 1.0 = realtime; 4.0 = 4x faster than realtime (1hr audio in 15min)
# Used by /api/transcribe/estimate to warn before long auto-sweeps.
_SPEED_FACTORS = {
    ("local", "tiny.en"): 8.0,
    ("local", "tiny"): 7.0,
    ("local", "small.en"): 4.0,
    ("local", "small"): 3.5,
    ("local", "distil-small.en"): 6.0,
    ("local", "medium.en"): 1.5,
    ("local", "medium"): 1.3,
    ("local", "large-v3"): 0.6,
}


ProgressCallback = Callable[[str, float], None]
"""(stage_message, fraction_complete) — fraction is 0.0-1.0."""


# ── Public surface ────────────────────────────────────────────────────────────


def is_transcribable(rel_path: str) -> bool:
    return Path(rel_path).suffix.lower() in TRANSCRIBABLE_EXTS


def estimate_seconds(rel_path: str) -> tuple[float, float]:
    """Return (media_duration_seconds, estimated_processing_seconds).

    Returns (0, 0) if the file isn't transcribable or ffprobe fails.
    """
    if not is_transcribable(rel_path):
        return 0.0, 0.0
    ext = Path(rel_path).suffix.lower()
    if ext in IMAGE_EXTS:
        # Images: a single vision call, ~3 seconds typical.
        return 0.0, 3.0
    abs_path = settings.resolve(rel_path)
    duration = _ffprobe_duration(abs_path)
    if duration <= 0:
        return 0.0, 0.0
    speed = _speed_factor()
    return duration, max(1.0, duration / speed)


def transcribe(
    rel_path: str,
    progress: ProgressCallback | None = None,
    *,
    force: bool = False,
) -> str:
    """Transcribe a multimedia file. Returns the transcript's rel_path.

    Hash-based skip: if a transcript with the matching source_hash already
    exists, returns its path immediately. Pass `force=True` to bypass the
    skip and regenerate even when the source bytes are unchanged.

    The actual work is serialized via a module-level semaphore so concurrent
    callers don't OOM by loading the model multiple times.
    """
    if not is_transcribable(rel_path):
        raise ValueError(f"Not a transcribable file: {rel_path}")

    abs_path = settings.resolve(rel_path)
    if not abs_path.exists():
        raise FileNotFoundError(rel_path)

    src_hash = hash_file(abs_path)
    out_rel = transcript_path(rel_path)
    out_abs = settings.generated_path / Path(out_rel).relative_to("generated")
    if not force and _existing_matches(out_abs, src_hash):
        if progress:
            progress("source unchanged — using cached transcript", 1.0)
        return out_rel

    # Cheap pre-check is done; serialize the heavy work. Concurrent callers
    # see "queued" progress so they know we received the request.
    _emit(progress, "queued", 0.0)
    with _transcribe_semaphore:
        ext = abs_path.suffix.lower()
        _emit(progress, "starting", 0.0)

        if ext in IMAGE_EXTS:
            body, frontmatter = _caption_image(abs_path, rel_path, src_hash, progress)
        elif ext in AUDIO_EXTS:
            body, frontmatter = _transcribe_audio(
                abs_path, rel_path, src_hash, progress
            )
        elif ext in VIDEO_EXTS:
            body, frontmatter = _transcribe_video(
                abs_path, rel_path, src_hash, progress
            )
        else:
            raise ValueError(f"Unsupported extension: {ext}")

        text = _format_transcript(rel_path, frontmatter, body)
        vault.write_file(out_rel, text)
        _emit(progress, "done", 1.0)
        return out_rel


# ── Internals ─────────────────────────────────────────────────────────────────


def _emit(progress: ProgressCallback | None, stage: str, frac: float) -> None:
    if progress is not None:
        try:
            progress(stage, frac)
        except Exception:
            log.debug(
                "transcription progress callback raised; continuing", exc_info=True
            )


def _speed_factor() -> float:
    model = settings.effective_local_whisper_model()
    return _SPEED_FACTORS.get(("local", model), 3.0)


def _ffprobe_duration(abs_path: Path) -> float:
    """Return media duration in seconds via ffprobe. 0 on failure.

    Cached in-process by (path, mtime). Subsequent calls in the same process
    return immediately; the cache invalidates automatically when a file's
    modification time changes.

    Distinguishes failure modes via WARNING-level logs so operators can tell
    "ffprobe missing" or "permission denied" apart from a legitimate 0-duration
    file. Callers still get 0.0 on any failure for backwards compatibility.
    """
    try:
        mtime = abs_path.stat().st_mtime
    except OSError as e:
        log.warning("ffprobe stat failed for %s: %s", abs_path, e)
        return 0.0
    key = (str(abs_path), mtime)
    cached = _duration_cache.get(key)
    if cached is not None:
        return cached
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "json",
                str(abs_path),
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except FileNotFoundError:
        log.warning("ffprobe binary not found on PATH (transcription will be limited)")
        return 0.0
    except subprocess.TimeoutExpired:
        log.warning("ffprobe timed out probing %s", abs_path)
        return 0.0
    except Exception as e:
        log.warning("ffprobe subprocess failed for %s: %s", abs_path, e)
        return 0.0
    if result.returncode != 0:
        log.warning(
            "ffprobe returned %d for %s: %s",
            result.returncode,
            abs_path,
            (result.stderr or "").strip()[:200],
        )
        return 0.0
    try:
        data = json.loads(result.stdout or "{}")
        duration = float(data.get("format", {}).get("duration", 0))
    except (ValueError, json.JSONDecodeError) as e:
        log.warning("ffprobe output unparseable for %s: %s", abs_path, e)
        return 0.0
    with _duration_cache_lock:
        _duration_cache[key] = duration
    return duration


def _existing_matches(out_abs: Path, src_hash: str) -> bool:
    """True iff a transcript exists with this source_hash in its frontmatter.

    Parses only the `---`-fenced frontmatter block at the file head — never
    matches a hash that happens to appear in the transcript body.
    """
    if not out_abs.exists():
        return False
    try:
        text = out_abs.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return False
    fm_match = _FRONTMATTER_SOURCE_HASH_RE.match(text)
    if not fm_match:
        return False
    hash_match = _SOURCE_HASH_LINE_RE.search(fm_match.group(1))
    if not hash_match:
        return False
    return hash_match.group(1) == src_hash


# ── Audio ─────────────────────────────────────────────────────────────────────


def _transcribe_audio(
    abs_path: Path, rel_path: str, src_hash: str, progress: ProgressCallback | None
) -> tuple[str, dict]:
    duration = _ffprobe_duration(abs_path)
    _emit(progress, "transcribing audio (local)", 0.05)

    segments, language, model_name = _whisper_local(abs_path, progress)

    body = _segments_to_markdown(segments)
    frontmatter = {
        "source_path": rel_path,
        "source_hash": src_hash,
        "source_duration_seconds": int(duration),
        "provider": "local",
        "model": model_name,
        "language": language,
        "frame_samples": 0,
        "transcribed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    return body, frontmatter


def _get_local_model(model_name: str, progress: ProgressCallback | None):
    """Return a cached WhisperModel. Loads on first call, reuses afterwards.

    Loading the model takes 1-3s and allocates ~150-500MB depending on size.
    The cache is module-global and protected by a lock so concurrent first
    calls don't race-load the same model twice.
    """
    cached = _model_cache.get(model_name)
    if cached is not None:
        return cached
    with _model_lock:
        cached = _model_cache.get(model_name)
        if cached is not None:
            return cached
        from faster_whisper import WhisperModel

        cache_dir = settings.generated_path / "models" / "whisper"
        cache_dir.mkdir(parents=True, exist_ok=True)
        # First-run download is the slowest single step in the local-Whisper
        # path (~150MB-1GB depending on model). Detect "no model directory yet"
        # and surface a clear warning so the UI doesn't show a silent stall.
        # Inexact (faster-whisper's HF cache layout drifts across versions)
        # but the worst case here is just a slightly noisy message.
        already_downloaded = any(cache_dir.glob("models--*"))
        if already_downloaded:
            _emit(progress, f"loading {model_name}", 0.10)
        else:
            _emit(progress, f"downloading {model_name} (~150 MB, one-time)…", 0.05)
        model = WhisperModel(
            model_name,
            device="cpu",
            compute_type="int8",
            download_root=str(cache_dir),
        )
        _model_cache[model_name] = model
        return model


def _whisper_local(
    abs_path: Path, progress: ProgressCallback | None
) -> tuple[list, str, str]:
    """Run faster-whisper. Returns (segments, language, model_name)."""
    model_name = settings.effective_local_whisper_model()
    model = _get_local_model(model_name, progress)

    _emit(progress, "decoding audio", 0.20)
    seg_iter, info = model.transcribe(
        str(abs_path),
        beam_size=1,
        vad_filter=True,
        word_timestamps=False,
    )

    duration = max(info.duration, 0.001)
    segments = []
    for seg in seg_iter:
        segments.append({"start": seg.start, "end": seg.end, "text": seg.text.strip()})
        _emit(
            progress,
            f"transcribed {int(seg.end)}s / {int(duration)}s",
            min(0.95, 0.20 + 0.75 * (seg.end / duration)),
        )

    return segments, getattr(info, "language", "") or "", model_name


def _segments_to_markdown(segments: list) -> str:
    if not segments:
        return "_(no speech detected)_\n"
    lines = []
    for seg in segments:
        ts = _format_timestamp(seg["start"])
        lines.append(f"[{ts}] {seg['text']}")
    return "\n".join(lines) + "\n"


def _format_timestamp(seconds: float) -> str:
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h:02d}:{m:02d}:{sec:02d}"
    return f"{m:02d}:{sec:02d}"


# ── Video ─────────────────────────────────────────────────────────────────────


def _transcribe_video(
    abs_path: Path, rel_path: str, src_hash: str, progress: ProgressCallback | None
) -> tuple[str, dict]:
    duration = _ffprobe_duration(abs_path)
    _emit(progress, "extracting audio from video", 0.02)

    with tempfile.TemporaryDirectory() as tmp:
        wav_path = Path(tmp) / "audio.wav"
        _ffmpeg_extract_audio(abs_path, wav_path, duration=duration)

        segments, language, model_name = _whisper_local(wav_path, progress)

        frames: list[tuple[float, str]] = []
        if settings.effective_video_frame_sampling() and duration > 0:
            max_frames = settings.effective_transcription_max_frames_per_video()
            frame_paths = _ffmpeg_sample_frames(
                abs_path, Path(tmp), duration, max_frames
            )
            for i, (t, frame_path) in enumerate(frame_paths):
                _emit(
                    progress,
                    f"captioning frame {i + 1}/{len(frame_paths)}",
                    0.85 + 0.10 * (i / max(1, len(frame_paths))),
                )
                try:
                    caption = _caption_image_bytes(
                        frame_path.read_bytes(), "image/jpeg"
                    )
                    frames.append((t, caption))
                except Exception as e:
                    log.warning("frame caption failed at %.1fs: %s", t, e)

    body = _interleave_audio_and_frames(segments, frames)
    frontmatter = {
        "source_path": rel_path,
        "source_hash": src_hash,
        "source_duration_seconds": int(duration),
        "provider": "local",
        "model": model_name,
        "language": language,
        "frame_samples": len(frames),
        "transcribed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    return body, frontmatter


def _ffmpeg_extract_audio(src: Path, dest: Path, duration: float = 0.0) -> None:
    """Extract audio to 16kHz mono pcm_s16le wav.

    Timeout scales with media duration so multi-hour lectures don't die at
    extraction; floor 5 min for short files, headroom = 2x source duration.
    """
    # `check=True` below does not cover a missing binary — subprocess raises
    # FileNotFoundError before the process exists. Ask first, so the caller
    # gets a named error naming the remedy.
    ensure_ffmpeg_available()
    timeout = max(300, int(duration * 2)) if duration > 0 else 1800
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(src),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-acodec",
            "pcm_s16le",
            str(dest),
        ],
        capture_output=True,
        check=True,
        timeout=timeout,
    )


def _ffmpeg_sample_frames(
    src: Path, tmp_dir: Path, duration: float, max_frames: int
) -> list[tuple[float, Path]]:
    """Sample evenly-spaced frames. Returns [(timestamp_seconds, jpeg_path)].

    Uses `-ss` AFTER `-i` (accurate seek) so frame timestamps match the
    transcript. Slightly slower than fast-seek but the cost is negligible
    relative to the per-frame vision call that follows.
    """
    n = max(1, min(max_frames, int(duration / 30) or 1))  # roughly one per 30s, capped
    interval = duration / (n + 1)
    out: list[tuple[float, Path]] = []
    for i in range(1, n + 1):
        t = interval * i
        frame_path = tmp_dir / f"frame_{i:03d}.jpg"
        try:
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-i",
                    str(src),
                    "-ss",
                    f"{t:.2f}",
                    "-frames:v",
                    "1",
                    "-q:v",
                    "5",
                    str(frame_path),
                ],
                capture_output=True,
                check=True,
                timeout=60,
            )
            if frame_path.exists() and frame_path.stat().st_size > 0:
                out.append((t, frame_path))
        except Exception:
            continue
    return out


def _interleave_audio_and_frames(
    segments: list, frames: list[tuple[float, str]]
) -> str:
    """Merge timestamped audio segments and frame captions into a single markdown body."""
    items: list[tuple[float, str]] = []
    for seg in segments:
        ts = _format_timestamp(seg["start"])
        items.append((seg["start"], f"[{ts}] {seg['text']}"))
    for t, caption in frames:
        ts = _format_timestamp(t)
        items.append((t, f"[Frame at {ts}] {caption}"))
    items.sort(key=lambda x: x[0])
    return "\n".join(line for _, line in items) + "\n" if items else "_(no content)_\n"


# ── Image ─────────────────────────────────────────────────────────────────────


def _caption_image(
    abs_path: Path, rel_path: str, src_hash: str, progress: ProgressCallback | None
) -> tuple[str, dict]:
    _emit(progress, "captioning image", 0.30)
    media_type = _image_media_type(abs_path)
    caption = _caption_image_bytes(abs_path.read_bytes(), media_type)
    body = caption.strip() + "\n"
    frontmatter = {
        "source_path": rel_path,
        "source_hash": src_hash,
        "source_duration_seconds": 0,
        "provider": "ollama",
        "model": settings.effective_vision_model(),
        "language": "",
        "frame_samples": 0,
        "transcribed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    return body, frontmatter


def _image_media_type(abs_path: Path) -> str:
    ext = abs_path.suffix.lower()
    return {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }.get(ext, "image/jpeg")


def _caption_image_bytes(image_bytes: bytes, media_type: str) -> str:
    """Single local vision call. Returns the caption text."""
    return describe_image(
        image_bytes,
        media_type,
        "Describe what's visible in this image in 1-3 sentences. "
        "Focus on subject, setting, notable details. No preamble.",
        max_tokens=300,
    ).strip()


# ── Frontmatter writer ────────────────────────────────────────────────────────

# Triggers a quoted YAML scalar:
#   - special chars: : # \n " \
#   - leading or trailing whitespace
#   - YAML reserved literals (true, false, null, ~, -, *)
# This catches every value type the transcription frontmatter actually emits;
# anything more exotic should move to PyYAML.
_YAML_NEEDS_QUOTE_RE = re.compile(
    r'[:#\n"\\]|^\s|\s$|^(true|false|null|yes|no|~|-|\*)$',
    re.IGNORECASE,
)


def _yaml_quote(v) -> str:
    """Render a Python scalar as a safe YAML scalar.

    Strings: double-quoted only when ambiguous (saves on noise for plain
    values like provider names); booleans become `true`/`false`; numbers
    pass through. Backslashes and quotes are escaped inside quoted strings.
    """
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    s = "" if v is None else str(v)
    if not s:
        return '""'
    if _YAML_NEEDS_QUOTE_RE.search(s):
        return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return s


def _format_transcript(rel_path: str, frontmatter: dict, body: str) -> str:
    fm_lines = ["---"]
    for k, v in frontmatter.items():
        fm_lines.append(f"{k}: {_yaml_quote(v)}")
    fm_lines.append("---")
    title = Path(rel_path).name
    return "\n".join(fm_lines) + f"\n\n# Transcript: {title}\n\n{body}"


# ── ffmpeg / ffprobe availability ─────────────────────────────────────────────


def ensure_ffmpeg_available() -> None:
    """Raise if ffmpeg/ffprobe binaries aren't on PATH. Useful as a startup check.

    Delegates to `services.capabilities` so this shares one cached probe and
    one wording with `/health` and the Settings panel, rather than being a
    second, separately-maintained answer to the same question.
    """
    from services import capabilities

    capabilities.require("ffmpeg")
    capabilities.require("ffprobe")
