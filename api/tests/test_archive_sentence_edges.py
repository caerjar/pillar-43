"""Passages are whole sentences (A3): a retrieved chunk is extended to the
sentence edges around it, using the item's text and the chunk's offsets.

The text is verbatim from the catalog's extraction of the synthetic contract
`Pellerin-Okafor Weather for Ferrymen CONTRACT signed.pdf`, where the chunker
cut between "6." and "Reversion" (clause number in one chunk, its heading in
the next).
"""

from __future__ import annotations

from types import SimpleNamespace

from services.archive.ask import number_passages
from services.archive.sentence_edges import extend_to_sentence_edges

FULL = (
    "4. Royalties\nThe Publisher shall pay royalties of 8 percent of net receipts on all\nsales. Royalties are accounted for twice a year.\n"
    "5. Subsidiary Rights\nAnthology and audio rights are held by the Publisher, with proceeds divided equally\n"
    "between the Author and the Publisher.\n6. Reversion\n"
    "If the Work is out of print in all formats granted in Clause 2, the Grantor may\n"
    "request in writing that the rights revert. If, within twelve (12) months after the\n"
    "Publisher's receipt of that written request, the Publisher has not made the Work\n"
    "available again in at least one format granted in Clause 2, all rights revert.\n"
)


def _span(start_marker: str, end_marker: str) -> tuple[int, int, str]:
    s = FULL.index(start_marker)
    e = FULL.index(end_marker) + len(end_marker)
    return s, e, FULL[s:e].strip()


def test_a_chunk_that_ends_on_a_clause_number_gives_it_up():
    s, e, text = _span("Anthology", "Publisher.\n6.")
    assert text.endswith("6.")
    out = extend_to_sentence_edges(FULL, s, e, text)
    assert out.endswith("between the Author and the Publisher.")


def test_a_chunk_that_starts_at_a_heading_takes_its_clause_number_back():
    s = FULL.index("Reversion")
    e = FULL.index("revert.") + len("revert.")
    out = extend_to_sentence_edges(FULL, s, e, FULL[s:e])
    assert out.startswith("6. Reversion")


def test_a_chunk_cut_mid_sentence_is_extended_both_ways():
    # starts at "sales." (the tail of "...royalties of 8 percent ... on all
    # sales.") and stops inside the second sentence of clause 6
    s = FULL.index("sales.")
    e = FULL.index("within twelve (12) months")
    out = extend_to_sentence_edges(FULL, s, e, FULL[s:e].strip())
    assert out.startswith("The Publisher shall pay royalties")
    assert out.endswith("all rights revert.")


def test_a_chunk_already_on_sentence_edges_is_unchanged():
    s = FULL.index("Anthology")
    e = FULL.index("Publisher.\n6.") + len("Publisher.")
    text = FULL[s:e]
    assert extend_to_sentence_edges(FULL, s, e, text) == text


PAGES = (
    "8. Permissions\nThe Publisher may grant permission to reprint single poems or extracts of up to\n"
    "fifty lines from the Work in anthologies.\n"
    "Lantern Wharf Editions - Agreement LWE-A-2016-02 - page 1 of 2\n\n"
    "[Page 2]\n9. Credit\nThe Publisher shall print the Author's name on every edition of the Work.\n"
)


def test_a_page_footer_and_marker_are_block_edges():
    # The footer is a long line with no full stop; the chunk must not run on
    # through the blank line into the next page.
    e = PAGES.index("page 1 of 2") + len("page 1 of 2")
    out = extend_to_sentence_edges(PAGES, 0, e, PAGES[:e])
    assert out.endswith("page 1 of 2") and "[Page 2]" not in out
    s = PAGES.index("[Page 2]")
    out = extend_to_sentence_edges(PAGES, s, len(PAGES), PAGES[s:].strip())
    assert out.startswith("[Page 2]")


def test_offsets_that_do_not_match_the_chunk_text_leave_it_alone():
    assert extend_to_sentence_edges(FULL, 3, 40, "something else entirely") == (
        "something else entirely"
    )


def test_passages_are_numbered_from_the_extended_text():
    chunk = SimpleNamespace(
        text="Reversion\nIf the Work is out of print.",
        score=1.0,
        chunk_id=7,
        ordinal=1,
        heading=None,
    )
    m = SimpleNamespace(rel_path="library/c.pdf", title="C", passages=[chunk])
    out = number_passages(
        [m], {}, None, {7: "6. Reversion\nIf the Work is out of print."}
    )
    assert out[0].sentences[0] == "6. Reversion"
