"""Chunker boundary rules.

`chunk_text` is pure, so this suite can be exhaustive about the rules that
matter for retrieval quality: never split a code fence or a table, prefer
heading boundaries, overlap only within a section, and keep char offsets
honest so the stored text can be dropped later and reconstructed.
"""

from __future__ import annotations

import pytest

from services.catalog.chunking import chunk_text
from services.catalog.constants import (
    CHUNK_MAX_CHARS,
    CHUNK_MIN_CHARS,
    MAX_CHUNKS_PER_FILE,
)


# ── Degenerate input ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("bad", ["", "   ", "\n\n\n", "\t \n"])
def test_empty_input_yields_nothing(bad):
    assert chunk_text(bad, ext=".md") == []


def test_short_file_is_one_chunk():
    chunks = chunk_text("Just a short note about comfrey.", ext=".md")
    assert len(chunks) == 1
    assert chunks[0].text == "Just a short note about comfrey."
    assert chunks[0].ordinal == 0
    assert chunks[0].heading is None


# ── Offsets are load-bearing ─────────────────────────────────────────────────


def test_char_offsets_round_trip_to_source():
    """Every chunk must be reconstructible from the source via its offsets.

    This is what keeps the "drop file_chunks.text and rebuild from
    extracted_text" escape hatch open if the storage cost bites.
    """
    text = (
        "# Comfrey\n\nSymphytum officinale. A perennial herb.\n\n"
        "## Dosage\n\nOne teaspoon of dried root per cup.\n\n"
        "## Cautions\n\nNot for internal use during pregnancy.\n"
    )
    for c in chunk_text(text, ext=".md"):
        assert text[c.char_start : c.char_end].strip() == c.text


def test_ordinals_are_dense_and_ascending():
    text = "\n\n".join(f"Paragraph number {i}. " + "filler " * 60 for i in range(12))
    chunks = chunk_text(text, ext=".md")
    assert [c.ordinal for c in chunks] == list(range(len(chunks)))


# ── Heading awareness ────────────────────────────────────────────────────────


def test_heading_breadcrumb_tracks_nesting():
    text = (
        "# Comfrey\n\nIntro body.\n\n"
        "## Dosage\n\nOne teaspoon.\n\n"
        "### Children\n\nHalf that.\n\n"
        "## Cautions\n\nAvoid in pregnancy.\n"
    )
    headings = [c.heading for c in chunk_text(text, ext=".md")]
    assert "Comfrey" in headings
    assert "Comfrey > Dosage" in headings
    assert "Comfrey > Dosage > Children" in headings
    # A sibling H2 must pop the H3 back off the stack.
    assert "Comfrey > Cautions" in headings
    assert "Comfrey > Dosage > Cautions" not in headings


def test_content_before_first_heading_has_no_breadcrumb():
    text = "Preamble text with no heading.\n\n# Later\n\nBody.\n"
    chunks = chunk_text(text, ext=".md")
    assert chunks[0].heading is None


def test_embed_text_prepends_heading_but_stored_text_does_not():
    text = "# Comfrey\n\n## Dosage\n\nOne teaspoon of dried root.\n"
    dosage = [
        c for c in chunk_text(text, ext=".md") if c.heading and "Dosage" in c.heading
    ]
    assert dosage, "expected a chunk under the Dosage heading"
    c = dosage[0]
    assert c.text.startswith("One teaspoon")
    assert c.embed_text.startswith("Comfrey > Dosage")
    assert "One teaspoon" in c.embed_text


# ── Atomic blocks: the rules that protect passage quality ────────────────────


def test_code_fence_is_never_split():
    code = "\n".join(f"    line_{i} = compute({i})" for i in range(120))
    text = f"# Notes\n\nBefore.\n\n```python\n{code}\n```\n\nAfter.\n"
    chunks = chunk_text(text, ext=".md")
    # Whichever chunk holds the fence must hold both delimiters.
    holders = [c for c in chunks if "```python" in c.text]
    assert len(holders) == 1
    assert holders[0].text.count("```") == 2
    # And no other chunk may contain a stray delimiter.
    assert sum(c.text.count("```") for c in chunks) == 2


def test_unterminated_code_fence_does_not_hang_or_leak():
    text = "# Notes\n\n```python\nx = 1\ny = 2\n"  # never closed
    chunks = chunk_text(text, ext=".md")
    assert chunks
    assert "x = 1" in "".join(c.text for c in chunks)


def test_table_is_never_split():
    rows = "\n".join(f"| herb {i} | dose {i} | note {i} |" for i in range(80))
    text = f"# Table\n\n| Herb | Dose | Note |\n|---|---|---|\n{rows}\n\nAfter the table.\n"
    chunks = chunk_text(text, ext=".md")
    holders = [c for c in chunks if "| Herb | Dose | Note |" in c.text]
    assert len(holders) == 1
    # All rows land in that one chunk.
    assert holders[0].text.count("| herb ") == 80


# ── Packing, overlap, runts ──────────────────────────────────────────────────


def test_long_document_splits_into_multiple_chunks():
    text = "\n\n".join(f"Paragraph {i}. " + "word " * 80 for i in range(20))
    chunks = chunk_text(text, ext=".md")
    assert len(chunks) > 1


def test_no_trailing_runt_below_minimum():
    text = "\n\n".join(f"Para {i}. " + "word " * 70 for i in range(9)) + "\n\nTiny."
    chunks = chunk_text(text, ext=".md")
    assert len(chunks) > 1, "test needs a multi-chunk document to be meaningful"
    assert len(chunks[-1].text) >= CHUNK_MIN_CHARS


def test_overlap_does_not_cross_a_heading_boundary():
    """Each section's first chunk must start with that section's own text.

    Without this, every section opens with the tail of the previous one and
    retrieval gets systematically muddier at every heading.
    """
    a = "Alpha content. " + "alpha " * 200
    b = "Bravo content. " + "bravo " * 200
    text = f"# A\n\n{a}\n\n# B\n\n{b}\n"
    chunks = chunk_text(text, ext=".md")
    first_b = next(c for c in chunks if c.heading == "B")
    assert "alpha" not in first_b.text
    assert first_b.text.startswith("Bravo content.")


def test_chunks_do_not_begin_mid_word():
    text = "\n\n".join(
        f"Paragraph {i} discussing herbal preparations. " + "word " * 90
        for i in range(15)
    )
    for c in chunk_text(text, ext=".md"):
        assert c.text == c.text.strip()
        assert not c.text[0].isspace()


# ── Non-markdown path ────────────────────────────────────────────────────────


def test_non_markdown_ignores_heading_syntax():
    """Extracted PDF text may contain '#' that isn't a heading."""
    text = "Item #1 is important.\n\nItem #2 follows.\n"
    chunks = chunk_text(text, ext=".pdf")
    assert all(c.heading is None for c in chunks)


def test_pdf_style_wall_of_text_still_chunks():
    """PDF extractions often have no blank lines at all — the sentence
    fallback has to carry the whole load."""
    text = " ".join(
        f"This is sentence number {i} in a long extracted document." for i in range(400)
    )
    chunks = chunk_text(text, ext=".pdf")
    assert len(chunks) > 1
    for c in chunks:
        assert len(c.text) <= CHUNK_MAX_CHARS * 1.5


def test_text_with_no_punctuation_or_whitespace_hard_splits():
    """Worst case: a single token longer than the cap. Must terminate and
    must not lose content."""
    text = "x" * (CHUNK_MAX_CHARS * 5)
    chunks = chunk_text(text, ext=".txt")
    assert len(chunks) > 1
    assert all(len(c.text) <= CHUNK_MAX_CHARS for c in chunks)


# ── Bounds ───────────────────────────────────────────────────────────────────


def test_chunk_cap_is_enforced():
    text = "\n\n".join(f"Para {i}. " + "word " * 100 for i in range(4000))
    chunks = chunk_text(text, ext=".md")
    assert len(chunks) <= MAX_CHUNKS_PER_FILE


# ── Skip-rerun key ───────────────────────────────────────────────────────────


def test_chunk_hash_is_content_identity():
    a = chunk_text("# H\n\nStable body text here.\n", ext=".md")[0]
    b = chunk_text("# Different\n\nStable body text here.\n", ext=".md")[0]
    # Same passage text under a different heading → same hash. The hash keys
    # re-embedding of the passage, and the heading rides along separately.
    assert a.text == b.text
    assert a.chunk_hash == b.chunk_hash


def test_chunk_hash_changes_with_content():
    a = chunk_text("Body one.", ext=".md")[0]
    b = chunk_text("Body two.", ext=".md")[0]
    assert a.chunk_hash != b.chunk_hash


def test_chunking_is_deterministic():
    text = "# A\n\n" + "\n\n".join(f"Para {i}. " + "word " * 70 for i in range(12))
    first = chunk_text(text, ext=".md")
    second = chunk_text(text, ext=".md")
    assert [(c.text, c.heading, c.char_start) for c in first] == [
        (c.text, c.heading, c.char_start) for c in second
    ]
