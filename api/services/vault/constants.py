"""Vault constants — binary file types, size limits, and regex patterns.

Extracted from vault.py to eliminate circular dependencies and improve organization.
All constants are re-exported in __init__.py for backward compatibility.
"""

import re

from services._media_exts import (
    AUDIO_EXTS as _AUDIO_EXTS,
    IMAGE_EXTS as _IMAGE_EXTS,
    VIDEO_EXTS as _VIDEO_EXTS,
)

# ── Binary File Type Definitions ──────────────────────────────────────────────

_DOCUMENT_EXTENSIONS = {
    ".pdf",
    ".epub",
    ".scriv",
    ".docx",
    ".doc",
    ".xlsx",
    ".xls",
    ".mobi",
}

_ARCHIVE_EXTENSIONS = {".zip", ".tar", ".gz"}

# Derived, not hand-listed. `services/_media_exts.py` declares itself "single
# source of truth for multimedia file extension sets" — and this set was
# maintained separately beside it and drifted, missing .m4a, .flac, .m4b,
# .aac, .opus, .aif, .aiff, .mkv, .webm and .heic.
#
# That drift was not cosmetic. `read_file` returns `binary: True` only for
# members of this set; anything else falls through to the size check and then
# to `read_text`. So an audiobook or a Mac voice memo opened as an empty
# markdown editor with the Edit button live, and the first keystroke
# autosaved over it 700ms later. Exactly the formats US-105 exists to
# support.
#
# .svg stays OUT deliberately — it is XML text, so the editor opens it as
# editable source (rendered via the Edit/View toggle), and read_file still
# falls back to binary on UnicodeDecodeError for non-text payloads.
# `test_svg_repair.py` pins that.
BINARY_EXTENSIONS = (
    _DOCUMENT_EXTENSIONS
    | _ARCHIVE_EXTENSIONS
    | set(_AUDIO_EXTS)
    | set(_VIDEO_EXTS)
    | set(_IMAGE_EXTS)
    | {".avi", ".heic", ".heif"}  # not transcribable, still not text
)

IWORK_EXTENSIONS = {".pages", ".key", ".numbers"}

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
AUDIO_EXTENSIONS = {".mp3", ".wav", ".ogg", ".m4a", ".flac"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}

# ── Size Limits ───────────────────────────────────────────────────────────────

MAX_EDITOR_BYTES = (
    2 * 1024 * 1024
)  # 2 MB — editor display limit (prevents browser hang)
AI_CONTEXT_LIMIT = 50_000  # characters — truncation threshold for AI reading

# ── PDF Rendering ─────────────────────────────────────────────────────────────

# Filters pdfjs cannot render or renders blank for.
# JBIG2Decode / JPXDecode: explicitly unsupported by pdfjs.
# CCITTFaxDecode: old fax compression used in scanned docs; pdfjs support is
#   partial and often produces blank pages.
PDF_UNSUPPORTED_FILTERS = (b"/JBIG2Decode", b"/JPXDecode", b"/CCITTFaxDecode")

# ── Regex Patterns ────────────────────────────────────────────────────────────

WIKILINK_PATH = re.compile(r"\[\[([^\]]+)\]\]")
MD_LINK = re.compile(r"\[([^\]]+)\]\(([^\)]+)\)")
