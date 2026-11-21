"""Shared helpers for the org-edition tests (C1-C6): a seeded catalog, a
lexical-only retrieval, and a recorded model in place of Ollama."""

from __future__ import annotations

import json
import time

import config


def settings(tmp_path, monkeypatch):
    for name in ("notes", "library", "generated"):
        (tmp_path / name).mkdir(exist_ok=True)
    monkeypatch.setattr(config.settings, "notes_path", tmp_path / "notes")
    monkeypatch.setattr(config.settings, "library_root", tmp_path / "library")
    monkeypatch.setattr(config.settings, "generated_path", tmp_path / "generated")


def seed(
    rel_path: str,
    text: str,
    consent: str | None,
    kind: str = "contract",
    sha: str | None = None,
    labels: list[str] | None = None,
) -> None:
    """Catalog row + one chunk + (if consent is not None) an item row."""
    from services.db import get_db

    conn = get_db()
    try:
        cur = conn.execute(
            "INSERT INTO files (rel_path, mount, abs_path, sha256, size_bytes, mtime, ext, "
            "extracted_text, summary, topics, cataloged_at, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                rel_path,
                "library",
                "/" + rel_path,
                "x",
                1,
                time.time(),
                ".pdf",
                text,
                "s",
                "[]",
                time.time(),
                time.time(),
            ),
        )
        conn.execute(
            "INSERT INTO file_chunks (file_id, ordinal, text, char_start, char_end, heading, chunk_hash) "
            "VALUES (?,?,?,?,?,?,?)",
            (cur.lastrowid, 0, text, 0, len(text), None, "h-" + rel_path),
        )
        if consent is not None:
            conn.execute(
                "INSERT INTO item (path, sha256, kind, consent) VALUES (?,?,?,?)",
                (rel_path, sha or "sha-" + rel_path, kind, consent),
            )
            if labels:
                conn.execute(
                    "UPDATE item SET labels = ? WHERE path = ?",
                    (json.dumps(labels), rel_path),
                )
        conn.commit()
    finally:
        conn.close()


def lexical_only(monkeypatch, paths):
    from services import retrieval

    monkeypatch.setattr(retrieval, "_semantic_hits", lambda *a, **k: [])
    monkeypatch.setattr(
        retrieval,
        "_ripgrep_hits",
        lambda *a, **k: [{"path": p, "score": 0.25} for p in paths],
    )


def fake_model(monkeypatch, sentence="Rights revert after a cure period.", cites=(1,)):
    """Replace Ollama with a recorder. Returns the list of prompts it saw."""
    from services.archive import ask as ask_mod

    prompts: list[str] = []

    def recorder(system, user, schema, model, timeout=300):
        prompts.append(system + user)
        return {
            "message": {
                "content": json.dumps(
                    {
                        "answer": [
                            {
                                "sentence": sentence,
                                "cites": list(cites),
                                "quote": {"passage": cites[0], "sentence": 1},
                            }
                        ],
                        "not_answered": False,
                        "would_answer": None,
                    }
                )
            },
            "_elapsed_s": 0.0,
        }

    monkeypatch.setattr(ask_mod, "call_ollama", recorder)
    return prompts
