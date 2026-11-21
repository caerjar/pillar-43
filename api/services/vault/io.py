"""Core file I/O operations - read and write.

Writes respect mount-level write permissions (notes/generated writable, library
read-only by default). The only callers are the transcription and handwriting
services, which write their output beside the source file. There is no git
history of `notes/`: that service was removed with the personal app.
"""

import logging
from pathlib import Path
from typing import Any

from config import settings
from .constants import BINARY_EXTENSIONS, IWORK_EXTENSIONS, MAX_EDITOR_BYTES
from .extraction import extract_viewer_text

log = logging.getLogger(__name__)


def _repair_svg_if_malformed(svg: str) -> str:
    """Return well-formed SVG, repairing malformed XML if needed.

    Model-generated SVG sometimes contains unescaped attribute values (e.g.
    `AttValue: ' expected`), which makes the browser's strict XML parser refuse
    to render the saved file. We parse leniently and re-serialize so the saved
    `.svg` is always renderable.

    Valid SVG is returned byte-for-byte untouched (strict parse succeeds first —
    no reformatting of hand-edited files). If lxml is unavailable or the markup
    is unrecoverable, the original string is returned so the editor can still
    surface it for manual fixing.
    """
    try:
        from lxml import etree
    except ImportError:  # pragma: no cover - lxml is a declared dependency
        return svg
    raw = svg.encode("utf-8")
    try:
        etree.fromstring(raw)  # strict: already well-formed → leave untouched
        return svg
    except etree.XMLSyntaxError:
        # Strict parse failed — that is the signal to attempt the lenient
        # repair below, not an error in itself.
        pass
    try:
        root = etree.fromstring(raw, parser=etree.XMLParser(recover=True))
        if root is None:
            return svg
        return etree.tostring(root, encoding="unicode")
    except Exception:  # never let repair block a save
        log.debug("SVG repair failed; writing original", exc_info=True)
        return svg


def _check_writable(rel_path: str, abs_path: Path) -> None:  # noqa: ARG001 — mount is derived from rel_path; abs_path kept for caller symmetry
    """Raise PermissionError if the path is in a read-only location."""
    mount = Path(rel_path).parts[0]
    if mount == "library" and settings.effective_library_readonly():
        raise PermissionError(
            "library/ is read-only (set LIBRARY_READONLY=false in .env to enable vault reorganisation)"
        )
    if mount in settings.extra_library_mounts:
        raise PermissionError(
            f"{mount}/ is read-only (extra vault sources are always read-only)"
        )
    if mount not in settings.all_mounts:
        raise PermissionError(f"Unknown mount: {mount!r}")


def read_file(rel_path: str) -> dict[str, Any]:
    """Read file metadata and content. Returns binary=True for non-text files."""
    path = settings.resolve(rel_path)

    # Unicode fallback: macOS screenshots use narrow no-break space (U+202F) ONLY before AM/PM
    # Tree normalizes to regular space, but disk may still have Unicode variant
    # Only replace the space before AM/PM at end of filename, not all spaces
    if not path.exists():
        import re

        path_str = str(path)
        # Replace space before AM/PM in screenshot pattern: "10.16.51 PM.png" → "10.16.51 PM.png"
        #   is the narrow no-break space
        replacement = " \\1.\\2"
        unicode_variant = Path(
            re.sub(
                r" (AM|PM)\.(png|jpg|jpeg)$", replacement, path_str, flags=re.IGNORECASE
            )
        )
        if unicode_variant.exists():
            path = unicode_variant
        else:
            raise FileNotFoundError(f"{rel_path} not found")

    if not path.is_file():
        raise IsADirectoryError(f"{rel_path} is a directory")

    ext = path.suffix.lower()

    # Try to extract text from iWork files
    if ext in IWORK_EXTENSIONS:
        try:
            extracted_text = extract_viewer_text(path, rel_path)
            if extracted_text:
                return {
                    "path": rel_path,
                    "content": extracted_text,
                    "binary": False,
                    "ext": ext,
                    "extracted": True,
                }
        except Exception as e:
            log.warning("iWork extraction failed for %s: %s", rel_path, e)
        # Fall through to binary if extraction fails
        return {"path": rel_path, "content": None, "binary": True, "ext": ext}

    if ext in BINARY_EXTENSIONS:
        return {"path": rel_path, "content": None, "binary": True, "ext": ext}

    # Check file size before reading to prevent browser hangs on large text files
    file_size = path.stat().st_size
    if file_size > MAX_EDITOR_BYTES:
        size_mb = file_size / (1024 * 1024)
        return {
            "path": rel_path,
            "content": None,
            "binary": False,
            "ext": ext,
            "too_large": True,
            "size_mb": round(size_mb, 2),
            "message": f"File too large for editor ({size_mb:.1f} MB). Maximum size: {MAX_EDITOR_BYTES / (1024 * 1024):.0f} MB",
        }

    try:
        content = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return {"path": rel_path, "content": None, "binary": True, "ext": ext}
    return {"path": rel_path, "content": content, "binary": False, "ext": ext}


def write_file(rel_path: str, content: str, authorship: str | None = None) -> None:
    """Write content to file. Injects authorship frontmatter for new markdown in notes/."""
    path = settings.resolve(rel_path)
    # notes/ and generated/ are always writable. library/ is writable only
    # when the user has flipped library_readonly off. Extra library sources
    # are never writable — see the branch below.
    is_active = False
    try:
        path.relative_to(settings.notes_path.resolve())
        is_active = True
        writable = True
    except ValueError:
        writable = False
    if not writable:
        try:
            path.relative_to(settings.generated_path.resolve())
            writable = True
        except ValueError:
            # relative_to raises when the path is NOT under this root — the
            # exception IS the membership answer. See the maintainer notes.
            pass
    if not writable and not settings.effective_library_readonly():
        # The toggle governs `library/` ONLY. Extra sources stay read-only
        # whatever it says, which is what `_check_writable` has always claimed
        # ("extra vault sources are always read-only") and what this branch
        # used to contradict by including them in the loop.
        #
        # Under Docker the contradiction was invisible: extra libraries were
        # bind-mounted `:ro`, so the kernel refused the write even when this
        # said yes. Natively there is no mount and this function is the only
        # thing in the way — flipping the toggle off would have started
        # writing into someone's read-only archive.
        try:
            path.relative_to(settings.library_root.resolve())
            writable = True
        except ValueError:
            pass
    if not writable:
        mount = rel_path.split("/")[0]
        if mount in settings.extra_library_mounts:
            raise PermissionError(
                f"{mount}/ is read-only — extra vault sources are always "
                "read-only, and the 'Library read-only' setting does not "
                "apply to them"
            )
        raise PermissionError(
            "library/ is read-only — toggle 'Library read-only' off in Settings to enable writes"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    # Inject authorship frontmatter for new markdown files in notes/ only
    if authorship and is_active and not path.exists() and rel_path.endswith(".md"):
        content = f"---\nauthorship: {authorship}\n---\n\n{content}"
    # Repair malformed SVG before it reaches disk so the saved file always
    # renders (model output is frequently not well-formed XML).
    if rel_path.lower().endswith(".svg"):
        content = _repair_svg_if_malformed(content)
    path.write_text(content, encoding="utf-8")
