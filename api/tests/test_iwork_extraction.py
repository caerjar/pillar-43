"""Characterization tests for iWork (.pages/.key/.numbers) text extraction.

30% covered before this, and one of the highest-complexity functions in the
tree — a bad combination, because it is also the code most exposed to hostile
input: an iWork file is a ZIP an attacker can shape freely.

The size limits below are not tuning knobs, they are the defence against a zip
bomb hanging the catalog pass. They are pinned first.
"""

from __future__ import annotations

import zipfile

import pytest

from services.vault.extraction import _extract_iwork_text


def _pages(tmp_path, members: dict[str, bytes], name="doc.pages"):
    p = tmp_path / name
    with zipfile.ZipFile(p, "w") as zf:
        for n, data in members.items():
            zf.writestr(n, data)
    return p


INDEX_XML = b"""<?xml version="1.0"?>
<document xmlns:sf="http://x">
  <sf:p>The first paragraph of the document.</sf:p>
  <sf:p>A second paragraph, also long enough.</sf:p>
  <sf:p>ok</sf:p>
</document>
"""


# ── index.xml (older format) ────────────────────────────────────────────────


def test_extracts_paragraph_text_from_index_xml(tmp_path):
    out = _extract_iwork_text(_pages(tmp_path, {"index.xml": INDEX_XML}))
    assert "The first paragraph of the document." in out
    assert "A second paragraph" in out


def test_very_short_strings_are_dropped(tmp_path):
    """<=2 chars is markup noise, not content."""
    out = _extract_iwork_text(_pages(tmp_path, {"index.xml": INDEX_XML}))
    assert "ok" not in out.split()


def test_malformed_xml_returns_empty_rather_than_raising(tmp_path):
    """A corrupt document must not abort the catalog pass it is part of."""
    out = _extract_iwork_text(_pages(tmp_path, {"index.xml": b"<not valid xml"}))
    assert out == ""


# ── the size limits, which are the DoS defence ──────────────────────────────


def test_a_file_over_the_size_cap_is_skipped(tmp_path, monkeypatch):
    p = _pages(tmp_path, {"index.xml": INDEX_XML})

    real_stat = type(p).stat

    class Huge:
        st_size = 51 * 1024 * 1024

    monkeypatch.setattr(type(p), "stat", lambda self, **kw: Huge())
    try:
        assert _extract_iwork_text(p) == ""
    finally:
        monkeypatch.setattr(type(p), "stat", real_stat)


def test_an_oversized_index_xml_is_skipped(tmp_path):
    """A small ZIP can hold a huge index.xml — the compressed size is not the
    thing to trust. 10MB uncompressed is the cap."""
    big = (
        b"<document>" + (b"<sf:p>" + b"x" * 200 + b"</sf:p>") * 60_000 + b"</document>"
    )
    assert len(big) > 10 * 1024 * 1024
    out = _extract_iwork_text(_pages(tmp_path, {"index.xml": big}))
    assert out == ""


# ── absent / unusable archives ──────────────────────────────────────────────


def test_an_archive_with_no_known_members_yields_empty(tmp_path):
    out = _extract_iwork_text(_pages(tmp_path, {"random.txt": b"hello there"}))
    assert out == ""


def test_a_file_that_is_not_a_zip_returns_empty(tmp_path):
    p = tmp_path / "broken.pages"
    p.write_bytes(b"this is not a zip archive at all")
    assert _extract_iwork_text(p) == ""


def test_an_empty_archive_yields_empty(tmp_path):
    assert _extract_iwork_text(_pages(tmp_path, {})) == ""


# ── .iwa (newer format) ─────────────────────────────────────────────────────


def test_iwa_members_yield_printable_runs(tmp_path):
    """Newer iWork stores protobuf-ish .iwa blobs. Extraction scavenges runs
    of printable ASCII, so the assertion is about that, not about fidelity."""
    # >=100 bytes: smaller .iwa members are skipped as locale/metadata noise,
    # which is why a minimal fixture reads as "extraction is broken".
    blob = b"\x00\x01" + b"A meaningful sentence of content here." + b"\x00" * 80
    assert len(blob) >= 100
    out = _extract_iwork_text(_pages(tmp_path, {"Index/Document.iwa": blob}))
    assert "meaningful sentence" in out


@pytest.mark.parametrize(
    "noise", [b"com.apple.iwork.something", b"en_US", b"gregorian"]
)
def test_iwa_metadata_strings_are_filtered(tmp_path, noise):
    """Without the skip list the output is mostly bundle identifiers."""
    blob = (
        b"\x00"
        + noise
        + b"\x00"
        + b"A real sentence worth keeping here."
        + b"\x00" * 60
    )
    out = _extract_iwork_text(_pages(tmp_path, {"Index/Document.iwa": blob}))
    assert noise.decode() not in out
