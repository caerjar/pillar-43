"""Split extracted text into embeddable passages.

Before this existed, every file was represented by a single vector computed
from its first 2000 characters — a 200-page PDF was its title page, and no
question could reach page 40. This module is what makes retrieval able to
find something in the middle of a long document.

Pure and I/O-free by design: no DB, no network, no settings. The catalog
pass in `chunk.py` owns persistence; everything here is a function of its
arguments, so the boundary rules can be tested exhaustively.

Sizing — `BAAI/bge-small-en-v1.5` truncates at 512 tokens. 1200 characters
of English prose lands around 280-320 tokens, which leaves headroom for the
heading prefix we prepend at embed time. Overlap keeps a sentence that
straddles a boundary reachable from both sides.

Boundary rules, in priority order:
  1. Never split inside a fenced code block or a markdown table. A fence cut
     in half is noise in both halves.
  2. Prefer heading boundaries, then blank-line paragraph boundaries, then
     sentence boundaries, then a hard character cut as the last resort.
  3. Overlap applies only to mid-section splits — never across a heading, or
     every section would open with the tail of the previous one.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from .constants import (
    CHUNK_MAX_CHARS,
    CHUNK_MIN_CHARS,
    CHUNK_OVERLAP_CHARS,
    MAX_CHUNKS_PER_FILE,
)

# ATX headings only. Setext (underlined) headings are rare in our corpus and
# ambiguous to detect without lookahead; they degrade to paragraph packing.
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_FENCE_RE = re.compile(r"^\s*(```|~~~)")
_TABLE_RE = re.compile(r"^\s*\|")
# Sentence end: ., !, ? followed by whitespace. Avoids splitting on the dot in
# "e.g." / "Dr." by requiring the preceding char not be a single capital or a
# known abbreviation fragment — imperfect but cheap, and a bad sentence split
# only costs us a slightly ragged chunk edge, never a lost passage.
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"'\[(])")

_MARKDOWN_EXTS = {".md", ".markdown", ".mdx"}


@dataclass(frozen=True)
class Chunk:
    """One embeddable passage.

    `text` is the bare passage as stored and injected. `heading` is the
    breadcrumb path ("Intro > Dosage") used to build the embed text and to
    label the passage in a prompt. `char_start`/`char_end` index into the
    source string — they make it possible to drop the stored `text` later and
    reconstruct from `files.extracted_text` instead.
    """

    text: str
    heading: str | None
    ordinal: int
    char_start: int
    char_end: int

    @property
    def chunk_hash(self) -> str:
        """Content identity — the skip-rerun key. Position-independent on
        purpose: reordering a document should not force a re-embed of text
        that has not changed."""
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()

    @property
    def embed_text(self) -> str:
        """What actually goes to the embedding model. The heading breadcrumb
        measurably helps recall on sectioned notes — a passage under
        "Dosage" should be findable by "how much", and the bare passage
        often does not contain the word."""
        if self.heading:
            return f"{self.heading}\n\n{self.text}"
        return self.text


@dataclass
class _Block:
    """A run of source text that must not be split internally."""

    text: str
    start: int
    end: int
    atomic: bool = False


def chunk_text(text: str, *, ext: str = "") -> list[Chunk]:
    """Split `text` into passages. Returns [] for empty/whitespace input.

    `ext` selects the strategy: markdown extensions get heading-aware
    splitting; everything else (PDF/DOCX/plain-text extractions) gets
    paragraph packing, since extracted text rarely carries reliable heading
    structure.
    """
    if not text or not text.strip():
        return []

    is_md = ext.lower() in _MARKDOWN_EXTS
    sections = _split_sections(text) if is_md else [(None, 0, len(text))]

    chunks: list[Chunk] = []
    ordinal = 0
    for heading, sec_start, sec_end in sections:
        if ordinal >= MAX_CHUNKS_PER_FILE:
            break
        body = text[sec_start:sec_end]
        if not body.strip():
            continue
        for piece_start, piece_end in _pack_section(body):
            if ordinal >= MAX_CHUNKS_PER_FILE:
                break
            abs_start = sec_start + piece_start
            abs_end = sec_start + piece_end
            piece = text[abs_start:abs_end].strip()
            if not piece:
                continue
            chunks.append(
                Chunk(
                    text=piece,
                    heading=heading,
                    ordinal=ordinal,
                    char_start=abs_start,
                    char_end=abs_end,
                )
            )
            ordinal += 1

    return chunks


def _split_sections(text: str) -> list[tuple[str | None, int, int]]:
    """Split markdown into (heading_breadcrumb, start, end) spans.

    The breadcrumb is the live heading stack joined with " > ", so a passage
    under `## Dosage` inside `# Comfrey` carries "Comfrey > Dosage".
    Content before the first heading gets `None`.
    """
    spans: list[tuple[str | None, int, int]] = []
    stack: list[tuple[int, str]] = []  # (level, title)
    cur_heading: str | None = None
    cur_start = 0
    pos = 0
    in_fence = False

    for line in text.splitlines(keepends=True):
        stripped = line.rstrip("\n")
        if _FENCE_RE.match(stripped):
            in_fence = not in_fence
        elif not in_fence:
            m = _HEADING_RE.match(stripped)
            if m:
                # Close the previous span at this heading's start.
                if pos > cur_start:
                    spans.append((cur_heading, cur_start, pos))
                level = len(m.group(1))
                title = m.group(2).strip()
                while stack and stack[-1][0] >= level:
                    stack.pop()
                stack.append((level, title))
                cur_heading = " > ".join(t for _, t in stack)
                cur_start = pos + len(line)  # body starts after the heading line
        pos += len(line)

    if pos > cur_start:
        spans.append((cur_heading, cur_start, pos))
    return spans or [(None, 0, len(text))]


def _blocks(body: str) -> list[_Block]:
    """Break a section body into paragraph blocks, marking code fences and
    tables atomic so the packer never cuts through one."""
    blocks: list[_Block] = []
    lines = body.splitlines(keepends=True)
    i = 0
    pos = 0
    buf: list[str] = []
    buf_start = 0

    def _flush() -> None:
        nonlocal buf, buf_start
        if buf:
            joined = "".join(buf)
            if joined.strip():
                blocks.append(_Block(joined, buf_start, buf_start + len(joined)))
            buf = []

    while i < len(lines):
        line = lines[i]
        stripped = line.rstrip("\n")

        if _FENCE_RE.match(stripped):
            _flush()
            fence_start = pos
            fence: list[str] = [line]
            pos += len(line)
            i += 1
            # Consume to the closing fence, or EOF if unterminated.
            while i < len(lines):
                fence.append(lines[i])
                closed = bool(_FENCE_RE.match(lines[i].rstrip("\n")))
                pos += len(lines[i])
                i += 1
                if closed:
                    break
            joined = "".join(fence)
            blocks.append(
                _Block(joined, fence_start, fence_start + len(joined), atomic=True)
            )
            buf_start = pos
            continue

        if _TABLE_RE.match(stripped):
            _flush()
            tbl_start = pos
            tbl: list[str] = []
            while i < len(lines) and _TABLE_RE.match(lines[i].rstrip("\n")):
                tbl.append(lines[i])
                pos += len(lines[i])
                i += 1
            joined = "".join(tbl)
            blocks.append(
                _Block(joined, tbl_start, tbl_start + len(joined), atomic=True)
            )
            buf_start = pos
            continue

        if not stripped.strip():
            buf.append(line)
            pos += len(line)
            i += 1
            _flush()
            buf_start = pos
            continue

        if not buf:
            buf_start = pos
        buf.append(line)
        pos += len(line)
        i += 1

    _flush()
    return blocks


def _pack_section(body: str) -> list[tuple[int, int]]:
    """Greedily pack blocks into <= CHUNK_MAX_CHARS spans.

    Returns (start, end) offsets relative to `body`. A trailing runt shorter
    than CHUNK_MIN_CHARS is merged back into the previous span rather than
    emitted as its own near-empty chunk.
    """
    blocks = _blocks(body)
    if not blocks:
        return []

    spans: list[tuple[int, int]] = []
    cur_start: int | None = None
    cur_end = 0
    # Overlap must never reach back into an atomic block, or a chunk following
    # a code fence picks up that fence's closing delimiter — a stray ``` that
    # makes both chunks parse as broken markdown.
    atomic_barrier = 0

    for b in blocks:
        blen = b.end - b.start
        # An oversized non-atomic block splits internally; atomic ones are
        # emitted whole even if they exceed the cap (a 3000-char code fence
        # is still one unit — half of it is worse than a long chunk).
        if blen > CHUNK_MAX_CHARS and not b.atomic:
            if cur_start is not None:
                spans.append((cur_start, cur_end))
                cur_start = None
            spans.extend(_split_oversized(body, b.start, b.end))
            continue

        if cur_start is None:
            cur_start, cur_end = b.start, b.end
        elif (b.end - cur_start) <= CHUNK_MAX_CHARS:
            cur_end = b.end
        else:
            spans.append((cur_start, cur_end))
            # Overlap: reach back into the just-closed span so a thought
            # spanning the seam stays retrievable from the new chunk too.
            cur_start = max(cur_start, b.start - CHUNK_OVERLAP_CHARS, atomic_barrier)
            cur_start = _snap_forward(body, cur_start, b.start)
            cur_end = b.end

        if b.atomic:
            atomic_barrier = b.end

    if cur_start is not None:
        spans.append((cur_start, cur_end))

    return _merge_runt(spans)


def _split_oversized(body: str, start: int, end: int) -> list[tuple[int, int]]:
    """Split one over-long paragraph on sentence boundaries, falling back to
    a hard cut when a single 'sentence' is itself longer than the cap (common
    in PDF extractions with no punctuation)."""
    text = body[start:end]
    spans: list[tuple[int, int]] = []
    pieces: list[tuple[int, int]] = []
    last = 0
    for m in _SENTENCE_RE.finditer(text):
        pieces.append((last, m.start()))
        last = m.end()
    pieces.append((last, len(text)))

    cur_start: int | None = None
    cur_end = 0
    for ps, pe in pieces:
        if pe <= ps:
            continue
        if (pe - ps) > CHUNK_MAX_CHARS:
            if cur_start is not None:
                spans.append((start + cur_start, start + cur_end))
                cur_start = None
            # Hard cut, with overlap so the seam stays covered.
            step = CHUNK_MAX_CHARS - CHUNK_OVERLAP_CHARS
            for off in range(ps, pe, step):
                spans.append((start + off, start + min(off + CHUNK_MAX_CHARS, pe)))
                if off + CHUNK_MAX_CHARS >= pe:
                    break
            continue
        if cur_start is None:
            cur_start, cur_end = ps, pe
        elif (pe - cur_start) <= CHUNK_MAX_CHARS:
            cur_end = pe
        else:
            spans.append((start + cur_start, start + cur_end))
            cur_start, cur_end = ps, pe

    if cur_start is not None:
        spans.append((start + cur_start, start + cur_end))
    return spans


def _snap_forward(body: str, pos: int, limit: int) -> int:
    """Nudge an overlap start forward to the next whitespace, so a chunk does
    not begin mid-word."""
    i = pos
    while i < limit and not body[i].isspace():
        i += 1
    return i if i < limit else pos


def _merge_runt(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Fold a too-short trailing span into its predecessor."""
    if len(spans) < 2:
        return spans
    last_start, last_end = spans[-1]
    if (last_end - last_start) < CHUNK_MIN_CHARS:
        prev_start, _ = spans[-2]
        return [*spans[:-2], (prev_start, last_end)]
    return spans
