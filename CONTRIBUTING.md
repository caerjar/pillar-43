# Contributing to Pillar-43

Thanks for looking. This project has a few conventions that are load-bearing
rather than stylistic — the sections below are the ones where guessing wrong
costs you a rejected PR or a rolled-back merge.

## Setup

```bash
ollama pull qwen3:8b     # the answer model, in Ollama on the host
make archive             # build and load the synthetic press: web :5211, api :8061
pre-commit install       # see "Gates" below
```

`./pillar43` and the `make` targets run
`scripts/ensure-host-files.sh` for you. If you bring the stack up with a bare
`docker compose up` instead, run that script first — `libraries.conf` and
`docker-compose.override.yml` are bind-mounted as individual files and are
gitignored, so a fresh clone has neither, and Docker answers a missing
bind-mount source by silently creating a *directory* there. See SECURITY.md.

## Gates

Everything that gates a PR also runs locally. CI runs ESLint, mypy, ruff,
both test suites, and five docs-vs-code drift linters, so a green local
`pre-commit` is a good predictor of a green PR.

```bash
./scripts/test-api            # backend, parallel, container-reused
./scripts/test-api-fast       # fast subset
cd web && npm test -- --run   # frontend
cd web && npx tsc --noEmit
```

**Never run `python -m pytest` directly** — the suite needs the container's
environment and fixture mounts. Use `./scripts/test-api`.

**Never run `npm run dev` inside Docker.**

Four ratchets exist and may only ever move down. Each is set at the
**measured** value, not an aspiration — their job is to stop things sliding
backwards, so raising one to admit a new violation defeats the point.

| Ratchet | Current | Where it lives |
|---|---|---|
| ESLint warnings | `--max-warnings=11` | `.pre-commit-config.yaml`, both `.github/workflows/`, and the header comment in `web/eslint.config.js` |
| Cyclomatic complexity | `max-complexity = 34` | `ruff.toml` |
| Frontend coverage | 56 / 70 / 38 / 56 (stmt/branch/func/line) | `web/vite.config.ts` |
| Backend coverage | `fail_under = 75` | `api/.coveragerc` |

The ESLint number lives in **four files** and has drifted twice — this line
once read 44 and `DEV_MANUAL.md` read 61 while the gate was actually 39.
Change all four together, or the docs go back to lying about the gate.

Both coverage floors carry a dated measurement log in their config comments.
Raise them only after writing tests, and record the new measurement there.

## Branching

`main → feat/<name>`. **Never commit to main directly**, even for a
one-line fix. Merge via `/feature-close`, which also handles the CHANGELOG.

## Commits

```
<type>: <subject>
```

`type` ∈ `feat` `fix` `chore` `test` `docs` `refactor`. Imperative mood,
subject ≤ 70 characters. `scripts/safe-commit` enforces both and refuses to
commit to main without `--allow-main`.

Explain *why* in the body. The commit log here is used as a record of
decisions, so "what changed" is the diff's job and "why" is yours.

## Definition of done

A change is not done until:

- It is on a `feat/*` branch with tests passing.
- Containers are rebuilt if backend or frontend code changed
  (`docker compose up --build -d`) — code is baked in at build time, so
  without `--build` you are running the previous image.
- You have **used the feature**, not just watched the tests pass.
- `CHANGELOG.md` has an `[Unreleased]` bullet.
- `MANUAL.md` (user-facing) or `DEV_MANUAL.md` (commands/tooling) is updated.

"The code looks right" is not verification. Neither is "it should work after
a rebuild."

## Two rules that have caused rollbacks

**Never decompose untested code.** Add the tests first. A previous refactor
was reverted for skipping this.

**Audit test-patch coupling before splitting a Python module.** Tests here
patch by module path (`monkeypatch.setattr("services.x.y", ...)`), so moving
a symbol silently breaks the patch target rather than failing loudly. Grep
for the symbol across `api/tests/` and pick a shim, DI, or migration
strategy explicitly before you move it.

**A regression guard isn't done until you've watched it fail.** Write the
test, reintroduce the bug, confirm the suite goes red, then restore from a
backup copy — not from memory — and diff against HEAD to prove the injection
is gone. A guard that passes against the broken code certifies the very
thing it was meant to catch.

Note that some guards fail *ungracefully*: `Editor.freeze.test.tsx` catches
its regression by hanging, because the bug is a synchronous infinite render
loop that blocks the event loop before vitest can fire its own timeout. In
CI that surfaces as a job timeout, not an assertion failure.

## Architecture orientation

Each area has a README listing its modules: `api/routes/README.md`,
`api/services/README.md`, `web/src/components/README.md` and
`web/src/hooks/README.md`. Read the one for the area you're touching before
you change it.

## Releasing

The git tag is the version — see [RELEASING.md](RELEASING.md). Short form:
move `[Unreleased]` to a `## [x.y.z]` heading in `CHANGELOG.md`, then push an
annotated `vx.y.z` tag. The workflow re-runs every gate against the tagged
commit before publishing anything.

## Security

Please don't open a public issue for a vulnerability — see
[SECURITY.md](SECURITY.md), which also lists the risks this project
knowingly accepts (there is no authentication; it is loopback-only by
design).
