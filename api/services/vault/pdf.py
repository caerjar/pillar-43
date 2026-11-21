"""PDF operations - native rendering checks, page counts, and server-side rendering.

All PDF rendering happens server-side, via PDFium, to handle all codecs.
Client-side pdfjs is still not an option: it cannot reliably decode JBIG2 or
JPX, which this vault's scanned material uses heavily.
"""

import io
import threading
from pathlib import Path

from .constants import PDF_UNSUPPORTED_FILTERS


# PDFium is not thread-safe: two threads inside it at once crash the whole
# worker (segfault, container restart). FastAPI runs sync routes in a thread
# pool, and the browser asks for a page image and the passage boxes for it at
# the same moment. Every PDFium call in the process goes through this lock.
PDFIUM_LOCK = threading.RLock()


def pdf_needs_native(abs_path: Path) -> bool:
    """Return True if the PDF uses filters pdfjs cannot reliably render.

    Scans in 64 KB chunks so large PDFs (200 MB+) don't load fully into RAM.
    Carries a 32-byte tail overlap between chunks to catch filter tags that
    span a chunk boundary.
    """
    _CHUNK = 65536
    try:
        with open(abs_path, "rb") as f:
            overlap = b""
            while True:
                chunk = f.read(_CHUNK)
                if not chunk:
                    return False
                block = overlap + chunk
                if any(tag in block for tag in PDF_UNSUPPORTED_FILTERS):
                    return True
                overlap = block[-32:]
    except OSError:
        return False


def get_pdf_page_count(abs_path: Path) -> int:
    """Return the number of pages in a PDF."""
    try:
        import pypdf

        with open(abs_path, "rb") as f:
            reader = pypdf.PdfReader(f)
            return len(reader.pages)
    except Exception:
        return 0


def render_pdf_page(abs_path: Path, page: int, dpi: int = 150) -> bytes:
    with PDFIUM_LOCK:
        return _render_pdf_page(abs_path, page, dpi)


def _render_pdf_page(abs_path: Path, page: int, dpi: int) -> bytes:
    """Render a single PDF page to PNG using PDFium (via pypdfium2).

    Returns PNG bytes. Raises `RuntimeError` on an out-of-range page or a
    document PDFium cannot open — there is no degraded form of "render a page",
    so this is one of the few places that raises rather than continuing with
    less.

    This shelled out to poppler's `pdftoppm` until 2026-08-29. That worked in
    Docker, where `api/Dockerfile` installed poppler-utils, and was dead in the
    macOS app: the bundle ships no poppler, and a Finder-launched app inherits
    launchd's PATH rather than the user's shell, so a Homebrew `pdftoppm` was
    invisible to it too. Every PDF in the desktop build showed "Failed to
    render page".

    PDFium is a library, not a binary. It arrives as a self-contained wheel, so
    there is no PATH to get wrong and no capability to probe — which is why
    this function no longer calls `capabilities.require`. Measured against
    poppler on this vault's JBIG2 / JPX / CCITTFax documents (the codecs that
    put rendering server-side to begin with): identical page dimensions and a
    mean absolute pixel difference of 1.6/255, at 7-27x the speed. A text-heavy
    page differs more (13.9/255) purely in font antialiasing.
    """
    import pypdfium2 as pdfium

    if page < 1:
        raise RuntimeError(f"page {page} is out of range")
    try:
        doc = pdfium.PdfDocument(abs_path)
    except Exception as e:  # PdfiumError, OSError - both mean "cannot render"
        raise RuntimeError(f"could not open PDF: {e}") from e
    try:
        if page > len(doc):
            raise RuntimeError(f"page {page} is out of range (document has {len(doc)})")
        bitmap = doc[page - 1].render(scale=dpi / 72)
        buf = io.BytesIO()
        bitmap.to_pil().save(buf, format="PNG")
        return buf.getvalue()
    finally:
        doc.close()
