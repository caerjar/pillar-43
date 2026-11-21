"""Read-only GET /stats for the catalog.

The endpoint is designed to never 500 — the health bar polls it every 60s, and a 500 here cascades into a
blank UI. OperationalError (DB locked by a writing pass) is caught
explicitly; the response degrades to zero-counts so the UI stays alive.
"""

import contextlib
import logging
import sqlite3

from models import CatalogStats
from services.catalog.state import read_catalog_state

from . import router

log = logging.getLogger("routes.catalog")


@router.get("/stats")
async def get_catalog_stats():
    """Return global catalog statistics.

    Must NEVER 500. The Maintain panel + bottom alert bar both poll this on
    a 60s interval; a 500 here cascades and the user sees a blank health bar.
    OperationalError (DB locked by an active catalog write) is caught
    explicitly and serves a degraded response — keep the UI alive.
    """
    conn = None
    try:
        from services.db import get_db

        conn = get_db()
        file_count = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]

        # Get last indexed time from catalog state, with fallback to the
        # newest summary timestamp if state.finished_at was never written
        # (e.g. every prior run hit billing-exhausted or was cancelled before
        # write_catalog_state with finished_at could fire).
        state = read_catalog_state()
        last_indexed = state.get("finished_at")
        if not last_indexed:
            try:
                row = conn.execute(
                    "SELECT MAX(cataloged_at) FROM files "
                    "WHERE summary IS NOT NULL AND summary != ''"
                ).fetchone()
                if row and row[0]:
                    last_indexed = row[0]
            except sqlite3.OperationalError:
                # Lock contention on this fallback query is non-fatal —
                # the primary value is the file_count above.
                pass
        interrupted = state.get("in_progress", False)

        return CatalogStats(
            file_count=file_count or 0,
            last_indexed=last_indexed,
            interrupted=interrupted,
        )
    except sqlite3.OperationalError as e:
        # DB locked — common when the catalog scan holds the writer slot.
        # Serve a degraded response so the frontend's 60s poll keeps working,
        # but flag it as `error` so the UI shows "unknown", not "empty vault".
        log.warning("[catalog/stats] DB busy — serving degraded stats: %s", e)
        return CatalogStats(
            file_count=0, last_indexed=None, interrupted=False, error="busy"
        )
    except Exception as e:
        log.warning("Failed to fetch catalog stats: %s", e, exc_info=True)
        return CatalogStats(
            file_count=0, last_indexed=None, interrupted=False, error="unavailable"
        )
    finally:
        if conn:
            with contextlib.suppress(Exception):
                conn.close()
