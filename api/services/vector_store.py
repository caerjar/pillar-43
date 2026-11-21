"""Vector store — embeddings in SQLite, searched with numpy.

Replaces `qdrant_store.py` (2026-08-18). That module was written as an
explicit facade for exactly this swap; its docstring said "every function here
has a direct one-statement SQL equivalent", and this is that. **The public
surface is unchanged** — same function names, same arguments, same return
shapes — so `routes/search.py`, `routes/links.py`, `services/retrieval.py`,
`services/connections.py`, `mcp_server.py` and the catalog embed pass carry on
without knowing. Only the name of the module moved, because the old one no
longer had anything to do with Qdrant and a lying filename is worse than a
rename.

**Why brute force rather than an ANN index.** The live vault is 22,624 chunks
at 384 dims — a 34.7MB float32 matrix, and one query is a single dot product
in single-digit milliseconds. sqlite-vec would add a `dlopen`'d `.dylib` to
bundle, ad-hoc sign and keep loadable inside a frozen macOS app, buying an
index nothing here needs yet. It remains a contained future change: this file
plus a migration, with every caller untouched again.

**Cosine is a dot product here, and that is load-bearing.** fastembed returns
L2-normalised vectors (measured norm exactly 1.0, pinned by
`test_embeddings_inprocess.py`) and `upsert_points` stores them as given. If
that ever stopped being true, scores would be quietly wrong rather than
raising — hence the test, and hence `_normalise` on the query side.

The matrix is cached in memory. It is rebuilt on the next search after any
write, **including writes made by another process**: index, intake and withdraw
run as `archive_cli.py`, whose writes never reach this process's `_invalidate`.
So the cache is keyed on `vector_generation` (migration 0030), a counter bumped
by SQLite triggers in the same transaction as every write to `chunk_vectors`;
each search compares it with the generation the cache was built at, one
single-row query. A vault this size loads in well under a second, and the
alternative — a join and a full materialise per query — would pay that cost on
every keystroke of an incremental search.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from collections import defaultdict
from typing import Any

import numpy as np

from services.embeddings import effective_dims

log = logging.getLogger(__name__)

# Over-fetch factor for chunk→file folding. Without it several chunks of one
# long document crowd out every other file. Unchanged from the Qdrant facade;
# `routes/search.py` and the tests both reference it.
CHUNK_SEARCH_FANOUT = 4

# Retained so callers and tests that referenced the Qdrant collection name keep
# resolving. There is no collection any more — the table is `chunk_vectors`.
COLLECTION = "pillar43_chunks"

_VECTOR_DTYPE = np.float32


class VectorStore:
    """Opaque handle.

    Every function here takes one as its first argument purely so the call
    signatures match the Qdrant facade this replaced (removed 2026-08-18) —
    call sites pass it through. It holds no connection: SQLite connections are not shareable
    across threads and the catalog embeds from a thread pool, so each operation
    opens its own via `services.db.get_db`.
    """

    __slots__ = ()


_store = VectorStore()

# ── in-memory matrix cache ───────────────────────────────────────────────────

_cache_lock = threading.Lock()
_cache: dict[str, Any] | None = None


def _invalidate() -> None:
    global _cache
    with _cache_lock:
        _cache = None


def _connect() -> sqlite3.Connection:
    from services.db import get_db

    return get_db()


def _current_generation() -> int:
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT generation FROM vector_generation WHERE id = 1"
        ).fetchone()
    finally:
        conn.close()
    return int(row[0]) if row else 0


def _load_matrix() -> dict[str, Any]:
    """Materialise every stored vector plus the metadata a hit needs.

    The join is `chunk_vectors → file_chunks → files` — the same one
    `catalog/embed.py` already runs to build its batches. `path` is
    `files.rel_path` verbatim: that is exactly what the Qdrant payload stored
    and what `search_chunks` returned, so consumers matching on it are
    unaffected.
    """
    global _cache
    dims = effective_dims()
    # Read the generation BEFORE the rows. A write landing between the two
    # leaves the cache stamped with the older number, so the next search sees a
    # mismatch and reloads; stamping after the load would let that write's
    # number in without its rows.
    generation = _current_generation()
    with _cache_lock:
        if (
            _cache is not None
            and _cache["generation"] == generation
            and _cache["dims"] == dims
        ):
            return _cache

    conn = _connect()
    try:
        rows = conn.execute(
            """SELECT cv.chunk_id AS chunk_id,
                      cv.vector   AS vector,
                      c.file_id   AS file_id,
                      c.ordinal   AS ordinal,
                      f.rel_path  AS path,
                      f.mount     AS mount
               FROM chunk_vectors cv
               JOIN file_chunks c ON c.id = cv.chunk_id
               JOIN files f       ON f.id = c.file_id
               WHERE cv.dims = ?
               ORDER BY cv.chunk_id""",
            (dims,),
        ).fetchall()
    finally:
        conn.close()

    n = len(rows)
    matrix = np.empty((n, dims), dtype=_VECTOR_DTYPE)
    chunk_ids: list[int] = []
    file_ids: list[int] = []
    paths: list[str] = []
    mounts: list[str] = []
    ordinals: list[int] = []

    for i, r in enumerate(rows):
        matrix[i] = np.frombuffer(r["vector"], dtype=_VECTOR_DTYPE)
        chunk_ids.append(r["chunk_id"])
        file_ids.append(r["file_id"])
        paths.append(r["path"])
        mounts.append(r["mount"])
        ordinals.append(r["ordinal"])

    built = {
        "matrix": matrix,
        "chunk_ids": chunk_ids,
        "file_ids": file_ids,
        "paths": paths,
        "mounts": np.array(mounts, dtype=object) if n else np.empty(0, dtype=object),
        "ordinals": ordinals,
        "dims": dims,
        "generation": generation,
    }
    with _cache_lock:
        _cache = built
    log.debug("[vectors] loaded %d vector(s) at %d dims", n, dims)
    return built


def _normalise(vector: list[float]) -> np.ndarray:
    v = np.asarray(vector, dtype=_VECTOR_DTYPE)
    norm = float(np.linalg.norm(v))
    # Stored vectors are already unit-length; normalising the query too makes
    # the dot product a true cosine even if a caller hands us something else.
    return v / norm if norm else v


# ── facade ───────────────────────────────────────────────────────────────────


def get_client() -> VectorStore:
    """Return the store handle."""
    return _store


def ensure_collection(client: VectorStore) -> bool:  # noqa: ARG001
    """Make the store consistent with the current embedding dims.

    Returns True when stored vectors were discarded and a **full re-embed is
    required**. Callers must honour it: `catalog/embed.py` clears
    `file_chunks.embedded_at` and `files.qdrant_synced_at` on True, and the
    original bug this contract exists for was a model change that dropped the
    vectors without clearing those markers, so nothing ever re-embedded.

    An empty store returns False — there is nothing to invalidate, and on a
    fresh install every chunk is already pending.
    """
    dims = effective_dims()
    conn = _connect()
    try:
        row = conn.execute("SELECT dims FROM chunk_vectors LIMIT 1").fetchone()
        if row is None or row["dims"] == dims:
            return False
        log.info(
            "[vectors] embedding dims changed %d → %d — discarding stored vectors",
            row["dims"],
            dims,
        )
        with conn:
            conn.execute("DELETE FROM chunk_vectors")
    finally:
        conn.close()
    _invalidate()
    return True


def reset_collection(client: VectorStore) -> None:  # noqa: ARG001
    """Drop every stored vector. The admin 'rebuild vectors' path.

    Replaces the raw `client.delete_collection(COLLECTION)` that
    `routes/catalog/passes/admin.py` reached around the old facade to call.
    """
    conn = _connect()
    try:
        with conn:
            conn.execute("DELETE FROM chunk_vectors")
    finally:
        conn.close()
    _invalidate()
    log.info("[vectors] store reset")


def upsert_points(client: VectorStore, points: list[dict]) -> None:  # noqa: ARG001
    """Upsert a batch. Each point: {id: int, vector: list[float], payload: dict}.

    `payload` is accepted for signature compatibility and deliberately not
    stored: `file_id`, `rel_path`, `mount` and `ordinal` are already columns of
    `file_chunks`/`files`, and a second copy here would be one to keep in step.
    """
    if not points:
        return
    dims = effective_dims()
    rows = [
        (
            int(p["id"]),
            dims,
            np.asarray(p["vector"], dtype=_VECTOR_DTYPE).tobytes(),
        )
        for p in points
    ]
    conn = _connect()
    try:
        with conn:
            conn.executemany(
                "INSERT OR REPLACE INTO chunk_vectors (chunk_id, dims, vector) "
                "VALUES (?, ?, ?)",
                rows,
            )
    finally:
        conn.close()
    _invalidate()


def search_chunks(
    client: VectorStore,  # noqa: ARG001
    vector: list[float],
    mount_filter: list[str] | None,
    limit: int = 60,
    score_threshold: float = 0.3,
    path_allow: set[str] | None = None,
) -> list[dict]:
    """Chunk-level nearest neighbours.

    `path_allow`, when given, restricts the search to those files BEFORE the
    top-`limit` cut, so files a caller may not use never take a slot.

    Returns [{chunk_id, file_id, path, mount, ordinal, score}] — the shape
    retrieval needs to hydrate passage text and group by file. Unchanged from
    the Qdrant facade.
    """
    data = _load_matrix()
    matrix = data["matrix"]
    if matrix.shape[0] == 0:
        return []

    q = _normalise(vector)
    if q.shape[0] != matrix.shape[1]:
        # A query embedded at different width than the store: no meaningful
        # comparison exists. Warn rather than raise — semantic search degrading
        # to lexical is survivable, a 500 on every search is not.
        log.warning(
            "[vectors] query dims %d != stored dims %d — skipping semantic search",
            q.shape[0],
            matrix.shape[1],
        )
        return []

    scores = matrix @ q  # cosine: both sides unit-length

    mask = scores >= score_threshold
    if mount_filter:
        mask &= np.isin(data["mounts"], np.array(mount_filter, dtype=object))
    if path_allow is not None:
        mask &= np.fromiter(
            (p in path_allow for p in data["paths"]), dtype=bool, count=len(mask)
        )

    idx = np.flatnonzero(mask)
    if idx.size == 0:
        return []
    # argsort only the survivors, then take the top `limit`.
    order = idx[np.argsort(-scores[idx], kind="stable")][:limit]

    return [
        {
            "chunk_id": data["chunk_ids"][i],
            "file_id": data["file_ids"][i],
            "path": data["paths"][i],
            "mount": str(data["mounts"][i]),
            "ordinal": data["ordinals"][i],
            "score": float(scores[i]),
        }
        for i in order
    ]


def search(
    client: VectorStore,
    vector: list[float],
    mount_filter: list[str] | None,
    limit: int = 15,
    score_threshold: float = 0.3,
) -> list[dict]:
    """Nearest-neighbour FILES. Returns [{path, score}].

    Over-fetches chunks and folds them back to files by max score — without
    the fan-out, several chunks of one long document would crowd out every
    other file. Byte-for-byte the same logic as the Qdrant facade.
    """
    hits = search_chunks(
        client,
        vector,
        mount_filter,
        limit=limit * CHUNK_SEARCH_FANOUT,
        score_threshold=score_threshold,
    )
    best: dict[str, float] = {}
    for h in hits:
        path = h["path"]
        if h["score"] > best.get(path, float("-inf")):
            best[path] = h["score"]
    ranked = sorted(best.items(), key=lambda kv: kv[1], reverse=True)
    return [{"path": p, "score": s} for p, s in ranked[:limit]]


def delete_points(client: VectorStore, point_ids: list[int]) -> None:  # noqa: ARG001
    """Delete specific chunk vectors."""
    if not point_ids:
        return
    conn = _connect()
    try:
        with conn:
            conn.executemany(
                "DELETE FROM chunk_vectors WHERE chunk_id = ?",
                [(int(i),) for i in point_ids],
            )
    finally:
        conn.close()
    _invalidate()


def delete_point(client: VectorStore, point_id: int) -> None:
    """Single delete. Retained as a shim — with chunking, deleting by *file* is
    almost always what's meant; use `delete_by_file`."""
    delete_points(client, [point_id])


def delete_by_file(client: VectorStore, file_id: int) -> None:  # noqa: ARG001
    """Delete every chunk vector belonging to one file.

    The rechunk path needs this: a file whose content changed sheds all its old
    passages before the new ones are embedded, or stale text stays retrievable
    forever. Note this is an explicit delete rather than a cascade —
    `PRAGMA foreign_keys` is off on this connection, so the declared
    `ON DELETE CASCADE` never fires (see migration 0021).
    """
    conn = _connect()
    try:
        with conn:
            conn.execute(
                "DELETE FROM chunk_vectors WHERE chunk_id IN "
                "(SELECT id FROM file_chunks WHERE file_id = ?)",
                (int(file_id),),
            )
    finally:
        conn.close()
    _invalidate()


def retrieve_vectors(
    client: VectorStore,  # noqa: ARG001
    point_ids: list[int],
) -> dict[int, list[float]]:
    """Fetch stored vectors for specific chunks. Returns {chunk_id: vector}."""
    if not point_ids:
        return {}
    ids = [int(i) for i in point_ids]
    placeholders = ",".join("?" * len(ids))
    conn = _connect()
    try:
        rows = conn.execute(
            f"SELECT chunk_id, vector FROM chunk_vectors "
            f"WHERE chunk_id IN ({placeholders})",
            ids,
        ).fetchall()
    finally:
        conn.close()
    return {
        r["chunk_id"]: np.frombuffer(r["vector"], dtype=_VECTOR_DTYPE).tolist()
        for r in rows
    }


def file_centroids(
    client: VectorStore,  # noqa: ARG001
    file_ids: list[int],
    *,
    batch: int = 256,
) -> dict[int, list[float]]:
    """Mean-of-chunks vector per file, L2-normalised. Returns {file_id: vector}.

    The connections features want "what does this document look like as a
    whole", which is an aggregate rather than a stored point. Normalising keeps
    cosine comparisons meaningful against individual chunk vectors.

    Files with no embedded chunks are simply absent from the result.
    """
    if not file_ids:
        return {}

    sums: dict[int, np.ndarray] = {}
    counts: dict[int, int] = defaultdict(int)

    conn = _connect()
    try:
        for i in range(0, len(file_ids), batch):
            window = [int(f) for f in file_ids[i : i + batch]]
            placeholders = ",".join("?" * len(window))
            rows = conn.execute(
                f"""SELECT c.file_id AS file_id, cv.vector AS vector
                    FROM chunk_vectors cv
                    JOIN file_chunks c ON c.id = cv.chunk_id
                    WHERE c.file_id IN ({placeholders})""",
                window,
            ).fetchall()
            for r in rows:
                vec = np.frombuffer(r["vector"], dtype=_VECTOR_DTYPE)
                fid = r["file_id"]
                if fid in sums:
                    sums[fid] = sums[fid] + vec
                else:
                    sums[fid] = vec.astype(_VECTOR_DTYPE).copy()
                counts[fid] += 1
    finally:
        conn.close()

    out: dict[int, list[float]] = {}
    for fid, total in sums.items():
        mean = total / counts[fid]
        norm = float(np.linalg.norm(mean))
        if norm:
            mean = mean / norm
        out[fid] = mean.tolist()
    return out
