# Pillar-43 — Operations Guide

How to run, stop, check and reset a press installation. To install for the
first time, follow [docs/guides/install.md](docs/guides/install.md). Day-to-day
care (updates, backups, changing the answer model, what to do when something is
wrong) is in [docs/guides/maintenance.md](docs/guides/maintenance.md). This file
covers the commands and the settings behind them.

## The press install

`make archive` runs Pillar-43 as its own Docker Compose project, separate from
the development stack, on its own ports. Defaults from the `Makefile`:

| Setting | Variable | Default |
|---|---|---|
| Compose project name | `ARCHIVE_PROJECT` | `pillar43` (the install guide sets `pillar-43`) |
| API port (host) | `ARCHIVE_API_PORT` | `8061` |
| Web port (host) | `ARCHIVE_WEB_PORT` | `5211` |
| Settings file | | `.env.archive` |

Both ports bind to `127.0.0.1` only. The API container itself always listens on 8000.

| To do this | Run |
|---|---|
| Build, start, ingest, index, open contracts and "yellow" documents to the model | `make archive` |
| Show the containers and the counts | `make archive-status` |
| Follow the API log | `make archive-logs` |
| Stop (the data volume is kept) | `make archive-stop` |
| Ask from the terminal | `make archive-ask Q="your question"` |

`make archive` runs intake again and reopens every contract and "yellow"
document to the AI, which undoes a decision made by hand. Do not use it to
restart. Restart with `docker compose -p "$ARCHIVE_PROJECT" start`.

Before the first account exists, anyone who can reach the web address can open
the archive. Create the administrator account at once (install guide, Step 7).
Never put a password on the command line: it ends up in the shell history. Use
the `read -s` pattern in that step.

## The `./pillar43` launcher

`./pillar43` drives the general development stack (`docker compose` with
`docker-compose.yml`, web on 5173, API on `API_PORT`, default 8002). It does not
manage the press install above.

| Command | What it does |
|---|---|
| `./pillar43` | Build and start the stack, then open it |
| `./pillar43 stop` | `docker compose down` |
| `./pillar43 status` | `docker compose ps` |
| `./pillar43 logs` | Follow all logs |
| `./pillar43 backup [dest]` | Save consent, withdrawals, accounts and the ledger to one verified file |
| `./pillar43 restore <file>` | Put such a file back (refuses to replace a longer ledger) |
| `./pillar43 reset` | Wipe app data, keep notes and `.env` (refuses without a backup; asks first) |
| `./pillar43 reset --hard` | Full wipe: containers, images, `.env` (refuses without a backup; asks first) |

`./pillar43 help` lists the rest. It refuses to run from a git worktree.

## Settings

- `.env` (copied from `.env.example`) holds `LIBRARY_ROOT`, `NOTES_PATH`,
  `GENERATED_PATH` and optional ports (`API_PORT`, `WEB_PORT`).
- The press install reads `.env.archive` instead.
- Extra read-only libraries: edit `libraries.conf`, run
  `./scripts/gen-libraries-override.sh`, then `docker compose up -d --build`.
  The generated `docker-compose.override.yml` is bind-mounted as a file; never
  delete it by hand (Docker would recreate it as a directory). If that already
  happened: `rmdir docker-compose.override.yml`, then
  `bash scripts/ensure-host-files.sh`.

## Port conflicts

If startup says `driver failed programming external connectivity`, another
program holds the port. Check with `lsof -i :8061`, then choose other numbers
and keep them:

```bash
export ARCHIVE_API_PORT=8063
export ARCHIVE_WEB_PORT=5213
```

For the development stack, set `API_PORT` or `WEB_PORT` in `.env`.

## Data

- Records (SQLite database, accounts, ledger, search index) live in the Docker
  volume `<project>_pillar43_data`. It survives `make archive-stop` and
  container rebuilds. `docker compose down -v`, `make clean` and
  `./pillar43 reset` / `reset --hard` delete it. `make clean` and both resets
  refuse until a backup covers the records (see Backups).
- Your documents stay where they are: Pillar-43 mounts the press folder
  read-only.
- Generated folders and saved settings live in the `.archive` (or `.press`)
  folder beside the program.

## Backups

The records that cannot be rebuilt are the levels of consent, withdrawals
(tombstones), accounts and the ledger. They share a Docker volume with the search
index, and deleting the volume loses them: a later intake would register withdrawn
files again. One command saves exactly those, while Pillar-43 is running:

```
./pillar43 backup                     # or: make archive-backup
./pillar43 backup /Volumes/Drive/     # a folder on another drive
```

It writes `backups/governance-<project>-<time>-seq<N>.sqlite` beside the program
(`<N>` is how many ledger lines it holds), then reads the file back and checks the
ledger chain. If the check fails nothing is kept and the command says so.
The file holds password hashes: keep it on a drive only the press uses. `backups/`
is not committed.

Put one back (`./pillar43 restore <file>` or `make archive-restore FILE=<file>`).
It checks the file first, refuses if the running archive's ledger is longer than the
backup's or is a different history (the lines since the backup would be lost; add
`--force` to mean it), replaces the records in one step, checks the chain again, and
undoes the step if it fails. People sign in again afterwards.

`make clean`, `./pillar43 reset` and `./pillar43 reset --hard` look in `backups/`
(or `$PILLAR43_BACKUP_DIR`) and refuse, printing what would be lost, unless the
newest backup holds every ledger line the archive has now. To delete anyway:
`CONFIRM_DATA_LOSS=yes make clean`. If the archive is not running the guard cannot
tell, and refuses the same way. A backup to another folder does not count for the
guard; set `PILLAR43_BACKUP_DIR` to that folder.

This does not save the `.press` folder, the settings file or the search index (rebuilt
by `make archive`); see [docs/guides/maintenance.md](docs/guides/maintenance.md)
"Backups" for those, and for the whole-volume copy.

## Security

- There is no sign-in on the development stack, and the press install has none
  until the first account is made. Keep the loopback bind; never expose the
  API or web port. See [SECURITY.md](SECURITY.md).
- Do not commit `.env` files or keep secrets in `notes/`.

## Development vs production images

`docker compose up` builds the production images (nginx serving the built web
bundle; uvicorn without `--reload`). `make dev` layers `docker-compose.dev.yml`
on top (Vite with hot reload; uvicorn `--reload`; source bind-mounted). Each
Dockerfile names its `runtime` stage explicitly in `docker-compose.yml`, because
Docker builds the last stage by default and the dev stage is last in the api
Dockerfile.

## More

- [DEV_MANUAL.md](DEV_MANUAL.md): commands and tooling for developers
- [RELEASING.md](RELEASING.md): cutting a tagged release
- `./scripts/test-api`: run the backend tests
