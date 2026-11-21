"""File tree operations for vault navigation.

Generates hierarchical file trees for all mounts with configurable depth limits.
"""

import logging
from pathlib import Path
from typing import Any

from config import settings

log = logging.getLogger(__name__)


# Package extensions that are directories on disk but should be treated as files
PACKAGE_EXTENSIONS = {".epub", ".pages", ".key", ".numbers"}


def _normalize_filename(name: str) -> str:
    """Normalize Unicode spaces in filenames (macOS screenshot fix).

    macOS creates screenshots with narrow no-break space ( ) before AM/PM.
    Replace with regular space so paths match between tree and file access.
    """
    return name.replace(" ", " ")


def _is_package_file(path: Path) -> bool:
    """Check if path is a package-format file (.epub, .pages, etc).

    These are directories on disk but should be treated as files in the tree.
    """
    return path.suffix.lower() in PACKAGE_EXTENSIONS


def _node(path: Path, root: Path, mount: str) -> dict[str, Any]:
    # Normalize filename for macOS screenshot compatibility
    normalized_name = _normalize_filename(path.name)

    # Calculate relative path with normalized name
    if path.parent != root:
        rel_parent = path.relative_to(root).parent
        rel = mount + "/" + str(rel_parent / normalized_name)
    else:
        rel = mount + "/" + normalized_name

    try:
        st = path.stat()
        mtime = st.st_mtime
        ctime = getattr(st, "st_birthtime", st.st_ctime)
    except OSError:
        mtime = 0.0
        ctime = 0.0

    # Determine node type: package files are treated as files even if they're directories
    is_directory = path.is_dir() and not _is_package_file(path)

    node = {
        "name": normalized_name,
        "path": rel,
        "type": "directory" if is_directory else "file",
        "mtime": mtime,
        "ctime": ctime,
    }
    # Add children: None for directories to match _tree() structure
    # This allows frontend lazy loading to detect unloaded directories
    if is_directory:
        node["children"] = None
    return node


def _tree(
    path: Path, root: Path, mount: str, depth: int = 0, max_depth: int = 3
) -> dict[str, Any]:
    node = _node(path, root, mount)
    # Only recurse for actual directories, not package files
    if path.is_dir() and not _is_package_file(path):
        if depth < max_depth:
            children = []
            try:
                entries = sorted(
                    path.iterdir(), key=lambda p: (p.is_file(), p.name.lower())
                )
                for entry in entries:
                    if entry.name.startswith("."):
                        continue
                    children.append(_tree(entry, root, mount, depth + 1, max_depth))
            except PermissionError:
                # Skipping an unreadable directory is right, but silently
                # skipping it leaves a user asking why a folder is missing.
                log.debug("skipping unreadable directory", exc_info=True)
            node["children"] = children
        else:
            node["children"] = None
    return node


def get_tree() -> list[dict[str, Any]]:
    """Return file tree for all mounts (notes, generated, library, + any extra vaults).

    Mounts with pending path changes return an "unavailable" node until
    user restarts containers with new environment variables.
    """
    entries = [
        ("notes", settings.notes_path, 3),
        ("generated", settings.generated_path, 2),
        ("library", settings.library_root, 2),
    ] + [(name, path, 2) for name, path in settings.extra_library_mounts.items()]
    result = []
    for mount, root, depth in entries:
        # Check if this mount has a pending path change
        if settings.is_path_pending_change(mount):
            result.append(
                {
                    "name": mount,
                    "path": mount,
                    "type": "unavailable",
                    "message": "Path change pending — restart required to apply new mount",
                    "children": [],
                }
            )
        elif root.exists():
            result.append(_tree(root, root, mount, max_depth=depth))
    return result


def get_dir_children(rel_path: str) -> list[dict[str, Any]]:
    """Return immediate children of a directory.

    Raises HTTPException if the mount has a pending path change.
    """
    import logging

    log = logging.getLogger(__name__)

    # Check if this mount has a pending path change
    mount = rel_path.split("/")[0]
    if settings.is_path_pending_change(mount):
        from fastapi import HTTPException

        # Both paths in the message: "restart required" alone told the user
        # nothing about what they were restarting *into*, and this 503 is the
        # one they meet with a broken tree and no other diagnostic.
        raise HTTPException(
            status_code=503,
            detail=(
                f"Mount '{mount}' has a pending path change — restart to apply. "
                f"Currently {settings.all_mounts.get(mount)}, "
                f"moving to {settings.pending_path_changes().get(mount)}"
            ),
        )

    path = settings.resolve(rel_path)

    # Raise error if directory doesn't exist
    if not path.exists():
        log.warning("Directory does not exist: %s", rel_path)
        raise FileNotFoundError(f"Directory not found: {rel_path}")

    # Package files should never be expanded as directories
    if _is_package_file(path):
        log.warning("Attempted to expand package file as directory: %s", rel_path)
        raise NotADirectoryError(f"Package file (not directory): {rel_path}")

    if not path.is_dir():
        log.warning("Path is not a directory: %s", rel_path)
        raise NotADirectoryError(f"Not a directory: {rel_path}")

    children = []
    # Determine mount and root from rel_path prefix
    mount = rel_path.split("/")[0]
    root = settings.all_mounts[mount]

    try:
        for entry in sorted(
            path.iterdir(), key=lambda p: (p.is_file(), p.name.lower())
        ):
            if entry.name.startswith("."):
                continue
            children.append(_node(entry, root, mount))
    except PermissionError as e:
        log.warning("Permission denied reading directory %s: %s", rel_path, e)
        raise PermissionError(f"Permission denied: {rel_path}") from e

    return children
