"""Vault health and initialization endpoints."""

import asyncio
import os
import sqlite3
from pathlib import Path

from fastapi import APIRouter

from config import settings
from services import capabilities

router = APIRouter(prefix="/api/library")

# A git-independent record that setup ran (read by `git_ready`).
INIT_MARKER = ".initialized"


def _count_files(root: Path) -> int:
    """Count non-hidden files recursively. Only used for small mounts (active, generated)."""
    if not root.exists():
        return 0
    try:
        return sum(
            1
            for p in root.rglob("*")
            if p.is_file() and not any(part.startswith(".") for part in p.parts[-3:])
        )
    except OSError:
        return 0


def _indexed_count(mount_name: str) -> int:
    """Return number of files for a given mount already in the catalog DB."""
    # settings.db_path is the canonical accessor (config.py:db_path). The DB
    # was moved from generated_path to a Docker named volume; reading from
    # generated_path here would always return 0 in production, making the
    # `has_catalog_data` branch in _mount_status dead code.
    db_path = settings.db_path
    if not db_path.exists():
        return 0
    try:
        # timeout=10.0 mirrors services.db.get_db so this read waits for a
        # concurrent writer (catalog scan) instead of failing instantly.
        conn = sqlite3.connect(db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                "SELECT COUNT(*) AS file_count FROM files WHERE mount=?",
                (mount_name,),
            ).fetchone()
            return row["file_count"] if row else 0
        finally:
            conn.close()
    except Exception:
        return 0


def _mount_status() -> dict:
    """Return health dict for all three mounts."""
    active = settings.notes_path
    generated = settings.generated_path
    vault = settings.library_root

    def _writable(p: Path) -> bool:
        if not p.exists():
            return False
        return os.access(p, os.W_OK)

    extra_libraries = {
        name: {
            "exists": path.exists(),
            "file_count": _indexed_count(name),
        }
        for name, path in settings.extra_library_mounts.items()
    }

    # `git_ready` is the frontend's "show wizard?" gate. We treat ANY of these
    # signals as "this is not a fresh setup, don't show the wizard":
    #   - notes/.git exists (the original signal — vault-init succeeded)
    #   - the catalog DB has rows (the user has run Index at least once,
    #     so they're past first-run regardless of git state)
    # Pre-fix, deleting notes/.git for any reason (manual cleanup, git error
    # mid-operation) would re-show the wizard even with a populated catalog.
    #   - generated/.initialized exists (written by POST /library/init)
    # That third signal exists because the first two are both unreachable on a
    # machine with no git: `.git` is never created, and a fresh vault has no
    # catalog rows, so `git_ready` would be false forever and the wizard would
    # reappear after every completed setup. That is precisely the failure in
    # the maintainer notes pitfalls list, arrived at from a different direction.
    git_exists = (active / ".git").exists()
    initialized_marker = (generated / INIT_MARKER).exists()
    library_indexed_count = _indexed_count("library")
    notes_indexed_count = _indexed_count("notes")
    has_catalog_data = (library_indexed_count + notes_indexed_count) > 0

    # `setup_complete` is the wizard gate; `git_ready` keeps its own meaning
    # ("the workspace is initialized"), which the Workspace step still reads to
    # decide whether to offer Initialize. Two fields, two questions — after a
    # soft reset the folders and git are still there (ready) while setup must
    # run again (not complete). Overloading one would make that state
    # inexpressible, which is what forced this flag in the first place.
    recorded = settings.effective_setup_complete()
    git_ready = git_exists or has_catalog_data or initialized_marker

    return {
        # None = no recorded decision (every install older than this key), so
        # fall back to the heuristic rather than showing the wizard to someone
        # with a populated vault.
        "setup_complete": git_ready if recorded is None else recorded,
        "notes": {
            "exists": active.exists(),
            "writable": _writable(active),
            "git_ready": git_ready,
            "git_actual": git_exists,  # underlying state for diagnostics
            "file_count": _count_files(active),
        },
        "generated": {
            "exists": generated.exists(),
            "writable": _writable(generated),
            "file_count": _count_files(generated),
        },
        "library": {
            "exists": vault.exists(),
            # DB-indexed count — instant regardless of library size.
            # 0 means library exists but hasn't been cataloged yet.
            "file_count": library_indexed_count,
        },
        "extra_libraries": extra_libraries,
        # Named degradations (missing external binaries), so the wizard can say
        # "version history unavailable" instead of the user discovering it.
        "capabilities": capabilities.report(),
    }


@router.get("/status")
async def library_status():
    """Return health of all mounts."""
    return await asyncio.to_thread(_mount_status)
