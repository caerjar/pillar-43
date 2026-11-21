"""File-level helpers: hash, frontmatter parse, authorship, text extraction,
and the SQL upsert used by the file-scan pass.

`extract_text_for_catalog` reuses the binary-format helpers in
`services.vault` (`_extract_epub_text`, `_extract_docx_text`) — those stay in
vault.py because vault uses them directly for the file-detail endpoints.
"""

from __future__ import annotations

import gc
import hashlib
import logging
import typing
import re
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from pathlib import Path

from config import settings
from pypdf import PdfReader
from services._media_exts import NO_TEXT_EXTENSIONS
from services._transcript_path import transcript_path
from services.vault import (
    BINARY_EXTENSIONS,
    _extract_docx_text,
    _extract_epub_text,
)

from .constants import (
    CATALOG_TEXT_LIMIT,
    REFERENCE_EXTENSIONS,
)
from .state import FileRecord

log = logging.getLogger(__name__)

EXTRACT_TIMEOUT_SEC = 30
_MAX_PDF_PAGES = 5000  # page-count cap — bounds crafted many-page PDFs
_extractor_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="extract")

_FM_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def _parse_frontmatter(text: str) -> dict:
    """Extract key: value pairs from YAML frontmatter. No external deps."""
    m = _FM_RE.match(text)
    if not m:
        return {}
    result: dict[str, str] = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            result[k.strip()] = v.strip().strip("\"'")
    return result


def _infer_authorship(rel_path: str, ext: str, mount: str, frontmatter: dict) -> str:  # noqa: ARG001 — frontmatter wins before the path heuristics need rel_path
    """Classify a file's authorship. Frontmatter wins; heuristics fill the rest."""
    if "authorship" in frontmatter:
        return frontmatter["authorship"]
    if mount == "generated":
        return "ai"
    if ext in REFERENCE_EXTENSIONS:
        return "reference"
    if ext == ".md" and mount in ("library", "notes"):
        return "user"
    return "reference"


def hash_file(path: Path) -> str:
    """Return hex SHA-256 of a file's contents, reading in 64 KB chunks."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# Unpaired UTF-16 surrogate code points (U+D800–U+DFFF) sometimes leak out
# of pypdf extraction on PDFs with damaged encoding. Python's UTF-8 codec
# refuses to encode them, so SQLite writes that include them raise
# "surrogates not allowed" and the whole catalog row is skipped. We replace
# them with U+FFFD (the official replacement char) at the extraction
# boundary so all downstream consumers see clean UTF-8.
_SURROGATE_RE = re.compile(r"[\ud800-\udfff]")


def _strip_surrogates(text: str | None) -> str | None:
    """Replace unpaired UTF-16 surrogate code points with U+FFFD.

    No-op for None / empty / clean strings; the regex sub returns the same
    object when nothing matches, so the hot path costs are a single search.
    See MAINTAIN_PANEL_PLAN.md §0 'UTF-8 surrogate encoding error'.
    """
    if not text:
        return text
    return _SURROGATE_RE.sub("�", text)


def _extract_text_inner(path: Path, rel_path: str) -> str | None:
    ext = path.suffix.lower()
    if ext in NO_TEXT_EXTENSIONS:
        try:
            t_rel = transcript_path(rel_path)
            t_abs = settings.generated_path / Path(t_rel).relative_to("generated")
            if t_abs.exists():
                return _strip_surrogates(
                    t_abs.read_text(encoding="utf-8", errors="replace")[
                        :CATALOG_TEXT_LIMIT
                    ]
                )
        except Exception as e:
            log.warning("transcript lookup failed for %s: %s", rel_path, e)
        return None
    try:
        if ext == ".pdf":
            reader = PdfReader(path)
            pages: list[str] = []
            chars = 0
            # Page-count cap: a crafted PDF with millions of near-empty pages
            # would otherwise iterate them all (never hitting the char limit),
            # bounded only by the leaky 30s timeout. 5000 pages is far beyond
            # any real document.
            for i, page in enumerate(reader.pages):
                if i >= _MAX_PDF_PAGES:
                    log.warning(
                        "PDF %s exceeds %d-page cap — truncating",
                        rel_path,
                        _MAX_PDF_PAGES,
                    )
                    break
                text = page.extract_text() or ""
                if text.strip():
                    chunk = f"[Page {i + 1}]\n{text}"
                    pages.append(chunk)
                    chars += len(chunk)
                    if chars >= CATALOG_TEXT_LIMIT:
                        break
            result = (
                "\n\n".join(pages)[:CATALOG_TEXT_LIMIT]
                if pages
                else f"[PDF: {rel_path} — no extractable text]"
            )
            del reader, pages
            gc.collect()
            return _strip_surrogates(result)
        if ext == ".epub":
            return _strip_surrogates(_extract_epub_text(path)[:CATALOG_TEXT_LIMIT])
        if ext in (".docx", ".doc"):
            text = _extract_docx_text(path)[:CATALOG_TEXT_LIMIT]
            # Tracked changes and comments are items with their own consent
            # (docx_changes.register_changes); keeping them in the
            # manuscript's text would leak a private comment through it.
            return _strip_surrogates(text)
        if ext in (".mbox", ".eml"):
            # Decoded messages, not the raw MIME: headers and base64 bodies
            # must never reach chunking or the sentence splitter.
            from services.archive.mail import render_text

            return _strip_surrogates(render_text(path)[:CATALOG_TEXT_LIMIT])
        if ext in BINARY_EXTENSIONS:
            return None
        content = path.read_text(encoding="utf-8", errors="replace")
        return _strip_surrogates(content[:CATALOG_TEXT_LIMIT])
    except Exception as e:
        log.warning("Text extraction failed for %s: %s", rel_path, e)
        return None


def extract_text_for_catalog(path: Path, rel_path: str) -> str | None:
    """Extract plain text for a file with a hard wall-clock budget.

    A malformed PDF (broken xref, JBIG2-encoded, encrypted) can wedge pypdf's
    pure-Python extraction loop indefinitely. Run on a 4-worker pool with a
    per-call timeout so one bad file can't stall the whole scan.

    On timeout the worker thread keeps running in the background until pypdf
    eventually returns; the pool's max_workers cap (4) limits how many can be
    wedged at once. Returns None on timeout (same as any extraction failure).

    NOTE: An earlier subprocess-per-file approach was tried (multiprocessing
    fork) but spawn-per-file overhead made the 39k-file library scan glacial.
    Threads have the leak risk but acceptable performance.
    """
    fut = _extractor_pool.submit(_extract_text_inner, path, rel_path)
    try:
        return fut.result(timeout=EXTRACT_TIMEOUT_SEC)
    except FuturesTimeout:
        log.warning(
            "[catalog] extract timeout (%ds) for %s — skipping",
            EXTRACT_TIMEOUT_SEC,
            rel_path,
        )
        return None


def upsert_file_record(
    conn: sqlite3.Connection,
    record: FileRecord,
    existing_map: dict | None = None,
    commit: bool = True,
) -> int:
    """Insert or update a file record in the catalog.

    If the file's SHA-256 is unchanged, only the mutable metadata (mtime,
    size_bytes, abs_path) is updated and the AI fields are preserved.
    If the hash changed (content modified), AI fields are cleared so they
    will be re-generated on the next summarization pass.

    Args:
        existing_map: Optional pre-loaded {rel_path: row_dict} to avoid
            a per-file SELECT. If None, falls back to a direct query.
        commit: If False, skip the commit (caller batches commits).

    Returns the row id.
    """
    r = record
    if existing_map is not None:
        existing = existing_map.get(r.rel_path)
    else:
        existing = conn.execute(
            "SELECT id, sha256 FROM files WHERE rel_path=?", (r.rel_path,)
        ).fetchone()

    if existing:
        if existing["sha256"] == r.sha256:
            conn.execute(
                "UPDATE files SET abs_path=?, size_bytes=?, mtime=? WHERE rel_path=?",
                (r.abs_path, r.size_bytes, r.mtime, r.rel_path),
            )
        else:
            conn.execute(
                """UPDATE files SET
                    mount=?, abs_path=?, sha256=?, size_bytes=?, mtime=?, ext=?,
                    extracted_text=?, summary=NULL, topics=NULL, entities=NULL,
                    cataloged_at=NULL, authorship=?
                WHERE rel_path=?""",
                (
                    r.mount,
                    r.abs_path,
                    r.sha256,
                    r.size_bytes,
                    r.mtime,
                    r.ext,
                    r.extracted_text,
                    r.authorship,
                    r.rel_path,
                ),
            )
        if commit:
            conn.commit()
        return existing["id"]

    conn.execute(
        """INSERT INTO files
            (rel_path, mount, abs_path, sha256, size_bytes, mtime, ext, extracted_text, authorship)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (
            r.rel_path,
            r.mount,
            r.abs_path,
            r.sha256,
            r.size_bytes,
            r.mtime,
            r.ext,
            r.extracted_text,
            r.authorship,
        ),
    )
    if commit:
        conn.commit()
    row = conn.execute(
        "SELECT id FROM files WHERE rel_path=?", (r.rel_path,)
    ).fetchone()
    # Keep existing_map in sync so subsequent lookups in this run are correct
    if existing_map is not None and row:
        existing_map[r.rel_path] = dict(row)
    return row["id"]


def reextract_all_files(
    progress_cb: typing.Callable[[str, int, int], None] | None = None,
) -> int:
    """Re-extract text from every file in the catalog.

    Walks all rows in ``files``, resolves each to its absolute path, runs
    ``extract_text_for_catalog``, and writes the result back to
    ``extracted_text``.  No AI calls — purely mechanical text extraction.

    Returns the number of files processed.
    """
    from services.db import get_db

    conn = get_db()
    rows = conn.execute("SELECT id, rel_path, abs_path FROM files").fetchall()
    total = len(rows)
    updated = 0

    for i, row in enumerate(rows, 1):
        rel_path = row["rel_path"]
        abs_path = row["abs_path"]
        if progress_cb:
            progress_cb(f"Extracting: {rel_path}", i, total)

        path = Path(abs_path)
        if not path.exists():
            log.debug("[reextract] skipping missing file: %s", rel_path)
            continue

        text = extract_text_for_catalog(path, rel_path)
        text = _strip_surrogates(text)
        conn.execute(
            "UPDATE files SET extracted_text = ? WHERE id = ?",
            (text, row["id"]),
        )
        updated += 1

        if updated % 50 == 0:
            conn.commit()

    conn.commit()
    return updated
