"""Detect code-project roots inside vault mounts.

Used by `/api/catalog/code-projects` to surface git repos / package roots
that live inside the vault. The detection logic itself (`_find_code_dirs`)
also informs Pass 1 — files inside a detected project are skipped except
for the README.
"""

from __future__ import annotations

import logging
from pathlib import Path

from config import settings

from .constants import CODE_PROJECT_MARKERS, README_NAMES, SKIP_DIR_NAMES
import contextlib

log = logging.getLogger(__name__)


def _find_code_dirs(
    root: Path,
    _debug: list | None = None,
) -> dict[Path, str]:
    """Return {abs_dir: language} for all code project roots under root.

    Only the outermost project is recorded — nested projects inside an
    already-detected code dir are skipped. Haskell projects are also
    detected by the presence of any *.cabal file.

    Pass _debug=[] to collect skip-reason records for the debug endpoint.
    """
    result: dict[Path, str] = {}
    for dirpath in sorted(p for p in root.rglob("*") if p.is_dir()):
        if dirpath.name in SKIP_DIR_NAMES:
            if _debug is not None:
                _debug.append(
                    {"path": str(dirpath), "reason": f"skip_dir ({dirpath.name})"}
                )
            continue
        if dirpath.name.startswith("."):
            if _debug is not None:
                _debug.append({"path": str(dirpath), "reason": "hidden dir"})
            continue
        if any(dirpath == cd or cd in dirpath.parents for cd in result):
            if _debug is not None:
                parent = next(
                    cd for cd in result if dirpath == cd or cd in dirpath.parents
                )
                _debug.append(
                    {"path": str(dirpath), "reason": f"nested inside {parent}"}
                )
            continue
        found_lang = None
        for marker, lang in CODE_PROJECT_MARKERS.items():
            if (dirpath / marker).exists():
                found_lang = lang
                result[dirpath] = lang
                log.debug("code-project: found %s (%s via %s)", dirpath, lang, marker)
                break
        if not found_lang:
            try:
                if any(f.suffix == ".cabal" for f in dirpath.iterdir() if f.is_file()):
                    result[dirpath] = "Haskell"
                    log.debug("code-project: found %s (Haskell via .cabal)", dirpath)
            except PermissionError:
                # Skipping an unreadable directory is right, but silently
                # skipping it leaves a user asking why a folder is missing.
                log.debug("skipping unreadable directory", exc_info=True)
        if _debug is not None and dirpath not in result:
            _debug.append({"path": str(dirpath), "reason": "no marker found"})
    return result


def list_code_projects(mounts: dict[str, Path] | None = None) -> list[dict]:
    """Scan vault mounts and return one record per detected code project root.

    Returns a list of dicts with:
      path       — mount-prefixed relative path to the project dir
      language   — detected language string
      file_count — total files inside (any type)
      size_bytes — total byte size of all files
      has_readme — whether a README file exists at the project root
      mount      — mount name (notes/library/generated)
      writable   — whether the mount allows deletion (only notes/ is writable)
    """
    if mounts is None:
        mounts = settings.all_mounts  # type: ignore[assignment]

    results: list[dict] = []
    for mount_name, root in mounts.items():
        if not root or not root.exists():
            continue
        code_dirs = _find_code_dirs(root)
        for dirpath, language in code_dirs.items():
            file_count = 0
            size_bytes = 0
            has_readme = False
            try:
                for f in dirpath.rglob("*"):
                    if f.is_file():
                        file_count += 1
                        with contextlib.suppress(OSError):
                            size_bytes += f.stat().st_size
                        if f.parent == dirpath and f.name.lower() in README_NAMES:
                            has_readme = True
            except PermissionError:
                # Skipping an unreadable directory is right, but silently
                # skipping it leaves a user asking why a folder is missing.
                log.debug("skipping unreadable directory", exc_info=True)
            rel_dir = mount_name + "/" + str(dirpath.relative_to(root))
            results.append(
                {
                    "path": rel_dir,
                    "language": language,
                    "file_count": file_count,
                    "size_bytes": size_bytes,
                    "has_readme": has_readme,
                    "mount": mount_name,
                    "writable": mount_name in ("notes",),
                }
            )
    results.sort(key=lambda r: (r["mount"], r["path"]))
    return results
