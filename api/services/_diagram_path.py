"""Compute the canonical SVG-diagram artifact path for a source file.

Mirrors `_transcript_path.transcript_path`: encode the source rel_path's
slashes as `__` and write under generated/diagrams/, suffixing with the
1-indexed diagram number:

    library/scans/note.png + 2 → generated/diagrams/library__scans__note.png.2.svg

A single source may produce zero, one, or many diagram SVGs depending on
what the AI extracts. Global numbering across multi-page PDFs is handled
by the orchestration service (not here).

NOTE: this helper performs *only* string manipulation. It does not
validate `rel_path` for traversal. Callers must run the result through
`vault.write_file` (which routes through `settings.resolve()` for the
sandbox check) — never construct an absolute path from this string and
write to it directly.
"""

from __future__ import annotations


def diagram_path(rel_path: str, index: int) -> str:
    encoded = rel_path.replace("/", "__")
    return f"generated/diagrams/{encoded}.{index}.svg"
