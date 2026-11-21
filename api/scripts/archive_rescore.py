"""Score a saved run again under the current questions. No model calls, no DB.

    python scripts/archive_rescore.py fixtures/press-eval/questions.jsonl \
        docs/eval/2026-11-18-baseline-qwen3-8b-constrained.jsonl > rescored.jsonl

Consent is read back from the saved run: a path the run's own scorer reported
as `closed:` was not open to the model; every other path in a question's source
sets was. The old scorer wrote those reasons for each question it expected to be
"not answered". Writes one JSON line per question and a last {"summary": ...}.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.archive.score import score_saved, source_sets, summarize


def main(questions_path: str, saved_path: str) -> None:
    questions = {}
    for line in Path(questions_path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            q = json.loads(line)
            questions[q["id"]] = q
    saved = [
        json.loads(ln)
        for ln in Path(saved_path).read_text(encoding="utf-8").splitlines()
        if ln.strip()
    ]
    saved = [s for s in saved if "score" in s]
    closed = {
        r[len("closed:") :]
        for s in saved
        for r in s["score"].get("why_not") or []
        if r.startswith("closed:")
    }
    consent = {
        p: ("private" if p in closed else "model")
        for q in questions.values()
        for st in source_sets(q)
        for p in st["paths"]
    }
    scores = []
    for s in saved:
        q = questions[s["score"]["id"]]
        sc = score_saved(q, s, consent)
        scores.append(sc)
        print(
            json.dumps(
                {
                    "score": sc.to_dict(),
                    "question": q["question"],
                    "answer": s.get("answer"),
                    "not_answered": s.get("not_answered"),
                },
                ensure_ascii=False,
            )
        )
    summary = summarize(scores)
    summary["rescored_from"] = Path(saved_path).name
    print(json.dumps({"summary": summary}))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
