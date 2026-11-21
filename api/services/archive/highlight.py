"""Where a cited passage sits on its PDF page.

PDFium gives every glyph on a page a box. The cited text is normalised to
letters and digits, found in the page's normalised text, and the glyphs it
covers are merged into one box per line, as fractions of the page so the
overlay scales with the rendered image.

If the text is not on the page word for word (the extractor and the page
disagree on a hyphen or a ligature), the span of lines that shares the most
words with it is returned and marked `nearest`; the screen says so. If
nothing is close enough there is no box and the match is `none`.
"""

from __future__ import annotations

import re
from pathlib import Path

_WORD = re.compile(r"[^\W_]+", re.UNICODE)
# Below this overlap of the cited words, a span of lines is not a match.
_NEAREST_MIN = 0.5


def _norm(s: str) -> str:
    return "".join(w.lower() for w in _WORD.findall(s))


def _words(s: str) -> list[str]:
    return [w.lower() for w in _WORD.findall(s)]


def _line_boxes(
    glyphs: list[tuple[float, float, float, float]],
) -> list[tuple[float, float, float, float]]:
    """Merge glyph boxes (l, b, r, t) into one box per text line."""
    lines: list[list[float]] = []
    for x0, b, x1, t in glyphs:
        if x1 <= x0 or t <= b:
            continue
        mid = (b + t) / 2
        for ln in lines:
            if ln[1] <= mid <= ln[3]:
                ln[0], ln[1] = min(ln[0], x0), min(ln[1], b)
                ln[2], ln[3] = max(ln[2], x1), max(ln[3], t)
                break
        else:
            lines.append([x0, b, x1, t])
    return [(ln[0], ln[1], ln[2], ln[3]) for ln in lines]


def locate(pdf_path: Path, page: int, text: str) -> dict:
    from services.vault.pdf import PDFIUM_LOCK

    with PDFIUM_LOCK:  # PDFium is not thread-safe; see PDFIUM_LOCK
        return _locate(pdf_path, page, text)


def _locate(pdf_path: Path, page: int, text: str) -> dict:
    """{page, match, boxes[{x, y, w, h}]}: fractions of the page, origin at the
    top left. `match` is `exact`, `nearest` or `none`."""
    import pypdfium2 as pdfium

    out: dict = {"page": page, "match": "none", "boxes": []}
    target = _norm(text)
    if page < 1 or not target:
        return out
    doc = pdfium.PdfDocument(pdf_path)
    try:
        if page > len(doc):
            return out
        pg = doc[page - 1]
        if pg.get_rotation() % 360:
            return out
        left, bottom, right, top = pg.get_cropbox()
        pw, ph = right - left, top - bottom
        if pw <= 0 or ph <= 0:
            return out
        tp = pg.get_textpage()
        n = tp.count_chars()
        chars = [tp.get_text_range(i, 1) for i in range(n)]
        boxes = [tp.get_charbox(i) for i in range(n)]

        # Page text reduced to letters and digits; remember each kept glyph.
        flat: list[str] = []
        owner: list[int] = []
        for i, ch in enumerate(chars):
            for c in _norm(ch):
                flat.append(c)
                owner.append(i)
        hay = "".join(flat)

        at = hay.find(target)
        if at >= 0:
            span: tuple[int, int] | None = (owner[at], owner[at + len(target) - 1])
            match = "exact"
        else:
            span = _nearest(chars, text)
            match = "nearest"
        if span is None:
            return out

        glyphs = [boxes[i] for i in range(span[0], span[1] + 1) if chars[i].strip()]
        merged = _line_boxes(glyphs)
        if not merged:
            return out
        out["match"] = match
        out["boxes"] = [
            {
                "x": round((x0 - left) / pw, 5),
                "y": round((top - t) / ph, 5),
                "w": round((x1 - x0) / pw, 5),
                "h": round((t - b) / ph, 5),
            }
            for x0, b, x1, t in merged
        ]
        return out
    finally:
        doc.close()


def _nearest(chars: list[str], text: str) -> tuple[int, int] | None:
    """The run of whole lines sharing the most of the cited words, as the
    (first, last) glyph index; None when no run shares enough."""
    want_set = set(_words(text))
    if not want_set:
        return None
    lines: list[tuple[int, int, list[str]]] = []
    start: int | None = None
    for i, ch in enumerate(chars):
        if ch in ("\r", "\n"):
            if start is not None and _words("".join(chars[start:i])):
                lines.append((start, i - 1, _words("".join(chars[start:i]))))
            start = None
        elif start is None:
            start = i
    if start is not None and _words("".join(chars[start:])):
        lines.append((start, len(chars) - 1, _words("".join(chars[start:]))))
    best: tuple[float, int, int] | None = None
    for a in range(len(lines)):
        have: set[str] = set()
        for b in range(a, min(len(lines), a + 12)):
            have |= set(lines[b][2])
            hit = len(have & want_set)
            if not hit:
                continue
            recall, precision = hit / len(want_set), hit / len(have)
            score = 2 * recall * precision / (recall + precision)
            if best is None or score > best[0]:
                best = (score, a, b)
    if best is None or best[0] < _NEAREST_MIN:
        return None
    return lines[best[1]][0], lines[best[2]][1]
