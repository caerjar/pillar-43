"""Stage 2d: tracked changes and comments in a .docx, kept and citable.

Editorial history is part of the archive. The plain text extractor keeps the
words as they stand now (insertions in, deletions out) and so loses who cut a
sentence and when. This reads the revision marks themselves and renders each
one as a sentence that says who, what and when, which the catalog appends to
the document's text. Each sentence then lands in a chunk like any other, so a
quotation of it is a quotation of the attribution as well as the words.

Hardened the same way the other extractors are: bounded zip reads, and an XML
parser with entities, DTDs and network off.
"""

from __future__ import annotations

import logging
import zipfile
from dataclasses import dataclass
from pathlib import Path

from services.vault.extraction import _hardened_xml_fromstring, _safe_zip_read

log = logging.getLogger(__name__)

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


@dataclass
class Change:
    kind: str  # "insertion" | "deletion" | "comment"
    author: str
    date: str  # YYYY-MM-DD, "" when the mark carries none
    text: str
    paragraph: int = 0  # 1-based index of the paragraph it belongs to; 0 = unknown
    paragraph_text: str = (
        ""  # that paragraph as it stands now (insertions in, deletions out)
    )


def _text(el) -> str:
    return "".join(t.text or "" for t in el.iter(f"{_W}t", f"{_W}delText")).strip()


def _meta(el) -> tuple[str, str]:
    author = el.get(f"{_W}author") or "Unknown author"
    return author, (el.get(f"{_W}date") or "")[:10]


def read_changes(path: Path) -> list[Change]:
    """Insertions, deletions and comments, in document order (comments last)."""
    out: list[Change] = []
    try:
        with zipfile.ZipFile(path, "r") as zf:
            try:
                root = _hardened_xml_fromstring(_safe_zip_read(zf, "word/document.xml"))
            except KeyError:
                return []
            refs: dict[str, tuple[int, str]] = {}  # comment id -> its paragraph
            for n, p in enumerate(root.iter(f"{_W}p"), 1):
                final = "".join(t.text or "" for t in p.iter(f"{_W}t")).strip()
                for r in p.iter(f"{_W}commentReference"):
                    refs[r.get(f"{_W}id") or ""] = (n, final)
                for el in p.iter(f"{_W}ins", f"{_W}del"):
                    text = _text(el)
                    if not text:
                        continue
                    author, date = _meta(el)
                    kind = "insertion" if el.tag == f"{_W}ins" else "deletion"
                    out.append(Change(kind, author, date, text, n, final))
            try:
                comments = _hardened_xml_fromstring(
                    _safe_zip_read(zf, "word/comments.xml")
                )
            except KeyError:
                comments = None
            if comments is not None:
                for el in comments.iter(f"{_W}comment"):
                    text = _text(el)
                    if text:
                        author, date = _meta(el)
                        n, final = refs.get(el.get(f"{_W}id") or "", (0, ""))
                        out.append(Change("comment", author, date, text, n, final))
    except Exception as e:
        log.warning("tracked-change extraction failed for %s: %s", path, e)
        return []
    return out


def render_changes(changes: list[Change]) -> str:
    """One self-contained sentence per change, as its own paragraph."""
    lines = []
    for c in changes:
        on = f" on {c.date}" if c.date else ""
        if c.kind == "comment":
            lines.append(f"{c.author} commented{on}: “{c.text}”")
        else:
            verb = "inserted" if c.kind == "insertion" else "deleted"
            lines.append(f"{c.author} {verb} “{c.text}”{on}.")
    return "\n\n".join(lines)


def render_item(c: Change) -> str:
    """The text a change is indexed as: its attribution sentence, then the
    paragraph it belongs to, so a citation of the change shows where it sits."""
    sentence = render_changes([c])
    if not c.paragraph_text:
        return sentence
    return f"{sentence}\n\nParagraph {c.paragraph}: {c.paragraph_text}"


def change_key(c: Change) -> str:
    import hashlib

    raw = "\x1f".join([c.kind, c.author, c.date, str(c.paragraph), c.text])
    return hashlib.sha1(raw.encode("utf-8", "replace")).hexdigest()[:10]


def register_changes(conn, rel_path: str, abs_path: Path, *, by: str = "intake") -> int:
    """One item per tracked change, `<docx>#change/<kind>-<key>`, with its own
    catalog row and consent. A change nobody has set follows the manuscript's
    level (consent_by stays `intake`); one a person set keeps theirs. Consent
    is read by the same `allowed_paths` filter as everything else."""
    import time

    from services.archive.items import register_virtual
    from services.catalog.chunk import rechunk_file

    row = conn.execute(
        "SELECT consent, sha256 FROM item WHERE path = ?", (rel_path,)
    ).fetchone()
    level = row[0] if row else "private"
    n = 0
    for c in read_changes(abs_path):
        path = f"{rel_path}#change/{c.kind}-{change_key(c)}"
        text = render_item(c)
        import hashlib

        sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
        r = register_virtual(
            conn,
            path,
            sha,
            "tracked-change",
            people=[{"name": c.author, "role": "author"}],
            consent=level,
            by=by,
        )
        if r is None:
            continue
        if not r["new"]:
            with conn:
                conn.execute(
                    "UPDATE item SET consent = ? WHERE path = ? AND consent_by = 'intake'",
                    (level, path),
                )
        now = time.time()
        f = conn.execute("SELECT id FROM files WHERE rel_path = ?", (path,)).fetchone()
        with conn:
            if f:
                conn.execute(
                    "UPDATE files SET extracted_text = ?, sha256 = ? WHERE id = ?",
                    (text, sha, f[0]),
                )
                fid = f[0]
            else:
                fid = conn.execute(
                    "INSERT INTO files (rel_path, mount, abs_path, sha256, size_bytes, mtime, "
                    "ext, extracted_text, summary, topics, cataloged_at, created_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        path,
                        "library",
                        str(abs_path),
                        sha,
                        len(text),
                        now,
                        ".docx",
                        text,
                        render_changes([c])[:200],
                        "[]",
                        now,
                        now,
                    ),
                ).lastrowid
        rechunk_file(conn, fid, text, ".docx")
        n += 1
    return n
