"""Compute the canonical transcript path for any source file.

Transcripts live under generated/transcripts/ with the source's mount + path
encoded into the filename, mirroring vault.annotation_path's scheme:

    library/lectures/jung-1957.mp3 → generated/transcripts/library__lectures__jung-1957.mp3.md

This keeps the transcript discoverable from the source path alone (no DB
lookup needed) and makes it a regular markdown file the catalog/threads/
summarization pipeline picks up unmodified.
"""

from __future__ import annotations


def transcript_path(rel_path: str) -> str:
    encoded = rel_path.replace("/", "__")
    return f"generated/transcripts/{encoded}.md"
