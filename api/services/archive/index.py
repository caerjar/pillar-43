"""Build the index Ask retrieves from: extract and chunk every file under
`library/`, then embed the chunks with the local embedder. No AI summary pass:
summaries were written about every file, private ones included, which is the
leak the 2026-11-18 audit found.

`skip_ai=True` keeps the summary pass off but also turns off embedding, so
the embedding pass is run separately afterwards with the local embedder on.
"""

from __future__ import annotations


def index_library() -> dict:
    from services.catalog import embed, run_catalog
    from services.db import get_db

    out = run_catalog(mounts=["library"], skip_ai=True)
    conn = get_db()
    try:
        from services.archive.withdraw import forget_withdrawn

        forget_withdrawn(conn)  # a withdrawn file's bytes may still be on disk
        emb = embed._pass_embedding(conn, None, None, out["files_scanned"], False)
        conn.commit()
    finally:
        conn.close()
    return {
        "files_scanned": out["files_scanned"],
        "embedded": bool(emb.get("qdrant_ok")),
        "errors": emb.get("errors", []),
    }
