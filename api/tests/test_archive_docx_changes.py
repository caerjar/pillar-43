"""Stage 2d: tracked changes and comments in a .docx are kept and citable.

The fixture is built here from raw WordprocessingML (invented text): one
paragraph with one insertion and one deletion by named authors on given dates,
and one comment. Editorial history is part of the archive, so the catalog text
must say who changed what and when, in sentences that can be quoted.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

DOC = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="{W}"><w:body>
<w:p><w:r><w:t xml:space="preserve">The translator delivers the manuscript by </w:t></w:r>
<w:del w:id="1" w:author="Wren Tallowfield" w:date="2026-06-02T10:00:00Z"><w:r><w:delText xml:space="preserve">1 June</w:delText></w:r></w:del>
<w:ins w:id="2" w:author="Ines Quillfeather" w:date="2026-06-09T14:30:00Z"><w:r><w:t xml:space="preserve">30 November</w:t></w:r></w:ins>
<w:r><w:t xml:space="preserve"> 2026.</w:t></w:r></w:p>
<w:p><w:commentRangeStart w:id="0"/><w:r><w:t>Fees are unchanged.</w:t></w:r><w:commentRangeEnd w:id="0"/><w:r><w:commentReference w:id="0"/></w:r></w:p>
</w:body></w:document>"""

COMMENTS = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:comments xmlns:w="{W}"><w:comment w:id="0" w:author="Marguerite Oyelaran-Voss" w:date="2026-06-10T09:00:00Z"><w:p><w:r><w:t>Check against the contract.</w:t></w:r></w:p></w:comment></w:comments>"""


@pytest.fixture
def docx(tmp_path) -> Path:
    p = tmp_path / "revisions.docx"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("word/document.xml", DOC)
        z.writestr("word/comments.xml", COMMENTS)
    return p


def test_changes_are_read_with_author_date_and_kind(docx):
    from services.archive.docx_changes import read_changes

    ch = read_changes(docx)

    by_kind = {c.kind: c for c in ch}
    assert set(by_kind) == {"insertion", "deletion", "comment"}
    assert (
        by_kind["deletion"].text,
        by_kind["deletion"].author,
        by_kind["deletion"].date,
    ) == (
        "1 June",
        "Wren Tallowfield",
        "2026-06-02",
    )
    assert (
        by_kind["insertion"].text,
        by_kind["insertion"].author,
        by_kind["insertion"].date,
    ) == (
        "30 November",
        "Ines Quillfeather",
        "2026-06-09",
    )
    assert by_kind["comment"].text == "Check against the contract."
    assert by_kind["comment"].author == "Marguerite Oyelaran-Voss"


def test_catalog_text_leaves_the_history_out(docx):
    """Tracked changes and comments are items with their own consent, so a
    private comment cannot leak through the manuscript's own text."""
    from services.catalog.extract import extract_text_for_catalog

    text = extract_text_for_catalog(docx, "library/manuscripts/revisions.docx")

    assert text is not None
    assert "delivers the manuscript by 30 November 2026." in text
    assert "Wren Tallowfield" not in text
    assert "Check against the contract." not in text
