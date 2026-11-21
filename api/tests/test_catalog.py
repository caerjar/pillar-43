"""Tests for catalog service — hash_file, upsert_file_record (FileRecord), extract_text_for_catalog."""

import os
import sqlite3
import time
from pathlib import Path


# Point settings at tmp paths before importing anything that uses config
# (same pattern as other API tests)
os.environ.setdefault("TESTING", "1")


def _make_conn(tmp_path: Path) -> sqlite3.Connection:
    from services.db import init_schema

    conn = sqlite3.connect(str(tmp_path / "test.db"), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    init_schema(conn)
    return conn


# ── hash_file ─────────────────────────────────────────────────────────────────


def test_hash_file_returns_hex(tmp_path):
    from services.catalog import hash_file

    f = tmp_path / "hello.txt"
    f.write_text("hello world")
    h = hash_file(f)
    assert len(h) == 64
    assert all(c in "0123456789abcdef" for c in h)


def test_hash_file_deterministic(tmp_path):
    from services.catalog import hash_file

    f = tmp_path / "a.md"
    f.write_text("# Herbalism\n\nSome content.")
    assert hash_file(f) == hash_file(f)


def test_hash_file_different_for_different_content(tmp_path):
    from services.catalog import hash_file

    a = tmp_path / "a.txt"
    b = tmp_path / "b.txt"
    a.write_text("content A")
    b.write_text("content B")
    assert hash_file(a) != hash_file(b)


# ── extract_text_for_catalog ──────────────────────────────────────────────────


def test_extract_text_markdown(tmp_path):
    from services.catalog import extract_text_for_catalog

    f = tmp_path / "note.md"
    f.write_text("# Hello\n\nSome text here.")
    result = extract_text_for_catalog(f, "notes/note.md")
    assert result is not None
    assert "Hello" in result


def test_extract_text_returns_none_for_image(tmp_path):
    from services.catalog import extract_text_for_catalog

    f = tmp_path / "photo.jpg"
    f.write_bytes(b"\xff\xd8\xff")  # JPEG magic bytes
    result = extract_text_for_catalog(f, "library/photo.jpg")
    assert result is None


def test_extract_text_returns_none_for_audio(tmp_path):
    from services.catalog import extract_text_for_catalog

    f = tmp_path / "audio.mp3"
    f.write_bytes(b"\xff\xfb\x90")
    result = extract_text_for_catalog(f, "library/audio.mp3")
    assert result is None


def test_extract_text_csv(tmp_path):
    from services.catalog import extract_text_for_catalog

    f = tmp_path / "data.csv"
    f.write_text("name,value\nherbalism,high\nastrology,medium")
    result = extract_text_for_catalog(f, "notes/data.csv")
    assert result is not None
    assert "herbalism" in result


def test_extract_text_json(tmp_path):
    from services.catalog import extract_text_for_catalog

    f = tmp_path / "data.json"
    f.write_text('{"key": "value", "topic": "saturn"}')
    result = extract_text_for_catalog(f, "notes/data.json")
    assert result is not None
    assert "saturn" in result


def test_extract_text_timeout_returns_none(tmp_path, monkeypatch):
    """A wedged extraction (e.g. pypdf on a malformed PDF) must not stall the
    catalog run. The thread-pool wrapper times out and returns None so the
    scan moves on. The wedged thread keeps running in the background; that's
    acceptable as long as the function returns quickly."""
    import time as _time

    from services.catalog import extract as _extract

    f = tmp_path / "wedged.md"
    f.write_text("does not matter")

    def _sleeps_forever(path, rel_path):
        _time.sleep(60)
        return "never"

    monkeypatch.setattr(_extract, "_extract_text_inner", _sleeps_forever)
    monkeypatch.setattr(_extract, "EXTRACT_TIMEOUT_SEC", 1)

    t0 = _time.time()
    result = _extract.extract_text_for_catalog(f, "notes/wedged.md")
    elapsed = _time.time() - t0

    assert result is None
    assert elapsed < 5, f"expected <5s, took {elapsed:.1f}s"


# ── upsert_file_record ────────────────────────────────────────────────────────


def _rec(**kw):
    """Helper: build a FileRecord with sensible defaults for test use."""
    from services.catalog import FileRecord

    defaults = dict(
        rel_path="notes/note.md",
        mount="notes",
        abs_path="/note.md",
        sha256="abc123",
        size_bytes=100,
        mtime=1000.0,
        ext=".md",
        extracted_text="content",
        authorship=None,
    )
    defaults.update(kw)
    return FileRecord(**defaults)


def test_upsert_inserts_new_file(tmp_path):
    from services.catalog import upsert_file_record

    conn = _make_conn(tmp_path)
    row_id = upsert_file_record(
        conn,
        _rec(
            rel_path="notes/note.md",
            abs_path=str(tmp_path / "note.md"),
            sha256="abc123",
            extracted_text="some content",
        ),
    )
    assert row_id is not None
    row = conn.execute("SELECT * FROM files WHERE rel_path='notes/note.md'").fetchone()
    assert row["sha256"] == "abc123"
    assert row["extracted_text"] == "some content"
    assert row["summary"] is None  # not yet summarized
    conn.close()


def test_upsert_preserves_summary_when_hash_unchanged(tmp_path):
    from services.catalog import upsert_file_record

    conn = _make_conn(tmp_path)
    upsert_file_record(
        conn,
        _rec(sha256="abc123", size_bytes=100, mtime=1000.0, extracted_text="content"),
    )
    # Manually set a summary
    conn.execute(
        "UPDATE files SET summary='A great note', topics='[\"herbalism\"]', cataloged_at=? "
        "WHERE rel_path='notes/note.md'",
        (time.time(),),
    )
    conn.commit()

    # Re-upsert with same hash — size/mtime changed but hash same
    upsert_file_record(
        conn,
        _rec(
            sha256="abc123",
            size_bytes=105,
            mtime=2000.0,
            extracted_text="content updated",
        ),
    )
    row = conn.execute("SELECT * FROM files WHERE rel_path='notes/note.md'").fetchone()
    assert row["summary"] == "A great note"  # preserved
    assert row["topics"] == '["herbalism"]'  # preserved
    conn.close()


def test_upsert_clears_summary_when_hash_changes(tmp_path):
    from services.catalog import upsert_file_record

    conn = _make_conn(tmp_path)
    upsert_file_record(conn, _rec(sha256="abc123", extracted_text="original"))
    conn.execute(
        "UPDATE files SET summary='Old summary', cataloged_at=? WHERE rel_path='notes/note.md'",
        (time.time(),),
    )
    conn.commit()

    # Re-upsert with different hash (content changed)
    upsert_file_record(
        conn,
        _rec(
            sha256="def456", size_bytes=200, mtime=2000.0, extracted_text="new content"
        ),
    )
    row = conn.execute("SELECT * FROM files WHERE rel_path='notes/note.md'").fetchone()
    assert row["summary"] is None  # cleared
    assert row["sha256"] == "def456"
    conn.close()


def test_upsert_unique_constraint(tmp_path):
    from services.catalog import upsert_file_record

    conn = _make_conn(tmp_path)
    upsert_file_record(conn, _rec(rel_path="notes/a.md", mtime=1.0))
    upsert_file_record(conn, _rec(rel_path="notes/a.md", mtime=2.0))
    count = conn.execute(
        "SELECT COUNT(*) FROM files WHERE rel_path='notes/a.md'"
    ).fetchone()[0]
    assert count == 1  # no duplicate rows
    conn.close()
