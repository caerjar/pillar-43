"""Vault file operations - decomposed into focused modules.

For backward compatibility, all public functions are re-exported here.
Existing imports like `from services.vault import read_file` continue to work.

Module structure:
- constants.py: Binary file types, size limits, regex patterns
- tree.py: Directory tree traversal
- pdf.py: PDF detection and rendering
- extraction.py: Text extraction (EPUB, DOCX, PDF)
- metadata.py: Frontmatter handling
- io.py: File read/write
"""

import logging

from config import settings

# Import constants from dedicated module
from .constants import (
    BINARY_EXTENSIONS,
    IMAGE_EXTENSIONS,
    AUDIO_EXTENSIONS,
    VIDEO_EXTENSIONS,
    AI_CONTEXT_LIMIT,
    PDF_UNSUPPORTED_FILTERS,
    WIKILINK_PATH,
    MD_LINK,
)

# Import tree operations
from .tree import (
    _node,
    _tree,
    get_tree,
    get_dir_children,
)

# Import PDF operations
from .pdf import (
    pdf_needs_native,
    get_pdf_page_count,
    render_pdf_page,
)

# Import text extraction and AI reading
from .extraction import (
    _extract_epub_text,
    _extract_docx_text,
    _extract_pdf_text,
    extract_viewer_text,
    read_text_for_ai,
)

# Import metadata helpers
from .metadata import (
    _strip_authorship_frontmatter,
    annotation_path,
)

# Import I/O operations
from .io import (
    _check_writable,
    read_file,
    write_file,
)

# Backward compatibility aliases for private constants
_PDF_UNSUPPORTED_FILTERS = PDF_UNSUPPORTED_FILTERS
_WIKILINK_PATH = WIKILINK_PATH
_MD_LINK = MD_LINK

log = logging.getLogger(__name__)


# Export everything for backward compatibility
__all__ = [
    "AI_CONTEXT_LIMIT",
    "AUDIO_EXTENSIONS",
    # Constants
    "BINARY_EXTENSIONS",
    "IMAGE_EXTENSIONS",
    "MD_LINK",
    "PDF_UNSUPPORTED_FILTERS",
    "VIDEO_EXTENSIONS",
    "WIKILINK_PATH",
    "_MD_LINK",
    "_PDF_UNSUPPORTED_FILTERS",
    "_WIKILINK_PATH",
    "_check_writable",
    "_extract_docx_text",
    # Extraction
    "_extract_epub_text",
    "_extract_pdf_text",
    # Metadata
    "annotation_path",
    "extract_viewer_text",
    "get_dir_children",
    "get_pdf_page_count",
    # Tree
    "get_tree",
    # PDF
    "pdf_needs_native",
    # I/O
    "read_file",
    "read_text_for_ai",
    "render_pdf_page",
    # Config
    "settings",
    "write_file",
]
