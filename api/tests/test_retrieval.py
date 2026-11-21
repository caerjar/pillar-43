"""Pre-flight retrieval — the shared archive-grounding chokepoint.

Four tests, all isolated from the live Qdrant + ripgrep runtimes via
monkeypatch on the helper internals. We test the orchestration of the
helpers, NOT the helpers themselves (those are upstream surfaces with
their own coverage).
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch


def _make_settings(tmp_path: Path, monkeypatch):
    notes = tmp_path / "notes"
    notes.mkdir()
    library = tmp_path / "library"
    library.mkdir()
    generated = tmp_path / "generated"
    generated.mkdir()
    monkeypatch.setenv("NOTES_PATH", str(notes))
    monkeypatch.setenv("LIBRARY_ROOT", str(library))
    monkeypatch.setenv("GENERATED_PATH", str(generated))
    import config

    monkeypatch.setattr(config.settings, "notes_path", notes)
    monkeypatch.setattr(config.settings, "library_root", library)
    monkeypatch.setattr(config.settings, "generated_path", generated)
    return notes


def _seed_files_table(rows: list[dict]) -> None:
    """INSERT a list of file rows into the catalog. `topics` is passed as
    a Python list and JSON-encoded here so callers stay readable.
    """
    from services.db import get_db

    conn = get_db()
    try:
        for r in rows:
            topics_json = json.dumps(r.get("topics", []))
            conn.execute(
                "INSERT INTO files (rel_path, mount, abs_path, sha256, "
                "                   size_bytes, mtime, ext, extracted_text, "
                "                   summary, topics, cataloged_at, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    r["rel_path"],
                    r["mount"],
                    r.get("abs_path", "/" + r["rel_path"]),
                    r.get("sha256", "deadbeef"),
                    r.get("size_bytes", 100),
                    r.get("mtime", time.time()),
                    r.get("ext", ".md"),
                    r.get("extracted_text"),
                    r.get("summary"),
                    topics_json,
                    r.get("cataloged_at", time.time()),
                    r.get("created_at", time.time()),
                ),
            )
            # Every caller is filtered on item consent; these files are open.
            conn.execute(
                "INSERT OR IGNORE INTO item (path, sha256, kind, consent) "
                "VALUES (?,?,?,?)",
                (r["rel_path"], r.get("sha256", "deadbeef"), "other", "model"),
            )
        conn.commit()
    finally:
        conn.close()


# ── 1. Empty vault → empty list ──────────────────────────────────────────────


def test_empty_vault_returns_empty_list(tmp_path, monkeypatch):
    """No files in the catalog → fetch_materials returns []. Both
    retrieval primitives are stubbed to return [] (so no Qdrant /
    ripgrep dependency).
    """
    _make_settings(tmp_path, monkeypatch)
    from services import retrieval as rr

    with (
        patch.object(rr, "_semantic_hits", return_value=[]),
        patch.object(rr, "_ripgrep_hits", return_value=[]),
    ):
        result = rr.fetch_materials("anything")

    assert result == []


# ── 2. Semantic + lexical merge dedups by rel_path ───────────────────────────


def test_semantic_and_lexical_merge_dedups_by_rel_path(tmp_path, monkeypatch):
    """When the same rel_path surfaces in both semantic and lexical
    results, the semantic hit (with its real score) wins; the lexical
    duplicate is dropped. Order: semantic-first, then lexical-only.
    """
    _make_settings(tmp_path, monkeypatch)

    # Seed three catalog rows so hydration works
    _seed_files_table(
        [
            {
                "rel_path": "notes/herbs/lemon-balm.md",
                "mount": "notes",
                "summary": "Notes on lemon balm preparation.",
                "topics": ["herbalism"],
            },
            {
                "rel_path": "library/herbalism/culpeper.pdf",
                "mount": "library",
                "ext": ".pdf",
                "summary": "Culpeper's Herbal.",
                "topics": ["herbalism", "astrology"],
            },
            {
                "rel_path": "library/papers/grieve.pdf",
                "mount": "library",
                "ext": ".pdf",
                "summary": "Grieve's Modern Herbal.",
                "topics": ["herbalism"],
            },
        ]
    )

    from services import retrieval as rr

    sem = [
        {"path": "notes/herbs/lemon-balm.md", "score": 0.85},
        {"path": "library/herbalism/culpeper.pdf", "score": 0.71},
    ]
    # Both lexical hits — one duplicates the semantic side, one is fresh.
    lex = [
        {"path": "library/herbalism/culpeper.pdf", "score": rr.SCORE_LEXICAL_FALLBACK},
        {"path": "library/papers/grieve.pdf", "score": rr.SCORE_LEXICAL_FALLBACK},
    ]
    with (
        patch.object(rr, "_semantic_hits", return_value=sem),
        patch.object(rr, "_ripgrep_hits", return_value=lex),
    ):
        result = rr.fetch_materials("herbalism")

    paths = [m.rel_path for m in result]
    assert paths == [
        "notes/herbs/lemon-balm.md",  # score 0.85
        "library/herbalism/culpeper.pdf",  # score 0.71 (semantic) — NOT lexical
        "library/papers/grieve.pdf",  # score from SCORE_LEXICAL_FALLBACK
    ]
    # The deduped culpeper kept its semantic score, not the lexical one
    culpeper = next(m for m in result if m.rel_path == "library/herbalism/culpeper.pdf")
    assert culpeper.score == 0.71


def test_lexical_fallback_score_below_semantic_floor(tmp_path, monkeypatch):
    """Audit fix: SCORE_LEXICAL_FALLBACK must sit below Qdrant's
    score_threshold (0.3) so a weak semantic match still outranks pure
    lexical noise. Earlier 0.4 inverted the relationship for semantic
    hits in [0.3, 0.4) — they'd sort below pure-lexical fallback.
    """
    _make_settings(tmp_path, monkeypatch)
    from services import retrieval as rr

    assert rr.SCORE_LEXICAL_FALLBACK < 0.3, (
        f"SCORE_LEXICAL_FALLBACK={rr.SCORE_LEXICAL_FALLBACK} must be below "
        "the Qdrant semantic threshold (0.3) to preserve sort order."
    )

    _seed_files_table(
        [
            {
                "rel_path": "notes/weak-semantic.md",
                "mount": "notes",
                "summary": "Weak but real semantic match.",
            },
            {
                "rel_path": "notes/lexical-only.md",
                "mount": "notes",
                "summary": "Lexical-only hit.",
            },
        ]
    )

    # Semantic hit at 0.32 (just above the threshold) MUST sort above
    # lexical fallback (0.25 post-fix).
    sem = [{"path": "notes/weak-semantic.md", "score": 0.32}]
    lex = [{"path": "notes/lexical-only.md", "score": rr.SCORE_LEXICAL_FALLBACK}]
    with (
        patch.object(rr, "_semantic_hits", return_value=sem),
        patch.object(rr, "_ripgrep_hits", return_value=lex),
    ):
        result = rr.fetch_materials("anything")

    assert [m.rel_path for m in result] == [
        "notes/weak-semantic.md",
        "notes/lexical-only.md",
    ]


# ── 3. Citation field is built correctly for both notes and library ──────────


def test_citation_field_built_correctly_for_each_mount(tmp_path, monkeypatch):
    """[[basename]] for notes (resolves through the wikilinks index);
    [library/path/file.ext] for library; topics list propagates from the
    JSON column; title humanises the basename.
    """
    _make_settings(tmp_path, monkeypatch)

    _seed_files_table(
        [
            {
                "rel_path": "notes/herbs/lemon-balm.md",
                "mount": "notes",
                "summary": "lemon balm notes",
                "topics": ["herbalism", "melissa"],
            },
            {
                "rel_path": "library/herbalism/culpeper-1653.pdf",
                "mount": "library",
                "ext": ".pdf",
                "summary": "Culpeper's herbal",
                "topics": ["herbalism", "astrology"],
            },
        ]
    )

    from services import retrieval as rr

    sem = [
        {"path": "notes/herbs/lemon-balm.md", "score": 0.9},
        {"path": "library/herbalism/culpeper-1653.pdf", "score": 0.7},
    ]
    with (
        patch.object(rr, "_semantic_hits", return_value=sem),
        patch.object(rr, "_ripgrep_hits", return_value=[]),
    ):
        materials = rr.fetch_materials("herbalism")

    by_path = {m.rel_path: m for m in materials}
    note = by_path["notes/herbs/lemon-balm.md"]
    pdf = by_path["library/herbalism/culpeper-1653.pdf"]

    assert note.citation == "[[lemon-balm]]"
    assert note.mount == "notes"
    assert "herbalism" in note.topics
    assert note.title == "Lemon Balm"

    assert pdf.citation == "[library/herbalism/culpeper-1653.pdf]"
    assert pdf.mount == "library"
    assert pdf.topics == ["herbalism", "astrology"]
    # Score preserved on both
    assert note.score == 0.9
    assert pdf.score == 0.7


# ── 4. Semantic path fails → lexical-only fallback, no exception ────────────


def test_qdrant_unreachable_falls_back_to_lexical(tmp_path, monkeypatch):
    """The semantic leg failing must never take retrieval down with it.

    Written when Qdrant was a container that could be down; the vector store
    is now a table in the same SQLite file, so the realistic trigger moved to
    embedding (a missing model, a bad dims change). The invariant is the one
    that mattered then and still does: `_semantic_hits` swallows it and
    `fetch_materials` still returns the lexical hits.
    """
    _make_settings(tmp_path, monkeypatch)

    _seed_files_table(
        [
            {
                "rel_path": "notes/herbs/lemon-balm.md",
                "mount": "notes",
                "summary": "lemon balm notes",
                "topics": ["herbalism"],
            },
        ]
    )

    from services import retrieval as rr

    # Drive _semantic_hits through its real path so the except-clause runs
    def boom(*args, **kwargs):
        raise ConnectionError("embedding unavailable")

    with patch.object(rr, "embed_query", boom, create=True):
        # The actual import is lazy inside _semantic_hits; _semantic_hits's
        # except clause should catch and return []. We also stub ripgrep
        # so the test doesn't depend on rg being installed.
        lex = [
            {"path": "notes/herbs/lemon-balm.md", "score": rr.SCORE_LEXICAL_FALLBACK}
        ]
        with patch.object(rr, "_ripgrep_hits", return_value=lex):
            result = rr.fetch_materials("lemon balm")

    assert len(result) == 1
    assert result[0].rel_path == "notes/herbs/lemon-balm.md"
    assert result[0].score == rr.SCORE_LEXICAL_FALLBACK


# ── Passages: real content, not summaries ────────────────────────────────────
#
# The point of chunking. Before it, fetch_materials returned only catalog
# summaries and the model answered from a table of contents.


def _seed_chunks(rel_path: str, passages: list[tuple[str, str | None]]) -> list[int]:
    """Give a seeded file some chunks. Returns the chunk ids, in order."""
    from services.db import get_db

    conn = get_db()
    try:
        fid = conn.execute(
            "SELECT id FROM files WHERE rel_path = ?", (rel_path,)
        ).fetchone()["id"]
        ids = []
        for i, (text, heading) in enumerate(passages):
            cur = conn.execute(
                "INSERT INTO file_chunks "
                "(file_id, ordinal, text, char_start, char_end, heading, chunk_hash) "
                "VALUES (?, ?, ?, 0, ?, ?, ?)",
                (fid, i, text, len(text), heading, f"h{fid}-{i}"),
            )
            ids.append(cur.lastrowid)
        conn.commit()
        return ids
    finally:
        conn.close()


def test_semantic_hits_carry_passage_text(tmp_path, monkeypatch):
    _make_settings(tmp_path, monkeypatch)
    _seed_files_table(
        [
            {
                "rel_path": "library/herbalism/culpeper.pdf",
                "mount": "library",
                "ext": ".pdf",
                "summary": "Culpeper's Herbal.",
            }
        ]
    )
    cids = _seed_chunks(
        "library/herbalism/culpeper.pdf",
        [
            ("Comfrey is under the dominion of Saturn.", "Comfrey"),
            ("The root boiled makes a poultice for bruises.", "Comfrey > Uses"),
        ],
    )

    from services import retrieval as rr

    sem = [
        {
            "path": "library/herbalism/culpeper.pdf",
            "score": 0.82,
            "chunks": [
                {
                    "chunk_id": cids[1],
                    "score": 0.82,
                    "path": "library/herbalism/culpeper.pdf",
                },
                {
                    "chunk_id": cids[0],
                    "score": 0.55,
                    "path": "library/herbalism/culpeper.pdf",
                },
            ],
        }
    ]
    with (
        patch.object(rr, "_semantic_hits", return_value=sem),
        patch.object(rr, "_ripgrep_hits", return_value=[]),
    ):
        out = rr.fetch_materials("what is comfrey good for")

    assert len(out) == 1
    passages = out[0].passages
    assert len(passages) == 2
    # Best-scoring passage first — this is the one a short renderer shows.
    assert "poultice for bruises" in passages[0].text
    assert passages[0].heading == "Comfrey > Uses"
    # And the actual text is present, not just the summary.
    assert out[0].summary == "Culpeper's Herbal."


def test_no_chunks_falls_back_to_summary_only(tmp_path, monkeypatch):
    """A vault catalogued before chunking has no file_chunks rows. It must
    keep behaving exactly as before — passages empty, summary intact — not
    return a blank context block. This is what makes the change no-flag-day.
    """
    _make_settings(tmp_path, monkeypatch)
    _seed_files_table(
        [
            {
                "rel_path": "notes/herbs/lemon-balm.md",
                "mount": "notes",
                "summary": "Notes on lemon balm preparation.",
            }
        ]
    )

    from services import retrieval as rr

    sem = [{"path": "notes/herbs/lemon-balm.md", "score": 0.9, "chunks": []}]
    with (
        patch.object(rr, "_semantic_hits", return_value=sem),
        patch.object(rr, "_ripgrep_hits", return_value=[]),
    ):
        out = rr.fetch_materials("lemon balm")

    assert len(out) == 1
    assert out[0].passages == []
    assert out[0].summary == "Notes on lemon balm preparation."


def test_lexical_only_still_returns_passages(tmp_path, monkeypatch):
    """Qdrant down. Before chunking this path could only ever inject
    summaries; now the chunk FTS index supplies real text.
    """
    _make_settings(tmp_path, monkeypatch)
    _seed_files_table(
        [
            {
                "rel_path": "notes/herbs/lemon-balm.md",
                "mount": "notes",
                "summary": "Notes on lemon balm.",
            }
        ]
    )
    _seed_chunks(
        "notes/herbs/lemon-balm.md",
        [
            ("Lemon balm is a nervine and a carminative.", "Lemon Balm"),
            ("Harvest before flowering for the best oil.", "Harvest"),
        ],
    )

    from services import retrieval as rr

    # _semantic_hits returns [] exactly as it does when Qdrant is unreachable.
    with (
        patch.object(rr, "_semantic_hits", return_value=[]),
        patch.object(
            rr,
            "_ripgrep_hits",
            return_value=[
                {
                    "path": "notes/herbs/lemon-balm.md",
                    "score": rr.SCORE_LEXICAL_FALLBACK,
                },
            ],
        ),
    ):
        out = rr.fetch_materials("nervine")

    assert len(out) == 1
    assert out[0].passages, "lexical-only mode must still inject real content"
    assert any("nervine" in p.text for p in out[0].passages)


def test_lexical_passages_survive_punctuation_in_the_question(tmp_path, monkeypatch):
    """FTS5 treats -, *, : and quotes as operators. An unescaped user question
    is a syntax error at best and a silent reinterpretation at worst."""
    _make_settings(tmp_path, monkeypatch)
    _seed_files_table(
        [
            {
                "rel_path": "notes/a.md",
                "mount": "notes",
                "summary": "S.",
            }
        ]
    )
    _seed_chunks("notes/a.md", [("Comfrey root poultice.", None)])

    from services import retrieval as rr

    with (
        patch.object(rr, "_semantic_hits", return_value=[]),
        patch.object(
            rr,
            "_ripgrep_hits",
            return_value=[
                {"path": "notes/a.md", "score": rr.SCORE_LEXICAL_FALLBACK},
            ],
        ),
    ):
        out = rr.fetch_materials('what about "comfrey" - root: poultice*?')

    assert len(out) == 1
    assert out[0].passages, "a punctuated question must not break FTS lookup"


def test_passages_capped_per_material(tmp_path, monkeypatch):
    _make_settings(tmp_path, monkeypatch)
    _seed_files_table([{"rel_path": "notes/a.md", "mount": "notes", "summary": "S."}])
    cids = _seed_chunks(
        "notes/a.md", [(f"Passage number {i}.", None) for i in range(10)]
    )

    from services import retrieval as rr

    sem = [
        {
            "path": "notes/a.md",
            "score": 0.9,
            "chunks": [
                {"chunk_id": c, "score": 0.9 - i / 100, "path": "notes/a.md"}
                for i, c in enumerate(cids)
            ],
        }
    ]
    with (
        patch.object(rr, "_semantic_hits", return_value=sem),
        patch.object(rr, "_ripgrep_hits", return_value=[]),
    ):
        out = rr.fetch_materials("passage")

    assert len(out[0].passages) <= rr.MAX_PASSAGES_PER_MATERIAL


def test_global_context_budget_is_enforced(tmp_path, monkeypatch):
    """Not advisory. Real passage text is 10-30x a summary's bytes, and this
    cost lands on every turn."""
    _make_settings(tmp_path, monkeypatch)

    from services import retrieval as rr

    big = "x" * rr.MAX_PASSAGE_CHARS
    rows, sem = [], []
    for i in range(8):
        rel = f"notes/{i}.md"
        rows.append({"rel_path": rel, "mount": "notes", "summary": "S."})
    _seed_files_table(rows)
    for i in range(8):
        rel = f"notes/{i}.md"
        cids = _seed_chunks(rel, [(big, None), (big, None), (big, None)])
        sem.append(
            {
                "path": rel,
                "score": 0.9 - i / 100,
                "chunks": [
                    {"chunk_id": c, "score": 0.9 - i / 100, "path": rel} for c in cids
                ],
            }
        )

    with (
        patch.object(rr, "_semantic_hits", return_value=sem),
        patch.object(rr, "_ripgrep_hits", return_value=[]),
    ):
        out = rr.fetch_materials("x")

    total = sum(len(p.text) for m in out for p in m.passages)
    assert total <= rr.MAX_CONTEXT_CHARS


def test_budget_trims_lowest_scored_first(tmp_path, monkeypatch):
    """The top hit must keep its passages; trimming starts from the bottom."""
    _make_settings(tmp_path, monkeypatch)

    from services import retrieval as rr

    big = "y" * rr.MAX_PASSAGE_CHARS
    rows = [
        {"rel_path": f"notes/{i}.md", "mount": "notes", "summary": "S."}
        for i in range(8)
    ]
    _seed_files_table(rows)
    sem = []
    for i in range(8):
        rel = f"notes/{i}.md"
        cids = _seed_chunks(rel, [(big, None), (big, None), (big, None)])
        sem.append(
            {
                "path": rel,
                "score": 0.99 - i / 10,
                "chunks": [
                    {"chunk_id": c, "score": 0.99 - i / 10, "path": rel} for c in cids
                ],
            }
        )

    with (
        patch.object(rr, "_semantic_hits", return_value=sem),
        patch.object(rr, "_ripgrep_hits", return_value=[]),
    ):
        out = rr.fetch_materials("y")

    assert out[0].passages, "the best-scoring material must keep its passages"
    assert len(out[-1].passages) < len(out[0].passages)


def test_materials_are_never_dropped_by_the_budget(tmp_path, monkeypatch):
    """Trimming drops passages, not materials — a citation with no passage is
    still better than the model not knowing the file exists."""
    _make_settings(tmp_path, monkeypatch)

    from services import retrieval as rr

    big = "z" * rr.MAX_PASSAGE_CHARS
    rows = [
        {"rel_path": f"notes/{i}.md", "mount": "notes", "summary": "S."}
        for i in range(8)
    ]
    _seed_files_table(rows)
    sem = []
    for i in range(8):
        rel = f"notes/{i}.md"
        cids = _seed_chunks(rel, [(big, None), (big, None), (big, None)])
        sem.append(
            {
                "path": rel,
                "score": 0.9,
                "chunks": [{"chunk_id": c, "score": 0.9, "path": rel} for c in cids],
            }
        )

    with (
        patch.object(rr, "_semantic_hits", return_value=sem),
        patch.object(rr, "_ripgrep_hits", return_value=[]),
    ):
        out = rr.fetch_materials("z")

    assert len(out) == 8
    assert all(m.citation for m in out)


def test_score_ordering_invariant_holds(tmp_path, monkeypatch):
    """SCORE_LEXICAL_FALLBACK is deliberately pinned below the store's 0.3
    threshold so ANY semantic hit outranks pure-lexical noise. Pin the
    relationship, not the values — passage-level scores distribute
    differently from document-level ones and the threshold may need to move.
    """
    from services import retrieval as rr
    from services.vector_store import search_chunks  # noqa: F401 — import guard

    import inspect

    sig = inspect.signature(rr._semantic_hits)
    assert "limit" in sig.parameters

    # The invariant itself.
    default_threshold = 0.3
    assert default_threshold > rr.SCORE_LEXICAL_FALLBACK, (
        "a weak semantic hit must still sort above lexical fallback"
    )
