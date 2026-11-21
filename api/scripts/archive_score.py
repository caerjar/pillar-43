"""Run the open test archive's questions through ask and score them.

    docker exec -i archive-api-1 python scripts/archive_score.py \
        [--model qwen3:8b] [--unconstrained] [--limit N] \
        < fixtures/press-eval/questions.jsonl > results.jsonl

Reads questions (JSON lines) on stdin. Writes one JSON line per question
(score, the answer, timing) and a last line {"summary": ...}: accuracy,
misquote rate, seconds per answer. Progress goes to stderr. Scored against the
consent in force in this archive; see services/archive/score.py.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.archive.ask import ask
from services.archive.items import item_meta
from services.archive.score import score_one, source_sets, summarize
from services.db import get_db


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=None)
    ap.add_argument("--unconstrained", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    questions = [json.loads(line) for line in sys.stdin if line.strip()]
    if args.limit:
        questions = questions[: args.limit]
    paths = sorted({p for q in questions for s in source_sets(q) for p in s["paths"]})
    conn = get_db()
    try:
        consent = {p: m["consent"] for p, m in item_meta(conn, paths).items()}
    finally:
        conn.close()

    scores = []
    for i, q in enumerate(questions, 1):
        try:
            out = ask(
                q["question"], model=args.model, constrained=not args.unconstrained
            )
        except OSError as exc:  # timeout or Ollama down: a wrong answer, not a crash
            out = {
                "answer": [],
                "not_answered": True,
                "passages": [],
                "dropped": {},
                "timing": {},
                "model": args.model or "default",
                "constrained": not args.unconstrained,
                "error": f"{type(exc).__name__}: {exc}",
            }
        s = score_one(q, out, consent)
        scores.append(s)
        print(
            json.dumps(
                {
                    "score": s.to_dict(),
                    "question": q["question"],
                    "answer": out["answer"],
                    "not_answered": out["not_answered"],
                    "model": out["model"],
                    "constrained": out["constrained"],
                    "truncated": out.get("truncated", False),
                    "error": out.get("error"),
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        print(
            f"{i}/{len(questions)} {s.id} {'ok ' if s.correct else 'BAD'} {s.seconds}s",
            file=sys.stderr,
            flush=True,
        )
    summary = summarize(scores)
    summary["model"] = args.model or "default"
    summary["constrained"] = not args.unconstrained
    print(json.dumps({"summary": summary}), flush=True)


if __name__ == "__main__":
    main()
