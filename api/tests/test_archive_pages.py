"""A cited passage knows which PDF page it starts on, so "Open file" can
land there instead of on page 1 (MVP step 4)."""

from __future__ import annotations

import json
import time

from services.archive import ask as ask_mod
from services.archive.pages import page_at

DOC = (
    "[Page 1]\nLANTERN WHARF EDITIONS\n3 Tallow Steps, Port Alder\n"
    "1. Grant\nThe Author grants...\n"
    "[Page 2]\n7. Reversion\nRights revert nine months after notice.\n"
    "[Page 3]\n12. Governing Law\n"
)


def test_page_at_counts_markers_before_the_chunk():
    assert page_at(DOC, 0) == 1
    assert page_at(DOC, DOC.index("1. Grant")) == 1
    # A chunk that starts exactly on a marker is on that page.
    assert page_at(DOC, DOC.index("[Page 2]")) == 2
    assert page_at(DOC, DOC.index("Rights revert")) == 2
    assert page_at(DOC, DOC.index("12. Governing")) == 3


def test_page_at_without_markers_is_none():
    assert page_at("a plain text letter", 5) is None
    assert page_at(None, 0) is None


def test_ask_returns_the_page_of_each_passage(tmp_path, monkeypatch):
    import config
    from services import retrieval
    from services.db import get_db

    for name in ("notes", "library", "generated"):
        (tmp_path / name).mkdir()
    monkeypatch.setattr(config.settings, "notes_path", tmp_path / "notes")
    monkeypatch.setattr(config.settings, "library_root", tmp_path / "library")
    monkeypatch.setattr(config.settings, "generated_path", tmp_path / "generated")

    rel = "library/contracts/c.pdf"
    start = DOC.index("[Page 2]")
    chunk = DOC[start : DOC.index("[Page 3]")]
    conn = get_db()
    try:
        cur = conn.execute(
            "INSERT INTO files (rel_path, mount, abs_path, sha256, size_bytes, mtime, ext, "
            "extracted_text, summary, topics, cataloged_at, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                rel,
                "library",
                "/" + rel,
                "x",
                1,
                time.time(),
                ".pdf",
                DOC,
                "s",
                "[]",
                time.time(),
                time.time(),
            ),
        )
        conn.execute(
            "INSERT INTO file_chunks (file_id, ordinal, text, char_start, char_end, heading, chunk_hash) "
            "VALUES (?,?,?,?,?,?,?)",
            (cur.lastrowid, 1, chunk, start, start + len(chunk), None, "h"),
        )
        conn.execute(
            "INSERT INTO item (path, sha256, kind, consent) VALUES (?,?,?,?)",
            (rel, "sha", "contract", "model"),
        )
        conn.commit()
    finally:
        conn.close()

    monkeypatch.setattr(retrieval, "_semantic_hits", lambda *a, **k: [])
    monkeypatch.setattr(
        retrieval, "_ripgrep_hits", lambda *a, **k: [{"path": rel, "score": 0.25}]
    )
    monkeypatch.setattr(
        ask_mod,
        "call_ollama",
        lambda *a, **k: {
            "message": {
                "content": json.dumps(
                    {"answer": [], "not_answered": True, "would_answer": None}
                )
            },
            "_elapsed_s": 0.0,
        },
    )
    out = ask_mod.ask("When do rights revert?")
    assert out["passages"], out
    assert out["passages"][0]["page"] == 2
