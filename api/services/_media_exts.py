"""Single source of truth for multimedia file extension sets.

Lives outside transcription.py and catalog.py to break the import cycle
that would otherwise form (transcription imports hash_file from catalog;
catalog wants the transcribable set from transcription).

Frontend mirror: web/src/lib/multimediaExts.ts. Drift between front and
back is acceptable — multimedia formats are stable. If it ever matters,
plumb this through /api/settings.
"""

from __future__ import annotations


AUDIO_EXTS: frozenset[str] = frozenset(
    {
        ".mp3",
        ".wav",
        ".ogg",
        ".m4a",
        ".flac",
        ".aac",
        ".m4b",
        ".opus",
        ".aif",
        ".aiff",
    }
)

VIDEO_EXTS: frozenset[str] = frozenset({".mp4", ".mov", ".mkv", ".webm"})

IMAGE_EXTS: frozenset[str] = frozenset({".jpg", ".jpeg", ".png", ".webp", ".gif"})

TRANSCRIBABLE_EXTS: frozenset[str] = AUDIO_EXTS | VIDEO_EXTS | IMAGE_EXTS

# Extensions the catalog can never extract text from. Superset of transcribable
# (audio/video/image have no plain text) plus archives + .svg (vector files
# we don't currently caption — text is encoded in tags rather than pixels).
NO_TEXT_EXTENSIONS: frozenset[str] = TRANSCRIBABLE_EXTS | frozenset(
    {
        ".svg",
        ".zip",
        ".tar",
        ".gz",
    }
)
