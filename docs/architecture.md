# Architecture

What Pillar-43 is made of, where each part runs, and where every kind of data
lives. Each part is marked **built** (with the file that implements it) or
**planned**. Checked against commit `8eb6d66` (2026-11-21).

Security boundaries are in [`SECURITY.md`](../SECURITY.md). Backend
invariants are in the maintainer notes; frontend invariants are in the maintainer notes.

## Components

| Component | What it is | Status |
|---|---|---|
| **api** | Python 3.12, FastAPI, listening on port 8000 inside its container. Intake, retrieval, Ask, consent, accounts, ledger, jobs. Entry point `api/main.py`; routers listed in `api/routes/README.md`, services in `api/services/README.md`. | built |
| **web** | React 18 single-page app built by Vite and served by nginx on port 5173 inside its container. nginx proxies `/api/` to `api:8000`, so the browser talks to one origin. Views: Ask, Explore, People, My work (writers' terms), sign-in, files. | built (`web/src/components/Archive/`) |
| **Answer model** | An open-weight model in Ollama on the host (`qwen3:8b`; vision `qwen2.5vl:7b`), named in `api/orgs/press.yaml` under `models:`. The api reaches it at `OLLAMA_URL` (`http://host.docker.internal:11434` in `docker-compose.archive.yml`). There is no hosted model provider. | built (`api/config.py`, `api/routes/ai/_provider.py`) |
| **Embedder** | `BAAI/bge-small-en-v1.5` through fastembed, run inside the api process. The model files are baked into the image at build time (`api/Dockerfile`) and never downloaded at run time. | built (`api/services/embeddings.py`) |
| **Database** | One SQLite file holding the search index, the governance state and the jobs table. Migrations are Alembic (`api/migrations/versions/`), run on first open. Vectors are float32 BLOBs in a table, searched with numpy; sqlite-vec is not used (`0021_chunk_vectors.py` says why). | built (`api/services/db.py`, `api/services/vector_store.py`) |
| **Archive CLI** | `api/scripts/archive_cli.py`: intake, index, accounts, consent, jobs, ledger verify. The `make archive-*` targets and the guides call it inside the api container. | built |
| **Operator script** | `./pillar43`: stop, status, logs, `backup`, `restore`, `reset` (reset refuses to drop governance state no backup covers; `scripts/governance.sh`). | built |
| **Desktop shell** | A Tauri app for macOS (`desktop/src-tauri/`) that spawns the api as a sidecar on a random loopback port (`desktop/backend_main.py`) and shows the web app. One menu model feeds the web menu bar and the native menu. | built, not yet hand-checked under the current bundle id |

## What runs where

- **Docker Compose** runs two services, `api` and `web` (`docker-compose.yml`,
  plus `docker-compose.archive.yml` for the press profile). Each install is
  its own compose project with its own ports and data volume
  (`ARCHIVE_PROJECT`, `ARCHIVE_API_PORT`, `ARCHIVE_WEB_PORT` in the `Makefile`).
- **Both ports bind to `127.0.0.1` only.** Nothing is reachable from another
  computer. There is no TLS.
- **Ollama runs on the host**, outside Docker, so the model uses the
  computer's GPU and memory directly.
- **The project root** is mounted read-only into the api container; only
  `libraries.conf` and `docker-compose.override.yml` are mounted writable
  (`scripts/ensure-host-files.sh` must create them first).
- **Outbound network:** none at run time apart from loopback and the Ollama
  host. `api/tests/test_archive_no_egress.py` checks this.

## Mounts

| Mount | In the container | Access | Holds |
|---|---|---|---|
| `library/` (`LIBRARY_ROOT`) | `/library` | read-only to the app (`LIBRARY_READONLY`) | The press's documents: manuscripts, correspondence, contracts, translations, recordings. |
| `notes/` (`NOTES_PATH`) | `/notes` | read-write | Text the model must be able to read back (retrieval searches `notes/` and `library/` only). |
| `generated/` (`GENERATED_PATH`) | `/generated` | read-write | Transcripts (`generated/transcripts/`), handwriting diagrams (`generated/diagrams/`), and `generated/pillar43.config.json` (settings, including pending path changes). |
| named volume `<project>_pillar43_data` | `/data` | read-write | The SQLite database. A named volume, not a bind mount, because SQLite locking is unreliable over macOS file sharing. |

## Data: every kind, and where it lives

All tables are in the one SQLite database on the data volume unless the row
says otherwise. "Governance" marks the tables `./pillar43 backup` copies
(`api/services/archive/backup.py`, `GOVERNANCE_TABLES`); the rest can be
rebuilt from the documents by re-indexing.

| Data | Where | Governance | Implemented by | Status |
|---|---|---|---|---|
| Documents | `library/` on the host disk | no (they are the source) | | built |
| Catalog of files | `files` | no | `api/services/catalog/scan.py` | built |
| Passages (chunks) | `file_chunks` | no | `api/services/catalog/chunk.py` | built |
| Vectors | `chunk_vectors`, with `vector_generation` recording which embedder made them | no | `api/services/catalog/embed.py`, `vector_store.py` (migrations 0021, 0030) | built |
| Archive items and consent level (private / staff / model), labels (writers' terms), year | `item` | yes | `api/services/archive/items.py`, `labels.py` (0022, 0025, 0027) | built |
| Withdrawn bytes (tombstones, by SHA-256) | `tombstone`; `item.withdrawn_at` | yes | `api/services/archive/withdraw.py` (0022, 0023) | built |
| Ledger: intake, consent changes, withdrawals, every model call (hash-chained) | `ledger` | yes | `api/services/archive/ledger.py` (0024) | built |
| Receipts: one `model_call` ledger line per answer, naming the model, the prompt hash and every item in the prompt | `ledger` | yes | `api/services/archive/answers.py:_receipt` | built |
| Answers, their citations, their silences, the passages they were given | `answer`, `answer_citation`, `answer_passage` | `answer`, `answer_citation` yes; `answer_passage` no | `api/services/archive/answers.py`, `silences.py` (0023, 0027, 0031) | built |
| Annotations (right of reply beside a passage) | `annotation` | yes | `api/services/archive/annotations.py` (0026) | built |
| Correspondents and their recorded consent | `correspondent` | yes | `api/services/archive/correspondents.py` (0029) | built |
| Accounts (admin / staff / writer), scrypt hashes | `account` | yes | `api/services/archive/accounts.py` (0028) | built |
| Which writer owns which items | `item_owner` | yes | `api/services/archive/accounts.py` (0028) | built |
| Sessions (SHA-256 of the cookie token only) | `session` | no; people sign in again after a restore | `api/services/archive/accounts.py` (0028) | built |
| Background jobs | `jobs` | no | `api/services/job_store.py`, `api/services/archive/jobs.py` | built |
| Settings and pending path changes | `generated/pillar43.config.json` | no | `api/routes/settings.py`, `api/config.py` | built |
| Org configuration: kinds, default levels, labels, models | `api/orgs/<org>.yaml` (in the image) | no | `api/services/archive/org.py` | built |
| Transcripts and handwriting output | `generated/transcripts/`, `generated/diagrams/` | no | `api/services/transcription.py`, `handwriting.py` | built |
| Backups of governance state | One SQLite file written by `./pillar43 backup [dest]`, wherever the operator puts it; `backup_meta` inside records where the ledger stood | is the governance state | `api/services/archive/backup.py`, `scripts/governance.sh` | built |

## Planned

| Part | What it is | Status |
|---|---|---|
| Consent control and Gaps view (C7) | A consent control in the staff interface using Local Contexts-style labels, and a view of what the archive is missing. The People view exists (`web/src/components/Archive/People/PeopleView.tsx`); the Silences line under each answer exists (`silences.py`). | planned |
| Recordings (D3) | Local transcription of recordings with citations that play from the cited second. Transcription itself exists (`transcription.py`); the citation-to-second link does not. | planned |
| Handwriting with corrections (D4) | The page image beside its reading, with corrections recorded as ledger lines. Handwriting transcription exists (`handwriting.py`). | planned |
| Training a local model per collection (F2) | LoRA on the host, fused into an Ollama model per collection, rebuilt when its sources change; item selection only through `labels.select_for`. | planned |
| Second press (W2) | A second org configuration running from config alone. | planned |
