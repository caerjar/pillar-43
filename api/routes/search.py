import asyncio
import json
import logging
import subprocess
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from config import settings
from services.archive.access import filter_results
from services.db import get_db

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api")


def _build_scope_paths() -> dict:
    """Build SCOPE_PATHS dynamically so extra vault mounts are included."""
    extra = {
        name: (lambda p: lambda: [str(p)])(path)
        for name, path in settings.extra_library_mounts.items()
    }
    return {
        "notes": lambda: [str(settings.notes_path)],
        "generated": lambda: [str(settings.generated_path)],
        "library": lambda: [str(settings.library_root)],
        "all": lambda: [str(p) for p in settings.all_mounts.values()],
        **extra,
    }


SCOPE_PATHS = _build_scope_paths()


@router.get("/search")
async def search(
    q: str = Query(..., min_length=1),
    scope: str = Query("all"),
    thread_folder: str | None = Query(default=None),
    semantic: bool = Query(default=False),
):
    valid_scopes = set(SCOPE_PATHS.keys()) | {"thread"}
    if scope not in valid_scopes:
        raise HTTPException(status_code=400, detail=f"Invalid scope: {scope!r}")

    if scope == "thread":
        if thread_folder:
            try:
                # Normalize: thread_folder may arrive as "herbs" or "notes/herbs"
                tf = thread_folder.lstrip("/")
                if not tf.startswith("notes/") and not tf.startswith("notes\\"):
                    tf = f"notes/{tf}"
                resolved = settings.resolve(tf)
                thread_path = str(resolved)
            except (ValueError, KeyError):
                # settings.resolve raises these for a bad/traversing/unknown-mount
                # path — a client error. Unexpected errors now propagate as 500
                # instead of being masked as a 400.
                # `from None`: the cause embeds the resolved path the caller was
                # probing for; the flat message is the whole point.
                raise HTTPException(
                    status_code=400, detail="Invalid thread folder path"
                ) from None
        else:
            thread_path = str(settings.notes_path)
        search_dirs = [thread_path] if Path(thread_path).exists() else []
    else:
        search_dirs = [d for d in SCOPE_PATHS[scope]() if Path(d).exists()]
    if not search_dirs:
        return {"query": q, "scope": scope, "results": []}

    cmd = [
        "rg",
        "--json",
        "--fixed-strings",
        "--ignore-case",
        "--max-count",
        "5",
        "--type",
        "md",
        "--",
        q,
        *search_dirs,
    ]
    try:
        # Off the event loop — ripgrep can run for up to `timeout` seconds and
        # would otherwise stall every concurrent request/SSE stream.
        proc = await asyncio.to_thread(
            subprocess.run, cmd, capture_output=True, text=True, timeout=10
        )
    except FileNotFoundError:
        # `from None`: the detail already states the whole diagnosis. The
        # underlying OSError adds only the binary name we just named.
        raise HTTPException(status_code=500, detail="ripgrep not available") from None
    except subprocess.TimeoutExpired:
        # `from None`: TimeoutExpired stringifies the full argv, which includes
        # every directory being searched — vault layout, back to the client.
        raise HTTPException(status_code=408, detail="Search timed out") from None

    rg_results = []
    for line in proc.stdout.splitlines():
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if obj.get("type") == "match":
            data = obj["data"]
            file_path = data["path"]["text"]
            rel = _to_mount_path(file_path)
            rg_results.append(
                {
                    "path": rel,
                    "line": data["line_number"],
                    "text": data["lines"]["text"].rstrip(),
                }
            )

    if semantic:
        return {
            "query": q,
            "scope": scope,
            "results": filter_results(
                merge_semantic(rg_results, _semantic_search(q, scope))
            ),
            "semantic": True,
        }

    # Catalogued non-markdown files (PDFs, EPUBs, transcripts of audio) are
    # searched through their extracted text; ripgrep only reads .md.
    seen_paths = {r["path"] for r in rg_results}
    mounts = _SCOPE_MOUNTS.get(scope)
    catalog_results = [
        c
        for c in await asyncio.to_thread(_catalog_search, q)
        if mounts is None or c["path"].split("/", 1)[0] in mounts
    ]
    merged = rg_results + [c for c in catalog_results if c["path"] not in seen_paths]
    return {
        "query": q,
        "scope": scope,
        "results": filter_results(merged)[:_MAX_RESULTS],
    }


def _catalog_search(q: str, limit: int = 15) -> list[dict]:
    """Search extracted_text of non-markdown catalogued files (PDFs, EPUBs, audio).

    Uses FTS5 MATCH for fast full-text search; falls back to LIKE if the
    files_fts virtual table is absent (older DB or SQLite without FTS5).
    """
    rows = []
    conn = get_db()
    try:
        try:
            # FTS5 path — phrase-safe: wrap in quotes to search the literal query
            safe_q = q.replace('"', '""')
            rows = conn.execute(
                """
                SELECT f.rel_path, f.summary, f.extracted_text
                FROM files_fts
                JOIN files f ON files_fts.rowid = f.id
                WHERE files_fts MATCH :query
                  AND f.ext NOT IN ('.md', '.txt', '.markdown')
                LIMIT :limit
                """,
                {"query": f'"{safe_q}"', "limit": limit},
            ).fetchall()
        except Exception:
            # FTS5 unavailable — fall back to LIKE
            rows = conn.execute(
                """
                SELECT rel_path, summary, extracted_text
                FROM files
                WHERE extracted_text LIKE :pattern
                  AND ext NOT IN ('.md', '.txt', '.markdown')
                LIMIT :limit
                """,
                {"pattern": f"%{q}%", "limit": limit},
            ).fetchall()
    except Exception:
        return []
    finally:
        conn.close()

    results = []
    for row in rows:
        text = row["extracted_text"] or ""
        idx = text.lower().find(q.lower())
        if idx >= 0:
            snippet = text[max(0, idx - 80) : idx + 120].strip()
        else:
            snippet = (row["summary"] or "")[:200]
        results.append(
            {
                "path": row["rel_path"],
                "line": 0,
                "text": snippet,
                "source": "catalog",
                "note": None,
            }
        )
    return results


_SCOPE_MOUNTS: dict[str, list[str] | None] = {
    "notes": ["notes"],
    "library": ["library"],
    "generated": ["generated"],
    "all": None,
    "thread": ["notes"],
    **{name: [name] for name in settings.extra_library_mounts},
}


#: Cap on the merged list, matching the lexical-only path.
_MAX_RESULTS = 50


def merge_semantic(rg_results: list[dict], sem_results: list[dict]) -> list[dict]:
    """Literal matches first, semantic appended, deduped by path.

    Extracted and tested directly because the ORDER is the whole behaviour and
    getting it wrong yields a plausible-looking result list rather than an
    error — the repo's rule for order-dependent logic.

    This used to PREPEND the semantic block. Typing an exact filename then put
    fuzzy matches above the file you had just named, which is not a file finder
    any more. That, and a snippet that was only a score, is why the flag stayed
    off.
    """
    seen = {r["path"] for r in rg_results}
    appended = [r for r in sem_results if r["path"] not in seen]
    return (rg_results + appended)[:_MAX_RESULTS]


#: How much passage text a semantic result carries. Long enough to judge
#: relevance at a glance, short enough not to crowd out the next row.
_SNIPPET_CHARS = 180


def _snippet(text: str) -> str:
    """One readable line from a passage."""
    collapsed = " ".join((text or "").split())
    if len(collapsed) <= _SNIPPET_CHARS:
        return collapsed
    return f"{collapsed[:_SNIPPET_CHARS].rsplit(' ', 1)[0]}\u2026"


def _semantic_search(q: str, scope: str, limit: int = 15) -> list[dict]:
    """Passages semantically near the query, one row per file.

    Chunk-level rather than file-level, because the point of a search result is
    the line that made it match. This used to search whole-file vectors and
    render "~87% semantic match" as the snippet \u2014 a row telling you a file is
    relevant without telling you why, which is most of why the path was never
    switched on.

    Returns [] on any failure (no embeddings yet, model unavailable, a vault
    catalogued before chunking). Semantic degrading to lexical is survivable; a
    500 on every keystroke is not.
    """
    try:
        from services.embeddings import embed_query
        from services.retrieval import _hydrate_passages
        from services.vector_store import get_client, search_chunks

        mount_filter = _SCOPE_MOUNTS.get(scope)
        # Over-fetch: several chunks of one file often rank together, and they
        # collapse to a single row below.
        hits = search_chunks(
            get_client(), embed_query(q), mount_filter, limit=limit * 4
        )
        if not hits:
            return []

        passages = _hydrate_passages([h["chunk_id"] for h in hits])

        out: list[dict] = []
        seen: set[str] = set()
        for h in hits:  # already ordered by descending score
            if h["path"] in seen:
                continue
            passage = passages.get(h["chunk_id"])
            text = _snippet(passage["text"]) if passage else ""
            if not text:
                # Nothing to show. Skipping beats a row whose only content is
                # its own score.
                continue
            seen.add(h["path"])
            out.append(
                {
                    "path": h["path"],
                    "line": 1,
                    "text": text,
                    "source": "semantic",
                    "note": (passage or {}).get("heading") or None,
                }
            )
            if len(out) >= limit:
                break
        return out
    except Exception:
        log.debug("semantic search unavailable", exc_info=True)
        return []


def _to_mount_path(abs_path: str) -> str:
    p = Path(abs_path)
    for mount, root in settings.all_mounts.items():
        try:
            rel = p.relative_to(root.resolve())
            return f"{mount}/{rel}"
        except ValueError:
            continue
    return abs_path
