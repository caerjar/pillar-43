"""Text extraction from binary formats and AI-ready content preparation.

EPUB/DOCX use stdlib only (no external deps). PDF uses pypdf for text extraction.
All extraction functions handle errors gracefully and return empty string on failure.
"""

import logging
from pathlib import Path

from config import settings

# Import constants locally for convenience
from .constants import (
    BINARY_EXTENSIONS,
    IWORK_EXTENSIONS,
    AI_CONTEXT_LIMIT,
)

log = logging.getLogger(__name__)

# ── Zip / XML bomb defenses (EPUB + DOCX are ZIP+XML containers) ──────────────
# The catalog extracts text from these formats; the files can be attacker-
# supplied (a Commons attachment, a synced doc). Without caps, a ~25 MB zip can
# inflate to hundreds of GB (decompression bomb) or an XML entity can expand
# exponentially (billion-laughs), OOM-ing the container — the 30s extract
# timeout doesn't help because the wedged thread keeps allocating. So we bound
# decompressed size per member + per archive, and parse XML with entity
# resolution and network access disabled.
_MAX_ZIP_MEMBER_BYTES = 50 * 1024 * 1024  # per decompressed member
_MAX_ZIP_TOTAL_BYTES = 200 * 1024 * 1024  # total decompressed per archive


def _safe_zip_read(zf, name: str) -> bytes:
    """Read a zip member only if its DECLARED uncompressed size is within the
    per-member cap (checked before decompressing). Raises ValueError otherwise."""
    info = zf.getinfo(name)
    if info.file_size > _MAX_ZIP_MEMBER_BYTES:
        raise ValueError(
            f"zip member {name!r} too large: {info.file_size} bytes "
            f"(cap {_MAX_ZIP_MEMBER_BYTES})"
        )
    return zf.read(name)


def _hardened_xml_fromstring(data: bytes):
    """Parse XML with entity resolution + DTD load + network access OFF, using
    the already-present lxml. Kills billion-laughs/XXE. Returns an lxml element
    whose findall(..., namespaces=) API matches ElementTree usage."""
    from lxml import etree

    parser = etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        load_dtd=False,
        dtd_validation=False,
        huge_tree=False,
    )
    return etree.fromstring(data, parser=parser)


def _extract_epub_text(path: Path) -> str:
    """Extract text from EPUB (ZIP+XHTML) using stdlib, with bomb caps."""
    import zipfile
    from html.parser import HTMLParser

    class TextExtractor(HTMLParser):
        def __init__(self):
            super().__init__()
            self.text = []

        def handle_data(self, data):
            self.text.append(data)

    try:
        with zipfile.ZipFile(path, "r") as zf:
            text_parts = []
            total = 0
            for name in sorted(zf.namelist()):
                if name.endswith((".html", ".xhtml", ".htm")):
                    try:
                        info = zf.getinfo(name)
                        total += info.file_size
                        if total > _MAX_ZIP_TOTAL_BYTES:
                            log.warning(
                                "EPUB %s exceeds decompression cap — truncating", path
                            )
                            break
                        content = _safe_zip_read(zf, name).decode(
                            "utf-8", errors="ignore"
                        )
                        parser = TextExtractor()
                        parser.feed(content)
                        text_parts.append(" ".join(parser.text))
                    except Exception:
                        continue
            return "\n\n".join(text_parts)
    except Exception as e:
        log.warning("EPUB extraction failed for %s: %s", path, e)
        return ""


def _extract_docx_text(path: Path) -> str:
    """Extract text from DOCX (ZIP+XML) using stdlib + hardened XML parse."""
    import zipfile

    try:
        with zipfile.ZipFile(path, "r") as zf:
            try:
                doc_xml = _safe_zip_read(zf, "word/document.xml")
            except KeyError:
                return ""
            root = _hardened_xml_fromstring(doc_xml)
            ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
            paragraphs = root.findall(".//w:p", namespaces=ns)
            text_parts = []
            for para in paragraphs:
                texts = para.findall(".//w:t", namespaces=ns)
                text_parts.append("".join(t.text or "" for t in texts))
            return "\n\n".join(text_parts)
    except Exception as e:
        log.warning("DOCX extraction failed for %s: %s", path, e)
        return ""


def _iwork_index_xml_parts(zf) -> list[str] | None:
    """Older iWork format: text lives in index.xml.

    Returns the extracted parts, or **None meaning abort the whole
    extraction** — not "no text found". That distinction is why this is not
    a plain list: an index.xml over 10MB uncompressed is a zip-bomb
    signature, and falling through to the other strategies on the same
    archive would defeat the guard. A small ZIP can hold a huge index.xml,
    so the compressed size is not the thing to trust.
    """
    import xml.etree.ElementTree as ET

    text_parts: list[str] = []
    try:
        xml_data = zf.read("index.xml")

        # Safety limit: skip huge XML files (>10MB uncompressed)
        if len(xml_data) > 10 * 1024 * 1024:
            log.warning(
                "index.xml too large (%d bytes), skipping XML parse",
                len(xml_data),
            )
            return None

        content = xml_data.decode("utf-8", errors="ignore")

        # Safety: truncate very long XML to prevent parser hangs
        if len(content) > 5 * 1024 * 1024:
            content = content[: 5 * 1024 * 1024]

        root = ET.fromstring(content)

        # Extract all text nodes from XML
        # iWork stores text in various tags depending on type
        for text_elem in root.iter():
            if text_elem.text and text_elem.text.strip():
                # Skip very short strings (likely metadata/formatting)
                if len(text_elem.text.strip()) > 2:
                    text_parts.append(text_elem.text.strip())

            # Safety: limit total extracted text
            if len("\n\n".join(text_parts)) > 500_000:
                break
    except Exception as e:
        log.debug("Failed to parse index.xml: %s", e)
    return text_parts


def _extract_iwork_text(path: Path) -> str:
    """Extract text from Apple iWork files (.pages, .key, .numbers).

    These are ZIP archives containing XML. Text is in index.xml.
    Size-limited to prevent hanging on huge files.
    """
    import zipfile

    # Safety limit: skip files larger than 50MB to prevent hangs
    MAX_IWORK_SIZE = 50 * 1024 * 1024
    if path.stat().st_size > MAX_IWORK_SIZE:
        log.warning(
            "iWork file too large (%d bytes), skipping: %s", path.stat().st_size, path
        )
        return ""

    try:
        with zipfile.ZipFile(path, "r") as zf:
            # Candidate members, tried in order below: index.xml (older
            # format), Index/Document.iwa (newer), QuickLook/Preview.pdf.
            text_parts = []

            # Try index.xml first (older format)
            if "index.xml" in zf.namelist():
                parts = _iwork_index_xml_parts(zf)
                if parts is None:
                    return ""
                text_parts = parts

            # If no text extracted, try QuickLook preview
            if not text_parts and "QuickLook/Preview.pdf" in zf.namelist():
                try:
                    import tempfile

                    with tempfile.NamedTemporaryFile(
                        suffix=".pdf", delete=False
                    ) as tmp:
                        tmp.write(zf.read("QuickLook/Preview.pdf"))
                        tmp_path = Path(tmp.name)

                    text = _extract_pdf_text(tmp_path, str(path))
                    tmp_path.unlink()
                    return text
                except Exception as e:
                    log.debug("Failed to extract QuickLook preview: %s", e)

            # If still no text, try extracting readable strings from .iwa files (newer format)
            # .iwa is Protocol Buffers format - we can't fully parse it without schemas,
            # but we can extract readable ASCII strings to show *something*
            if not text_parts:
                try:
                    # Prioritize content .iwa files that are more likely to have text
                    iwa_files = sorted(
                        [name for name in zf.namelist() if name.endswith(".iwa")]
                    )
                    # Prioritize: Tables/DataList, Document, Metadata (skip small locale files)
                    priority = []
                    other = []
                    for name in iwa_files:
                        info = zf.getinfo(name)
                        # Skip very small files (likely just metadata/locale)
                        if info.file_size < 100:
                            continue
                        if (
                            "Tables" in name
                            or "DataList" in name
                            or "Document.iwa" in name
                        ):
                            priority.append(name)
                        else:
                            other.append(name)

                    iwa_to_check = (
                        priority + other[:10]
                    )  # Check priority files + up to 10 others

                    for iwa_name in iwa_to_check:
                        try:
                            iwa_data = zf.read(iwa_name)
                            # Extract sequences of printable ASCII (likely text content)
                            readable = []
                            current = []
                            for byte in iwa_data:
                                if 32 <= byte < 127:  # Printable ASCII
                                    current.append(chr(byte))
                                elif current:
                                    # End of string - keep if length > 6 chars (filter short metadata)
                                    if len(current) > 6:
                                        text = "".join(current).strip()
                                        # Filter out format strings, metadata, and gibberish
                                        skip_patterns = (
                                            "com.apple",
                                            "SF",
                                            "en_US",
                                            "gregorian",
                                            "latn",
                                            "January",
                                            "February",
                                            "March",
                                            "April",
                                            "August",
                                            "September",
                                            "October",
                                            "November",
                                            "December",
                                            "Sunday",
                                            "Monday",
                                            "Tuesday",
                                            "Wednesday",
                                            "Thursday",
                                            "Friday",
                                            "Saturday",
                                            "Anno Domini",
                                            "Before Christ",
                                            "#,##0",
                                            "EEEE",
                                            "MMM",
                                        )
                                        # Keep if it doesn't start with known patterns and has mostly letters
                                        if (
                                            text
                                            and not any(
                                                text.startswith(p)
                                                for p in skip_patterns
                                            )
                                            and sum(c.isalpha() for c in text)
                                            > len(text) * 0.5
                                        ):
                                            readable.append(text)
                                    current = []

                            # Add any remaining string
                            if len(current) > 6:
                                text = "".join(current).strip()
                                if (
                                    text
                                    and sum(c.isalpha() for c in text) > len(text) * 0.5
                                ):
                                    readable.append(text)

                            if readable:
                                text_parts.extend(readable)
                        except Exception:
                            continue

                        # Stop if we have enough text
                        if len("\n".join(text_parts)) > 5000:
                            break
                except Exception as e:
                    log.debug("Failed to extract from .iwa files: %s", e)

            return "\n\n".join(text_parts)
    except Exception as e:
        log.warning("iWork extraction failed for %s: %s", path, e)
        return ""


def _extract_pdf_text(path: Path, rel_path: str) -> str:
    """Extract text from PDF using pypdf."""
    try:
        import pypdf

        with open(path, "rb") as f:
            reader = pypdf.PdfReader(f)
            text_parts = []
            for page in reader.pages:
                text_parts.append(page.extract_text() or "")
            return "\n\n".join(text_parts)
    except Exception as e:
        log.warning("PDF text extraction failed for %s: %s", rel_path, e)
        return ""


def extract_viewer_text(path: Path, rel_path: str) -> str | None:
    """Extract text from binary files for viewer display.

    Returns None if the file is not a supported text-extractable format.
    Used by the viewer to show content when possible.
    """
    ext = path.suffix.lower()
    if ext == ".epub":
        return _extract_epub_text(path)
    if ext == ".docx":
        return _extract_docx_text(path)
    if ext == ".pdf":
        return _extract_pdf_text(path, rel_path)
    if ext in IWORK_EXTENSIONS:
        return _extract_iwork_text(path)
    return None


def read_text_for_ai(rel_path: str) -> str:
    """Read file as plain text, extracting from binary formats when possible.

    Returns empty string if the file cannot be read as text.
    Truncates to AI_CONTEXT_LIMIT characters.
    """
    path = settings.resolve(rel_path)
    ext = path.suffix.lower()

    # Binary extraction
    if ext == ".epub":
        content = _extract_epub_text(path)
    elif ext == ".docx":
        content = _extract_docx_text(path)
    elif ext == ".pdf":
        content = _extract_pdf_text(path, rel_path)
    elif ext in IWORK_EXTENSIONS:
        content = _extract_iwork_text(path)
    elif ext in BINARY_EXTENSIONS:
        return ""
    else:
        try:
            content = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            return ""

    if len(content) > AI_CONTEXT_LIMIT:
        content = content[:AI_CONTEXT_LIMIT] + "\n\n[… file truncated for context …]"
    return content
