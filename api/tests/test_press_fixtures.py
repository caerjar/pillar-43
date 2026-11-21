"""The synthetic press is an archive: nothing in it may be an answer key.

`_truth.json` (expected clause text) and `_script.json` (what the recordings
say) used to sit inside the press folder, so intake took them in as items, and
the model could read the answers it was being scored against. They live with
the questions now, in fixtures/press-eval/answer-keys/.

The test compose file mounts ./fixtures at /fixtures; elsewhere the tests find
the repo's own fixtures directory.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

_CANDIDATES = [Path("/fixtures"), Path(__file__).resolve().parents[2] / "fixtures"]
FIXTURES = next((p for p in _CANDIDATES if (p / "press-eval").is_dir()), None)

pytestmark = pytest.mark.skipif(FIXTURES is None, reason="fixtures not mounted")


def test_no_answer_key_sits_inside_the_press():
    press = FIXTURES / "synthetic-press"
    keys = [p for p in press.rglob("_*.json")]
    assert keys == []


def test_the_answer_keys_live_with_the_questions():
    keys = FIXTURES / "press-eval" / "answer-keys"
    truth = json.loads((keys / "contracts_truth.json").read_text(encoding="utf-8"))
    script = json.loads((keys / "recordings_script.json").read_text(encoding="utf-8"))
    assert len(truth["contracts"]) == 6
    assert len(script["recordings"]) == 3


def test_every_question_source_is_an_item_of_the_press():
    # `library/x` in a question is `fixtures/synthetic-press/x` on disk.
    press = FIXTURES / "synthetic-press"
    missing = []
    for line in (FIXTURES / "press-eval" / "questions.jsonl").read_text().splitlines():
        q = json.loads(line)
        for s in q["sources"]:
            for path in s["paths"]:
                if not (press / path.removeprefix("library/")).is_file():
                    missing.append((q["id"], path))
    assert missing == []
