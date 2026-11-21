# Security and privacy

What Pillar-43 protects, how, and what it does not protect. Pillar-43 runs on one
computer at a press. Several people sign in to it; contributors' consent decides
what each of them, and the model, may read.

## What stays on the computer

- **The model.** Answers come from a model in Ollama on the same computer
  (`qwen3:8b`, `api/orgs/press.yaml`). The press edition has no hosted AI
  provider, so there is no API key to set and none to leak.
- **Search.** The embedder is built into the api image; indexing makes no network call.
- **No tracking.** No analytics, no telemetry, no web fonts or scripts from elsewhere.
- **Checked by a test.** `api/tests/test_archive_no_egress.py` runs intake and
  Ask with every outbound connection recorded and refused, except loopback and
  the configured Ollama host, and asserts that nothing was attempted. It has not
  been repeated with the network physically off.

The internet is used to install and update: Docker Desktop, Ollama, the model,
and the base images during a build.

## Who can read what

Every item in `library/` has one of three levels, set from the press's defaults
per kind (`api/orgs/press.yaml`) and changed only by an admin or the
item's writer:

| Level | Staff see it | The model reads it |
|---|---|---|
| private | no | no |
| staff | yes, when signed in | no |
| model | yes | yes, when a question is asked |

Two layers enforce this, and both refuse by default:

1. **Before the model.** `services/retrieval.py:fetch_materials` keeps only
   items at `model` before any passage is ranked or put in a prompt. Ask reads
   nothing else.
2. **Before the HTTP API.** `services/archive/access.py:org_gate` answers 404
   for every endpoint the archive screens do not use, and for any `path`
   parameter naming an item staff may not see. Tree and search listings drop
   such items (`filter_tree`, `filter_results`).

Withdrawing an item (`services/archive/withdraw.py`) tombstones its bytes,
removes it from search, refuses it at intake, and marks earlier answers that
used it.

## Accounts

Roles are admin, staff and writer (`services/archive/accounts.py`).

- **admin:** accounts, linking writers to their items, consent on any item.
- **staff:** asks, reads what is open to staff, annotates.
- **writer:** sees and controls only the items an admin linked to them (level,
  terms, withdraw). A writer never asks and never sees the ledger.

Passwords are hashed with scrypt and a per-account salt. A session is a random
token in an HttpOnly, SameSite=Strict cookie; only its SHA-256 is stored.
There is no password reset by email: an admin makes a new account.

**Before the first account exists, the archive is open** to anyone who can
reach the port, because a fresh install has to be able to make its admin
(`access.py`, `_session_account`). The first account must be an admin. Make it
before loading any documents ([install guide](docs/guides/install.md), Step 7).
Until then reads are open, but withdrawing an item or changing its consent or
terms is refused with a 403 (`routes/archive.py:_require_account`). The ledger
line route (`/api/archive/ledger/{seq}`) gives staff only the `model_call` lines
whose items they may see; admins read any line.

Account administration answers only to a loopback `Host` header
(`routes/archive.py:loopback_only`). Sign-in does not check `Host`, because the
web container's proxy rewrites it; DNS rebinding is blocked by the host
allowlist below.

## The ledger

Intake, consent changes, withdrawals and every model call are appended to a
hash-chained ledger in the archive's database (`services/archive/ledger.py`).
Each line's hash covers the previous line's, so an edited or deleted line breaks
the chain at that point; `verify` names the first line that does not hold. A
writer's My work shows when the model read each of their items.

The ledger detects changes made through the database; it does not stop someone
with the computer's disk from rewriting the whole chain.

## Network exposure

- Both containers publish on `127.0.0.1` only (`docker-compose.yml`). Other
  computers on the network cannot reach them.
- `TrustedHostMiddleware` (`api/main.py`, `ALLOWED_HOSTS`) refuses any `Host`
  header not on the loopback allowlist, which blocks DNS rebinding.
- CORS allows only the local web origins, and `services/origin_guard.py`
  refuses any state-changing request a page on another origin makes the browser
  send (CORS alone would not stop a preflight-free POST).
- Do not publish the ports to the network or the internet. Pillar-43 has no
  TLS and is not hardened for that.

## Other hardening

- **Paths.** `config.Settings.resolve()` rejects traversal with
  `Path.relative_to()`; writes outside `notes/` and `generated/` are refused.
  The app treats `library/` as read-only (`LIBRARY_READONLY`, default true), and
  `org_gate` allows no file-writing endpoint at all. The Docker mount itself is
  not read-only. `scripts/check_path_traversal.py` lints for
  unguarded joins.
- **Document text is untrusted.** Retrieved passages are fenced as data in the
  prompt; the model is told to cite them, not follow them. Rendered markdown
  goes through DOMPurify (`web/src/lib/markdown.ts`).
- **Extraction.** Every extraction path strips unpaired surrogates before
  storing (`services/catalog/extract.py:_strip_surrogates`).

## The api container's view of the checkout

The api container mounts the project root read-only. Two files are mounted
writable, `libraries.conf` and `docker-compose.override.yml`, because Settings
can add library folders. A bind-mounted file cannot be atomically replaced, so
`libraries_config._write_file` writes in place. Both files must exist before the
stack starts, or Docker creates directories in their place;
`scripts/ensure-host-files.sh` creates them and runs from `./pillar43` and
the `make` targets. Run it yourself before a bare
`docker compose up` on a fresh clone.

## Not protected

- **Someone with the computer.** The database, the documents and the ledger are
  ordinary files on its disk. Turn on FileVault (macOS disk encryption); the
  [maintenance guide](docs/guides/maintenance.md) says how.
- **A compromised container or dependency.** Code running inside the api
  container can read everything the api can.
- **Backups you do not make.** `./pillar43 backup` writes consent, tombstones,
  accounts and the ledger to one file (`services/archive/backup.py`); it does
  not run on a schedule and does not copy the documents. A lost disk without a
  recent backup loses the consent records, accounts and ledger.

## Reporting a problem

Open an issue on the repository with the `security` label, or write to the
maintainers directly if it should not be public first. There is no embargoed
disclosure process yet.
