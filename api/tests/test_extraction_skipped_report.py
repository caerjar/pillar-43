"""Tests for the extraction-skipped markdown report (Phase A).

Covers:
  * scan.py collects (rel_path, size, ext, reason) for over-size and
    empty-extraction files
  * unchanged-hash files are NOT collected (would explode the report)
  * generate_extraction_skipped_report writes the markdown file with the
    expected sections + rows
"""

import os
import sqlite3
from pathlib import Path
from unittest.mock import patch


os.environ.setdefault("TESTING", "1")


def _make_conn(tmp_path: Path) -> sqlite3.Connection:
    from services.db import init_schema

    conn = sqlite3.connect(str(tmp_path / "test.db"), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    init_schema(conn)
    return conn


# ── _pass_file_scan: skipped_extractions collection ──────────────────────────


def test_scan_reports_oversize_file(tmp_path, monkeypatch):
    """A file larger than the cap is recorded with reason='over_size'."""
    # Patch the cap to a tiny value so we don't need a real 50 MB file.
    import services.catalog.scan as scan_mod

    monkeypatch.setattr(scan_mod, "MAX_TEXT_EXTRACT_BYTES", 100)

    from services.catalog import _pass_file_scan

    notes = tmp_path / "notes"
    notes.mkdir()
    big = notes / "huge.md"
    big.write_text("x" * 5000)  # well over the 100-byte patched cap

    result = _pass_file_scan(
        _make_conn(tmp_path),
        mounts=["notes"],
        mount_roots={"notes": notes},
        force_rescan=False,
        progress_callback=None,
        job_id=None,
    )
    skipped = result["skipped_extractions"]
    over = [s for s in skipped if s["reason"] == "over_size"]
    assert len(over) == 1
    assert over[0]["rel_path"] == "notes/huge.md"
    assert over[0]["size_bytes"] == 5000
    assert over[0]["ext"] == ".md"


def test_scan_reports_empty_extraction(tmp_path):
    """A file whose extractor returns None lands in skipped_extractions
    with reason='empty_extraction'."""
    from services.catalog import _pass_file_scan
    import services.catalog as cat_pkg

    notes = tmp_path / "notes"
    notes.mkdir()
    # An mp3 has no transcript here; extract_text_for_catalog returns None
    # for NO_TEXT_EXTENSIONS without a transcript file. We still pass
    # through scan, so we should see the skip recorded.
    silent = notes / "silent.mp3"
    silent.write_bytes(b"\x00fake mp3 bytes")

    # Force extract_text_for_catalog to return None unconditionally —
    # avoids relying on real format-specific behavior.
    with patch.object(cat_pkg, "extract_text_for_catalog", return_value=None):
        result = _pass_file_scan(
            _make_conn(tmp_path),
            mounts=["notes"],
            mount_roots={"notes": notes},
            force_rescan=False,
            progress_callback=None,
            job_id=None,
        )
    skipped = result["skipped_extractions"]
    empty = [s for s in skipped if s["reason"] == "empty_extraction"]
    assert len(empty) == 1
    assert empty[0]["rel_path"] == "notes/silent.mp3"
    assert empty[0]["ext"] == ".mp3"


def test_scan_does_not_report_unchanged_files(tmp_path):
    """Unchanged-hash skips must NOT appear in skipped_extractions —
    that's the whole point of excluding them (would dominate the report)."""
    from services.catalog import _pass_file_scan

    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "note.md").write_text("indexed content")

    conn = _make_conn(tmp_path)
    _pass_file_scan(conn, ["notes"], {"notes": notes}, False, None, None)
    # Second pass: file is unchanged — should NOT be reported as skipped.
    result = _pass_file_scan(conn, ["notes"], {"notes": notes}, False, None, None)
    conn.close()

    assert result["skipped_extractions"] == []


# ── generate_extraction_skipped_report ──────────────────────────────────────


def test_report_writes_file_with_oversize_row(tmp_path, monkeypatch):
    """End-to-end: a known oversize entry shows up in the markdown report."""
    from config import settings
    from services.catalog.reports import generate_extraction_skipped_report

    monkeypatch.setattr(settings, "generated_path", tmp_path)

    skipped = [
        {
            "rel_path": "library/huge.pdf",
            "size_bytes": 80 * 1024 * 1024,
            "ext": ".pdf",
            "reason": "over_size",
        },
        {
            "rel_path": "notes/scan.pdf",
            "size_bytes": 4 * 1024 * 1024,
            "ext": ".pdf",
            "reason": "empty_extraction",
        },
    ]
    rep = generate_extraction_skipped_report(skipped)
    assert rep["skipped_count"] == 2

    out_path = Path(rep["output"])
    assert out_path.exists()
    content = out_path.read_text(encoding="utf-8")

    # Both sections present
    assert "Over size limit (1 files)" in content
    assert "Empty extraction result (1 files)" in content
    # Oversize row content (path + size formatting)
    assert "library/huge.pdf" in content
    assert "80.0 MB" in content
    # Empty-extraction row
    assert "notes/scan.pdf" in content


def test_report_handles_no_skips(tmp_path, monkeypatch):
    """Empty list still writes a report (so it doesn't show stale data
    from a previous run)."""
    from config import settings
    from services.catalog.reports import generate_extraction_skipped_report

    monkeypatch.setattr(settings, "generated_path", tmp_path)

    rep = generate_extraction_skipped_report([])
    assert rep["skipped_count"] == 0
    out_path = Path(rep["output"])
    assert out_path.exists()
    content = out_path.read_text(encoding="utf-8")
    assert "No files skipped" in content
