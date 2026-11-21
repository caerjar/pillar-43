"""E3: the open test archive scores from its own package, with no app code.

The package is fixtures/press-eval plus a copy of services/archive/score.py
(scripts/package-test-archive.sh). This test builds the same layout in a temp
dir and runs the scorer there in a fresh interpreter, so an import of anything
from the app would fail it.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

API = Path(__file__).resolve().parents[1]
EVAL = Path("/fixtures/press-eval")


@pytest.fixture
def package(tmp_path):
    if not EVAL.exists():
        pytest.skip("fixtures not mounted")
    pkg = tmp_path / "pkg"
    shutil.copytree(EVAL, pkg)
    shutil.copy(API / "services/archive/score.py", pkg / "score.py")
    return pkg


def _run(pkg: Path, *args: str) -> list[dict]:
    r = subprocess.run(
        [sys.executable, "-I", str(pkg / "run_score.py"), *args],
        cwd=pkg,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert r.returncode == 0, r.stderr
    return [json.loads(ln) for ln in r.stdout.splitlines() if ln.strip()]


def test_scorer_runs_from_the_package(package, tmp_path):
    q = json.loads((package / "questions.jsonl").read_text().splitlines()[0])
    results = tmp_path / "results.jsonl"
    results.write_text(
        json.dumps(
            {
                "id": q["id"],
                "answered": True,
                "text": "Clause 2: " + q["expect_any"][0] + ", paperback.",
                "cited_paths": q["sources"][0]["paths"],
                "seconds": 3.0,
            }
        )
        + "\n"
        + json.dumps(
            {"id": "q002", "answered": True, "text": "no idea", "cited_paths": []}
        )
        + "\n"
    )
    out = _run(package, "questions.jsonl", str(results))
    scores = {o["score"]["id"]: o["score"] for o in out if "score" in o}
    assert scores[q["id"]]["correct"] is True
    assert scores["q002"]["correct"] is False
    summary = out[-1]["summary"]
    assert summary["questions"] == 2 and summary["accuracy"] == 0.5


def test_a_private_source_makes_the_right_answer_a_decline(package, tmp_path):
    q = json.loads((package / "questions.jsonl").read_text().splitlines()[0])
    consent = tmp_path / "consent.json"
    consent.write_text(json.dumps({p: "private" for p in q["sources"][0]["paths"]}))
    results = tmp_path / "results.jsonl"
    results.write_text(json.dumps({"id": q["id"], "answered": False}) + "\n")
    out = _run(package, "questions.jsonl", str(results), "--consent", str(consent))
    assert out[0]["score"]["expected"] == "not_answered"
    assert out[0]["score"]["correct"] is True
