# routes/ — FastAPI routers

One line per file. New endpoints register in `api/main.py` (explicit imports — no dynamic discovery).

| File | Prefix | What it serves |
|---|---|---|
| `files.py` | `/api/tree*`, `/api/file*` | Read-only: tree listing, `file/raw`, `file/text`, `file/pdf-info`, `file/pdf-page`, `GET /api/file`. The write, move, trash, duplicate, rename, restore, folder and find handlers were removed (the org profile never writes the vault). |
| `vault.py` | `/api/library` | `library/status` (mount health). `POST library/init` was removed. |
| `settings.py` | `/api/settings*` | GET/POST settings, `_settings_response()` shape, `SettingsUpdate` Pydantic model. Path-staging endpoints live here too. |
| `catalog/` (package) | `/api/catalog*` | `read.py`: `GET /api/catalog/stats` only. The Maintain pipeline routes (`run.py`, `passes/`, `_helpers.py`) were removed. |
| `ai/` (package) | `/api/ai*` | `_provider.py`: `GET /api/ai/local-models` (Ollama model discovery). The chat, inline, classify, folder-generate, agent and `ping` routes were removed. |
| `search.py` | `/api/search` | ripgrep-backed full-text search. Always `--fixed-strings --ignore-case`. |
| `transcription.py` | `/api/transcription*` | Audio/video → text endpoints. |
| `archive.py`, `archive_explore.py` | `/api/archive*` | The org routers (ask, consent, withdraw, explore). See `services/archive/`. |
| `settings_paths.py` | `/api/settings/paths*` | Mount path staging. |
| `_sse_worker.py` | Not a router — `stream_background_work()`, the queue.Queue + daemon-thread + async-generator scaffold shared by the handwriting and transcription SSE endpoints. Two behaviours are load-bearing: the worker keeps running after a client disconnect (so the artifact is still written), and worker exceptions go through `_human_error` before reaching the wire (provider SDKs put the API key in the exception body). |
| `handwriting.py` | `/api/handwriting*` | Image/PDF → markdown + SVG diagrams via a tool-use prompt. Reached from the file tree's right-click "Transcribe handwriting" (`TreeNodeRow.tsx`); accepted extensions must stay in sync with `services/handwriting.py:HANDWRITING_EXTS` and `web/src/lib/multimediaExts.ts`. |

When adding a router:
1. Create the file with `router = APIRouter(prefix="/api/<name>")`.
2. Add `from routes.<name> import router as <name>_router` and `app.include_router(<name>_router)` in `api/main.py`.
3. Add a row here.
4. If using SSE, reuse `routes/_sse_worker.py:stream_background_work` and `services/sse_format.py`.
