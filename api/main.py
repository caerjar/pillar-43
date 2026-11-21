import logging
import os
import sys
from contextlib import asynccontextmanager

# Configure the root logger before other imports run, so anything logged during
# import lands in `docker logs`. This used to be undone by Alembic's fileConfig
# during DB schema init below (alembic.ini sets the root logger to WARN), which
# needed a _reconfigure_logging() repair pass afterwards; migrations no longer
# touch logging — see api/migrations/env.py.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    stream=sys.stderr,
    force=True,
)

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse

from config import settings

from routes.ai import router as ai_router
from routes.archive import router as archive_router
from routes.archive_explore import router as archive_explore_router
from routes.catalog import router as catalog_router
from routes.files import router as files_router
from routes.settings import router as settings_router
from routes.settings_paths import router as settings_paths_router
from routes.vault import router as vault_router
from routes.search import router as search_router
from routes.transcription import router as transcription_router
from routes.handwriting import router as handwriting_router

logger = logging.getLogger(__name__)
logging.getLogger("onnxruntime").setLevel(logging.ERROR)


async def _startup_orphan_cleanup() -> None:
    """Mark jobs stuck in 'running' state as cancelled on API startup.

    Runs two passes:
      1. `reclassify_running_jobs_as_interrupted` — any row still in
         'running' status is, by definition, an orphan: its owning thread
         died when the previous container went down. Catches the case where
         the user restarted within 2 minutes of a live scan and would
         otherwise see Run buttons disabled until heartbeat-stale elapses.
      2. `cleanup_old_jobs` — deletes old finished rows + applies the
         threshold-based sweep for any future orphans during this run.

    Runs after DB schema init (which happens during module import below).
    """
    import asyncio
    from services.job_store import (
        cleanup_old_jobs,
        reclassify_running_jobs_as_interrupted,
    )

    def _cleanup():
        interrupted = reclassify_running_jobs_as_interrupted()
        if interrupted:
            logger.info(
                "Startup reclassified %d orphan running job(s) as interrupted",
                interrupted,
            )
        cleanup_old_jobs()
        logger.info("Startup orphan cleanup completed")

    try:
        await asyncio.to_thread(_cleanup)
    except Exception as e:
        logger.error("Startup orphan cleanup failed: %s", e, exc_info=True)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Startup work before `yield`, shutdown work after.

    The `_app` argument is required by FastAPI's lifespan protocol and
    unused here — underscore-prefixed so the linter does not flag it and the
    next reader does not go looking for where it is consumed.

    Replaces the deprecated `@app.on_event("startup"/"shutdown")` pair. The
    two halves keep their original behaviour exactly, including that each
    swallows its own exceptions: orphan cleanup may not prevent the API from
    serving.

    Note what is deliberately NOT in here — DB schema init and config
    validation stay at module import below. See the comment there.
    """
    await _startup_orphan_cleanup()
    yield


# Version is the git tag, injected at image build time — NOT a literal here.
# It was hardcoded "0.1.0" while web/package.json said "0.0.1"; two
# hand-maintained version strings had already drifted apart with no release to
# anchor either. "dev" for an untagged build, which is what it is.
app = FastAPI(
    title="pillar43",
    version=os.environ.get("PILLAR43_VERSION", "dev"),
    lifespan=lifespan,
)


# Initialize database schema immediately during module import.
# This ensures migrations run before FastAPI starts handling requests.
#
# Deliberately NOT in the lifespan startup half: module-level code in the
# routers imported above touches the DB during import, which is before any
# lifespan hook would run. The original note here said "cannot use
# @app.on_event due to deadlock (see TODO below)" and pointed at a TODO that
# does not exist anywhere in this file — the reference was already dangling
# when the lifespan migration landed 2026-08-17.
try:
    from services.db import get_db

    _init_conn = get_db()
    _init_conn.close()
    logger.info("Database schema initialized successfully")
except Exception as e:
    logger.error("Failed to initialize database schema: %s", e, exc_info=True)


# Fail-fast config validation: surface a broken mount / missing key as a clear
# startup log line instead of an opaque error at first use. Strict (refuse to
# start) in production; advisory under tests (tmp mounts always exist anyway).
try:
    settings.validate_startup(strict=not settings.testing)
except RuntimeError:
    logger.error("Refusing to start due to config problems (see above).")
    raise


# A staged path change means "restart to apply". This IS that restart, so any
# entry the running mounts already satisfy is stale — and a surviving entry
# makes services/vault/tree.py answer 503 for that mount, leaving the user with
# a broken tree and a banner asking them to do the thing they just did.
# Must run before the first request, hence module level rather than lifespan.
try:
    _cleared = settings.reconcile_pending_path_changes()
    if _cleared:
        logger.info("Applied staged path changes: %s", ", ".join(_cleared))
except Exception:
    logger.warning("Could not reconcile staged path changes", exc_info=True)


from services.origin_guard import CORS_ORIGINS, OriginGuardMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "PATCH", "PUT"],
    allow_headers=["Content-Type", "Authorization", "Accept"],
)

# Cross-origin pages can still make the browser SEND a no-preflight POST; CORS
# only hides the response. Refuse unsafe methods from foreign origins.
# See services/origin_guard.py.
app.add_middleware(OriginGuardMiddleware)

# Anti-DNS-rebinding: reject requests whose Host header isn't in the allowlist,
# so a web page the user visits can't rebind a hostname to 127.0.0.1 and drive
# the API cross-origin. Loopback-only by default; extend via ALLOWED_HOSTS.
# See config.effective_allowed_hosts.
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=settings.effective_allowed_hosts(),
)

# Organization edition: only the endpoints the org screens use answer, and
# no route serves an item consent closes to staff. No-op in personal.
from services.archive.access import org_gate as _org_gate

app.middleware("http")(_org_gate)

app.include_router(files_router)
app.include_router(search_router)
app.include_router(ai_router)
app.include_router(catalog_router)
app.include_router(settings_router)
app.include_router(settings_paths_router)
app.include_router(vault_router)
app.include_router(transcription_router)
app.include_router(handwriting_router)
# Organization edition.
app.include_router(archive_router)
app.include_router(archive_explore_router)


@app.exception_handler(Exception)
async def _global_exception_handler(request: Request, _exc: Exception) -> JSONResponse:
    """Catch-all handler: log the real error server-side, return a generic body.

    Prevents internal exception messages (which may contain API keys, paths, or
    other sensitive details) from leaking into HTTP 500 response bodies.
    """
    # LOG004 is a false positive here: Starlette invokes exception handlers from inside its own
    # `except` block, so sys.exc_info() is set and .exception() does capture the
    # traceback. Losing it here would defeat the whole point of this handler.
    logger.exception(  # noqa: LOG004
        "Unhandled exception on %s %s", request.method, request.url.path
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )


@app.get("/health")
async def health() -> dict:
    """Liveness probe + build stamp.

    `api_sha` / `web_sha` / `built_at` are injected at image build time via
    Docker ARGs (see api/Dockerfile, web/Dockerfile). Falls back to "unknown"
    when running outside Docker without the env vars set.

    `missing_capabilities` lists external binaries that are absent (see
    services/capabilities.py). In Docker it is always empty — the image
    installs all of them. It exists for the desktop build, where the Tauri
    shell polls this endpoint before showing the window and can surface a
    degradation the user would otherwise only meet as a broken feature.
    `status` stays "ok": a missing optional binary is a degradation, not a
    liveness failure, and a health probe that fails on it would stop the app
    from starting at all.
    """
    import os

    from services import capabilities

    return {
        "status": "ok",
        "service": "api",
        "version": os.environ.get("PILLAR43_VERSION", "dev"),
        "api_sha": os.environ.get("PILLAR43_API_SHA", "unknown"),
        "web_sha": os.environ.get("PILLAR43_WEB_SHA", "unknown"),
        "built_at": os.environ.get("PILLAR43_BUILT_AT", "unknown"),
        "missing_capabilities": capabilities.missing(),
    }


# ── Optional: serve the built SPA from this process ──────────────────────────
#
# Off unless WEB_DIST_PATH is set, so the Docker stack is untouched: there,
# nginx serves web/dist and proxies /api to this process (see web/nginx.conf).
#
# The desktop build has no nginx, and this is why it doesn't need one. Serving
# the SPA from the API means the page's origin IS the API's origin, which
# removes three problems rather than solving them:
#
#   - `_fetch.ts`'s `BASE = import.meta.env.VITE_API_URL ?? ''` is baked at
#     build time, so it cannot learn a port chosen at launch. Same-origin means
#     it stays '' and keeps working, and the `apiBase.test.ts` lexical guard
#     keeps passing untouched.
#   - No CORS entry is needed for the shell's origin, and `allow_origins` is an
#     exact-match list including the port — which a dynamic port cannot satisfy.
#   - `PDFViewer.tsx`'s `new URL(url, window.location.origin)` resolves against
#     the right origin for free.
#
# Registered last, so every /api route and /health match first. There is
# deliberately no SPA catch-all: the frontend has no client-side router (panels
# are state-driven), so an unknown path is genuinely a 404 and pretending
# otherwise would mask typos with a blank app shell.
_web_dist = os.environ.get("WEB_DIST_PATH", "").strip()
if _web_dist:
    from pathlib import Path as _Path

    from fastapi.staticfiles import StaticFiles

    _dist = _Path(_web_dist)
    if _dist.is_dir() and (_dist / "index.html").is_file():
        app.mount("/", StaticFiles(directory=_dist, html=True), name="web")
        logger.info("Serving frontend from %s", _dist)
    else:
        # Loud, because the window would otherwise open on a blank page and the
        # cause would be invisible.
        logger.error(
            "WEB_DIST_PATH=%s is not a built frontend directory "
            "(no index.html) — the UI will not be served",
            _web_dist,
        )
