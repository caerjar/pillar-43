import logging
import mimetypes
from urllib.parse import quote

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from config import settings
from models import TreeResponse
from services import capabilities
from services.archive.access import filter_children, filter_tree
from services.vault import (
    extract_viewer_text,
    get_dir_children,
    get_tree,
    read_file,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api")


@router.get("/tree", response_model=TreeResponse)
async def tree():
    return filter_tree(get_tree())


@router.get("/tree/dir")
async def tree_dir(path: str):
    """Return one level of children for a vault directory (lazy loading)."""
    try:
        children = get_dir_children(path)
        if not children:
            log.debug("Directory empty: %s", path)
        return {"path": path, "children": filter_children(children)}
    except FileNotFoundError as e:
        log.error("Directory not found: %s", path)
        raise HTTPException(status_code=404, detail=str(e)) from e
    except NotADirectoryError as e:
        log.error("Not a directory: %s", path)
        raise HTTPException(status_code=400, detail=str(e)) from e
    except PermissionError as e:
        log.error("Permission denied: %s", path)
        raise HTTPException(status_code=403, detail=str(e)) from e
    except (ValueError, KeyError) as e:
        log.error("Invalid path: %s - %s", path, e)
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/file/raw")
async def file_raw(path: str):
    """Serve the raw binary (or text) file with correct Content-Type.
    PDFs open in browser; other types trigger a download."""
    try:
        resolved = settings.resolve(path)
    except (ValueError, KeyError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    # Unicode fallback: macOS screenshots use narrow no-break space (U+202F) ONLY before AM/PM
    # Tree normalizes to regular space, but disk may still have Unicode variant
    # Only replace the space before AM/PM at end of filename, not all spaces
    if not resolved.exists() or not resolved.is_file():
        import re
        from pathlib import Path

        path_str = str(resolved)
        # Replace space before AM/PM in screenshot pattern: "10.16.51 PM.png" → "10.16.51 PM.png"
        #   is the narrow no-break space
        replacement = " \\1.\\2"
        unicode_variant = Path(
            re.sub(
                r" (AM|PM)\.(png|jpg|jpeg)$", replacement, path_str, flags=re.IGNORECASE
            )
        )
        if unicode_variant.exists() and unicode_variant.is_file():
            resolved = unicode_variant
        else:
            raise HTTPException(status_code=404, detail=f"{path} not found")
    mime, _ = mimetypes.guess_type(resolved.name)
    media_type = mime or "application/octet-stream"
    headers: dict[str, str] = {}
    if resolved.suffix.lower() == ".pdf":
        from services.vault import pdf_needs_native

        if pdf_needs_native(resolved):
            headers["X-PDF-Native"] = "true"
    # SVG is rendered as a *document* (not an image) when opened directly,
    # so embedded <script>/event handlers would execute. Defense in depth
    # alongside the handwriting service's write-time sanitizer: forbid
    # scripts and sandbox the document. nosniff prevents the browser from
    # second-guessing the media type if the bytes look HTML-y.
    if resolved.suffix.lower() == ".svg":
        headers["Content-Security-Policy"] = (
            "default-src 'none'; style-src 'unsafe-inline'; img-src 'self' data:; sandbox"
        )
        headers["X-Content-Type-Options"] = "nosniff"
    encoded_name = quote(resolved.name, safe="")
    response = FileResponse(
        str(resolved),
        media_type=media_type,
        content_disposition_type="inline",
        headers=headers,
    )
    # Use only the UTF-8 encoded filename to avoid Latin-1 encoding errors with Unicode characters (U+202F)
    response.headers["Content-Disposition"] = f"inline; filename*=UTF-8''{encoded_name}"
    return response


@router.get("/file/pdf-info")
async def file_pdf_info(path: str):
    """Return page count for a PDF (server-side rendering via poppler)."""
    try:
        resolved = settings.resolve(path)
    except (ValueError, KeyError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    # Unicode fallback: macOS screenshots use narrow no-break space (U+202F) ONLY before AM/PM
    # Only replace the space before AM/PM at end of filename, not all spaces
    if not resolved.exists() or not resolved.is_file():
        import re
        from pathlib import Path

        path_str = str(resolved)
        # Replace space before AM/PM in screenshot pattern: "10.16.51 PM.png" → "10.16.51 PM.png"
        #   is the narrow no-break space
        replacement = " \\1.\\2"
        unicode_variant = Path(
            re.sub(
                r" (AM|PM)\.(png|jpg|jpeg)$", replacement, path_str, flags=re.IGNORECASE
            )
        )
        if unicode_variant.exists() and unicode_variant.is_file():
            resolved = unicode_variant
        else:
            raise HTTPException(status_code=404, detail=f"{path} not found")
    if resolved.suffix.lower() != ".pdf":
        return {"page_count": 0}
    from services.vault import get_pdf_page_count

    return {"page_count": get_pdf_page_count(resolved)}


@router.get("/file/pdf-page")
async def file_pdf_page(path: str, page: int = 1, dpi: int = 150):
    """Render a single PDF page server-side using poppler and return PNG.

    dpi controls resolution — use 72 * scale to map viewer scale to dpi.
    Clamped to 50–300 to prevent abuse.
    """
    if not (50 <= dpi <= 300):
        raise HTTPException(status_code=400, detail="dpi must be 50–300")
    if page < 1:
        raise HTTPException(status_code=400, detail="page must be ≥ 1")
    try:
        resolved = settings.resolve(path)
    except (ValueError, KeyError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    # Unicode fallback: macOS screenshots use narrow no-break space (U+202F) ONLY before AM/PM
    # Only replace the space before AM/PM at end of filename, not all spaces
    if not resolved.exists() or not resolved.is_file():
        import re
        from pathlib import Path

        path_str = str(resolved)
        # Replace space before AM/PM in screenshot pattern: "10.16.51 PM.png" → "10.16.51 PM.png"
        #   is the narrow no-break space
        replacement = " \\1.\\2"
        unicode_variant = Path(
            re.sub(
                r" (AM|PM)\.(png|jpg|jpeg)$", replacement, path_str, flags=re.IGNORECASE
            )
        )
        if unicode_variant.exists() and unicode_variant.is_file():
            resolved = unicode_variant
        else:
            raise HTTPException(status_code=404, detail=f"{path} not found")
    if resolved.suffix.lower() != ".pdf":
        raise HTTPException(status_code=400, detail="not a PDF")
    try:
        from services.vault import render_pdf_page

        png = render_pdf_page(resolved, page, dpi)
    except capabilities.CapabilityUnavailableError as e:
        # 503, not 500: nothing is broken, a binary this deployment needs is
        # simply not installed. The message carries the remedy.
        raise HTTPException(status_code=503, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    from fastapi.responses import Response

    return Response(
        content=png,
        media_type="image/png",
        headers={"Cache-Control": "max-age=3600, private"},
    )


@router.get("/file/text")
async def file_text(path: str):
    """Extract readable text from EPUB, DOCX, MOBI for in-app viewing."""
    try:
        resolved = settings.resolve(path)
    except (ValueError, KeyError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    # Unicode fallback: macOS screenshots use narrow no-break space (U+202F) ONLY before AM/PM
    # Only replace the space before AM/PM at end of filename, not all spaces
    if not resolved.exists() or not resolved.is_file():
        import re
        from pathlib import Path

        path_str = str(resolved)
        # Replace space before AM/PM in screenshot pattern: "10.16.51 PM.png" → "10.16.51 PM.png"
        #   is the narrow no-break space
        replacement = " \\1.\\2"
        unicode_variant = Path(
            re.sub(
                r" (AM|PM)\.(png|jpg|jpeg)$", replacement, path_str, flags=re.IGNORECASE
            )
        )
        if unicode_variant.exists() and unicode_variant.is_file():
            resolved = unicode_variant
        else:
            raise HTTPException(status_code=404, detail=f"{path} not found")

    text = extract_viewer_text(resolved, path)
    return {"path": path, "text": text}


@router.get("/file")
async def file_read(path: str):
    try:
        result = read_file(path)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except (ValueError, IsADirectoryError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return result
