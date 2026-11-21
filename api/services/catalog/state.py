"""Module-level state for the catalog package.

`FileRecord` mirrors a row in the `files` table at the moment of upsert.

Catalog state management functions persist run metadata to `generated/._catalog_state.json`.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from config import settings

log = logging.getLogger(__name__)


@dataclass
class FileRecord:
    rel_path: str
    mount: str
    abs_path: str
    sha256: str
    size_bytes: int
    mtime: float
    ext: str
    extracted_text: str | None
    authorship: str | None = None


# ── Catalog Run State (Persisted Metadata) ───────────────────────────────────


def catalog_state_path() -> Path:
    """Return path to catalog state JSON file."""
    return settings.generated_path / "._catalog_state.json"


def read_catalog_state() -> dict:
    """Read catalog state from disk, returning empty dict if missing or malformed."""
    p = catalog_state_path()
    try:
        return json.loads(p.read_text()) if p.exists() else {}
    except Exception:
        return {}


def write_catalog_state(state: dict) -> None:
    """Write catalog state to disk."""
    p = catalog_state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state))
