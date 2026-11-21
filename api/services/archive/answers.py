"""A record of every answer Ask gave, and which items it cited.

Kept so that a withdrawal can mark the earlier answers that rested on the
withdrawn item (the text is not rewritten: it is what was said, and it is
flagged). Written by `ask()` through one hook call, `record_answer`.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone

from services.archive import ledger


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def record_answer(out: dict) -> int | None:
    """Store an `ask()` result; return the answer id. Never raises into ask."""
    import logging

    from services.db import get_db

    conn = get_db()
    try:
        from services.archive.annotations import attach_to_passages

        attach_to_passages(conn, out.get("passages", []))
        from services.archive.silences import compute

        seen = [p["path"] for p in out.get("passages", [])] + [
            s["path"] for s in out.get("staff_only_sources", [])
        ]
        out["silences"] = compute(
            conn,
            out.get("question", ""),
            seen,
            out.get("withheld_from_ai", 0),
            out.get("closed_named"),
            closed_by=out.get("closed_by"),
            no_document=out.get("no_document"),
        )
        cited = sorted(
            {
                out["passages"][c - 1]["path"]
                for s in out.get("answer", [])
                for c in s.get("cites", [])
                if 1 <= c <= len(out.get("passages", []))
            }
        )
        shas = {
            p: (
                r[0]
                if (
                    r := conn.execute(
                        "SELECT sha256 FROM item WHERE path=?", (p,)
                    ).fetchone()
                )
                else ""
            )
            for p in cited
        }
        with conn:
            cur = conn.execute(
                "INSERT INTO answer (asked_at, question, answer_json, prompt_sha256, model, silences) "
                "VALUES (?,?,?,?,?,?)",
                (
                    _now(),
                    out.get("question", ""),
                    json.dumps(out.get("answer", []), ensure_ascii=False),
                    out.get("prompt_sha256"),
                    out.get("model"),
                    json.dumps(out["silences"], ensure_ascii=False),
                ),
            )
            aid = cur.lastrowid
            for p, sha in shas.items():
                conn.execute(
                    "INSERT OR IGNORE INTO answer_citation (answer_id, path, sha256) VALUES (?,?,?)",
                    (aid, p, sha),
                )
            if aid is not None:
                _record_passages(conn, aid, out.get("passages", []))
        out["receipt_id"] = _receipt(conn, out, aid)
        return aid
    except sqlite3.Error:
        logging.getLogger(__name__).warning("could not record answer", exc_info=True)
        return None
    finally:
        conn.close()


def passage_sha256(sentences: list[str]) -> str:
    """Hash of a passage as the model read it (its lines joined by a space)."""
    return hashlib.sha256(" ".join(sentences).encode("utf-8")).hexdigest()


def _record_passages(conn: sqlite3.Connection, answer_id: int, passages: list[dict]):
    """Keep the numbered passage list the answer's `cites` and `quote.passage`
    numbers refer to: per passage its number, item path and sha256, chunk and
    character span, and the hash of the text the model read. Without this a
    stored number cannot be walked back to a document."""
    for p in passages:
        sha = conn.execute(
            "SELECT sha256 FROM item WHERE path=?", (p["path"],)
        ).fetchone()
        span = conn.execute(
            "SELECT char_start, char_end FROM file_chunks WHERE id=?",
            (p.get("chunk_id"),),
        ).fetchone()
        conn.execute(
            "INSERT OR REPLACE INTO answer_passage (answer_id, n, path, sha256, "
            "chunk_id, ordinal, char_start, char_end, passage_sha256) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (
                answer_id,
                p["n"],
                p["path"],
                sha[0] if sha else "",
                p.get("chunk_id"),
                p.get("ordinal"),
                span[0] if span else None,
                span[1] if span else None,
                passage_sha256(p.get("sentences") or []),
            ),
        )


def _receipt(conn: sqlite3.Connection, out: dict, answer_id: int | None) -> int | None:
    """One `model_call` ledger line per answer whose prompt held passages: what
    was asked, which model, the prompt's hash, and the items the model read
    (every passage in the prompt, not only the ones the answer cited)."""
    passages = out.get("passages") or []
    if not passages:
        return None
    paths = sorted({p["path"] for p in passages})
    ph = ",".join("?" * len(paths))
    shas = dict(
        conn.execute(f"SELECT path, sha256 FROM item WHERE path IN ({ph})", paths)
    )
    return ledger.append(
        conn,
        "model_call",
        "ask",
        "",
        {
            "answer_id": answer_id,
            "model": out.get("model"),
            "prompt_sha256": out.get("prompt_sha256"),
            "prompt_version": out.get("prompt_version"),
            "items": [{"path": p, "sha256": shas.get(p, "")} for p in paths],
        },
    )


def _squash(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def verify_answer(conn: sqlite3.Connection, answer_id: int) -> dict | None:
    """Re-check every stored quote of an answer from storage alone: quote ->
    passage number -> item path and sha256 -> the item's bytes today.

    Per quote, `reason` is one of: ok; no_passage_record (answers recorded
    before the passage list was kept); item_withdrawn (the item is gone, so
    nothing can be checked); item_changed (its sha256 is no longer the one the
    model read); text_missing (no extracted text to compare); quote_not_in_item
    (the quoted words are not in the passage's place in the item)."""
    from services.archive.sentence_edges import MAX_EXTEND_CHARS

    row = conn.execute(
        "SELECT answer_json FROM answer WHERE id=?", (answer_id,)
    ).fetchone()
    if row is None:
        return None
    checks = []
    for pos, sent in enumerate(json.loads(row[0])):
        q = sent.get("quote")
        if not isinstance(q, dict):
            continue
        n = q.get("passage")
        rec = conn.execute(
            "SELECT path, sha256, char_start, char_end FROM answer_passage "
            "WHERE answer_id=? AND n=?",
            (answer_id, n),
        ).fetchone()
        check = {"position": pos, "passage": n, "path": None, "ok": False}
        if rec is None:
            check["reason"] = "no_passage_record"
            checks.append(check)
            continue
        path, sha, start, end = rec
        check["path"] = path
        item = conn.execute(
            "SELECT sha256, withdrawn_at FROM item WHERE path=?", (path,)
        ).fetchone()
        full = conn.execute(
            "SELECT extracted_text FROM files WHERE rel_path=?", (path,)
        ).fetchone()
        if item is None or item[1] or full is None:
            check["reason"] = "item_withdrawn"
        elif item[0] != sha:
            check["reason"] = "item_changed"
        elif not full[0]:
            check["reason"] = "text_missing"
        else:
            text = full[0]
            if start is not None and end is not None:
                # The passage was widened to whole sentences, never by more
                # than MAX_EXTEND_CHARS a side.
                text = text[max(0, start - MAX_EXTEND_CHARS) : end + MAX_EXTEND_CHARS]
            if _squash(str(q.get("text", ""))) and _squash(q["text"]) in _squash(text):
                check["ok"] = True
                check["reason"] = "ok"
            else:
                check["reason"] = "quote_not_in_item"
        checks.append(check)
    return {
        "answer_id": answer_id,
        "quotes": checks,
        "all_verified": all(c["ok"] for c in checks),
    }


def answer_view(conn: sqlite3.Connection, answer_id: int) -> dict | None:
    row = conn.execute(
        "SELECT id, asked_at, question, answer_json, model FROM answer WHERE id=?",
        (answer_id,),
    ).fetchone()
    if row is None:
        return None
    cites = conn.execute(
        "SELECT c.path, "
        "EXISTS(SELECT 1 FROM tombstone t WHERE t.sha256 = c.sha256 AND c.sha256 != '') "
        "FROM answer_citation c WHERE c.answer_id=? ORDER BY c.path",
        (answer_id,),
    ).fetchall()
    return {
        "answer_id": row[0],
        "asked_at": row[1],
        "question": row[2],
        "answer": json.loads(row[3]),
        "model": row[4],
        "cited_paths": [c[0] for c in cites],
        "withdrawn_sources": [c[0] for c in cites if c[1]],
        "verification": verify_answer(conn, answer_id),
    }
