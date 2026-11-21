"""Migration 0017 — file_chunks + its FTS mirror.

Same shape as test_migration_0014_commons_channels.py: assert the schema
after init, assert idempotency, and — because this table carries an
external-content FTS5 index whose triggers are easy to get subtly wrong —
assert the index actually stays in sync through insert/update/delete.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path


def _make_conn(tmp_path: Path) -> sqlite3.Connection:
    from services.db import init_schema

    conn = sqlite3.connect(str(tmp_path / "test.db"), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    init_schema(conn)
    return conn


def _objects(conn, kind: str) -> set[str]:
    return {
        r["name"]
        for r in conn.execute("SELECT name FROM sqlite_master WHERE type=?", (kind,))
    }


def _insert_file(conn, rel_path="notes/a.md") -> int:
    cur = conn.execute(
        "INSERT INTO files "
        "(rel_path, mount, abs_path, sha256, size_bytes, mtime, ext) "
        "VALUES (?, 'notes', ?, 'abc', 10, 1.0, '.md')",
        (rel_path, f"/{rel_path}"),
    )
    conn.commit()
    return cur.lastrowid


def _insert_chunk(conn, file_id, ordinal, text, heading=None) -> int:
    cur = conn.execute(
        "INSERT INTO file_chunks "
        "(file_id, ordinal, text, char_start, char_end, heading, chunk_hash) "
        "VALUES (?, ?, ?, 0, ?, ?, ?)",
        (file_id, ordinal, text, len(text), heading, f"hash-{ordinal}-{len(text)}"),
    )
    conn.commit()
    return cur.lastrowid


# ── Schema ───────────────────────────────────────────────────────────────────


def test_file_chunks_table_exists(tmp_path):
    conn = _make_conn(tmp_path)
    try:
        assert "file_chunks" in _objects(conn, "table")
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(file_chunks)")}
        assert cols == {
            "id",
            "file_id",
            "ordinal",
            "text",
            "char_start",
            "char_end",
            "heading",
            "chunk_hash",
            "embedded_at",
        }
    finally:
        conn.close()


def test_fts_table_and_triggers_exist(tmp_path):
    conn = _make_conn(tmp_path)
    try:
        assert "file_chunks_fts" in _objects(conn, "table")
        triggers = _objects(conn, "trigger")
        assert {
            "file_chunks_fts_insert",
            "file_chunks_fts_update",
            "file_chunks_fts_delete",
        } <= triggers
    finally:
        conn.close()


def test_indexes_exist(tmp_path):
    conn = _make_conn(tmp_path)
    try:
        idx = _objects(conn, "index")
        assert "idx_file_chunks_file" in idx
        assert "idx_file_chunks_pending" in idx
    finally:
        conn.close()


def test_unique_file_id_ordinal(tmp_path):
    conn = _make_conn(tmp_path)
    try:
        fid = _insert_file(conn)
        _insert_chunk(conn, fid, 0, "first")
        try:
            _insert_chunk(conn, fid, 0, "duplicate ordinal")
        except sqlite3.IntegrityError:
            pass
        else:
            raise AssertionError("expected UNIQUE(file_id, ordinal) to reject")
    finally:
        conn.close()


def test_init_schema_is_idempotent(tmp_path):
    """Second init on the same DB must not raise or duplicate objects."""
    from services.db import init_schema

    conn = _make_conn(tmp_path)
    try:
        before = _objects(conn, "table") | _objects(conn, "trigger")
        init_schema(conn)
        after = _objects(conn, "table") | _objects(conn, "trigger")
        assert before == after
    finally:
        conn.close()


# ── FTS stays in sync ────────────────────────────────────────────────────────


def _fts_match(conn, term) -> set[int]:
    return {
        r["rowid"]
        for r in conn.execute(
            "SELECT rowid FROM file_chunks_fts WHERE file_chunks_fts MATCH ?", (term,)
        )
    }


def test_fts_indexes_on_insert(tmp_path):
    conn = _make_conn(tmp_path)
    try:
        fid = _insert_file(conn)
        cid = _insert_chunk(conn, fid, 0, "comfrey poultice for bruising")
        assert _fts_match(conn, "poultice") == {cid}
    finally:
        conn.close()


def test_fts_follows_an_update(tmp_path):
    conn = _make_conn(tmp_path)
    try:
        fid = _insert_file(conn)
        cid = _insert_chunk(conn, fid, 0, "comfrey poultice for bruising")
        conn.execute(
            "UPDATE file_chunks SET text = ? WHERE id = ?",
            ("mullein infusion for coughs", cid),
        )
        conn.commit()
        assert _fts_match(conn, "poultice") == set(), "stale term still indexed"
        assert _fts_match(conn, "mullein") == {cid}
    finally:
        conn.close()


def test_fts_follows_a_delete(tmp_path):
    conn = _make_conn(tmp_path)
    try:
        fid = _insert_file(conn)
        cid = _insert_chunk(conn, fid, 0, "comfrey poultice for bruising")
        conn.execute("DELETE FROM file_chunks WHERE id = ?", (cid,))
        conn.commit()
        assert _fts_match(conn, "poultice") == set()
    finally:
        conn.close()


def test_fts_survives_a_full_file_rechunk(tmp_path):
    """The rechunk path deletes every chunk for a file and reinserts. The FTS
    index must not retain the old passages."""
    conn = _make_conn(tmp_path)
    try:
        fid = _insert_file(conn)
        for i, t in enumerate(["alpha passage", "beta passage", "gamma passage"]):
            _insert_chunk(conn, fid, i, t)
        conn.execute("DELETE FROM file_chunks WHERE file_id = ?", (fid,))
        conn.commit()
        assert _fts_match(conn, "alpha") == set()
        assert _fts_match(conn, "passage") == set()

        new_id = _insert_chunk(conn, fid, 0, "delta passage")
        assert _fts_match(conn, "passage") == {new_id}
    finally:
        conn.close()
