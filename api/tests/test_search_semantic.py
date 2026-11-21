"""Guards for the semantic branch of GET /api/search.

The path existed and was never reachable: the frontend hardcoded
`semantic=false`. Two things about its behaviour explain why nobody turned it
on, and both are what these tests pin.

1. It rendered "~87% semantic match" as the result snippet — a row that tells
   you a file is relevant without telling you why.
2. It PREPENDED semantic hits, so switching it on demoted exact filename
   matches behind fuzzy ones. ⌘K stopped being a file finder.
"""

from __future__ import annotations

import pytest

from routes import search as search_mod


@pytest.fixture()
def stub_vectors(monkeypatch):
    """Three chunk hits across two files, in descending score order."""
    hits = [
        {
            "chunk_id": 11,
            "file_id": 1,
            "path": "notes/grief.md",
            "mount": "notes",
            "ordinal": 3,
            "score": 0.81,
        },
        {
            "chunk_id": 12,
            "file_id": 1,
            "path": "notes/grief.md",
            "mount": "notes",
            "ordinal": 9,
            "score": 0.77,
        },
        {
            "chunk_id": 21,
            "file_id": 2,
            "path": "library/mourning.epub",
            "mount": "library",
            "ordinal": 0,
            "score": 0.62,
        },
    ]
    passages = {
        11: {
            "text": "  The work of mourning is   slow, and it is not linear.  ",
            "heading": "On grief",
            "ordinal": 3,
        },
        12: {
            "text": "A second passage from the same file.",
            "heading": None,
            "ordinal": 9,
        },
        21: {
            "text": "Freud distinguishes mourning from melancholia.",
            "heading": None,
            "ordinal": 0,
        },
    }
    monkeypatch.setattr(
        "services.vector_store.search_chunks", lambda *a, **k: hits, raising=False
    )
    monkeypatch.setattr(
        "services.vector_store.get_client", lambda *a, **k: object(), raising=False
    )
    monkeypatch.setattr(
        "services.embeddings.embed_query", lambda q: [0.1] * 384, raising=False
    )
    monkeypatch.setattr(
        "services.retrieval._hydrate_passages", lambda ids: passages, raising=False
    )
    return hits


def test_a_semantic_row_carries_the_passage_that_matched(stub_vectors):
    """Not a score. The snippet is the reason the row is there."""
    out = search_mod._semantic_search("grief", "all")

    assert out[0]["path"] == "notes/grief.md"
    assert out[0]["text"] == "The work of mourning is slow, and it is not linear."
    assert "%" not in out[0]["text"], "the snippet is passage text, not a score"
    assert out[0]["note"] == "On grief"
    assert out[0]["source"] == "semantic"


def test_one_row_per_file_keeping_the_best_chunk(stub_vectors):
    """Several chunks of one file rank together; they must collapse."""
    out = search_mod._semantic_search("grief", "all")

    assert [r["path"] for r in out] == ["notes/grief.md", "library/mourning.epub"]
    # The higher-scoring chunk (11) is the one kept, not the later one (12).
    assert "not linear" in out[0]["text"]


def test_a_long_passage_is_cut_at_a_word_boundary(monkeypatch, stub_vectors):
    monkeypatch.setattr(
        "services.retrieval._hydrate_passages",
        lambda ids: {11: {"text": "alpha " * 200, "heading": None, "ordinal": 0}},
        raising=False,
    )
    text = search_mod._semantic_search("x", "all")[0]["text"]

    assert len(text) <= search_mod._SNIPPET_CHARS + 1  # + the ellipsis
    assert text.endswith("…")
    assert not text.rstrip("…").endswith(" "), "cut mid-space, not at a word"


def test_a_chunk_with_no_passage_text_is_skipped(monkeypatch, stub_vectors):
    """A row whose only content would be its own score is worse than no row."""
    monkeypatch.setattr(
        "services.retrieval._hydrate_passages", lambda ids: {}, raising=False
    )
    assert search_mod._semantic_search("x", "all") == []


def test_semantic_never_raises_into_the_caller(monkeypatch):
    """It runs on every keystroke. Degrading to lexical is survivable."""

    def boom(*a, **k):
        raise RuntimeError("model not loaded")

    monkeypatch.setattr("services.embeddings.embed_query", boom, raising=False)
    assert search_mod._semantic_search("x", "all") == []


def test_literal_matches_come_first():
    """The ordering guard.

    Semantic hits used to be PREPENDED. Typing an exact filename then put fuzzy
    matches above the file you named, which is not a file finder any more.

    Tested against `merge_semantic` directly rather than through the route:
    ripgrep runs inline there against the real vault, so a route-level test
    would be asserting on whatever happens to be on disk.
    """
    rg = [{"path": "notes/exact.md", "line": 2, "text": "grief"}]
    sem = [
        {"path": "notes/grief.md", "line": 1, "text": "mourning", "source": "semantic"}
    ]

    merged = search_mod.merge_semantic(rg, sem)

    assert merged[0]["path"] == "notes/exact.md", "a literal match was demoted"
    assert merged[0].get("source") != "semantic"
    assert merged[1]["source"] == "semantic", "semantic rows still arrive, after"


def test_a_file_matched_literally_is_not_repeated_semantically():
    rg = [{"path": "notes/grief.md", "line": 2, "text": "grief"}]
    sem = [
        {"path": "notes/grief.md", "line": 1, "text": "mourning", "source": "semantic"}
    ]

    paths = [r["path"] for r in search_mod.merge_semantic(rg, sem)]

    assert paths == ["notes/grief.md"]


def test_the_merged_list_is_capped():
    rg = [{"path": f"notes/{i}.md"} for i in range(40)]
    sem = [{"path": f"notes/s{i}.md", "source": "semantic"} for i in range(40)]

    assert len(search_mod.merge_semantic(rg, sem)) == search_mod._MAX_RESULTS


def test_lexical_results_survive_with_no_semantic_hits():
    """The degraded path: no embeddings yet, or the model is unavailable."""
    rg = [{"path": "notes/a.md"}]
    assert search_mod.merge_semantic(rg, []) == rg
