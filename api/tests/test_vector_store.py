"""The SQLite vector store — chunk→file contract and the search maths.

Replaces `test_qdrant_store.py`. That file mocked a Qdrant client object and
asserted on how the facade drove it; with vectors in SQLite there is no client
to mock, so these go through real rows in a real table. The *contract* under
test is unchanged and deliberately so — `search` still folds chunks to files by
max score, still over-fetches by `CHUNK_SEARCH_FANOUT`, and still returns
`{path, score}` where `path` is `files.rel_path` verbatim.

Two things here are not just plumbing:

  - **cosine == dot product** only because stored vectors are unit-length.
    `test_scores_are_cosine` pins the actual number, so a change that dropped
    normalisation would fail loudly instead of quietly returning wrong scores.
  - **the cache must invalidate on writes.** It exists so a search does not
    re-materialise the whole matrix per keystroke; if it went stale, freshly
    embedded chunks would be invisible until the process restarted — which
    presents as "indexing did nothing" long after indexing worked.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from services import vector_store as vs
from services.db import get_db


@pytest.fixture(autouse=True)
def _fresh_store():
    vs._invalidate()
    conn = get_db()
    try:
        with conn:
            conn.execute("DELETE FROM chunk_vectors")
            conn.execute("DELETE FROM file_chunks")
            conn.execute("DELETE FROM files")
    finally:
        conn.close()
    yield
    vs._invalidate()


@pytest.fixture
def client():
    return vs.get_client()


def _seed(rows, *, invalidate=True):
    """rows: [(chunk_id, file_id, rel_path, mount, ordinal, vector)]"""
    conn = get_db()
    try:
        with conn:
            seen_files = {}
            for cid, fid, path, mount, ordinal, vec in rows:
                if fid not in seen_files:
                    conn.execute(
                        "INSERT OR REPLACE INTO files "
                        "(id, rel_path, mount, abs_path, sha256, size_bytes, mtime, ext) "
                        "VALUES (?,?,?,?,'',0,0,'.md')",
                        (fid, path, mount, f"/{path}"),
                    )
                    seen_files[fid] = path
                conn.execute(
                    "INSERT OR REPLACE INTO file_chunks "
                    "(id, file_id, ordinal, text, char_start, char_end, chunk_hash) "
                    "VALUES (?,?,?,?,0,0,?)",
                    (cid, fid, ordinal, f"chunk {cid}", f"h{cid}"),
                )
                conn.execute(
                    "INSERT OR REPLACE INTO chunk_vectors (chunk_id, dims, vector) "
                    "VALUES (?,?,?)",
                    (cid, len(vec), np.asarray(vec, dtype=np.float32).tobytes()),
                )
    finally:
        conn.close()
    if invalidate:
        vs._invalidate()


def _unit(*parts) -> list[float]:
    v = np.asarray(parts, dtype=np.float32)
    return (v / np.linalg.norm(v)).tolist()


@pytest.fixture
def dims2(monkeypatch):
    """The store keys on effective_dims(); these fixtures use 2-D vectors."""
    monkeypatch.setattr(vs, "effective_dims", lambda: 2)


# ── the chunk→file contract ──────────────────────────────────────────────────


def test_search_folds_chunks_to_files_by_max_score(client, dims2):
    # Two chunks of the same file; the better one must set the file's score.
    # Every vector here is deliberately above the default 0.3 threshold — an
    # orthogonal one would be filtered out and the test would prove nothing
    # about folding.
    _seed(
        [
            (1, 10, "notes/a.md", "notes", 0, _unit(1.0, 0.0)),  # cos 1.0
            (2, 10, "notes/a.md", "notes", 1, _unit(0.6, 0.8)),  # cos 0.6
            (3, 20, "notes/b.md", "notes", 0, _unit(0.8, 0.6)),  # cos 0.8
        ]
    )
    out = vs.search(client, [1.0, 0.0], None, limit=5)
    assert [r["path"] for r in out] == ["notes/a.md", "notes/b.md"]
    # a.md scores 1.0 (its best chunk), not 0.6 (its worst)
    assert out[0]["score"] == pytest.approx(1.0, abs=1e-5)
    assert out[1]["score"] == pytest.approx(0.8, abs=1e-5)
    # one row per file, not per chunk
    assert len(out) == 2


def test_search_chunks_returns_the_retrieval_shape(client, dims2):
    _seed([(7, 30, "library/x.pdf", "library", 3, _unit(1.0, 0.0))])
    hit = vs.search_chunks(client, [1.0, 0.0], None, limit=5)[0]
    assert hit == {
        "chunk_id": 7,
        "file_id": 30,
        "path": "library/x.pdf",
        "mount": "library",
        "ordinal": 3,
        "score": pytest.approx(1.0, abs=1e-5),
    }


def test_path_is_rel_path_verbatim(client, dims2):
    """Not mount-prefixed. The Qdrant payload stored `rel_path` and
    `search_chunks` returned it as `path`; consumers match on that string."""
    _seed([(1, 10, "notes/deep/x.md", "notes", 0, _unit(1.0, 0.0))])
    assert vs.search(client, [1.0, 0.0], None)[0]["path"] == "notes/deep/x.md"


def test_mount_filter_excludes_other_mounts(client, dims2):
    _seed(
        [
            (1, 10, "notes/a.md", "notes", 0, _unit(1.0, 0.0)),
            (2, 20, "library/b.pdf", "library", 0, _unit(1.0, 0.0)),
        ]
    )
    out = vs.search(client, [1.0, 0.0], ["notes"])
    assert [r["path"] for r in out] == ["notes/a.md"]


def test_score_threshold_excludes_weak_hits(client, dims2):
    _seed(
        [
            (1, 10, "notes/near.md", "notes", 0, _unit(1.0, 0.0)),
            (2, 20, "notes/far.md", "notes", 0, _unit(0.0, 1.0)),
        ]
    )
    out = vs.search(client, [1.0, 0.0], None, score_threshold=0.5)
    assert [r["path"] for r in out] == ["notes/near.md"]


def test_search_overfetches_by_the_fanout(client, dims2, monkeypatch):
    seen = {}

    real = vs.search_chunks

    def spy(c, v, mf, limit=60, score_threshold=0.3):
        seen["limit"] = limit
        return real(c, v, mf, limit=limit, score_threshold=score_threshold)

    monkeypatch.setattr(vs, "search_chunks", spy)
    _seed([(1, 10, "notes/a.md", "notes", 0, _unit(1.0, 0.0))])
    vs.search(client, [1.0, 0.0], None, limit=5)
    assert seen["limit"] == 5 * vs.CHUNK_SEARCH_FANOUT


def test_empty_store_returns_nothing(client, dims2):
    assert vs.search(client, [1.0, 0.0], None) == []
    assert vs.search_chunks(client, [1.0, 0.0], None) == []


# ── the maths ────────────────────────────────────────────────────────────────


def test_scores_are_cosine(client, dims2):
    """45° apart → 0.7071. Pinned as a number, because losing normalisation
    would still return plausible-looking scores rather than raising."""
    _seed([(1, 10, "notes/a.md", "notes", 0, _unit(1.0, 1.0))])
    out = vs.search(client, [1.0, 0.0], None, score_threshold=0.0)
    assert out[0]["score"] == pytest.approx(math.sqrt(0.5), abs=1e-5)


def test_query_is_normalised_so_magnitude_does_not_matter(client, dims2):
    _seed([(1, 10, "notes/a.md", "notes", 0, _unit(1.0, 0.0))])
    small = vs.search(client, [1.0, 0.0], None)[0]["score"]
    large = vs.search(client, [1000.0, 0.0], None)[0]["score"]
    assert small == pytest.approx(large, abs=1e-5)


def test_dims_mismatch_degrades_instead_of_raising(client, dims2, caplog):
    """Semantic search going quiet is survivable; a 500 on every search is not."""
    _seed([(1, 10, "notes/a.md", "notes", 0, _unit(1.0, 0.0))])
    with caplog.at_level("WARNING"):
        assert vs.search_chunks(client, [1.0, 0.0, 0.0], None) == []
    assert "query dims" in caplog.text


# ── writes, deletes, cache coherence ─────────────────────────────────────────


def test_upsert_then_search_finds_it(client, dims2):
    _seed([(1, 10, "notes/a.md", "notes", 0, _unit(0.0, 1.0))])
    assert vs.search(client, [1.0, 0.0], None) == []
    vs.upsert_points(client, [{"id": 1, "vector": _unit(1.0, 0.0), "payload": {}}])
    out = vs.search(client, [1.0, 0.0], None)
    assert out and out[0]["score"] == pytest.approx(1.0, abs=1e-5)


def test_delete_by_file_removes_every_chunk(client, dims2):
    _seed(
        [
            (1, 10, "notes/a.md", "notes", 0, _unit(1.0, 0.0)),
            (2, 10, "notes/a.md", "notes", 1, _unit(1.0, 0.0)),
            (3, 20, "notes/b.md", "notes", 0, _unit(1.0, 0.0)),
        ]
    )
    vs.delete_by_file(client, 10)
    assert [r["path"] for r in vs.search(client, [1.0, 0.0], None)] == ["notes/b.md"]


def test_delete_points_invalidates_the_cache(client, dims2):
    _seed([(1, 10, "notes/a.md", "notes", 0, _unit(1.0, 0.0))])
    assert vs.search(client, [1.0, 0.0], None)  # populates the cache
    vs.delete_points(client, [1])
    assert vs.search(client, [1.0, 0.0], None) == []


def test_reset_clears_everything(client, dims2):
    _seed([(1, 10, "notes/a.md", "notes", 0, _unit(1.0, 0.0))])
    vs.reset_collection(client)
    assert vs.search(client, [1.0, 0.0], None) == []


def test_retrieve_vectors_round_trips(client, dims2):
    v = _unit(0.6, 0.8)
    _seed([(5, 10, "notes/a.md", "notes", 0, v)])
    got = vs.retrieve_vectors(client, [5])
    assert set(got) == {5}
    assert got[5] == pytest.approx(v, abs=1e-6)


def test_retrieve_vectors_empty_input(client):
    assert vs.retrieve_vectors(client, []) == {}


# ── ensure_collection: the re-embed contract ─────────────────────────────────


def test_ensure_collection_false_on_empty_store(client, dims2):
    """Nothing stored means nothing to invalidate — returning True here would
    pointlessly clear every embed marker on a fresh install."""
    assert vs.ensure_collection(client) is False


def test_ensure_collection_false_when_dims_match(client, dims2):
    _seed([(1, 10, "notes/a.md", "notes", 0, _unit(1.0, 0.0))])
    assert vs.ensure_collection(client) is False


def test_ensure_collection_discards_on_dims_change(client, dims2, monkeypatch):
    """The regression this contract exists for: a model change dropped the
    vectors without clearing the synced markers, so nothing re-embedded."""
    _seed([(1, 10, "notes/a.md", "notes", 0, _unit(1.0, 0.0))])
    monkeypatch.setattr(vs, "effective_dims", lambda: 768)
    assert vs.ensure_collection(client) is True
    conn = get_db()
    try:
        assert conn.execute("SELECT COUNT(*) c FROM chunk_vectors").fetchone()["c"] == 0
    finally:
        conn.close()


# ── centroids ────────────────────────────────────────────────────────────────


def test_file_centroids_is_normalised_mean_of_chunks(client, dims2):
    _seed(
        [
            (1, 10, "notes/a.md", "notes", 0, _unit(1.0, 0.0)),
            (2, 10, "notes/a.md", "notes", 1, _unit(0.0, 1.0)),
        ]
    )
    c = vs.file_centroids(client, [10])[10]
    # mean of the two axes, normalised → 45°
    assert c == pytest.approx(_unit(1.0, 1.0), abs=1e-5)
    assert math.isclose(sum(x * x for x in c) ** 0.5, 1.0, abs_tol=1e-5)


def test_file_centroids_omits_files_without_vectors(client, dims2):
    _seed([(1, 10, "notes/a.md", "notes", 0, _unit(1.0, 0.0))])
    assert set(vs.file_centroids(client, [10, 99])) == {10}


def test_file_centroids_empty_input(client):
    assert vs.file_centroids(client, []) == {}


# ── writes from another process (the archive CLI) ────────────────────────────
#
# Index, intake and withdraw run as `archive_cli.py` in a second process, so
# the API's in-process `_invalidate()` never fires for them. These tests write
# through a separate connection WITHOUT calling `_invalidate`, which is exactly
# what the CLI does; the store must notice through the generation counter.


def test_vectors_written_by_another_process_are_found(client, dims2):
    _seed([(1, 10, "notes/a.md", "notes", 0, _unit(1.0, 0.0))])
    assert [r["path"] for r in vs.search(client, [1.0, 0.0], None)] == ["notes/a.md"]

    _seed([(2, 20, "notes/b.md", "notes", 0, _unit(1.0, 0.0))], invalidate=False)

    paths = {r["path"] for r in vs.search(client, [1.0, 0.0], None)}
    assert paths == {"notes/a.md", "notes/b.md"}


def test_an_empty_store_is_not_cached_as_final(client, dims2):
    assert vs.search(client, [1.0, 0.0], None) == []
    _seed([(1, 10, "notes/a.md", "notes", 0, _unit(1.0, 0.0))], invalidate=False)
    assert [r["path"] for r in vs.search(client, [1.0, 0.0], None)] == ["notes/a.md"]


def test_vectors_withdrawn_by_another_process_disappear(client, dims2):
    _seed(
        [
            (1, 10, "notes/a.md", "notes", 0, _unit(1.0, 0.0)),
            (2, 20, "notes/b.md", "notes", 0, _unit(1.0, 0.0)),
        ]
    )
    assert len(vs.search(client, [1.0, 0.0], None)) == 2
    conn = get_db()
    try:
        with conn:
            conn.execute("DELETE FROM chunk_vectors WHERE chunk_id = 2")
    finally:
        conn.close()
    assert [r["path"] for r in vs.search(client, [1.0, 0.0], None)] == ["notes/a.md"]


def test_forget_file_removes_the_chunk_from_results(client, dims2):
    from services.catalog.forget import forget_file

    _seed(
        [
            (1, 10, "notes/a.md", "notes", 0, _unit(1.0, 0.0)),
            (2, 20, "notes/b.md", "notes", 0, _unit(1.0, 0.0)),
        ]
    )
    assert len(vs.search_chunks(client, [1.0, 0.0], None)) == 2
    conn = get_db()
    try:
        assert forget_file(conn, "notes/b.md") is True
    finally:
        conn.close()
    assert [h["path"] for h in vs.search_chunks(client, [1.0, 0.0], None)] == [
        "notes/a.md"
    ]
