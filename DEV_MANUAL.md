# Pillar-43 — Developer Manual

Commands and tooling for building Pillar-43. For the product and its rules read
`PROJECT.md`; for finding things, the module READMEs (`api/routes/README.md`,
`api/services/README.md`, `web/src/components/README.md`). To run an install, see
`DEPLOYMENT_GUIDE.md`.

The repo root is the git root. There is no `src/` directory.

## Stack

| Layer | Tech | Port | Notes |
|-------|------|------|-------|
| API | Python 3.12, FastAPI | 8000 in the container; host `API_PORT` (default 8002; 8061 for `make archive`) | Routes in `api/routes/`, services in `api/services/` |
| Web | React 18, TypeScript, Vite; nginx in production | host `WEB_PORT` (default 5173; 5211 for `make archive`) | Zustand global state, TanStack Query server state |
| DB | SQLite WAL | | `/data/pillar43.db` in the `pillar43_data` named volume (`settings.db_path`) |
| Vectors | SQLite table `chunk_vectors`, numpy search | | `api/services/vector_store.py` |
| Embeddings | fastembed, in the api process | | `api/services/embeddings.py` |
| Models | Ollama on the host | 11434 | `OLLAMA_URL`; no hosted providers |
| Search | ripgrep | | Always `--fixed-strings --ignore-case` |

There is no worker container, no Qdrant and no embeddings container. Background
work runs inside the api process.

Containers are named `<compose project>-api-1` and `<compose project>-web-1`:
`pillar43-api-1` by default and for `make archive` (`ARCHIVE_PROJECT`).

## Makefile

```bash
make dev              # hot-reload dev stack (Vite HMR + uvicorn --reload)
make build            # production images, detached (`make logs` to follow)
make stop             # docker compose down
make restart          # stop, then dev
make status           # docker compose ps
make logs             # all logs (also logs-api, logs-web)

# Pillar-43 (Local Archive): its own compose project, API 8061, web 5211
make archive          # up + intake + index + open contracts and "yellow" documents to the AI
make archive-ask Q="Where can we sell the Lanterns book?"
make archive-status   # containers + consent counts
make archive-logs     # tail the archive api
make archive-stop     # down; the data volume is kept
make archive-backup   # consent, withdrawals, accounts, ledger -> ./backups/governance-*.sqlite (verified)
make archive-restore FILE=backups/governance-....sqlite   # FORCE=--force to replace a longer ledger

make test             # backend + frontend
make test-backend     # ./scripts/test-api
make test-backend-v   # verbose
make test-file f=tests/test_search.py
make test-frontend    # npm test -- --run (Vitest, no Docker)
make typecheck        # npx tsc --noEmit
make test-all         # test + typecheck
make lint             # ruff check (in the test container)
make format           # ruff format
make shell-api        # bash in the api container (also shell-web)
make clean            # down --volumes --remove-orphans; refuses unless a backup covers the ledger
                      # (make archive-backup) or CONFIRM_DATA_LOSS=yes; same guard on ./pillar43 reset [--hard]
make reset            # ./pillar43 reset: wipe app data, keep notes + .env
make reset-hard       # ./pillar43 reset --hard: also containers, images, .env
make install-hooks    # one-time: install the pre-commit hooks
make ensure-host-files  # create the two bind-mounted host files if missing
```

`make archive` runs intake again and reopens every contract and "yellow"
document to the AI. Do not use it to restart (see `DEPLOYMENT_GUIDE.md`).

`make dev`, `make build` and `make archive` depend on `ensure-host-files`, which
creates `libraries.conf` and `docker-compose.override.yml` if a fresh clone lacks
them. A bare `docker compose up` does not: run `bash scripts/ensure-host-files.sh`
first. Both files are bind-mounted individually so the rest of the project root
can stay read-only to the api container, and Docker answers a missing bind-mount
source by creating a *directory*. See `SECURITY.md`.

### Archive CLI

Run inside the archive api container (output in `generated/archive/`). Replace
`pillar43` with your `ARCHIVE_PROJECT` if you changed it.

```bash
docker exec pillar43-api-1 python scripts/archive_cli.py counts
docker exec pillar43-api-1 python scripts/archive_cli.py job rights-answer "The Drowned Orchard"
#   other jobs: editorial-history, teaching-packet. --cover-note adds the one
#   model call and limits the job to model-level items (without it staff-level
#   items enter).
docker exec pillar43-api-1 python scripts/archive_cli.py stats     # stats.json, counted by code
docker exec pillar43-api-1 python scripts/archive_cli.py consent 'glob:*yellow*' model
```

Explore and People are staff/admin endpoints: `POST /api/archive/explore`
(`{"query": "yellow", "summarize": true}`) and `GET /api/archive/people`,
`GET /api/archive/people/{name}`.

**Never pass a password as a command-line argument**: it is saved in the shell
history and visible in the process list. To create an account, read it silently
first (the pattern from `docs/guides/install.md`, Step 7):

```bash
printf 'Administrator name: '; read ADMIN_NAME
printf 'Password (at least 8 characters, not shown): '; read -s ADMIN_PW; echo
export ADMIN_NAME ADMIN_PW
docker compose -p "${ARCHIVE_PROJECT:-pillar43}" exec -e ADMIN_NAME -e ADMIN_PW api \
  sh -c 'python scripts/archive_cli.py account "$ADMIN_NAME" admin "$ADMIN_PW"'
unset ADMIN_PW
```

## Native macOS build

```bash
./scripts/build-desktop.sh          # full: interpreter + bundle + sign + notarize
SKIP_FREEZE=1 ./scripts/build-desktop.sh   # Rust/UI-only change
SKIP_WEB=1 SKIP_FREEZE=1 ./scripts/build-desktop.sh

# Signed + notarized (needs a Developer ID cert; see docs/MACOS_CODE_SIGNING.md)
export APPLE_SIGNING_IDENTITY="Developer ID Application: <Name> (<TEAMID>)"
export NOTARY_PROFILE="<notary-profile-name>"
./scripts/build-desktop.sh
```

Unset `APPLE_SIGNING_IDENTITY` and the build is ad-hoc signed: it runs on the
machine that built it and nowhere else without stripping the quarantine bit by
hand. Ad-hoc builds cannot be notarized, so the notarize step skips itself.
Setup: `docs/MACOS_CODE_SIGNING.md`.

### What gates a desktop build

Three checks run inside step 4, cheapest first. `SKIP_TESTS=1` skips all of them.

| Gate | Catches |
|---|---|
| `cargo test` | The vault-path precedence table (`desktop/src-tauri/src/paths.rs`) and the generated menu model: shell logic no Python test can see. |
| `./scripts/test-desktop-bundle` | The backend suite, run by the **bundled interpreter** rather than Docker's. |
| `./scripts/smoke-desktop-boot.py` | Startup itself: the migration chain against a fresh DB, `validate_startup`, the static mount, router wiring. |

`scripts/smoke-desktop-python.py` also runs, right after pruning
(`scripts/prune-desktop-python.sh`), to guard the prune.

Every other gate in this repo runs against Docker, and no CI workflow builds the
desktop app, so the bundle needed a gate of its own. The bundle's backend source
is copied verbatim from `api/`; *dependencies* are what drift. So
`test-desktop-bundle` layers a venv on the bundled interpreter with
`--system-site-packages` (adding only `requirements-dev.txt`) and runs the fast
subset against the repo's own fixtures. That venv lives in
`desktop/.tools/testvenv`, **never** under `desktop/src-tauri/resources/`:
everything there is bundled into the `.app` and signed.

Gotchas:

- **The backend is not frozen.** The bundle ships a relocatable CPython
  (`Resources/python/`) running the backend source, not a PyInstaller binary
  (antivirus engines quarantined PyInstaller's bootloader). `SKIP_FREEZE=1`
  keeps its name and now skips restaging the interpreter.
- **Never edit `scripts/build-desktop.sh` while a build is running.** bash reads
  a script incrementally by byte offset, so an insertion mid-run makes it
  execute a fragment.
- **The build is arm64-only.** `lipo -info` on the output confirms it.
- **Signing happens before imaging.** Tauri's combined `--bundles app,dmg` writes
  the image before any signing step can run. The script bundles `app` only,
  signs inside-out, then makes the image with `hdiutil` (not Tauri's
  `bundle_dmg.sh`, which drives Finder over AppleScript).
- **ffmpeg is not fetched.** Drop `ffmpeg`/`ffprobe` into
  `desktop/src-tauri/resources/bin/` and they are bundled and signed with
  everything else. Without them transcription is reported unavailable.

Output lands in `desktop/src-tauri/target/release/bundle/` (a `Pillar-43.app`
and a `.dmg`).

## Pre-commit hooks

After cloning, run `make install-hooks` (or `pre-commit install`). The hooks in
`.pre-commit-config.yaml`:

**Lint and type gates**
- `ruff-format`: Python layout. Reformats and fails the commit if it had to.
- `ruff`: Python lint (`max-complexity = 34` in `ruff.toml`).
- `mypy`: via `scripts/mypy-api`. Lenient config with a shrinking
  `ignore_errors` allowlist in `api/mypy.ini`. New code must not join it.
- `tsc`: TypeScript typecheck.
- `eslint`: frontend lint, gated at `--max-warnings=11`. Any net-new warning
  blocks the commit.

**Tests**
- `vitest`: frontend unit tests.
- `test-api-changed`: runs the backend tests matching the `.py` files the commit
  touches.

**Docs-vs-code drift linters**
- `module-readmes`: every module listed in the per-area `README.md` files
  (`scripts/check_module_readmes.py`).
- `function-reference-drift`: function names cited in markdown still exist
  (`scripts/check_function_reference_drift.py`).
- `route-docstring-drift`, `route-reachability`: route docstrings and route
  wiring against their handlers.
- `menu-model-drift`: the generated native menu model against `menuModel.ts`.
- `path-traversal-lint`: heuristic for path handling that skips
  `Settings.resolve()`.

If `pre-commit` is missing, install it with `pipx install pre-commit`. To run
the hooks ahead of time: `pre-commit run --all-files`.

## Running tests

```bash
./scripts/test-api                          # never python -m pytest directly
./scripts/test-api tests/test_search.py -v
./scripts/test-api -k archive_ask           # filter by keyword
./scripts/test-api-fast                     # skip slow + integration
./scripts/test-api -n 1                     # serial (debug)
./scripts/test-api --no-reuse               # fresh container each run
./scripts/test-api --down                   # remove this tree's test container + network
cd web && npm test -- --run
cd web && npm test                          # watch mode

./scripts/coverage                          # both suites, with thresholds
./scripts/coverage backend
./scripts/coverage frontend
```

`./scripts/test-api` runs `pytest -n auto` in a warm test container that is
reused between runs. Each working tree gets its own test project
(`scripts/lib/test-container.sh`), so trees and worktrees do not collide.

**After changing `api/requirements*.txt`, rebuild the test image
(`--rebuild`).** The container stays warm, so a new dependency is absent from
the reused one and the whole suite fails with `ModuleNotFoundError`, which looks
like broken code and is stale infrastructure:

```bash
./scripts/test-api --rebuild
```

**Coverage floors** (enforced in CI): backend `fail_under = 75`
(`api/.coveragerc`); frontend 56 statements / 70 branches / 38 functions / 56
lines (`web/vite.config.ts` → `test.coverage`). They are the measured floor, not
a target: raise them after writing tests, never as an aspiration. HTML reports
land in `api/htmlcov/` and `web/coverage/`. Backend excludes `tests/` and
`migrations/`; frontend excludes `_generated.ts` and specs.

Mark expensive tests so the fast loop stays fast (markers live in
`api/pytest.ini`):

```python
import pytest

@pytest.mark.slow
def test_full_ingest(...): ...

@pytest.mark.integration
def test_against_real_ollama(...): ...

# Or at module top for all tests in the file:
pytestmark = pytest.mark.slow
```

## Pydantic → TypeScript codegen

Backend Pydantic models are the source of truth for API shapes. The frontend
imports them from a generated file; never re-type a shape by hand.

```bash
./scripts/codegen-types     # or, from web/: npm run codegen
```

This boots the test API container, dumps `app.openapi()` to `web/openapi.json`,
and runs `openapi-typescript` to write `web/src/lib/api/_generated.ts`.
`.github/workflows/codegen-drift.yml` fails CI if the committed output is stale.

Adding a field: add it to the Pydantic model, run codegen, and the frontend type
updates. Adding an endpoint: declare a Pydantic response model and pass it as
`@router.get("/foo", response_model=FooResponse)` (without it the response is
typed `unknown`), run codegen, then import
`components['schemas']['FooResponse']` from `./_generated` in the TS client.
The settings endpoints are the reference: `api/routes/settings.py:SettingsResponse`
and `web/src/lib/api/settings.ts`.

Pydantic `X | None` emits as `X | null` in TS, not `X | undefined`. Use `?? ''`
or widen local types to accept `null`.

## Running the app

```bash
make dev      # hot reload
make build    # production images
make stop
```

App: **http://127.0.0.1:5173**. API: **http://127.0.0.1:8002** (host port
`API_PORT` in `.env`; inside the containers it is always `api:8000`).

## Debugging

| Symptom | Likely cause |
|---------|-------------|
| Search returns nothing | ripgrep not in PATH, or query has special chars without `--fixed-strings` |
| 500 on file op | Path not through `Settings.resolve()`, or wrong mount prefix |
| `database is locked` | A second connection writing the jobs row; use `try_update_job` (see the maintainer notes) |
| Answers cite nothing from an item | The item is closed to the model; `make archive-status` shows the consent counts |
| PDF renders blank | `task.destroy()` called in cleanup (React Strict Mode) |
| SSE stream cuts off | `async for` loop not consuming the stream completely |
| Test isolation failure | Test wrote to a real path instead of `tmp_path` |
| Backend changes not visible | The API image bakes code in: run `docker compose up --build -d` after any `.py` change |
| Every tree test returns 503 | A test staged a path change into the shared fixture config; see the root the maintainer notes Test suite section |
| `.env` path with spaces fails | Value not quoted: write `VAR="/path/with spaces"` |

Check `docker ps` and `docker logs pillar43-api-1` (substitute your project
name) after a rebuild.

## Worktree workflow

Run feature work in a git worktree while the main checkout's stack keeps
running.

In a worktree you MAY edit code, run `./scripts/test-api` (its own test project;
fixtures under `api/tests/fixtures/`, so your real notes/library/generated are
never touched), run `cd web && npx tsc --noEmit`, and commit.

In a worktree you MUST NOT run `./pillar43` (it refuses anyway), `./pillar43
reset` (removes `pillar43_pillar43_data` whatever the directory), or any
`docker compose up/down` for the main stack. Those belong to the main checkout.

```bash
# In the main checkout:
git worktree add ../pillar43-feat-x feat/the-thing
cd ../pillar43-feat-x

# Develop: edit, ./scripts/test-api, npx tsc --noEmit, commit.

# Done, from the main checkout:
git merge --ff-only feat/the-thing
./pillar43                    # rebuilds + restarts

# Cleanup:
cd ../pillar43-feat-x && ./scripts/test-api --down && cd -
git worktree remove ../pillar43-feat-x
git branch -d feat/the-thing
```

## Feature verification

How to check each feature end-to-end. The org gate answers only the endpoints
the archive screens use (see `api/services/archive/access.py`); once an account
exists, the HTTP endpoints below need a signed-in session.

**Health**
```bash
curl -s http://127.0.0.1:8002/health
# Expected: "status":"ok" in the JSON
```

**Search (`/api/search`)**
```bash
curl "http://127.0.0.1:8002/api/search?q=your+keyword&scope=notes"
# Expected: {"query":..., "results":[...]}
```
In the app: open the search palette (⌘K), type a keyword. Results show file
path, line number and matching text.

**Ask**
```bash
make archive-ask Q="Where can we sell the Lanterns book?"
```
In the app: open Ask, type a question. The answer cites passages; opening a
citation shows the page. Closed items are not read.

**Ingest**
`make archive-status` lists the counts per consent level after `make archive`.

## Branching and closing a feature

`main → feat/<name>`; never commit to `main` directly. `/feature-close` merges,
runs the tests and updates `CHANGELOG.md`. Before merging:

```bash
./scripts/test-api
cd web && npm test -- --run && npx tsc --noEmit
```

Update the living docs the change touches:

| Doc | What to update |
|-----|---------------|
| `CHANGELOG.md` | A bullet under `[Unreleased]` for every feature |
| `MANUAL.md` | User-facing features, settings, keyboard shortcuts |
| `DEV_MANUAL.md` | New commands, tools, or workflow changes |
| `docs/guides/` | Anything staff do (install, permissions, maintenance) |

Commit format: `type: description`, with no `Co-Authored-By` trailer.
Stage by path, not `git add -A`.

## Conventions

- All client paths are mount-prefixed (`notes/`, `library/`, `generated/`).
- `Settings.resolve()` on every path; never bypass it.
- `get_db()` always in try/finally; the connection must close.
- No f-string SQL; parameterised queries only.
- ripgrep: `--fixed-strings` always.
- SSE streams: `fetch()` directly, not the `api` helper. On the frontend, drain
  with `web/src/lib/sse.ts:parseSSEStream`; do not hand-roll line-buffered
  parsing. On the backend use `services/sse_format.py` and
  `routes/_sse_worker.py`.
- If you can catch it, log it. Bare `except Exception: pass` swallows real bugs;
  use `log.debug("brief reason", exc_info=True)` or a higher level (see
  the maintainer notes).
- Tests use `tmp_path` and `monkeypatch`, never real vault paths.
- `.env` path values are quoted if they may contain spaces.
- After any Python change: `docker compose up --build -d`. The API image bakes
  code in; there is no bind mount.
- After any rename (label, route, UI text): `git grep "OldName" -- web/src api`
  to catch stragglers.

### Key files

| File | Purpose |
|------|---------|
| `api/config.py` | `Settings`: path resolution, traversal guard, `effective_*()` methods |
| `api/services/db.py` | `get_db()`: open SQLite, caller closes; schema via Alembic |
| `api/services/_schema_baseline.py` | Frozen baseline schema SQL, used by Alembic `0001` and the in-memory test fallback |
| `api/migrations/versions/` | Alembic migrations |
| `api/services/vault/` | File reads and the writes transcription/handwriting make |
| `api/services/archive/` | The press archive: items, consent, ask, explore, people, ledger |
| `api/services/catalog/` | Ingest pipeline: scan, chunk, embed |
| `api/orgs/press.yaml` | Organization config (`ORG_CONFIG`) |
| `web/src/stores/appStore.ts` | Zustand: current file, panel mode, left tab, jobs |
| `web/src/lib/api.ts` | Re-exports every API module in `web/src/lib/api/`; `BASE` from `VITE_API_URL` |

## Database migrations (Alembic)

The schema is managed by [Alembic](https://alembic.sqlalchemy.org/). Migrations
live in `api/migrations/versions/`. The frozen baseline lives in
`api/services/_schema_baseline.py`; both Alembic and the in-memory test fallback
import from there.

**On startup:**
- `services.db.init_schema()` runs `alembic upgrade head` against the live DB.
- Pre-Alembic databases (no `alembic_version` table but already a `files` table)
  are stamped at `0001_baseline` first, so `upgrade head` is a no-op.
- In-memory test DBs (`:memory:`) bypass Alembic and apply `BASELINE_SQL`
  directly.

### Adding a migration

1. Shell into the API container: `docker compose exec api bash`.
2. `alembic revision -m "add_X_to_Y"`.
3. Hand-edit the file under `api/migrations/versions/`: implement `upgrade()` and
   `downgrade()` with `op.add_column(...)`, `op.create_index(...)`, etc.
4. Test against a fresh DB: drop the dev DB, restart the API, check the schema.
5. Test against an existing DB: restart the API on a copy and check it upgrades
   cleanly.
6. Any test using `sqlite3.connect(":memory:")` will NOT see your migration. If
   the test depends on the new column, use `tmp_path / "test.db"` instead.

### CLI cheat sheet

Run inside the API container (`docker compose exec api bash`):

| Command | What |
|---------|------|
| `alembic current` | The revision the live DB is at |
| `alembic history` | All revisions |
| `alembic upgrade head` | Apply pending migrations (also runs at startup) |
| `alembic downgrade -1` | Roll back one revision (destructive) |
| `alembic stamp 0001_baseline` | Mark a DB as already at baseline (recovery) |

`alembic revision --autogenerate` is not wired (`target_metadata` is `None`, no
ORM models). Hand-write the DDL.

### Recovering a corrupted state

If `alembic_version` is missing or wrong: check what schema the DB has
(`sqlite3 <db> ".schema"`), find the matching revision in
`api/migrations/versions/`, run `docker compose exec api alembic stamp
<revision_id>`, then `alembic upgrade head` resumes.

### Legacy DB migration shim

An older commit moved the SQLite DB off the `GENERATED_PATH` bind mount onto the
named volume (`pillar43_data` → `/data`), to escape macOS VirtioFS WAL/mmap
problems. `services.db._migrate_db_from_bind_mount(target)` copies the old DB
(plus `-wal`, `-shm`, `-journal` siblings) once, when `DATA_PATH` is set,
`/data/pillar43.db` is absent and `${GENERATED_PATH}/pillar43.db` exists. On
failure it logs a warning and starts a fresh DB; the legacy file is untouched.
Tests never set `DATA_PATH`, so it is a no-op there. It can be removed once no
install predates the move.
