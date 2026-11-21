"""Scoring one archive answer against a checked question.

The question set lives in fixtures/press-eval/questions.jsonl (the open test
archive); scripts/archive_score.py runs it through `ask` with any local model.

A question is scored against the consent in force when it is asked. It lists
alternative source sets (`sources`): each is the items an answer can rest on
and the pipeline stages (`needs`) that set depends on. The same fact can sit in
a letter and in the minutes that restate it, so any one set will do. If no set
is fully open to the model and buildable, the right result is "not answered",
and an answer that cites something else instead is wrong. That keeps the score
honest about consent: the model is never credited for working around a
writer's choice.

Older questions with `must_cite` and `needs` are one set.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

# Validator drop reasons that mean the model tried to cite or quote outside
# what it was given, or wrote a quotation that is not in its passages.
MISQUOTE_REASONS = frozenset(
    {
        "cite_outside_set",
        "names_passage_outside_set",
        "quote_pointer_invalid",
        "unverified_inline_quote",
    }
)


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


@dataclass
class Score:
    id: str
    job: str
    expected: str  # "answer" | "not_answered"
    why_not: list[str] = field(default_factory=list)
    correct: bool = False
    answered: bool = False
    fact_found: bool = False
    cite_hit: bool = False
    cited_paths: list[str] = field(default_factory=list)
    off_target_cites: int = 0
    misquote: bool = False
    dropped: dict[str, int] = field(default_factory=dict)
    seconds: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


def source_sets(q: dict) -> list[dict]:
    """The question's alternative source sets: [{"paths": [...], "needs": [...]}].
    A legacy question (`must_cite` + `needs`) is one set; no paths at all is no
    set, which means the archive has no answer."""
    if "sources" in q:
        sets = [
            {"paths": list(s.get("paths") or []), "needs": list(s.get("needs") or [])}
            for s in q["sources"] or []
        ]
    else:
        sets = [
            {
                "paths": list(q.get("must_cite") or []),
                "needs": list(q.get("needs") or []),
            }
        ]
    return [s for s in sets if s["paths"]]


def _set_reasons(s: dict, consent: dict[str, str]) -> list[str]:
    return [f"needs:{n}" for n in s["needs"]] + [
        f"closed:{p}" for p in s["paths"] if consent.get(p) != "model"
    ]


def expectation(q: dict, consent: dict[str, str]) -> tuple[str, list[str]]:
    """What a correct result is for this question under `consent`
    ({path: level}), and why if it is "not_answered": the reasons of the set
    that is closest to open (fewest reasons)."""
    sets = source_sets(q)
    if not sets:
        return "not_answered", ["archive_has_no_answer"]
    reasons = [_set_reasons(s, consent) for s in sets]
    if any(not r for r in reasons):
        return "answer", []
    return "not_answered", min(reasons, key=len)


def _score(
    q: dict,
    consent: dict[str, str],
    *,
    cited: list[str],
    answered: bool,
    text: str,
    dropped: dict[str, int],
    seconds: float,
) -> Score:
    expected, why = expectation(q, consent)
    s = Score(id=q["id"], job=q.get("job", ""), expected=expected, why_not=why)
    sets = source_sets(q)
    every = {p for st in sets for p in st["paths"]}
    usable = {
        p for st in sets if not _set_reasons(st, consent) for p in st["paths"]
    } or every
    s.cited_paths = sorted(cited)
    s.answered = answered
    s.cite_hit = bool(usable & set(cited))
    s.off_target_cites = len([p for p in cited if p not in every])
    s.fact_found = any(norm(e) in norm(text) for e in q.get("expect_any") or [])
    s.dropped = dict(dropped)
    s.misquote = any(s.dropped.get(r) for r in MISQUOTE_REASONS)
    s.seconds = seconds
    if expected == "answer":
        s.correct = s.answered and s.fact_found and s.cite_hit
    else:
        s.correct = not s.answered
    return s


def _answer_text(answer: list[dict]) -> str:
    return " ".join(
        sent["text"] + " " + ((sent.get("quote") or {}).get("text") or "")
        for sent in answer
    )


def score_one(q: dict, out: dict, consent: dict[str, str]) -> Score:
    by_n = {p["n"]: p["path"] for p in out.get("passages", [])}
    cited = {by_n[c] for sent in out["answer"] for c in sent["cites"] if c in by_n}
    t = out.get("timing") or {}
    return _score(
        q,
        consent,
        cited=sorted(cited),
        answered=bool(out["answer"]) and not out.get("not_answered"),
        text=_answer_text(out["answer"]),
        dropped=out.get("dropped") or {},
        seconds=round(float(t.get("retrieve_s", 0)) + float(t.get("model_s", 0)), 2),
    )


def score_saved(q: dict, saved: dict, consent: dict[str, str]) -> Score:
    """Score again a result line saved by scripts/archive_score.py, with no
    model call: the answer text, the cited paths and the timing were kept."""
    old = saved["score"]
    return _score(
        q,
        consent,
        cited=list(old.get("cited_paths") or []),
        answered=bool(old.get("answered")),
        text=_answer_text(saved.get("answer") or []),
        dropped=old.get("dropped") or {},
        seconds=float(old.get("seconds", 0)),
    )


def score_plain(q: dict, line: dict, consent: dict[str, str]) -> Score:
    """Score a result in the plain format any system can write (the open test
    archive's run_score.py): `answered`, `text` (the whole answer, quotes
    included), `cited_paths`, optional `seconds`."""
    return _score(
        q,
        consent,
        cited=list(line.get("cited_paths") or []),
        answered=bool(line.get("answered")),
        text=str(line.get("text") or ""),
        dropped={},
        seconds=float(line.get("seconds") or 0),
    )


def summarize(scores: list[Score]) -> dict:
    def rate(xs: list[bool]) -> float | None:
        return round(sum(xs) / len(xs), 3) if xs else None

    secs = sorted(s.seconds for s in scores)
    by_job: dict[str, list[Score]] = {}
    for s in scores:
        by_job.setdefault(s.job, []).append(s)
    ans = [s for s in scores if s.expected == "answer"]
    return {
        "questions": len(scores),
        "accuracy": rate([s.correct for s in scores]),
        "accuracy_answerable_now": rate([s.correct for s in ans]),
        "answerable_now": len(ans),
        "misquote_rate": rate([s.misquote for s in scores]),
        "answers_with_off_target_cites": rate([s.off_target_cites > 0 for s in ans]),
        "seconds_p50": secs[len(secs) // 2] if secs else None,
        "seconds_max": secs[-1] if secs else None,
        "by_job": {
            j: {"n": len(v), "correct": sum(s.correct for s in v)}
            for j, v in sorted(by_job.items())
        },
    }
