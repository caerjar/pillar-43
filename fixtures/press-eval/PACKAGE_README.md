# Lantern Wharf Editions: an open test archive

A small literary press that does not exist: contracts, board minutes,
correspondence, manuscripts with tracked changes, a catalog and recordings,
all invented. With 50 questions a press's staff would ask of it, each with a
hand-checked answer and the items it can rest on. Use it to test any system
that answers questions from an archive and cites its sources.

- `library/` — the archive. Cite items by their path, starting `library/`.
- `questions.jsonl` — one question per line: `id`, `job`, `question`, `answer`,
  `expect_any` (spans a correct answer must contain, any one), `sources`
  (alternative sets of items the answer can rest on, each with the pipeline
  stages it `needs`: `transcribe`, `tracked_changes`, `email`). An empty set
  means the archive has no answer, and the right result is to decline.
- `answer-keys/` — what the generator knows; keep it away from your system.
- `run_score.py` + `score.py` — the scorer. Python 3.10+, nothing to install.

## Scoring

    python run_score.py questions.jsonl results.jsonl [--consent consent.json]

`results.jsonl`, one line per question:

    {"id": "q001", "answered": true, "text": "the whole answer, quotes included",
     "cited_paths": ["library/contracts/....pdf"], "seconds": 3.1}

An answer is correct when it answers, contains one of `expect_any`, and cites
an item from an open source set. When no set is open (an item is private in
`consent.json`, or a set needs a stage your system does not have, which you
mark by closing those items), the only correct result is to decline. The score
never credits an answer that works around a closed item.

The summary reports accuracy overall and on the questions answerable under
the given consent, misquotes, answers citing items outside every source set,
and seconds p50/max.

Licence: CC BY 4.0 for the archive and questions; Apache-2.0 for the
scorer. See LICENSE.
