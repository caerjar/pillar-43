"""Metadata and sidecar file helpers.

Annotation paths and frontmatter stripping for vault files.
"""

import re


def _strip_authorship_frontmatter(content: str) -> str:
    """Remove authorship frontmatter from markdown content."""
    # Match frontmatter block with authorship field
    pattern = r"^---\s*\nauthorship:.*?\n---\s*\n\n?"
    return re.sub(pattern, "", content, count=1, flags=re.MULTILINE)


def annotation_path(rel_path: str) -> str:
    """Return the notes/_annotations/ sidecar path for any vault file.

    library/47/2024/paper.pdf → notes/_annotations/library__47__2024__paper.pdf.md
    """
    encoded = rel_path.replace("/", "__")
    return f"notes/_annotations/{encoded}.md"
