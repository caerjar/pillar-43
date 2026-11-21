"""Runtime probes for the external binaries Pillar-43 shells out to.

Pillar-43 is not self-contained: it invokes `git` for version history, `rg` for
search, and `ffmpeg`/`ffprobe` for transcription.
In Docker these are installed by `api/Dockerfile` and always present, so the
code was written as though they always would be. The desktop build breaks that
assumption — a tester's Mac may have no Xcode Command Line Tools, in which case
`/usr/bin/git` is a stub that does nothing but offer to install them.

What that actually costs was measured, not guessed (2026-08-17, API booted with
`git` off `PATH`):

  - `POST /api/library/init` returned a **500** — the first-run wizard's own
    workspace step, dead on the first click, with `{"detail":"Internal server
    error"}` and a `FileNotFoundError` in the log.
  - `POST /api/file` returned **201** and the note landed on disk. The commit
    is batched onto a background thread, so the failure surfaced there, was
    logged, and was swallowed. Writes keep working and **version history
    silently never records anything, forever**.

The second is the worse failure, because nothing surfaces it. This module is
where that stops being invisible: probe once, cache, and let `/health` and
Settings report a missing binary as a named degradation instead of a 500 or a
log line nobody reads.

Probes are cached because `shutil.which` hits the filesystem and these are
called on hot paths (every vault write asks about git). Call `reset_cache()`
in tests, or after anything that could change `PATH`.
"""

from __future__ import annotations

import logging
import shutil
from typing import TypedDict

log = logging.getLogger(__name__)


class CapabilityUnavailableError(RuntimeError):
    """A feature was invoked that needs an external binary which is absent.

    Subclasses `RuntimeError` deliberately: several routes already catch
    `RuntimeError` and turn it into an HTTP error, so raising this keeps them
    working while letting a caller that cares match the narrower type and
    answer with the remedy instead of a generic 500.
    """


class Capability(TypedDict):
    """One external binary and what the app loses without it."""

    binary: str
    available: bool
    label: str
    degraded: str
    remedy: str


# The single source of truth for "what does Pillar-43 shell out to". Keep the
# `degraded` text specific about what stops working — a user reading Settings
# should be able to tell whether they care, without reading the code.
_BINARIES: dict[str, dict[str, str]] = {
    "git": {
        "binary": "git",
        "label": "Version history",
        "degraded": (
            "Notes still save normally, but no version history is recorded and "
            "earlier versions cannot be restored."
        ),
        "remedy": "Install the Xcode Command Line Tools: xcode-select --install",
    },
    "ripgrep": {
        "binary": "rg",
        "label": "Full-text search",
        "degraded": "Text search across the vault returns no results.",
        "remedy": "Install ripgrep: brew install ripgrep",
    },
    "ffmpeg": {
        "binary": "ffmpeg",
        "label": "Audio & video transcription",
        "degraded": "Audio cannot be extracted from media, so transcription is unavailable.",
        "remedy": "Install ffmpeg: brew install ffmpeg",
    },
    "ffprobe": {
        "binary": "ffprobe",
        "label": "Media duration",
        "degraded": "Media duration reads as zero; transcription progress is not estimated.",
        "remedy": "Install ffmpeg (ffprobe ships with it): brew install ffmpeg",
    },
}

_cache: dict[str, bool] = {}
_warned: set[str] = set()


def _available(key: str) -> bool:
    """Is this binary on PATH? Cached; probes at most once per process."""
    if key not in _cache:
        binary = _BINARIES[key]["binary"]
        found = shutil.which(binary) is not None
        _cache[key] = found
        if not found and key not in _warned:
            # WARNING, not debug: per the maintainer notes this is "not what you asked
            # for" territory — the app runs but quietly does less, which is
            # exactly the case that must not be invisible at production level.
            _warned.add(key)
            log.warning(
                "%s not found on PATH — %s",
                binary,
                _BINARIES[key]["degraded"],
            )
    return _cache[key]


def git_available() -> bool:
    return _available("git")


def ripgrep_available() -> bool:
    return _available("ripgrep")


def ffmpeg_available() -> bool:
    return _available("ffmpeg")


def ffprobe_available() -> bool:
    return _available("ffprobe")


def report() -> dict[str, Capability]:
    """Full capability report, for `/health` and the Settings panel."""
    return {
        key: Capability(
            binary=spec["binary"],
            available=_available(key),
            label=spec["label"],
            degraded=spec["degraded"],
            remedy=spec["remedy"],
        )
        for key, spec in _BINARIES.items()
    }


def require(key: str) -> None:
    """Raise `CapabilityUnavailableError` unless `key`'s binary is present.

    For features that have no useful degraded form — extracting audio from a
    video cannot half-happen. Prefer the `*_available()` predicates wherever
    the operation CAN continue with less, so the user keeps their result.

    PDF rendering used to be the example here. It stopped shelling out on
    2026-08-29 (`services/vault/pdf.py` renders through PDFium, a wheel), which
    is the better answer whenever a library exists: a capability you cannot
    fail to have needs no probe, no remedy text and no 503.
    """
    if not _available(key):
        spec = _BINARIES[key]
        raise CapabilityUnavailableError(
            f"{spec['label']} is unavailable — {spec['binary']} is not installed. "
            f"{spec['remedy']}"
        )


def missing() -> list[str]:
    """Keys of the binaries that are absent. Empty list == fully capable."""
    return [key for key in _BINARIES if not _available(key)]


def reset_cache() -> None:
    """Drop cached probe results. For tests, and after any PATH change."""
    _cache.clear()
    _warned.clear()
