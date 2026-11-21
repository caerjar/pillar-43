# Install guide: verification record

Developer record, not a staff guide. It shows that [install.md](install.md) and the
commands in the other guides were run, in order, on a fresh clone with a clean
compose project.

- Date: 2026-11-20
- Machine: MacBook Pro, Apple M3 Max, 48 GB, macOS 26.6.2; Docker 29.4.0 client / 29.3.1 engine, Compose v5.1.1, Ollama 0.40.13, GNU Make 3.81
- Fresh clone: `git clone -b feat/l3-guides` of this branch into an empty directory, commit `08391b0` (the install guide draft). Later commits changed only `docs/`.
- Names: the guide's `ARCHIVE_PROJECT=pillar-43`, ports 8061 / 5211 were replaced by `p43-l3`, 8151 / 5251 (the guide's own Step 5 `export` lines, with other values), because those were reserved for this check. Nothing else differs.
- Ports 8151 and 5251 were checked free with `lsof` first. Ollama had no model loaded at the start (`ollama ps` empty).

## Deviations from a person at a keyboard

1. Steps 1 to 4 (install Docker Desktop, Ollama, command-line tools, get the folder) were not performed: all were already installed. Only their checks were run: `docker version`, `ollama list` (shows `qwen3:8b`), `make --version` (GNU Make 3.81), `ls Makefile`. The downloads and the time they take are not verified.
2. Step 6 was fast (20 seconds) because Docker had every build layer cached from earlier builds. A cold build was not timed.
3. Step 7 was run with `docker compose ... exec -T` (no terminal) and answers fed from a file, because no person was typing. A person at a Terminal uses the line without `-T`.
4. Step 8 was run in a browser driven by Playwright. Screenshot: (a local scratch file, not kept).

## Step 5

```
$ export ARCHIVE_PROJECT=p43-l3 ARCHIVE_API_PORT=8151 ARCHIVE_WEB_PORT=5251
```

## Step 6

```
$ make archive
Created libraries.conf
Created docker-compose.override.yml (inert - no libraries configured)
API_PORT=8151 WEB_PORT=5251 docker compose -p p43-l3 --env-file .env.archive -f docker-compose.yml -f docker-compose.archive.yml up --build -d
 (build output, all layers CACHED)
Waiting for the API on :8151 .
docker exec p43-l3-api-1 python scripts/archive_cli.py intake
 (counts; "mail": {"messages": 40, "attachments": 5, "refused": 0, "threads": 8})
docker exec p43-l3-api-1 python scripts/archive_cli.py index
{ "files_scanned": 38, "embedded": true, "errors": [] }
docker exec p43-l3-api-1 python scripts/archive_cli.py consent kind:contract model --by "setup"
6 item(s) set to model
docker exec p43-l3-api-1 python scripts/archive_cli.py consent 'glob:*yellow*' model --by "setup"
5 item(s) set to model
Pillar-43: http://127.0.0.1:5251
real 19.6 s
```

```
$ make archive-status
NAME           STATUS                    PORTS
p43-l3-api-1   Up 36 seconds (healthy)   127.0.0.1:8151->8000/tcp
p43-l3-web-1   Up 36 seconds             127.0.0.1:5251->5173/tcp
{ "attachment:private": 5, "catalog:model": 1, "contract:model": 6, "design:model": 3,
  "design:staff": 3, "document:private": 4, "email:private": 41, "handwritten:private": 1,
  "letter:model": 1, "letter:private": 11, "minutes:model": 1, "minutes:staff": 2,
  "note:staff": 1, "recording:private": 3, "tracked-change:private": 24 }
```

## Step 7 (before and after the first account)

```
$ curl -s http://127.0.0.1:8151/api/archive/me
{"name":null,"role":null}                 <- open: no account yet
$ curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8151/api/archive/open-to-ai
200
$ zsh step7.zsh      (the guide's lines: printf/read, read -s, export, docker compose exec, unset)
Administrator name: Password (at least 8 characters, not shown):
account Stephen Test (admin) created
$ curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8151/api/archive/open-to-ai
401                                        <- closed once the account exists
```

Short password (run with the writer variant of the same lines): the command ends
`ValueError: password must be at least 8 characters`, after a Python traceback.

## Step 8 (browser)

Opened http://127.0.0.1:5251: sign-in form titled "Pillar-43 - Local Archive". Signed in as the
administrator created above. Ask screen with the sentence "Open to the AI: 12 items". Asked
"How long is the cure period before rights revert on The Drowned Orchard?". Answer
(about 10 seconds): "If, within nine (9) months after the Publisher's receipt of that written
request, ... all rights granted under this Agreement revert to the Grantor automatically and
without further notice." with source button `[2]` and "Quoted from T 2014 Vasconcelo Reis
Orchard Rights+Translator: The Drowned Orchard". Under it: "17 items closed by their
writers" and "3 items at staff level, not read by the AI". Clicking `[2]` opened the contract
PDF page with clause "7. Reversion" and the sentence highlighted (screenshot above).
Browser console showed 2 errors on load (not investigated; the API log shows
`GET /api/catalog/stats 404`).

## Step 9 and the own-documents section

Stop and start (`docker compose -p p43-l3 stop`, `... start`): both services came back, API
health ok, accounts and decisions intact (see Backups below, which stops and starts the same way).

Own-documents recipe, run on a second project `p43-l3b` (API 8152, web 5252) with a one-file
folder: `cp .env.archive .env.press`, `sed` edits of the three lines, the long `up --build -d`
line with `--env-file .env.press`. Result: `Started`; `GET /api/archive/me` returned
`{"name":null,"role":null}` (open until an account is made); `intake` registered the one file
as `"contract:staff": 1`; `index` embedded it; `consent ... model` then `ask` answered. A first
attempt reusing port 8151 failed at start with `Error response from daemon: failed to set up
container networking: driver failed programming external connectivity on endpoint ...`.
The second project was removed with `docker compose -p p43-l3b down -v`.

## Commands from permissions.md, archivist.md, maintenance.md and workshop.md

All run on the `p43-l3` stack (with `-T` after `exec`):

| Command | Result |
|---|---|
| `ls fixtures/synthetic-press/correspondence/letters` | 12 file names |
| `archive_cli.py counts`, `intake` (twice) | counts as above; second run `"existing": 38`, no new items |
| `consent "library/correspondence/letters/2026-03-02_vasconcelo-reis_reversion-request.txt" staff --by "Test Archivist"` | `1 item(s) set to staff` |
| `consent "library/contracts/Pellerin-Okafor Weather for Ferrymen CONTRACT signed.pdf" private ...` (spaces in name) | `1 item(s) set to private` |
| `consent "glob:*merrowby*" private ...` | `10 item(s) set to private` (more than one file) |
| `consent "person:ines@lanternwharf.example" model ...` | `3 item(s) set to model` |
| `consent "library/no/such/file.pdf" model ...` | traceback ending `KeyError: 'library/no/such/file.pdf'` |
| `labels "library/contracts/contract_merrowby_SaltLedger_2012.pdf" teaching_only never_for_training ...` | `...: ['never_for_training', 'teaching_only']` |
| `labels ... nonsense` | traceback ending `ValueError: unknown label(s): nonsense` |
| `withdraw "library/correspondence/letters/2025-11-04_dunmore_translator-fee.txt" --by ...` | JSON with `sha256`, `"answers_marked": []`; next `intake` showed `"refused_tombstoned": 1` |
| `ask "How much was the translator fee in the Dunmore letter?"` after the withdrawal | answered `USD 60 a page, 48 pages` from an email message (a different item, opened by the `person:` consent above), not from the withdrawn letter |
| python one-liner `verify(get_db())` | `{'ok': True, 'entries': 70, 'first_bad_seq': None}`, later 75, 79, 85 |
| python one-liner `add_annotation(...)` | `1` |
| `job editorial-history "The Drowned Orchard"`, `teaching-packet`, `rights-answer` | a folder path under `/generated/archive/jobs/` each; the editorial history held 2 items (minutes docx, reversion request) plus `manifest.json` |
| `stats`, `colophon` | `/generated/archive/stats.json`, `/generated/archive/COLOPHON.md` |
| `make archive-ask Q="When can the estate get the rights to The Drowned Orchard back?"` | JSON answer quoting the nine-months clause |
| account for a writer (`read -s` lines, role `writer`), `owner "Cassia Merrowby" <two paths>` | `account Cassia Merrowby (writer) created`; `Cassia Merrowby: 2 item(s) linked` |
| writer signs in in the browser | My work lists both items with levels, terms, "Not read by the AI", Withdraw; setting Model and withdrawing the letter wrote ledger lines `consent` and `withdraw` with actor `Cassia Merrowby`; item now `private` with `withdrawn_at` set |
| staff account (`staff` role), signs in in the browser | sidebar: Ask, Explore, People |
| backup: `stop`, `docker run ... tar czf`, `cp -R .archive`, `start` | `data.tar.gz` 361,704 bytes, `press/`, settings file |
| restore: `stop`, `docker run ... sh -c 'rm -rf ... ; tar xzf ...'`, `start` | a consent change made after the backup (`catalog` set to private) was gone after the restore; record check `ok: True` |
| update: `git pull`, `make archive-stop`, the long `up --build -d` line, `/health` | `Already up to date.`; containers recreated; counts unchanged; account still signed in; health `{"status":"ok",...,"profile":"org"}` |
| change model to `llama3.2:1b` in `api/orgs/press.yaml`, rebuild, ask | answered; `ollama ps` listed `llama3.2:1b` |
| change model to `qwen3:nope`, rebuild, ask | traceback ending `urllib.error.HTTPError: HTTP Error 404: Not Found` |
| `consent "library/contracts/t_2014_vasconcelo-reis_orchard_RIGHTS+TRANSLATOR.pdf" staff`, then ask the cure-period question | no nine-months sentence; an unrelated sentence about a cover was returned instead |
| the same with `model` | nine-months sentence returned |
| ask "What is the printer's phone number?" | `not_answered: true`, no sentences |
| `lsof -i :8151` | one line, command `com.docke...` listening |

Not run: Steps 1 to 4 downloads; `xcode-select --install`; FileVault; Ollama stopped (the
"local model is not running" row is from the program's code, not from a run); the web
sign-in "Wrong name or password" message; a cold build; any run on a Mac smaller than 48 GB.

## Live run 2026-11-21

The reordered Steps 6 and 7 and `./pillar43 backup|restore`, run on a live stack
from a fresh clone of `main` at `f75fef5`, followed literally with
`ARCHIVE_PROJECT=p43-live ARCHIVE_API_PORT=8071 ARCHIVE_WEB_PORT=5221 ARCHIVE_ENV=.env.archive`.
The images were already in Docker's build cache, so this is not a cold build.
The admin password came from `openssl rand` into the environment instead of
`read -s`; the `docker compose ... exec` line is the guide's, unchanged.

| Command | What it printed | Time |
|---|---|---|
| `make archive-up` (Step 6) | containers created and started, `Waiting for the API on :8071 .`; `make archive-status`: `api` and `web` Up, counts `{}` | 14 s |
| the Step 7 account line | `account liveadmin (admin) created` | 1 s |
| `make archive` (Step 7) | intake `"new": 38`, mail 40 messages, 8 threads, 5 attachments; index `"files_scanned": 38, "embedded": true, "errors": []`; `6 item(s) set to model` (contracts), `5 item(s) set to model` (yellow); `Pillar-43: http://127.0.0.1:5221` | 8 s |
| `./pillar43 backup` | `backed up 50 ledger line(s), 107 item(s), 0 tombstone(s), 1 account(s); ledger chain verified`, then `Backup written and verified: backups/governance-p43-live-20261121T183525Z-seq50.sqlite (50 ledger line(s))` | 1 s |
| `archive_cli.py consent library/contracts/Kaminrowska_Lanterns_translation-contract_signed-2020-02-17.pdf private --by livecheck` | `1 item(s) set to private`; item now `private`, ledger 51 lines | |
| `./pillar43 restore <that file>` | `refused: the archive's ledger has 51 lines; the backup has 50. Restoring would lose 1 ledger line(s) and the consent changes they record. Make a fresh backup, or restore with --force if you mean to discard them.` Item still `private`. | 0 s |
| `./pillar43 restore <that file> --force` | `restored 9 table(s); ledger now 50 line(s), chain verified. Sign in again.` Item back to `model`, set by `setup`; ledger 50 lines; web 200, `/health` 200 | 0 s |
| `docker compose -p p43-live down` | containers removed; volume `p43-live_pillar43_data` kept | |

Nothing failed as written, so no step of the guide changed.
