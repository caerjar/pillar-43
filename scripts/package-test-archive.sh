#!/usr/bin/env bash
# Build the open test archive (CC BY 4.0) as a folder anyone can use without
# Pillar-43: the synthetic press under library/, the questions, the answer keys,
# the scorer and its runner.
#
#   scripts/package-test-archive.sh <out-dir>
#
# Gate: api/tests/test_open_test_archive.py runs the scorer from this layout.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd -P)"
OUT="${1:?usage: package-test-archive.sh <out-dir>}"
if [[ -e "$OUT" ]]; then
  echo "refusing: $OUT exists" >&2
  exit 1
fi
mkdir -p "$OUT"
cp -R "$ROOT/fixtures/synthetic-press" "$OUT/library"
cp -R "$ROOT/fixtures/press-eval/answer-keys" "$OUT/answer-keys"
cp "$ROOT/fixtures/press-eval/questions.jsonl" "$ROOT/fixtures/press-eval/run_score.py" "$OUT/"
cp "$ROOT/api/services/archive/score.py" "$OUT/score.py"
cp "$ROOT/fixtures/make_synthetic_press.py" "$OUT/"
cp "$ROOT/fixtures/press-eval/PACKAGE_README.md" "$OUT/README.md"
cat > "$OUT/LICENSE" <<'LIC'
The Lantern Wharf Editions test archive (library/, questions.jsonl,
answer-keys/, make_synthetic_press.py) is licensed under the Creative Commons
Attribution 4.0 International License (CC BY 4.0).
Full text: https://creativecommons.org/licenses/by/4.0/legalcode
Attribution: "Lantern Wharf Editions test archive, Eon Meridian (Pillar-43)".

score.py and run_score.py are licensed under Apache-2.0, as is Pillar-43.
Everything in the press is invented: no real person, contract or letter.
LIC
find "$OUT" -name '.DS_Store' -delete
echo "wrote $OUT ($(find "$OUT" -type f | wc -l | tr -d ' ') files)"
