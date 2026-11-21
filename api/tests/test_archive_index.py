"""`archive_cli index`: a fresh install can build the index Ask retrieves
from, without the AI summary pass (MVP step 5 fresh-clone run, 2026-11-18).

In org, `/api/catalog/run` is refused by the consent middleware, and
`skip_ai=True` also skipped the local embedder, so a fresh clone had chunks
but no vectors and every question came back unanswered.
"""

from __future__ import annotations

import config


def test_index_library_chunks_and_embeds_without_summaries(tmp_path, monkeypatch):
    for name in ("notes", "library", "generated"):
        (tmp_path / name).mkdir()
    monkeypatch.setattr(config.settings, "notes_path", tmp_path / "notes")
    monkeypatch.setattr(config.settings, "library_root", tmp_path / "library")
    monkeypatch.setattr(config.settings, "generated_path", tmp_path / "generated")
    (tmp_path / "library" / "contract.txt").write_text(
        "2. Grant of Rights\nThe Grantor grants the Publisher the right to publish "
        "the Work in the United States, paperback only.\n"
    )

    from services.catalog import embed

    calls: list[bool] = []

    def fake_embed(conn, job_id, cb, n, skip_ai):
        calls.append(skip_ai)
        return {"qdrant_ok": True, "errors": []}

    monkeypatch.setattr(embed, "_pass_embedding", fake_embed)

    from services.archive.index import index_library
    from services.db import get_db

    out = index_library()

    conn = get_db()
    try:
        files = conn.execute(
            "SELECT rel_path, summary FROM files WHERE rel_path LIKE 'library/%'"
        ).fetchall()
        chunks = conn.execute("SELECT COUNT(*) FROM file_chunks").fetchone()[0]
    finally:
        conn.close()

    assert [f[0] for f in files] == ["library/contract.txt"]
    assert all(not f[1] for f in files), "no AI summary may be written"
    assert chunks >= 1
    assert calls == [False], "the local embedder must run"
    assert out["files_scanned"] == 1
