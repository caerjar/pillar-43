"""Pass 1.5 — chunk persistence and the skip-rerun contract.

The invariant that matters: re-running the catalog on unchanged content must
not re-embed anything. `embedded_at` surviving a rerun is what makes a
nightly catch-up cheap, and losing it would re-embed the whole vault every
night.
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


def _insert_file(conn, rel_path: str, text: str, ext: str = ".md") -> int:
    cur = conn.execute(
        "INSERT INTO files "
        "(rel_path, mount, abs_path, sha256, size_bytes, mtime, ext, extracted_text) "
        "VALUES (?, 'notes', ?, 'sha', ?, 1.0, ?, ?)",
        (rel_path, f"/{rel_path}", len(text), ext, text),
    )
    conn.commit()
    return cur.lastrowid


def _chunks(conn, file_id):
    return conn.execute(
        "SELECT * FROM file_chunks WHERE file_id = ? ORDER BY ordinal", (file_id,)
    ).fetchall()


_LONG = "\n\n".join(
    f"Paragraph {i} about herbal preparation. " + "word " * 60 for i in range(12)
)


# ── rechunk_file ─────────────────────────────────────────────────────────────


def test_rechunk_writes_chunks(tmp_path):
    from services.catalog.chunk import rechunk_file

    conn = _make_conn(tmp_path)
    try:
        fid = _insert_file(conn, "notes/a.md", _LONG)
        n = rechunk_file(conn, fid, _LONG, ".md")
        rows = _chunks(conn, fid)
        assert n == len(rows) > 1
        assert [r["ordinal"] for r in rows] == list(range(len(rows)))
        assert all(r["embedded_at"] is None for r in rows)
    finally:
        conn.close()


def test_rerun_on_identical_content_preserves_embedded_at(tmp_path):
    """THE skip-rerun invariant. If this breaks, every catalog run re-embeds
    the entire vault."""
    from services.catalog.chunk import rechunk_file

    conn = _make_conn(tmp_path)
    try:
        fid = _insert_file(conn, "notes/a.md", _LONG)
        rechunk_file(conn, fid, _LONG, ".md")
        with conn:
            conn.execute(
                "UPDATE file_chunks SET embedded_at = 123.0 WHERE file_id = ?", (fid,)
            )
        before = [
            (r["id"], r["chunk_hash"], r["embedded_at"]) for r in _chunks(conn, fid)
        ]

        rechunk_file(conn, fid, _LONG, ".md")

        after = [
            (r["id"], r["chunk_hash"], r["embedded_at"]) for r in _chunks(conn, fid)
        ]
        assert after == before, "identical content must be a no-op"
        assert all(r["embedded_at"] == 123.0 for r in _chunks(conn, fid))
    finally:
        conn.close()


def test_changed_content_replaces_chunks_and_marks_pending(tmp_path):
    from services.catalog.chunk import rechunk_file

    conn = _make_conn(tmp_path)
    try:
        fid = _insert_file(conn, "notes/a.md", _LONG)
        rechunk_file(conn, fid, _LONG, ".md")
        with conn:
            conn.execute(
                "UPDATE file_chunks SET embedded_at = 123.0 WHERE file_id = ?", (fid,)
            )

        changed = _LONG.replace("herbal preparation", "mineral extraction")
        rechunk_file(conn, fid, changed, ".md")

        rows = _chunks(conn, fid)
        assert rows
        assert all(r["embedded_at"] is None for r in rows), (
            "changed content must re-embed"
        )
        assert "mineral extraction" in " ".join(r["text"] for r in rows)
        assert "herbal preparation" not in " ".join(r["text"] for r in rows)
    finally:
        conn.close()


def test_rechunk_leaves_no_orphan_ordinals(tmp_path):
    """Shrinking a file must drop its surplus chunks, not leave them behind."""
    from services.catalog.chunk import rechunk_file

    conn = _make_conn(tmp_path)
    try:
        fid = _insert_file(conn, "notes/a.md", _LONG)
        rechunk_file(conn, fid, _LONG, ".md")
        many = len(_chunks(conn, fid))
        assert many > 1

        rechunk_file(conn, fid, "Now a very short note.", ".md")
        rows = _chunks(conn, fid)
        assert len(rows) == 1
        assert rows[0]["ordinal"] == 0
    finally:
        conn.close()


def test_empty_text_clears_chunks(tmp_path):
    from services.catalog.chunk import rechunk_file

    conn = _make_conn(tmp_path)
    try:
        fid = _insert_file(conn, "notes/a.md", _LONG)
        rechunk_file(conn, fid, _LONG, ".md")
        assert _chunks(conn, fid)

        rechunk_file(conn, fid, "", ".md")
        assert _chunks(conn, fid) == []
    finally:
        conn.close()


def test_offsets_index_into_source_text(tmp_path):
    from services.catalog.chunk import rechunk_file

    conn = _make_conn(tmp_path)
    try:
        fid = _insert_file(conn, "notes/a.md", _LONG)
        rechunk_file(conn, fid, _LONG, ".md")
        for r in _chunks(conn, fid):
            assert _LONG[r["char_start"] : r["char_end"]].strip() == r["text"]
    finally:
        conn.close()


# ── _pass_chunking ───────────────────────────────────────────────────────────


def test_pass_chunks_every_file_with_text(tmp_path):
    from services.catalog.chunk import _pass_chunking

    conn = _make_conn(tmp_path)
    try:
        a = _insert_file(conn, "notes/a.md", _LONG)
        b = _insert_file(conn, "notes/b.md", "A short second note.")
        result = _pass_chunking(conn, None, None, 2)

        assert result["files_chunked"] == 2
        assert result["chunks_written"] == len(_chunks(conn, a)) + len(_chunks(conn, b))
        assert result["errors"] == []
    finally:
        conn.close()


def test_pass_skips_files_without_text(tmp_path):
    from services.catalog.chunk import _pass_chunking

    conn = _make_conn(tmp_path)
    try:
        conn.execute(
            "INSERT INTO files (rel_path, mount, abs_path, sha256, size_bytes, mtime, ext) "
            "VALUES ('library/x.pdf', 'library', '/x.pdf', 's', 1, 1.0, '.pdf')"
        )
        conn.commit()
        result = _pass_chunking(conn, None, None, 1)
        assert result["files_chunked"] == 0
        assert result["chunks_written"] == 0
    finally:
        conn.close()


def test_pass_is_idempotent(tmp_path):
    from services.catalog.chunk import _pass_chunking

    conn = _make_conn(tmp_path)
    try:
        fid = _insert_file(conn, "notes/a.md", _LONG)
        _pass_chunking(conn, None, None, 1)
        with conn:
            conn.execute("UPDATE file_chunks SET embedded_at = 99.0")
        first = [(r["id"], r["embedded_at"]) for r in _chunks(conn, fid)]

        _pass_chunking(conn, None, None, 1)
        assert [(r["id"], r["embedded_at"]) for r in _chunks(conn, fid)] == first
    finally:
        conn.close()


def test_pass_survives_one_bad_file(tmp_path, monkeypatch):
    """One file blowing up must not abort the whole pass."""
    from services.catalog import chunk as chunk_mod

    conn = _make_conn(tmp_path)
    try:
        _insert_file(conn, "notes/bad.md", _LONG)
        good = _insert_file(conn, "notes/good.md", "A fine note here.")

        real = chunk_mod.chunk_text

        def _explode(text, *, ext=""):
            if "Paragraph 0" in text:
                raise ValueError("synthetic chunker failure")
            return real(text, ext=ext)

        monkeypatch.setattr(chunk_mod, "chunk_text", _explode)

        result = chunk_mod._pass_chunking(conn, None, None, 2)
        assert len(result["errors"]) == 1
        assert result["files_chunked"] == 1
        assert _chunks(conn, good), "the healthy file must still be chunked"
    finally:
        conn.close()


def test_pass_stops_when_cancelled(tmp_path, monkeypatch):
    from services.catalog import chunk as chunk_mod

    conn = _make_conn(tmp_path)
    try:
        for i in range(5):
            _insert_file(conn, f"notes/{i}.md", _LONG)
        monkeypatch.setattr(chunk_mod.job_store, "is_cancelled", lambda _jid: True)

        result = chunk_mod._pass_chunking(conn, "job-1", None, 5)
        assert result["files_chunked"] == 0
    finally:
        conn.close()
