.PHONY: dev build stop restart status logs logs-api logs-web \
        test test-backend test-backend-v test-frontend typecheck \
        lint format shell-api shell-web clean \
        reset reset-hard \
        install-hooks \
        archive archive-up archive-ask archive-status archive-logs archive-stop \
        archive-backup archive-restore

# ── First-time setup ─────────────────────────────────────────────────────────

## install-hooks — install pre-commit hooks (ruff, tsc, vitest, eslint)
## Run once after cloning. Hooks then fire on every `git commit`.
install-hooks:
	@command -v pre-commit >/dev/null 2>&1 || { \
	  echo "pre-commit not found. Install with: pipx install pre-commit (or pip install --user pre-commit)"; \
	  exit 1; \
	}
	pre-commit install
	@echo "Pre-commit hooks installed. Run 'pre-commit run --all-files' to test."

# ── Running the app ───────────────────────────────────────────────────────────

# ensure-host-files — create the two bind-mounted host files if missing.
# docker-compose.yml mounts them individually; a missing source makes Docker
# create a directory instead of erroring. Both are gitignored.
.PHONY: ensure-host-files
ensure-host-files:
	@bash scripts/ensure-host-files.sh

dev: ensure-host-files
	docker compose -f docker-compose.yml -f docker-compose.dev.yml up

## build — rebuild images and bring the stack up (detached; `make logs` to follow)
build: ensure-host-files
	# --remove-orphans: the `worker` service was deleted 2026-08-18 when its
	# jobs moved into the api process. Without this flag an existing worker
	# container keeps running alongside the new in-process scheduler, and
	# every background job fires twice.
	docker compose up --build -d --remove-orphans

stop:
	docker compose down

restart: stop dev

status:
	docker compose ps

logs:
	docker compose logs -f

logs-api:
	docker compose logs -f api

logs-web:
	docker compose logs -f web

# ── Pillar-43 (Local Archive) ─────────────────────────────────────────────────
# A separate compose project from the personal app above, on its own ports.
# `make archive` brings it up, ingests and indexes the library, and opens the
# contracts and the yellow-thread documents (file names with "yellow") to the
# AI. Safe to rerun: intake keeps existing items. Note it
# reopens every contract and yellow document, so rerunning undoes one closed by hand.
# Ask from the terminal: make archive-ask Q="Where can we sell the Lanterns book?"

ARCHIVE_PROJECT  ?= pillar43
ARCHIVE_API_PORT ?= 8061
ARCHIVE_WEB_PORT ?= 5211
# ARCHIVE_ENV is the settings file: `.env.archive` for the invented press,
# `.env.press` for a real one (`make archive ARCHIVE_ENV=.env.press`). It is
# passed twice, because compose reads two things from it: `--env-file` fills in
# ports and paths, `PILLAR43_ENV_FILE` picks the file the containers load.
ARCHIVE_ENV      ?= .env.archive
ARCHIVE_COMPOSE  = API_PORT=$(ARCHIVE_API_PORT) WEB_PORT=$(ARCHIVE_WEB_PORT) \
	PILLAR43_ENV_FILE=$(ARCHIVE_ENV) \
	docker compose -p $(ARCHIVE_PROJECT) --env-file $(ARCHIVE_ENV) \
	-f docker-compose.yml -f docker-compose.archive.yml
ARCHIVE_CLI      = docker exec $(ARCHIVE_PROJECT)-api-1 python scripts/archive_cli.py

## archive-up — build and start only; make the admin account, then run `make archive`
archive-up: ensure-host-files
	$(ARCHIVE_COMPOSE) up --build -d
	@printf 'Waiting for the API on :%s ' $(ARCHIVE_API_PORT); \
	for i in $$(seq 1 90); do \
	  curl -sf http://127.0.0.1:$(ARCHIVE_API_PORT)/health >/dev/null && break; \
	  printf .; sleep 2; \
	done; echo; \
	curl -sf http://127.0.0.1:$(ARCHIVE_API_PORT)/health >/dev/null || { echo "API did not come up: make archive-logs"; exit 1; }

archive: archive-up
	$(ARCHIVE_CLI) intake
	$(ARCHIVE_CLI) index
	$(ARCHIVE_CLI) consent kind:contract model --by "setup"
	$(ARCHIVE_CLI) consent 'glob:*yellow*' model --by "setup"
	@echo "Pillar-43: http://127.0.0.1:$(ARCHIVE_WEB_PORT)"

archive-ask:
	@test -n "$(Q)" || { echo 'Usage: make archive-ask Q="your question"'; exit 1; }
	$(ARCHIVE_CLI) ask "$(Q)"

archive-status:
	$(ARCHIVE_COMPOSE) ps
	$(ARCHIVE_CLI) counts

archive-logs:
	$(ARCHIVE_COMPOSE) logs -f api

## archive-backup — save consent, withdrawals, accounts and the ledger to ./backups/
## One verified file outside the data volume. Optional: DEST=/Volumes/Drive/folder
archive-backup:
	@ARCHIVE_PROJECT=$(ARCHIVE_PROJECT) bash scripts/governance.sh backup $(DEST)

## archive-restore — put a backup back: make archive-restore FILE=backups/governance-....sqlite
## Refuses to replace a longer ledger; add FORCE=--force to override.
archive-restore:
	@test -n "$(FILE)" || { echo 'Usage: make archive-restore FILE=<backup file> [FORCE=--force]'; exit 1; }
	@ARCHIVE_PROJECT=$(ARCHIVE_PROJECT) bash scripts/governance.sh restore "$(FILE)" $(FORCE)

## archive-stop — stop the archive; its data volume is kept
archive-stop:
	$(ARCHIVE_COMPOSE) down


# ── Tests — always use the wrapper scripts ────────────────────────────────────
# Backend: ./scripts/test-api (pytest lives inside Docker only)
# Frontend: npm test directly from web/ (Vitest, no Docker needed)

test: test-backend test-frontend

test-backend:
	./scripts/test-api

test-backend-v:
	./scripts/test-api -v

# Usage: make test-file f=tests/test_search.py
test-file:
	./scripts/test-api $(f)

test-frontend:
	cd web && npm test -- --run

typecheck:
	cd web && npx tsc --noEmit

# Full gate: both suites + typecheck
test-all: test typecheck

# ── Quality ──────────────────────────────────────────────────────────────────

lint:
	docker compose -f docker-compose.test.yml run --rm api ruff check .

format:
	docker compose -f docker-compose.test.yml run --rm api ruff format .

# ── Shells ────────────────────────────────────────────────────────────────────

shell-api:
	docker compose exec api bash

shell-web:
	docker compose exec web sh

# ── Housekeeping ──────────────────────────────────────────────────────────────

## Deletes the data volume (consent, withdrawals, accounts, ledger): refuses
## unless a backup covers the ledger (`make archive-backup`) or you pass
## CONFIRM_DATA_LOSS=yes.
clean:
	@ARCHIVE_PROJECT=$(ARCHIVE_PROJECT) bash scripts/governance.sh check
	docker compose down -v --remove-orphans

## reset — wipe app data (catalog DB + generated/), keep notes + .env
## Prompts for confirmation before doing anything.
reset:
	@bash pillar43 reset

## reset-hard — full wipe: containers, images, generated/, .env
## Copy .env.example to .env afterwards to reconfigure.
reset-hard:
	@bash pillar43 reset --hard
