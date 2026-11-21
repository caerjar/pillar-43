"""Handwriting → markdown (and SVG diagrams) transcription service.

Distinct from `services/transcription.py` because:

  - Accepts PDFs in addition to images (PDF lands in Step 6).
  - Produces multiple artifacts: one markdown plus 0..N SVG diagrams.
  - Uses a local Ollama vision model with a JSON-schema `format` for
    structured output instead of a free-text caption. The model decides
    per-page whether it's text-only, mixed, diagram-only, or blank, and emits SVG redrawings for diagrams it finds.

This file lands incrementally:
  - Step 3 (current): images only, text-only tool schema (no diagrams).
  - Step 4: extend schema with diagrams[] + page_kind; write SVG sidecars.
  - Step 5: HEIC → JPEG transcoding before the vision call.
  - Step 6: PDF multi-page assembly with global diagram numbering.
"""

from __future__ import annotations

import io
import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from config import settings
from services._diagram_path import diagram_path
from services._transcript_path import transcript_path
from services.catalog import hash_file
from services import vault
from services.vision import describe_image
from services.transcription import _existing_matches, _format_transcript

log = logging.getLogger(__name__)


# Image set accepted by the handwriting route. HEIC requires in-memory
# transcoding to JPEG before the vision call (the model doesn't
# accept image/heic). Defined locally rather than widening the catalog's
# _media_exts.IMAGE_EXTS — extending that set would route HEIC inputs
# through /api/transcribe's existing image-caption path, which has no
# transcoder and would fail at the API boundary.
HANDWRITING_IMAGE_EXTS: frozenset[str] = frozenset(
    {
        ".jpg",
        ".jpeg",
        ".png",
        ".webp",
        ".gif",
        ".heic",
    }
)

# Multi-page PDFs are rendered page-by-page server-side via PDFium and
# fed through the vision call in a loop. Renders at 200 DPI (vs the
# default 150) — handwriting needs the extra detail.
HANDWRITING_EXTS: frozenset[str] = HANDWRITING_IMAGE_EXTS | frozenset({".pdf"})
_PDF_RENDER_DPI: int = 200

# Cost/memory caps. The image cap matches transcription.py's Whisper limit;
# the PDF page cap is calibrated so a worst-case run is ~$0.20 (single-digit
# dollars on the longest PDF a user is likely to drop on a phone). Raise
# only deliberately — vision calls aren't cheap.
_MAX_SOURCE_BYTES: int = 25 * 1024 * 1024
_MAX_PDF_PAGES: int = 50


# Serialize handwriting work. Vision calls aren't CPU-bound but
# the local vision model serves one request at a time, and we don't want
# PDF-page loops from one user request to starve another. One at a time is fine.
_handwriting_semaphore = threading.Semaphore(1)


ProgressCallback = Callable[[str, float], None]
"""(stage_message, fraction_complete) — fraction is 0.0-1.0."""


# ── Public surface ────────────────────────────────────────────────────────────


def is_handwriting_transcribable(rel_path: str) -> bool:
    return Path(rel_path).suffix.lower() in HANDWRITING_EXTS


def transcribe(
    rel_path: str,
    progress: ProgressCallback | None = None,
    *,
    force: bool = False,
) -> dict:
    """Transcribe a handwritten page (image now; PDF in Step 6).

    Returns a dict matching `routes.handwriting.HandwritingDone`:
        {
            "transcript_path": "generated/transcripts/<encoded>.md",
            "diagram_paths": [...],          # empty in Step 3
            "diagrams_found": int,           # 0 in Step 3
            "pages_processed": int,
        }

    Hash-based skip: a transcript whose frontmatter `source_hash` matches
    the current source's content hash short-circuits the call. `force=True`
    bypasses the skip.
    """
    if not is_handwriting_transcribable(rel_path):
        raise ValueError(f"Not a handwriting-transcribable file: {rel_path}")

    abs_path = settings.resolve(rel_path)
    if not abs_path.exists():
        raise FileNotFoundError(rel_path)

    # Cost + memory cap. A 1 GB image is loaded whole into RAM and
    # ~3x'd by base64 — quickest path to OOM on a small machine.
    size = abs_path.stat().st_size
    if size > _MAX_SOURCE_BYTES:
        mib = lambda b: b // (1024 * 1024)  # noqa: E731 — local clarity
        raise ValueError(
            f"{rel_path} is {mib(size)} MB; max is {mib(_MAX_SOURCE_BYTES)} MB"
        )
    # PDF page cap. Cheaper to reject up front than after page 1 renders.
    # _transcribe_pdf will re-fetch the count; the duplicate call is fine
    # (pypdf reads the trailer dict only — sub-ms).
    if abs_path.suffix.lower() == ".pdf":
        from services.vault.pdf import get_pdf_page_count

        pc = get_pdf_page_count(abs_path)
        if pc > _MAX_PDF_PAGES:
            raise ValueError(
                f"PDF has {pc} pages; max is {_MAX_PDF_PAGES}. "
                f"Split the PDF or raise the cap in services.handwriting."
            )

    src_hash = hash_file(abs_path)
    out_rel = transcript_path(rel_path)
    out_abs = settings.generated_path / Path(out_rel).relative_to("generated")
    if not force and _existing_matches(out_abs, src_hash):
        _emit(progress, "source unchanged — using cached transcript", 1.0)
        return {
            "transcript_path": out_rel,
            "diagram_paths": [],
            "diagrams_found": 0,
            "pages_processed": 1,
        }

    # On force, clear any prior SVGs for this source so the new run doesn't
    # leave orphaned `.<n>.svg` files behind when the diagram count shrinks.
    if force:
        _clear_existing_diagrams(rel_path)

    _emit(progress, "queued", 0.0)
    # Bounded wait. Single-page vision calls finish in <30s and multi-page
    # PDFs in <2min, so 3 minutes is a generous ceiling. Waiting longer
    # almost certainly means the previous worker hung at the network layer
    # below the vision call's own timeout — surface that explicitly so
    # the user doesn't queue more work onto a stuck server.
    if not _handwriting_semaphore.acquire(timeout=180):
        raise RuntimeError(
            "previous handwriting transcription appears hung; restart the API "
            "or wait several minutes"
        )
    try:
        _emit(progress, "starting", 0.05)
        if abs_path.suffix.lower() == ".pdf":
            body, page_kind, diagram_paths, pages_processed = _transcribe_pdf(
                rel_path, abs_path, progress
            )
        else:
            body, page_kind, diagram_paths = _transcribe_image(
                rel_path, abs_path, progress
            )
            pages_processed = 1

        frontmatter = {
            "source_path": rel_path,
            "source_hash": src_hash,
            "page_kind": page_kind,
            "pages_processed": pages_processed,
            "diagrams_found": len(diagram_paths),
            "provider": "ollama",
            "model": settings.effective_vision_model(),
            "transcribed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        text = _format_transcript(rel_path, frontmatter, body)
        vault.write_file(out_rel, text)

        try:
            source_stem = Path(rel_path).stem
            inbox_name = f"{source_stem}-transcript.md"
            inbox_abs = settings.notes_path / "inbox" / inbox_name
            inbox_abs.parent.mkdir(parents=True, exist_ok=True)
            inbox_abs.write_text(text, encoding="utf-8")
            log.info("[handwriting] copied transcript to inbox: %s", inbox_name)
        except Exception:
            log.debug("[handwriting] inbox copy failed", exc_info=True)

        _emit(progress, "done", 1.0)
        return {
            "transcript_path": out_rel,
            "diagram_paths": diagram_paths,
            "diagrams_found": len(diagram_paths),
            "pages_processed": pages_processed,
        }
    finally:
        _handwriting_semaphore.release()


# ── Internals ─────────────────────────────────────────────────────────────────


def _emit(progress: ProgressCallback | None, stage: str, frac: float) -> None:
    if progress is not None:
        try:
            progress(stage, frac)
        except Exception:
            log.debug("handwriting progress callback raised; continuing", exc_info=True)


def _image_media_type(abs_path: Path) -> str:
    return {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }.get(abs_path.suffix.lower(), "image/jpeg")


def _load_image_for_vision(abs_path: Path) -> tuple[bytes, str]:
    """Return (image_bytes, media_type) ready for the local vision model.

    HEIC inputs are transcoded in-memory to JPEG because vision models
    take jpeg / png / webp / gif, not HEIC. Other extensions pass through.
    Transcoding lives here rather than in services/vault/extraction.py
    so the catalog/chat surface isn't widened by handwriting's needs.
    """
    if abs_path.suffix.lower() == ".heic":
        return _heic_to_jpeg_bytes(abs_path), "image/jpeg"
    return abs_path.read_bytes(), _image_media_type(abs_path)


def _heic_to_jpeg_bytes(abs_path: Path) -> bytes:
    """In-memory HEIC → JPEG using Pillow + pillow-heif.

    `register_heif_opener()` is idempotent — safe to call per-image. We
    re-encode at quality 92 (visually lossless for handwriting OCR)
    rather than copying the embedded JPEG preview iPhones include,
    because the preview may be downscaled.
    """
    from PIL import Image
    import pillow_heif

    pillow_heif.register_heif_opener()
    # `with` guarantees the file handle closes when the function returns,
    # rather than waiting on CPython refcount/GC. Matters for concurrent
    # HEIC processing — file descriptors are a process-wide resource.
    with Image.open(abs_path) as img:
        if img.mode != "RGB":
            img = img.convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=92)
        return buf.getvalue()


def _transcribe_pdf(
    rel_path: str, abs_path: Path, progress: ProgressCallback | None
) -> tuple[str, str, list[str], int]:
    """Transcribe a multi-page PDF page-by-page.

    Renders each page to PNG via PDFium, feeds it through the same
    structured vision call as single-image transcribe, then assembles
    everything into one markdown with `## Page N` headers and globally-
    numbered diagrams (so `<encoded>.<n>.svg` filenames stay unique
    across the whole PDF).

    Per-page error tolerance: a page that fails to render or fails the
    vision call emits `[page N — extraction failed: ...]` into the body
    and the loop continues. We do not abort the whole transcript on one
    bad page.

    Returns (markdown_body, page_kind, diagram_paths, pages_processed).
    The `page_kind` summarizes the whole PDF — "mixed" if any page had
    a diagram, "text-only" if every page was text-only, "blank" only if
    every page was blank, else "mixed".
    """
    from services.vault.pdf import get_pdf_page_count, render_pdf_page

    # Pre-check at top of transcribe() already rejected counts > _MAX_PDF_PAGES.
    # This guard handles 0 / -1 from a corrupt PDF — a different failure mode,
    # hence the asymmetric condition.
    page_count = get_pdf_page_count(abs_path)
    if page_count <= 0:
        raise RuntimeError(f"PDF has no readable pages: {rel_path}")

    page_sections: list[str] = []
    all_diagrams: list[dict] = []
    all_paths: list[str] = []
    kinds: list[str] = []
    next_diagram_index = 1

    for page_num in range(1, page_count + 1):
        frac = 0.05 + 0.90 * (page_num - 1) / page_count
        _emit(progress, f"page {page_num} of {page_count}: rendering", frac)
        try:
            png_bytes = render_pdf_page(abs_path, page_num, dpi=_PDF_RENDER_DPI)
        except Exception as e:
            log.warning("PDF page %d render failed: %s", page_num, e)
            page_sections.append(
                _page_header(page_num, page_count)
                + f"\n_[page {page_num} — render failed: {e}]_\n"
            )
            continue
        _emit(
            progress,
            f"page {page_num} of {page_count}: vision",
            frac + 0.45 / page_count,
        )
        try:
            result = _call_vision(png_bytes, "image/png")
        except Exception as e:
            log.warning("PDF page %d vision call failed: %s", page_num, e)
            page_sections.append(
                _page_header(page_num, page_count)
                + f"\n_[page {page_num} — extraction failed: {e}]_\n"
            )
            continue

        diagrams = result.get("diagrams") or []
        page_paths = _write_diagrams(rel_path, diagrams, start_index=next_diagram_index)
        body = _substitute_diagram_placeholders(
            result["markdown"], diagrams, page_paths
        )
        next_diagram_index += len(diagrams)
        # Only count non-empty diagrams toward the global paths list (Step 4
        # rule: empty/whitespace svgs are skipped with a "" placeholder).
        all_paths.extend([p for p in page_paths if p])
        all_diagrams.extend(diagrams)
        kinds.append(result.get("page_kind", "text-only"))
        page_sections.append(
            _page_header(page_num, page_count) + "\n" + body.rstrip() + "\n"
        )

    return "\n".join(page_sections), _summarize_kinds(kinds), all_paths, page_count


def _page_header(page_num: int, page_count: int) -> str:
    """Single-page PDFs don't need an `## Page 1` header; multi-page do."""
    if page_count <= 1:
        return ""
    return f"## Page {page_num}\n"


def _summarize_kinds(kinds: list[str]) -> str:
    """Collapse per-page page_kind values into one summary for the doc."""
    if not kinds:
        return "blank"
    non_blank = [k for k in kinds if k != "blank"]
    if not non_blank:
        return "blank"
    if all(k == "text-only" for k in non_blank):
        return "text-only"
    if all(k == "diagram-only" for k in non_blank):
        return "diagram-only"
    return "mixed"


def _transcribe_image(
    rel_path: str, abs_path: Path, progress: ProgressCallback | None
) -> tuple[str, str, list[str]]:
    """Send an image through the structured-output vision call.

    Writes any extracted SVG diagrams as sidecars at
    `generated/diagrams/<encoded>.<n>.svg`, then substitutes the
    `{{DIAGRAM:n}}` placeholders in the markdown with relative image
    links. Returns (markdown_body, page_kind, diagram_paths).
    """
    _emit(progress, "calling vision model", 0.30)
    image_bytes, media_type = _load_image_for_vision(abs_path)
    result = _call_vision(image_bytes, media_type)
    _emit(progress, "writing diagrams", 0.80)
    diagrams = result.get("diagrams") or []
    diagram_paths = _write_diagrams(rel_path, diagrams, start_index=1)
    _emit(progress, "writing transcript", 0.90)
    body = _substitute_diagram_placeholders(result["markdown"], diagrams, diagram_paths)
    return body + "\n", result["page_kind"], diagram_paths


_TRANSCRIBE_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "markdown": {
            "type": "string",
            "description": (
                "Full transcription of the page as GitHub-flavored markdown. "
                "Preserve headings, lists, emphasis, tables, and inline math "
                "($..$) where present. Where you see a diagram, sketch, chart, "
                "or figure, emit a {{DIAGRAM:n}} placeholder at the position "
                "it occupies (1-indexed, monotonic). The post-processor will "
                "replace each placeholder with a relative-path image link to "
                "the SVG file written from the diagrams[] array below."
            ),
        },
        "diagrams": {
            "type": "array",
            "description": (
                "One entry per diagram present on the page. Order MUST match "
                "the {{DIAGRAM:n}} placeholder numbering in the markdown. "
                "Empty array if the page is pure text."
            ),
            "items": {
                "type": "object",
                "properties": {
                    "caption": {
                        "type": "string",
                        "description": "Short caption (one sentence) for accessibility.",
                    },
                    "svg": {
                        "type": "string",
                        "description": (
                            "A complete, self-contained <svg>...</svg> document "
                            "redrawing the diagram. Use semantic shapes (lines, "
                            "circles, rectangles, paths, text) — not embedded "
                            "raster. Include a viewBox so the SVG scales. Aim "
                            "for legible, not pixel-perfect."
                        ),
                    },
                },
                "required": ["caption", "svg"],
            },
        },
        "page_kind": {
            "type": "string",
            "enum": ["text-only", "diagram-only", "mixed", "blank"],
            "description": "Coarse classification of the page content.",
        },
    },
    "required": ["markdown", "diagrams", "page_kind"],
}

_SYSTEM_PROMPT = (
    "You transcribe handwritten and scanned pages into clean markdown. Rules:\n"
    "1. Preserve structure: headings, lists, indentation, emphasis. Underline → italic, "
    "double-underline → bold.\n"
    "2. Where you find a diagram, sketch, chart, or figure, emit a {{DIAGRAM:n}} "
    "placeholder (1-indexed, monotonic).\n"
    "3. Tables use markdown tables. Math uses LaTeX in $...$ or $$...$$.\n"
    "4. Do not invent content. If a region is illegible, write [illegible].\n"
    "5. Strip page numbers and marginalia unless they carry meaning.\n"
    "\n"
    "Reply with a single JSON object matching the provided schema and nothing else."
)


def _call_vision(image_bytes: bytes, media_type: str) -> dict:
    """Single local vision call returning the parsed transcription object.

    The reply is constrained to `_TRANSCRIBE_SCHEMA` through Ollama's `format`
    field. SVG strings ride inside the JSON, so a parse failure (usually a
    reply cut off at the token limit) is surfaced as an error rather than
    guessed at.
    """
    raw = describe_image(
        image_bytes,
        media_type,
        "Transcribe this page.",
        system=_SYSTEM_PROMPT,
        schema=_TRANSCRIBE_SCHEMA,
        max_tokens=8192,
    )
    try:
        result = json.loads(raw)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"vision model returned invalid JSON: {e}") from e
    if not isinstance(result, dict):
        raise RuntimeError("vision model returned malformed output: not an object")
    missing = [k for k in ("markdown", "diagrams", "page_kind") if k not in result]
    if missing:
        # The `format` schema constrains shape, but a small model can still
        # return an empty or partial object on adversarial / tiny inputs.
        raise RuntimeError(f"vision model returned malformed output: missing {missing}")
    return result


_PLACEHOLDER_RE = __import__("re").compile(r"\{\{DIAGRAM:(\d+)\}\}")

# SVG sanitizer: write-time defense against `<script>`, inline event
# handlers, `<foreignObject>` (can host arbitrary HTML/JS), and
# `javascript:` hrefs. The /api/file/raw route also ships a strict CSP
# when serving .svg as a fallback. Together they cover both "render
# inline as an image" (safe by browser default) and "open the file
# directly" (where browsers execute SVG scripts unless told otherwise).
_SVG_SCRIPT_RE = __import__("re").compile(
    r"<script\b[^>]*>.*?</script\s*>",
    __import__("re").IGNORECASE | __import__("re").DOTALL,
)
_SVG_FOREIGN_RE = __import__("re").compile(
    r"<foreignObject\b[^>]*>.*?</foreignObject\s*>",
    __import__("re").IGNORECASE | __import__("re").DOTALL,
)
_SVG_EVENT_ATTR_RE = __import__("re").compile(
    # Anchor before `on*=` on any non-word boundary character (whitespace,
    # `/`, `"`, `'`, or string start) — the old `\s+` form missed
    # multi-attribute jams like `<svg width="1"onload="alert(1)">` where
    # there's no whitespace between `"` and `onload`. The captured boundary
    # character is re-emitted by the substitution (`sub(r"\1", svg)`) so
    # the surrounding markup stays intact.
    r"(^|[\s/'\"])on[a-z]+\s*=\s*(['\"])[^'\"]*\2",
    __import__("re").IGNORECASE,
)
_SVG_JS_URL_RE = __import__("re").compile(
    r"(href|xlink:href)\s*=\s*(['\"])\s*javascript:[^'\"]*\2",
    __import__("re").IGNORECASE,
)


def _sanitize_svg(svg: str) -> str:
    """Strip script-execution vectors from model-generated SVG.

    Permissive regex (not a full parser). Goal: make it safe to render the
    SVG as a standalone document. Trade-off: we may strip legitimate SVG
    `<script>` blocks the model emits for animation — handwriting SVGs
    don't need scripts, so this is acceptable.
    """
    svg = _SVG_SCRIPT_RE.sub("", svg)
    svg = _SVG_FOREIGN_RE.sub("", svg)
    # Replace with group 1 (the captured boundary char) so we drop only the
    # `on*="..."` payload, not the whitespace/quote that preceded it.
    svg = _SVG_EVENT_ATTR_RE.sub(r"\1", svg)
    return _SVG_JS_URL_RE.sub(r"\1=\2about:blank\2", svg)


def _clear_existing_diagrams(rel_path: str) -> None:
    """Delete any previously-generated SVGs for this source.

    Called on force regenerate. Without this, a run that previously
    produced 4 diagrams but now produces 2 would leave `.3.svg` and
    `.4.svg` orphaned on disk. Errors are logged at debug level; a
    permission issue on one file shouldn't fail the whole run.
    """
    encoded = rel_path.replace("/", "__")
    diagrams_dir = settings.generated_path / "diagrams"
    if not diagrams_dir.exists():
        return
    for stale in diagrams_dir.glob(f"{encoded}.*.svg"):
        try:
            stale.unlink()
        except OSError:
            log.debug("could not unlink stale diagram %s", stale, exc_info=True)


def _write_diagrams(rel_path: str, diagrams: list, *, start_index: int) -> list[str]:
    """Write each diagram's SVG to generated/diagrams/<encoded>.<n>.svg.

    Returns the list of rel_paths written, in the same order as `diagrams`.
    Numbering starts at `start_index` so multi-page docs (Step 6) can pass
    a running counter for global numbering across pages.
    """
    paths: list[str] = []
    for offset, entry in enumerate(diagrams):
        svg_text = entry.get("svg") or ""
        if not svg_text.strip():
            log.warning("diagram %d returned empty SVG; skipping", start_index + offset)
            paths.append("")
            continue
        diag_rel = diagram_path(rel_path, start_index + offset)
        vault.write_file(diag_rel, _sanitize_svg(svg_text))
        paths.append(diag_rel)
    return paths


def _substitute_diagram_placeholders(
    markdown: str, diagrams: list, diagram_paths: list[str]
) -> str:
    """Replace {{DIAGRAM:n}} with `![caption](../diagrams/<encoded>.<n>.svg)`.

    Placeholder numbers are 1-indexed within the *page* (or within the
    single image, for non-PDF inputs). They map to `diagrams[n-1]` and
    `diagram_paths[n-1]`. The model only sees one page at a time, so it
    always restarts at 1 — page-local numbering is the right contract.

    Filenames in `diagram_paths` are already globally numbered by the
    PDF loop, so cross-page uniqueness is preserved without the model
    needing to know its global page offset.

    Unknown numbers leave `_[diagram n missing]_` so the markdown stays
    valid and reviewable; empty SVGs leave `_[diagram n empty]_`. Both
    files live under generated/, so the link is `../diagrams/<file>`.
    """

    def _replace(match):
        n = int(match.group(1))
        offset = n - 1
        if offset < 0 or offset >= len(diagrams):
            log.warning("diagram placeholder %d has no matching entry", n)
            return f"_[diagram {n} missing]_"
        diag_rel = diagram_paths[offset]
        if not diag_rel:
            return f"_[diagram {n} empty]_"
        caption = diagrams[offset].get("caption", f"Diagram {n}")
        filename = diag_rel.split("/")[-1]
        return f"![{caption}](../diagrams/{filename})"

    return _PLACEHOLDER_RE.sub(_replace, markdown)
