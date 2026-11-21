"""Replay the newest committed Lantern Wharf run without a model.

docs/eval/*.jsonl holds saved runs of the 50 press questions. A saved line
keeps the validated answer (sentences, quotes, cites as passage numbers), the
cited paths, the validator's drop counts and the score. It does NOT keep the
raw model output or the numbered passages, so `validate` itself cannot be run
again from a saved run; that needs a model. What can be replayed is the
model-free rescore (`services.archive.score.score_saved`, the same code as
api/scripts/archive_rescore.py) under today's questions.jsonl and scorer.

Failing here means one of: a question that answered in the saved run now
scores as not answered or no longer correct; a kept cite now falls outside the
question's listed sources, or a question picked up more off-target cites; a
question's expected answer or source sets changed under the saved run.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.archive.score import score_saved, source_sets

_ROOTS = [Path("/repo"), Path(__file__).resolve().parents[2]]
ROOT = next((p for p in _ROOTS if (p / "docs" / "eval").is_dir()), None)

pytestmark = pytest.mark.skipif(
    ROOT is None or not (ROOT / "fixtures" / "press-eval").is_dir(),
    reason="repo docs/eval and fixtures not mounted",
)


def _jsonl(path: Path) -> list[dict]:
    return [
        json.loads(ln)
        for ln in path.read_text(encoding="utf-8").splitlines()
        if ln.strip()
    ]


def _questions() -> dict[str, dict]:
    path = ROOT / "fixtures" / "press-eval" / "questions.jsonl"
    return {q["id"]: q for q in _jsonl(path)}


def _latest_run() -> Path:
    # Names start with an ISO date; the baseline-rescored file is a derived
    # copy, not a model run.
    runs = sorted(
        p
        for p in (ROOT / "docs" / "eval").glob("*-constrained.jsonl")
        if "rescored" not in p.name
    )
    return runs[-1]


def _replay():
    questions = _questions()
    saved = [s for s in _jsonl(_latest_run()) if "score" in s]
    # As in archive_rescore.py: a path the run reported as `closed:` was not
    # open to the model; every other listed path was.
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
    out = []
    for s in saved:
        q = questions[s["score"]["id"]]
        out.append((s, q, score_saved(q, s, consent)))
    return out


def test_the_latest_saved_run_covers_every_question():
    replayed = {s["score"]["id"] for s, _, _ in _replay()}
    assert replayed == set(_questions())


def test_no_answered_question_now_declines_or_loses_its_fact_or_source():
    broken = []
    for s, q, now in _replay():
        old = s["score"]
        if old["answered"] and not now.answered:
            broken.append((q["id"], "answered then, declines now"))
        if old["correct"] and not now.correct:
            broken.append((q["id"], "was correct, not correct now"))
        for field in ("expected", "fact_found", "cite_hit"):
            if old[field] != getattr(now, field):
                broken.append(
                    (q["id"], f"{field}: {old[field]} -> {getattr(now, field)}")
                )
    assert broken == []


def test_kept_cites_stay_inside_the_questions_listed_sources():
    # Saved runs do keep some off-target cites (the model cited a related
    # item). A question may not gain any beyond what the run recorded.
    over = []
    for s, q, now in _replay():
        listed = {p for st in source_sets(q) for p in st["paths"]}
        outside = [p for p in now.cited_paths if p not in listed]
        if len(outside) > s["score"]["off_target_cites"]:
            over.append((q["id"], outside))
    assert over == []
