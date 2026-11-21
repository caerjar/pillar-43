"""services.catalog — file-scan, chunking and embedding pipeline.

The package was decomposed from a 1,661-LOC `services/catalog.py` monolith
during the foundation sprint (Day 1). All public symbols previously available
on the module are re-exported here so existing import paths keep working.

Layout:
  constants.py       — magic numbers (batch sizes, thresholds, exclusion sets)
  state.py           — FileRecord dataclass, catalog run-state file
  code_projects.py   — _find_code_dirs + list_code_projects (used by Pass 1 + /code-projects)
  scan.py            — Pass 1: filesystem walk + per-file upsert
  extract.py         — text/PDF/EPUB/DOCX extraction, hashing, file upsert
  chunk.py           — Pass 1.5: split extracted text into passages
  embed.py           — Pass 2: Qdrant embedding
  orchestrator.py    — run_catalog: scan, chunk, embed
"""

from __future__ import annotations

# ── Constants & shared state (re-exported for backwards-compat) ──────────────
from services._media_exts import NO_TEXT_EXTENSIONS as _NO_TEXT_EXTENSIONS
from services.db import get_db

from .constants import (
    CATALOG_TEXT_LIMIT,
    CODE_PROJECT_MARKERS as _CODE_PROJECT_MARKERS,
    EXCLUDE_DIRS as _EXCLUDE_DIRS,
    EXCLUDE_FILES as _EXCLUDE_FILES,
    README_NAMES as _README_NAMES,
    SKIP_DIR_NAMES as _SKIP_DIR_NAMES,
)
from .code_projects import _find_code_dirs, list_code_projects
from .embed import _pass_embedding
from .extract import (
    _infer_authorship,
    _parse_frontmatter,
    extract_text_for_catalog,
    hash_file,
    upsert_file_record,
)
from .orchestrator import run_catalog
from .scan import _pass_file_scan
from .state import FileRecord

__all__ = [
    "CATALOG_TEXT_LIMIT",
    "_CODE_PROJECT_MARKERS",
    "_EXCLUDE_DIRS",
    "_EXCLUDE_FILES",
    "_NO_TEXT_EXTENSIONS",
    "_README_NAMES",
    "_SKIP_DIR_NAMES",
    "FileRecord",
    "_find_code_dirs",
    "_infer_authorship",
    "_parse_frontmatter",
    "_pass_embedding",
    # Compat re-exports (underscore-prefixed names used by tests + routes)
    "_pass_file_scan",
    "extract_text_for_catalog",
    "get_db",
    "hash_file",
    "list_code_projects",
    # Public API
    "run_catalog",
    "upsert_file_record",
]
