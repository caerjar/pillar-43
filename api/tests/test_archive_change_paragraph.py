"""D2b: a tracked change is tied to its paragraph and has its own consent.

Invented manuscript: an insertion in paragraph 1, a deletion in paragraph 2,
an editor's comment in paragraph 3. The manuscript is open to the model; the
comment is then closed on its own. Retrieval is lexical-only and returns every
path, so what comes back is exactly what consent lets through.
"""

from __future__ import annotations

import zipfile

import pytest

from tests.archive_fixtures import lexical_only, seed, settings

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
REL = "library/manuscripts/ferry.docx"

DOC = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="{W}"><w:body>
<w:p><w:r><w:t xml:space="preserve">The ferry leaves at </w:t></w:r>
<w:ins w:id="1" w:author="Ines Quillfeather" w:date="2026-06-09T14:30:00Z"><w:r><w:t>dawn</w:t></w:r></w:ins><w:r><w:t>.</w:t></w:r></w:p>
<w:p><w:r><w:t xml:space="preserve">The harbour fee is </w:t></w:r>
<w:del w:id="2" w:author="Wren Tallowfield" w:date="2026-06-02T10:00:00Z"><w:r><w:delText>eight coins</w:delText></w:r></w:del><w:r><w:t xml:space="preserve">paid in full.</w:t></w:r></w:p>
<w:p><w:commentRangeStart w:id="0"/><w:r><w:t>The lighthouse keeper is unnamed.</w:t></w:r><w:commentRangeEnd w:id="0"/><w:r><w:commentReference w:id="0"/></w:r></w:p>
</w:body></w:document>"""

COMMENTS = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:comments xmlns:w="{W}"><w:comment w:id="0" w:author="Marguerite Oyelaran-Voss" w:date="2026-06-10T09:00:00Z"><w:p><w:r><w:t>Keeper is the author's uncle, keep quiet.</w:t></w:r></w:p></w:comment></w:comments>"""


@pytest.fixture
def docx(tmp_path):
    p = tmp_path / "ferry.docx"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("word/document.xml", DOC)
        z.writestr("word/comments.xml", COMMENTS)
    return p


def test_each_change_reports_its_paragraph(docx):
    from services.archive.docx_changes import read_changes

    by = {c.kind: c for c in read_changes(docx)}
    assert by["insertion"].paragraph == 1
    assert by["insertion"].paragraph_text == "The ferry leaves at dawn."
    assert by["deletion"].paragraph == 2
    assert by["deletion"].paragraph_text == "The harbour fee is paid in full."
    assert by["comment"].paragraph == 3
    assert by["comment"].paragraph_text == "The lighthouse keeper is unnamed."


@pytest.fixture
def vault(tmp_path, monkeypatch, docx):
    settings(tmp_path, monkeypatch)
    d = tmp_path / "library" / "manuscripts"
    d.mkdir()
    (d / "ferry.docx").write_bytes(docx.read_bytes())
    seed(REL, "The ferry leaves at dawn. The harbour fee is paid in full.", None)
    from scripts import archive_cli

    archive_cli.intake()
    return d / "ferry.docx"


def _change_paths():
    from services.db import get_db

    conn = get_db()
    try:
        return {
            r[0]: r[1]
            for r in conn.execute(
                "SELECT path, consent FROM item WHERE kind='tracked-change'"
            )
        }
    finally:
        conn.close()


def _cited(monkeypatch):
    from services.retrieval import fetch_materials_counted

    lexical_only(monkeypatch, [REL, *_change_paths()])
    mats, _ = fetch_materials_counted("ferry harbour keeper", audience="model")
    return {m.rel_path: m for m in mats}


def test_changes_are_items_defaulting_to_private_manuscript(vault):
    ch = _change_paths()
    assert len(ch) == 3
    assert set(ch.values()) == {"private"}


def test_private_comment_is_never_returned_the_rest_is(vault, monkeypatch):
    from scripts import archive_cli

    archive_cli.consent(REL, "model", "reviewer")
    archive_cli.intake()  # changes that were never set follow the manuscript
    ch = _change_paths()
    assert set(ch.values()) == {"model"}
    comment = next(p for p in ch if "comment" in p)
    archive_cli.consent(comment, "private", "reviewer")
    archive_cli.intake()  # a re-run does not reopen what was closed

    got = _cited(monkeypatch)
    assert REL in got
    assert comment not in got
    assert not any("uncle" in str(vars(m)) for m in got.values())
    others = [p for p in ch if p != comment]
    assert set(others) <= set(got)
    ins = str(vars(got[next(p for p in others if "insertion" in p)]))
    assert "Ines Quillfeather inserted" in ins
    assert "The ferry leaves at dawn." in ins  # its paragraph travels with it


def test_manuscript_text_does_not_carry_the_history_in_org(docx, monkeypatch):
    from services.catalog.extract import extract_text_for_catalog

    text = extract_text_for_catalog(docx, REL)
    assert "uncle" not in text and "inserted" not in text
