"""Score any system's answers against the open test archive.

    python run_score.py questions.jsonl results.jsonl [--consent consent.json]

`results.jsonl` has one line per question:
    {"id": "q001", "answered": true, "text": "<the whole answer, quotes included>",
     "cited_paths": ["library/contracts/....pdf"], "seconds": 3.1}
`cited_paths` are paths under `library/`, as in each question's `sources`.

`consent.json` (optional) maps a path to private / staff / model. A path not
listed is open to the model. A question whose every source set has a closed or
unbuildable item is expected to come back not answered.

Prints one JSON line per scored question and a last {"summary": ...}.
Needs Python 3.10+ and nothing else; `score.py` sits beside this file.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from score import score_plain, source_sets, summarize


def main(argv: list[str]) -> int:
    if len(argv) not in (2, 4) or (len(argv) == 4 and argv[2] != "--consent"):
        print(__doc__, file=sys.stderr)
        return 2
    questions = {
        q["id"]: q
        for q in (
            json.loads(ln)
            for ln in Path(argv[0]).read_text(encoding="utf-8").splitlines()
            if ln.strip()
        )
    }
    given = json.loads(Path(argv[3]).read_text()) if len(argv) == 4 else {}
    consent = {
        p: given.get(p, "model")
        for q in questions.values()
        for st in source_sets(q)
        for p in st["paths"]
    }
    scores = []
    for ln in Path(argv[1]).read_text(encoding="utf-8").splitlines():
        if not ln.strip():
            continue
        line = json.loads(ln)
        sc = score_plain(questions[line["id"]], line, consent)
        scores.append(sc)
        print(json.dumps({"score": sc.to_dict()}, ensure_ascii=False))
    print(json.dumps({"summary": summarize(scores)}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
