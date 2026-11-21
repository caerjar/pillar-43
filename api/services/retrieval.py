"""Vault retrieval — the shared grounding chokepoint for every AI surface.

`fetch_materials(topic)` is what stands between a question and the user's
archive. Its caller is `services/archive/ask.py`. Nothing here calls a model — this
module only builds the digest that gets injected.

(Historical note: this file was once `roundtable_retrieval.py`, named for a
multi-agent orchestrator removed in `682931a`; it survived because it was
always the retrieval layer, independent of that feature.)

Search strategy (matches `routes/search.py:_semantic_search` /
`routes/search.py:search` patterns):

  1. Embed the topic → the SQLite vector store (`vector_store.search_chunks`).
     Take 2×limit hits, score_threshold=0.3 (vector_store default).
  2. Ripgrep `--fixed-strings --ignore-case --type md` for the topic over
     the configured mounts. Top-3 by match count.
  3. Merge by `rel_path` (semantic wins on dedup).
  4. Bulk-hydrate summary/topics/mount from the `files` table.
  5. Drop entries with empty summary AND no extracted_text (degenerate).
  6. Sort by score desc, trim to `limit`.

Tolerates the vector search failing (lexical-only fallback, no exception). Returns
[] on empty vault. Never raises — retrieval failure shouldn't crash the
caller.
"""

from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from config import settings
from services.db import get_db

log = logging.getLogger(__name__)


# Defaults tuned for "grounded, not noisy": ~8 materials keeps the injected
# digest focused. More than 8 risks filling the prompt with marginal hits.
DEFAULT_LIMIT = 8
DEFAULT_MOUNTS: tuple[str, ...] = ("notes", "library")
RIPGREP_LIMIT = 3
RIPGREP_TIMEOUT_S = 5

# Lexical hits don't have a real similarity score. Pin them BELOW
# the vector store's score_threshold (0.3) so any semantic match — even a weak
# one — sorts above lexical fallback. Earlier value (0.4) inverted
# the relationship for semantic hits in [0.3, 0.4): they'd sort below
# pure-lexical noise. Audit catch on Day 5.
SCORE_LEXICAL_FALLBACK = 0.25

# ── Passage budget ───────────────────────────────────────────────────────────
# Real passage text is 10-30x the bytes of a summary, so the thing that used
# to be free now costs real tokens and latency. These caps are mandatory, not
# advisory: without the global one, 8 materials x 3 passages is ~29k chars
# (~7k tokens) on every single turn.
MAX_PASSAGES_PER_MATERIAL = 3
MAX_PASSAGE_CHARS = 1200
MAX_CONTEXT_CHARS = 24_000
# How many chunks to pull for a file that only matched lexically.
LEXICAL_PASSAGES_PER_FILE = 2


@dataclass
class Passage:
    """One retrieved chunk of a file — the actual text, not a summary of it."""

    text: str
    heading: str | None = None
    ordinal: int = 0
    score: float = 0.0
    chunk_id: int = 0


@dataclass
class Material:
    """One file digest the caller hands the model.

    `citation` is the canonical string the prompt teaches the model to
    copy back. The citation parser is exact-match — slug derivation in the
    prompt is a footgun; pre-build the string here.

    `passages` carries the actual retrieved text. It is additive and may be
    empty — a vault catalogued before chunking has no `file_chunks` rows, and
    callers fall back to `summary` in that case. That fallback is what makes
    this a no-flag-day change.
    """

    rel_path: str  # "notes/herbs/lemon-balm.md", "library/x/y.pdf"
    mount: str  # 'notes' | 'library' | 'generated'
    title: str  # human-friendly basename
    summary: str  # files.summary (may be "" if extracted_text exists)
    topics: list[str] = field(default_factory=list)
    citation: str = ""  # "[[lemon-balm]]" or "[library/x/y.pdf]"
    score: float = 0.0  # max passage score — preserves the sort invariant
    passages: list[Passage] = field(default_factory=list)  # score desc


# ── Citation building ────────────────────────────────────────────────────────


def _build_citation(rel_path: str, mount: str) -> str:
    """Canonical citation string. Wikilinks for vault notes (resolver
    matches basename), full mount-prefixed path for everything else.
    """
    if mount == "notes" and rel_path.endswith(".md"):
        return f"[[{Path(rel_path).stem}]]"
    return f"[{rel_path}]"


def _humanize_title(rel_path: str) -> str:
    stem = Path(rel_path).stem
    return stem.replace("-", " ").replace("_", " ").strip().title() or stem


# ── Retrieval primitives ─────────────────────────────────────────────────────


def _semantic_hits(
    topic: str,
    mounts: tuple[str, ...],
    limit: int,
    allow: set[str] | None = None,
) -> list[dict]:
    """Top-K file-level hits, each carrying its matching passages, or [].

    `allow` restricts the search to those paths before the top-K cut. A
    consent filter applied after the cut lets withheld items take every slot
    (A11: sixteen mail messages crowded out the one contract that answered).

    Searches at passage level and folds up to files: a file's score is its
    best passage's score, which keeps the `SCORE_LEXICAL_FALLBACK < 0.3`
    ordering invariant intact. Tolerates vector search failing.
    """
    try:
        from services.embeddings import embed_query
        from services.vector_store import (
            CHUNK_SEARCH_FANOUT,
            get_client,
            search_chunks,
        )

        client = get_client()
        vec = embed_query(topic)
        hits = search_chunks(
            client,
            vec,
            list(mounts),
            limit=limit * CHUNK_SEARCH_FANOUT,
            path_allow=allow,
        )
    except Exception as exc:  # broad on purpose, retrieval is best-effort
        log.debug(
            "retrieval: semantic search unavailable (%s); falling back to lexical-only",
            exc,
            exc_info=True,
        )
        return []

    by_path: dict[str, dict] = {}
    for h in hits:
        path = h["path"]
        entry = by_path.get(path)
        if entry is None:
            entry = {"path": path, "score": h["score"], "chunks": []}
            by_path[path] = entry
        entry["score"] = max(entry["score"], h["score"])
        entry["chunks"].append(h)

    for entry in by_path.values():
        entry["chunks"].sort(key=lambda c: c["score"], reverse=True)
        entry["chunks"] = entry["chunks"][:MAX_PASSAGES_PER_MATERIAL]

    ranked = sorted(by_path.values(), key=lambda e: e["score"], reverse=True)
    return ranked[:limit]


def _hydrate_passages(chunk_ids: list[int]) -> dict[int, dict]:
    """Bulk-fetch passage text for chunk ids. Never raises — a vault
    catalogued before chunking simply has no rows, and callers fall back to
    summaries."""
    if not chunk_ids:
        return {}
    placeholders = ",".join("?" * len(chunk_ids))
    try:
        conn = get_db()
        try:
            rows = conn.execute(
                f"SELECT id, text, heading, ordinal FROM file_chunks "
                f"WHERE id IN ({placeholders})",
                chunk_ids,
            ).fetchall()
        finally:
            conn.close()
    except Exception as exc:  # grounding is best-effort
        log.debug("retrieval: passage hydration failed (%s)", exc, exc_info=True)
        return {}
    return {
        r["id"]: {"text": r["text"], "heading": r["heading"], "ordinal": r["ordinal"]}
        for r in rows
    }


def _passages_for_paths(rel_paths: list[str], topic: str) -> dict[str, list[Passage]]:
    """Best passages for files that matched lexically (so have no chunk hits).

    Uses the chunk FTS index, falling back to the file's opening passage when
    FTS returns nothing. This is what lets lexical-only mode inject real
    content rather than only summaries — which it could not do at all before
    chunking.
    """
    if not rel_paths:
        return {}
    out: dict[str, list[Passage]] = {}
    try:
        conn = get_db()
        try:
            for rel_path in rel_paths:
                row = conn.execute(
                    "SELECT id FROM files WHERE rel_path = ?", (rel_path,)
                ).fetchone()
                if not row:
                    continue
                fid = row["id"]
                rows = []
                try:
                    rows = conn.execute(
                        "SELECT c.id, c.text, c.heading, c.ordinal "
                        "FROM file_chunks c "
                        "JOIN file_chunks_fts f ON f.rowid = c.id "
                        "WHERE c.file_id = ? AND file_chunks_fts MATCH ? "
                        "ORDER BY rank LIMIT ?",
                        (fid, _fts_query(topic), LEXICAL_PASSAGES_PER_FILE),
                    ).fetchall()
                except Exception:
                    # FTS5 rejects some query syntax outright; the opening
                    # passage is still better than a summary.
                    log.debug("retrieval: chunk FTS query failed", exc_info=True)
                if not rows:
                    rows = conn.execute(
                        "SELECT id, text, heading, ordinal FROM file_chunks "
                        "WHERE file_id = ? ORDER BY ordinal LIMIT ?",
                        (fid, LEXICAL_PASSAGES_PER_FILE),
                    ).fetchall()
                if rows:
                    out[rel_path] = [
                        Passage(
                            text=r["text"],
                            heading=r["heading"],
                            ordinal=r["ordinal"],
                            score=SCORE_LEXICAL_FALLBACK,
                            chunk_id=r["id"],
                        )
                        for r in rows
                    ]
        finally:
            conn.close()
    except Exception as exc:  # grounding is best-effort
        log.debug("retrieval: lexical passage lookup failed (%s)", exc, exc_info=True)
        return out
    return out


def _fts_query(topic: str) -> str:
    """Quote each term so FTS5 treats punctuation as literal text.

    An unquoted user question containing `-`, `"`, `*` or `:` is either a
    syntax error or, worse, silently reinterpreted as an operator.
    """
    terms = [t for t in "".join(c if c.isalnum() else " " for c in topic).split() if t]
    return " OR ".join(f'"{t}"' for t in terms) if terms else '""'


def _ripgrep_hits(topic: str, mounts: tuple[str, ...], limit: int) -> list[dict]:
    """Top-K ripgrep hits over the topic. Counts matches per file; best
    effort — ripgrep missing or timing out yields []. Markdown only —
    PDFs and library binaries are reached via the vector store (which embeds the
    extracted_text) or by being in the same topic neighbourhood.
    """
    search_dirs: list[str] = []
    for m in mounts:
        if m == "notes":
            search_dirs.append(str(settings.notes_path))
        elif m == "library":
            search_dirs.append(str(settings.library_root))
            for path in settings.extra_library_mounts.values():
                search_dirs.append(str(path))
        elif m == "generated":
            search_dirs.append(str(settings.generated_path))
    search_dirs = [d for d in search_dirs if Path(d).exists()]
    if not search_dirs:
        return []

    cmd = [
        "rg",
        "--json",
        "--fixed-strings",
        "--ignore-case",
        "--max-count",
        "3",
        "--type",
        "md",
        "--",
        topic,
        *search_dirs,
    ]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=RIPGREP_TIMEOUT_S
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        log.debug("retrieval: ripgrep failed (%s)", exc, exc_info=True)
        return []

    counts: dict[str, int] = {}
    for line in proc.stdout.splitlines():
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if obj.get("type") != "match":
            continue
        abs_path = obj["data"]["path"]["text"]
        rel = _abs_to_rel(abs_path)
        if rel is None:
            continue
        counts[rel] = counts.get(rel, 0) + 1

    sorted_paths = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
    return [
        {"path": p, "score": SCORE_LEXICAL_FALLBACK} for p, _ in sorted_paths[:limit]
    ]


def _abs_to_rel(abs_path: str) -> str | None:
    """Map an absolute path to a mount-prefixed rel_path. Returns None if
    the path isn't under any configured mount.
    """
    p = Path(abs_path)
    for mount, root in settings.all_mounts.items():
        try:
            rel = p.relative_to(root.resolve())
            return f"{mount}/{rel}"
        except ValueError:
            continue
    return None


def _hydrate_from_files_table(rel_paths: list[str]) -> dict[str, dict]:
    """Bulk-fetch mount/summary/topics/has_extracted_text for the given
    paths. Skips paths the catalog hasn't seen (rare — semantic hits
    came from the vector store, which is keyed off `files.id`, but lexical hits
    from raw filesystem scan can include uncatalogued files).
    """
    if not rel_paths:
        return {}
    placeholders = ",".join("?" * len(rel_paths))
    conn = get_db()
    try:
        rows = conn.execute(
            f"SELECT rel_path, mount, summary, topics, extracted_text "
            f"FROM files WHERE rel_path IN ({placeholders})",
            rel_paths,
        ).fetchall()
    finally:
        conn.close()

    out: dict[str, dict] = {}
    for r in rows:
        try:
            topics = json.loads(r["topics"]) if r["topics"] else []
        except (json.JSONDecodeError, TypeError):
            topics = []
        if not isinstance(topics, list):
            topics = []
        out[r["rel_path"]] = {
            "mount": r["mount"],
            "summary": (r["summary"] or "").strip(),
            "topics": topics,
            "has_extracted": bool(r["extracted_text"]),
        }
    return out


# ── Public surface ───────────────────────────────────────────────────────────


def fetch_materials(
    topic: str,
    limit: int = DEFAULT_LIMIT,
    mounts: tuple[str, ...] = DEFAULT_MOUNTS,
    audience: str | None = None,
) -> list[Material]:
    """Pre-flight retrieval for a topic (grounding).

    Combines semantic (vector store) + lexical (ripgrep on .md) hits, hydrates
    each result with summary + topics from the `files` table, and returns
    up to `limit` Material entries sorted by score.

    Empty topic, empty vault, or all-degenerate hits → []. Vector search failing
    → lexical-only fallback. Never raises.

    `audience`: `"staff"` or `"model"`. Every caller is filtered on item
    consent, and a caller that does not say defaults to `"model"`, because
    every caller that predates consent feeds a model. See `fetch_materials_counted`, which also
    returns how many matching items consent withheld.
    """
    return fetch_materials_counted(
        topic,
        limit=limit,
        mounts=mounts,
        audience=audience,
    )[0]


def fetch_materials_counted(
    topic: str,
    limit: int = DEFAULT_LIMIT,
    mounts: tuple[str, ...] = DEFAULT_MOUNTS,
    audience: str | None = None,
    purpose: str | None = None,
    role: str | None = None,
    withheld_out: list[str] | None = None,
) -> tuple[list[Material], int]:
    """`fetch_materials`, plus the number of matching items consent withheld.

    The count is a number only — never paths — so it can be shown to staff
    ("N items on this were not opened to the AI") without saying what they are.
    A caller that needs to say who closed them passes `withheld_out`, a list
    that is filled with the withheld paths; they stay inside the process and
    are tallied before anything is returned to a client.
    """
    if audience is None:
        audience = "model"

    topic = (topic or "").strip()
    if not topic:
        return [], 0

    allow: set[str] | None = None
    if audience is not None:
        # Consent narrows the semantic search itself, not only its result:
        # filtered after the top-K cut, withheld items take the slots of the
        # items this audience may see.
        from services.archive.items import allowed_paths
        from services.db import get_db as _get_db

        conn = _get_db()
        try:
            every = [r[0] for r in conn.execute("SELECT path FROM item")]
            allow = allowed_paths(conn, every, audience, purpose, role)
        finally:
            conn.close()
    sem = _semantic_hits(topic, mounts, limit=limit * 2, allow=allow)
    lex = _ripgrep_hits(topic, mounts, limit=RIPGREP_LIMIT)

    # Merge with semantic priority. Both sides already produce {path, score}.
    seen: set[str] = set()
    merged: list[dict] = []
    for h in sem:
        if h["path"] in seen:
            continue
        seen.add(h["path"])
        merged.append(h)
    for h in lex:
        if h["path"] in seen:
            continue
        seen.add(h["path"])
        merged.append(h)

    if not merged and allow is None:
        return [], 0

    withheld_by_consent = 0
    if allow is not None:
        # Consent runs FIRST, before hydration, passages and the limit: a
        # withheld item never has its text read into this process's result,
        # and never takes a slot from an item the audience may see. The
        # count is of what an unfiltered search would have matched, so staff
        # still learn how many items were not opened.
        unfiltered = {h["path"] for h in _semantic_hits(topic, mounts, limit=limit * 2)}
        unfiltered |= {h["path"] for h in lex}
        withheld_by_consent = len(unfiltered - allow)
        if withheld_out is not None:
            withheld_out.extend(sorted(unfiltered - allow))
        merged = [h for h in merged if h["path"] in allow]
        if not merged:
            return [], withheld_by_consent

    meta = _hydrate_from_files_table([h["path"] for h in merged])

    # Passage text for semantic hits comes from their chunk ids; lexical hits
    # have none, so they go through the chunk FTS index instead.
    all_chunk_ids = [c["chunk_id"] for h in merged for c in h.get("chunks", [])]
    chunk_text_by_id = _hydrate_passages(all_chunk_ids)
    lexical_paths = [h["path"] for h in merged if not h.get("chunks")]
    lexical_passages = _passages_for_paths(lexical_paths, topic)

    out: list[Material] = []
    for h in merged:
        m = meta.get(h["path"])
        if m is None:
            # Vector-store or filesystem hit on a path the catalog hasn't seen yet.
            continue
        if not m["summary"] and not m["has_extracted"]:
            # Empty stub — would just take up prompt slots.
            continue

        passages: list[Passage] = []
        for c in h.get("chunks", []):
            hydrated = chunk_text_by_id.get(c["chunk_id"])
            if not hydrated:
                continue
            passages.append(
                Passage(
                    text=hydrated["text"][:MAX_PASSAGE_CHARS],
                    heading=hydrated["heading"],
                    ordinal=hydrated["ordinal"],
                    score=c["score"],
                    chunk_id=c["chunk_id"],
                )
            )
        if not passages:
            passages = [
                Passage(
                    text=p.text[:MAX_PASSAGE_CHARS],
                    heading=p.heading,
                    ordinal=p.ordinal,
                    score=p.score,
                    chunk_id=p.chunk_id,
                )
                for p in lexical_passages.get(h["path"], [])
            ]

        out.append(
            Material(
                rel_path=h["path"],
                mount=m["mount"],
                title=_humanize_title(h["path"]),
                summary=m["summary"],
                topics=m["topics"],
                citation=_build_citation(h["path"], m["mount"]),
                score=h["score"],
                passages=passages[:MAX_PASSAGES_PER_MATERIAL],
            )
        )

    out.sort(key=lambda mat: mat.score, reverse=True)
    out = out[:limit]
    return _apply_context_budget(out), withheld_by_consent


def _apply_context_budget(materials: list[Material]) -> list[Material]:
    """Trim passage text from the lowest-scored materials up, until the total
    fits MAX_CONTEXT_CHARS.

    Drops passages, never whole materials: a material with no passages still
    contributes its summary and its citation, which is strictly better than
    the model not knowing the file exists.
    """
    total = sum(len(p.text) for m in materials for p in m.passages)
    if total <= MAX_CONTEXT_CHARS:
        return materials

    # materials are score-desc, so walk from the back.
    for mat in reversed(materials):
        while mat.passages and total > MAX_CONTEXT_CHARS:
            total -= len(mat.passages.pop().text)
        if total <= MAX_CONTEXT_CHARS:
            break
    return materials
