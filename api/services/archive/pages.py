"""Which PDF page a passage starts on.

The PDF extractor writes a "[Page N]" line at the top of each page, and each
chunk stores its `char_start` into `files.extracted_text`. The page is the
last marker at or before that offset. Texts without markers (letters,
minutes, transcripts) have no page.
"""

from __future__ import annotations

import re
import sqlite3

_PAGE_MARK = re.compile(r"\[Page (\d+)\]")


def page_at(text: str | None, char_start: int) -> int | None:
    if not text:
        return None
    page = None
    for m in _PAGE_MARK.finditer(text):
        if m.start() > char_start:
            break
        page = int(m.group(1))
    return page


def chunk_pages(conn: sqlite3.Connection, chunk_ids: list[int]) -> dict[int, int]:
    """{chunk_id: page} for the chunks that have one."""
    ids = [i for i in set(chunk_ids) if i]
    if not ids:
        return {}
    q = ",".join("?" * len(ids))
    rows = conn.execute(
        f"SELECT fc.id, fc.char_start, f.extracted_text FROM file_chunks fc "
        f"JOIN files f ON f.id = fc.file_id WHERE fc.id IN ({q})",
        ids,
    ).fetchall()
    out: dict[int, int] = {}
    for cid, start, text in rows:
        page = page_at(text, start or 0)
        if page is not None:
            out[cid] = page
    return out
