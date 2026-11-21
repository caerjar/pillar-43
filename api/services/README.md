# services/ — backend logic modules

One line per module. Use this to find the right service fast instead of `ls`-ing the directory.

LOC is noted for modules over ~400 lines, so this doubles as a code-health map.

> **Rewritten 2026-07-20 against the files actually on disk.** The previous
> version documented 18 modules deleted one or two refactors ago — the whole
> Counter-Archive layer (`counter_archive.py`, `fabulation*.py`,
> `counterfactual*.py`, `apparatus.py`), the Roundtable orchestrator and its
> satellites (`sessions.py`, `agent_identity.py`, `roundtable_prompts.py`,
> `librarian_*.py`), and `skill_loader.py`. None of those exist. If you find a
> doc still referencing them, it is stale.

## Storage + infra

| File | What it does |
|---|---|
| `db.py` | SQLite catalog DB — `get_db()`, `init_schema()` (runs `alembic upgrade head` on first open per process), plus a one-time migration from the legacy bind-mount location. **Always use `settings.db_path`**, never `generated_path / "pillar43.db"`. |
| `job_store.py` (423 LOC) | Background-job registry, SQLite-backed. `create_job` / `update_job` / `try_update_job` / `heartbeat` / `cancel_job` / `is_cancelled`. Also `reclassify_running_jobs_as_interrupted()` (startup) and `retry_cancel_in_background()` (sub-10s Stop recovery). Single-writer pattern — see the maintainer notes. |
| `embeddings.py` | In-process fastembed (the `embeddings` container was removed 2026-08-18). `embed_texts`, `embed_query`, `effective_dims`, `release_model`, `MODEL_DIMS`. Model files read from `FASTEMBED_CACHE_PATH`, else the baked `/opt/fastembed`; never downloaded. |
| `vector_store.py` | Embeddings in SQLite (`chunk_vectors`), searched with numpy — `ensure_collection`, `upsert_points`, `search`, `search_chunks`, `delete_by_file`, `file_centroids`, `reset_collection`. Point IDs are `file_chunks.id`. Replaced `qdrant_store.py` 2026-08-18. |
| `libraries_config.py` | Read/mutate `libraries.conf` and regenerate `docker-compose.override.yml` in-process. Python port of `scripts/gen-libraries-override.sh`; the two produce equivalent mounts but not identical bytes — each stamps its own provenance header, and only the Python side writes `libraries.conf`. Both EMPTY the override rather than deleting it (a bind-mounted file cannot be unlinked from inside a container). |
| `sse_format.py` | The SSE wire format (`data: {json}\n\n`) in one place, plus the `[DONE]` sentinel. Was hand-written at 30 call sites across 15 modules, each independently remembering that a frame terminates on a BLANK line — a single missing `\n` yields a stream the browser accepts and then never dispatches from.  |

## File / vault

| File | What it does |
|---|---|
| `vault/` (package) | File reads and the writes the transcription and handwriting services make. `__init__.py` re-exports the public surface. `io.py` (`read_file`, `write_file`), `tree.py` (`get_tree`, `get_dir_children`), `extraction.py` (EPUB/DOCX stdlib-only, PDF via pypdf), `pdf.py` (PDFium rendering, page counts), `metadata.py`, `constants.py`. The trash, move/rename and wikilink-rewrite modules and `git_history.py` were removed with the personal app. |

## Catalog (scan → chunk → embed)

| File | What it does |
|---|---|
| `catalog/` (package) | The ingest pipeline: scan, chunk, embed. `orchestrator.py` (`run_catalog`) is the entry point `archive/index.py` calls. `scan.py` (filesystem walk + upsert), `chunk.py` / `chunking.py` (passages into `file_chunks`), `embed.py` (passages into `chunk_vectors`), `forget.py`, `reports.py`, `state.py`, `constants.py`, `code_projects.py`. Chunk and embed invariants are in the maintainer notes. |
| `catalog/extract.py` | Hash, frontmatter parse, authorship, text extraction, upsert. **`_strip_surrogates` lives here** — every extraction path must go through it before persistence (SQLite rejects unpaired UTF-16 surrogates). |

## Errors + retrieval

| File | What it does |
|---|---|
| `ai_errors.py` | Typed exceptions (Billing / Auth / ModelNotFound / ProviderConnection / RateLimit), `_is_*` classifiers, `_human_error` (used by `routes/ai/_provider.py`). |
| `retrieval.py` | **The shared vault-retrieval chokepoint.** `fetch_materials_counted(topic, audience=...)` = embed, vector search, plus ripgrep `--fixed-strings --ignore-case`, merged by `rel_path` (semantic wins), hydrated from `files`, filtered on item consent, sorted, trimmed. Never raises. Caller: `archive/ask.py`. |

## Transcription + handwriting

| File | What it does |
|---|---|
| `transcription.py` (681 LOC) | Audio/video → text via faster-whisper (local); images → a caption from the local vision model. Writes `generated/transcripts/<encoded>.md`. Hash-based dedup short-circuits unchanged re-runs. |
| `handwriting.py` (608 LOC) | Handwriting → markdown plus 0..N SVG diagrams, via the local vision model returning JSON against a schema (not free-text captioning). Accepts images, HEIC, and multi-page PDFs. **Reachable**: `routes/handwriting.py` → the "Transcribe handwriting" right-click action in `web/src/components/FileTree/TreeNodeRow.tsx`. |

## Private helpers (underscore-prefixed — internal use)

- `_media_exts.py` — audio/video/image extension sets. Single source of truth, kept outside `transcription.py` to break an import cycle. Frontend mirror at `web/src/lib/multimediaExts.ts`.
- `_transcript_path.py` — `transcript_path(rel_path)` → `generated/transcripts/<mount__path>.md`. Pure string manipulation.
- `_diagram_path.py` — `diagram_path(rel_path, index)` → `generated/diagrams/<mount__path>.N.svg`. Pure string manipulation; **does not validate traversal** — always write through `vault.write_file`.
- `_schema_baseline.py` — frozen `BASELINE_SQL`, shared by Alembic's `0001_baseline` and the in-memory test DB. Do not edit; write a migration instead.

When adding a service: put it here, add a row, prefer single-responsibility files. Anything over ~600L is a candidate to split into a package (see `vault/` and `catalog/` precedents).
