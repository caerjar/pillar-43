# Open test set for the synthetic press

Questions for `fixtures/synthetic-press` (Lantern Wharf Editions, fully invented; CC BY 4.0 with the press). Kept outside the press folder so it is never taken in as an archive item.

`questions.jsonl`, one question per line: `id`, `job`, `question` (as staff would ask it), `answer` (checked by hand against the source), `expect_any` (short spans, any one of which a correct answer must contain, each verbatim in a cited source), `sources` (alternative sets of items the answer can rest on: `[{"paths": [...], "needs": [...]}, ...]`; `needs` lists the pipeline stages that set depends on and that are not built yet: `transcribe`, `tracked_changes`, `email`). Several sets are for a fact stated in more than one place, such as a letter and the minutes that restate it; an empty `paths` means the archive has no answer.

`answer-keys/` holds what the generator knows and the archive must not: `contracts_truth.json` (expected fields and verbatim clause text) and `recordings_script.json` (what the recordings say). They used to sit inside the press, where intake took them in as items.

Run with any local model:

    docker exec -i pillar43-api-1 python scripts/archive_score.py [--model qwen3:8b] [--unconstrained] \
        < fixtures/press-eval/questions.jsonl > results.jsonl

Scoring rules are in `api/services/archive/score.py`: a question is expected to be answered if any source set is fully open to the model and buildable; otherwise it is correct only when it comes back not answered. `api/scripts/archive_rescore.py` scores a saved run again without the model.

To score another system without Pillar-43: `scripts/package-test-archive.sh <dir>` builds the open test archive (press under `library/`, questions, answer keys, `run_score.py` + `score.py`, LICENSE); `run_score.py` takes a plain results format, described in `PACKAGE_README.md`.

50 questions now (milestone 1); 200 by milestone 3.
