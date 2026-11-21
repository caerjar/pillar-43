# Baseline rescored with alternative source sets

Run: `2026-11-18-baseline-qwen3-8b-constrained.jsonl` (qwen3:8b, constrained, 50 questions). Rescored with no model call:

    python scripts/archive_rescore.py ../fixtures/press-eval/questions.jsonl \
        ../docs/eval/2026-11-18-baseline-qwen3-8b-constrained.jsonl \
        > ../docs/eval/2026-11-18-baseline-rescored-alt-sources.jsonl

Questions now list `sources`: alternative sets of items, each with its own `needs`. An answer is expected when any set is fully open to the model and buildable. Four questions have a second set because the open board minutes restate the fact: q003 (cure end date, April and September minutes), q025 (award size and reference), q026 (interim report date), q032 (cover version and sign-off date). Rejected as coincidental or partial: q006 (a different book's contract mentions Canada), q022 (minutes give only the expected date, not the outcome), q033 (minutes give the consent date, not the condition).

| | before | after |
|---|---|---|
| questions answerable now | 19 | 23 |
| accuracy, all 50 | 0.28 | 0.36 |
| accuracy, answerable now | 0.632 (12/19) | 0.696 (16/23) |
| answers citing an item outside every source set | 0.316 | 0.261 |
| misquote rate | 0 | 0 |

Only the scoring changed; the answers are the saved ones.
