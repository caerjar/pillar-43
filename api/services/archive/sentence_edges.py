"""Extend a retrieved chunk to the sentence edges around it.

The catalog chunks by size, so a chunk can start in the middle of a sentence or
end on a clause number whose heading is in the next chunk ("...Publisher.\\n6."
| "Reversion\\nIf the Work..."). A passage handed to the model, and a quote
pointer into it, should be whole sentences. Rather than re-chunk (a reindex of
every item, and chunk ids that other tables point at), the passage is widened
at retrieval time from the item's own text and the chunk's offsets: nothing
stored changes, and an item with no usable offsets falls back to the chunk.

Lines are the unit. PDF extraction keeps the page's line wrap, so a line that
fills the column and has no closing punctuation continues on the next one; a
short line (a heading, a letterhead, a signature) ends where it ends.
"""

from __future__ import annotations

import re

# How far past the chunk a passage may be widened, each way.
MAX_EXTEND_CHARS = 900
MAX_EXTEND_LINES = 8
_WRAP_SHARE = 0.75
_MIN_WRAP_WIDTH = 40

_PAGE_MARK = re.compile(r"\[Page \d+\]")
_TERMINAL = re.compile(r"[.!?][\"'”’)\]]?$")
_ABBREV = re.compile(
    r"(?:\b(?:No|Nos|Mr|Mrs|Ms|Dr|St|Inc|Ltd|Co|Corp|Jr|Sr|vol|pp|p|cf|cl|art|para)"
    r"|\be\.g|\bi\.e|\b[A-Z])\.$",
    re.IGNORECASE,
)
# A clause number alone on its line: "6." "7.1" "(b)". It belongs to the
# heading that follows it, so a chunk never ends on it and never starts after it.
_BARE_NUMBER = re.compile(r"(?:\d+(?:\.\d+)*\.?|\(?[a-z]{1,3}\))$")


def _norm(s: str) -> str:
    return " ".join(s.split())


def _ends_sentence(line: str, wrap_at: int) -> bool:
    """Does this line end a sentence or stand alone (heading, marker)?"""
    s = line.rstrip()
    if not s:
        return True
    if _TERMINAL.search(s) and not _ABBREV.search(s):
        return True
    return len(s) < wrap_at


def _line_bounds(full: str, pos: int) -> tuple[int, int]:
    """Start and end (exclusive of the newline) of the line holding `pos`."""
    a = full.rfind("\n", 0, pos) + 1
    b = full.find("\n", pos)
    return a, len(full) if b == -1 else b


def extend_chunks(conn, chunk_texts: dict[int, str]) -> dict[int, str]:
    """{chunk_id: widened text} for chunks whose offsets describe their text."""
    ids = list(chunk_texts)
    if not ids:
        return {}
    rows = conn.execute(
        "SELECT fc.id, fc.char_start, fc.char_end, f.extracted_text "
        "FROM file_chunks fc JOIN files f ON f.id = fc.file_id "
        f"WHERE fc.id IN ({','.join('?' * len(ids))})",
        ids,
    ).fetchall()
    return {
        cid: extend_to_sentence_edges(full or "", s or 0, e or 0, chunk_texts[cid])
        for cid, s, e, full in rows
    }


def extend_to_sentence_edges(full: str, start: int, end: int, chunk_text: str) -> str:
    """`full[start:end]` widened to whole sentences, or `chunk_text` unchanged
    if the offsets do not describe it."""
    if not (0 <= start < end <= len(full)) or _norm(full[start:end]) != _norm(
        chunk_text
    ):
        return chunk_text
    width = max((len(ln.rstrip()) for ln in full.splitlines()), default=0)
    wrap_at = max(_MIN_WRAP_WIDTH, int(width * _WRAP_SHARE))

    # Give up a trailing bare clause number: it heads the next chunk.
    tail = full[start:end].rstrip()
    last_line = tail.rsplit("\n", 1)[-1].strip()
    if "\n" in tail and _BARE_NUMBER.fullmatch(last_line):
        end = start + len(tail) - len(tail.rsplit("\n", 1)[-1])
    # Take back a bare clause number sitting just before the chunk.
    before = full[:start].rstrip()
    prev_line = before.rsplit("\n", 1)[-1].strip()
    if prev_line and _BARE_NUMBER.fullmatch(prev_line):
        start = before.rfind(prev_line)

    # Backward: while the line before the cut runs on into it, take that line.
    lo = max(0, start - MAX_EXTEND_CHARS)
    for _ in range(MAX_EXTEND_LINES):
        before = full[:start]
        if not before.strip() or start <= lo:
            break
        if before.endswith("\n"):
            if before.rstrip(" \t").endswith("\n\n"):
                break  # a blank line ends a block
            a, b = _line_bounds(full, start - 2 if start >= 2 else 0)
            prev = full[a:b]
            if _ends_sentence(prev, wrap_at):
                break
            start = a
        else:
            # cut inside a line: begin at the line's start
            start = _line_bounds(full, start)[0]

    # Forward: finish the line the cut falls in, then keep taking lines while
    # the last one runs on.
    if end < len(full) and full[end - 1] != "\n" and full[end] != "\n":
        end = _line_bounds(full, end)[1]
    cap = min(len(full), end + MAX_EXTEND_CHARS)
    for _ in range(MAX_EXTEND_LINES):
        last = full[start:end].rstrip().rsplit("\n", 1)[-1]
        if _ends_sentence(last, wrap_at) or end >= cap:
            break
        nxt = full.find("\n", end + 1)
        line = full[end : len(full) if nxt == -1 else nxt].strip()
        if not line or _PAGE_MARK.fullmatch(line):
            break  # a blank line or a page marker ends a block
        end = len(full) if nxt == -1 else nxt
    return full[start:end].strip()
