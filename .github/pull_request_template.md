## What and why

<!-- What changed, and what problem it solves. The diff shows what; explain why. -->

## Verification

<!-- How you confirmed this works. "Tests pass" alone is not enough for a
     user-facing change — say what you actually did. -->

- [ ] `./scripts/test-api` passes
- [ ] `cd web && npm test -- --run` passes
- [ ] `cd web && npx tsc --noEmit` clean
- [ ] Containers rebuilt (`docker compose up --build -d`) if backend/frontend code changed
- [ ] I used the feature, not just the test suite

<!-- If this adds a regression guard: did you watch it fail against the bug
     before fixing it? A guard that never went red hasn't been verified. -->

## Checklist

- [ ] On a `feat/*` branch (not main)
- [ ] Commit subjects are `<type>: <subject>`, imperative, ≤70 chars
- [ ] `CHANGELOG.md` `[Unreleased]` bullet added
- [ ] `MANUAL.md` / `DEV_MANUAL.md` updated if user- or tooling-facing
- [ ] Neither ratchet raised (ESLint `--max-warnings`, ruff `max-complexity`)

## Notes for the reviewer

<!-- Anything you're unsure about, deliberately left out, or want argued with. -->
