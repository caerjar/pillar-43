"""What a person at the machine may reach in the organization edition.

`fetch_materials` decides what the *model* reads. This module decides what
the *HTTP API* serves, so a private item cannot be opened, listed or found
by search either. Both read consent from the same `item` table.

Two layers, both fail closed:
  1. `org_gate` (middleware): only the endpoints the archive screens use
     answer at all; everything else is 404. This stays unconditional: it is
     what hides the transcription and handwriting routes until W6 opens them
     through consent. Any `path` query parameter must
     name an item a staff member may see.
  2. `staff_may_see` / `filter_tree` / `filter_results`: the listing routes
     (tree, search) drop items staff may not see from their output.

Only `library/` holds the archive. `notes/` and `generated/` are the app's
own working space (and `generated/catalog_summary.md` summarises every file,
private ones included), so they are never served.
"""

from __future__ import annotations

from collections.abc import Iterable

from fastapi import Request
from starlette.responses import JSONResponse

from services.archive.items import allowed_paths

# GET endpoints the org screens use (taken from the org api log,
# 2026-11-18). Exact paths, or prefixes ending in "/".
ORG_GET_ALLOW: tuple[str, ...] = (
    "/api/archive/",
    "/api/settings",
    "/api/settings/",
    "/api/tree",
    "/api/tree/dir",
    "/api/file",
    "/api/file/raw",
    "/api/file/pdf-info",
    "/api/file/pdf-page",
    "/api/file/text",
    "/api/search",
    "/api/library/status",
    "/api/catalog/stats",
    "/api/ai/local-models",
)
# Anything that changes state. Settings saves; archive asks.
ORG_WRITE_ALLOW: tuple[str, ...] = ("/api/archive/", "/api/settings", "/api/settings/")

# Query parameters that name a vault file.
_PATH_PARAMS = ("path", "src", "dest", "from_path", "to_path", "thread_folder")


def _allowed(url_path: str, allow: tuple[str, ...]) -> bool:
    return any(
        url_path.startswith(a) if a.endswith("/") else url_path == a for a in allow
    )


def staff_may_see_many(rel_paths: Iterable[str]) -> set[str]:
    """The subset of `rel_paths` a staff member may see."""
    paths = list(rel_paths)
    lib = [p for p in paths if p.startswith("library/")]
    if not lib:
        return set()
    from services.db import get_db

    conn = get_db()
    try:
        return allowed_paths(conn, lib, "staff")
    finally:
        conn.close()


def staff_may_see(rel_path: str) -> bool:
    p = rel_path.lstrip("/")
    return p in staff_may_see_many([p])


def filter_results(results: list[dict], key: str = "path") -> list[dict]:
    ok = staff_may_see_many({r[key] for r in results if r.get(key)})
    return [r for r in results if r.get(key) in ok]


def _tree_paths(nodes: list[dict]) -> list[str]:
    out: list[str] = []
    for n in nodes:
        if n.get("type") == "file":
            out.append(n["path"])
        for c in n.get("children") or []:
            out.extend(_tree_paths([c]))
    return out


def filter_tree(nodes: list[dict]) -> list[dict]:
    """Keep the `library` mount, and in it only files staff may see and the
    directories that still contain one. Original order is kept."""
    ok = staff_may_see_many(_tree_paths(nodes))

    def keep(n: dict) -> dict | None:
        if n.get("type") == "file":
            return n if n["path"] in ok else None
        children = n.get("children")
        if children is None:  # lazy directory: its level is filtered on load
            return n
        kept = [k for k in (keep(c) for c in children) if k is not None]
        return {**n, "children": kept} if kept else None

    roots = [n for n in nodes if str(n.get("path", "")).split("/")[0] == "library"]
    return [k for k in (keep(n) for n in roots) if k is not None]


def filter_children(children: list[dict]) -> list[dict]:
    """One lazily loaded level under `library/`: drop files staff may not see.
    Directories stay (their own level is filtered when opened)."""
    ok = staff_may_see_many(c["path"] for c in children if c.get("type") == "file")
    return [c for c in children if c.get("type") != "file" or c["path"] in ok]


_NOT_FOUND = {"detail": "Not found"}

# Readable without a session even once accounts exist: the app asks the
# profile first to know whether to draw a sign-in.
_PUBLIC = ("/api/archive/profile", "/api/archive/login")


def _session_account(request: Request) -> tuple[bool, dict | None]:
    """(accounts_exist, the signed-in account or None)."""
    from services.archive.accounts import COOKIE, account_for_token, accounts_exist
    from services.db import get_db

    conn = get_db()
    try:
        if not accounts_exist(conn):
            return False, None
        token = request.cookies.get(COOKIE)
        auth = request.headers.get("authorization", "")
        if not token and auth.lower().startswith("bearer "):
            token = auth[7:].strip()
        return True, account_for_token(conn, token)
    finally:
        conn.close()


async def org_gate(request: Request, call_next):
    """Middleware: the allowlist, session and consent gate for every /api/ request."""
    url_path = request.url.path
    if not url_path.startswith("/api/"):
        return await call_next(request)
    allow = ORG_GET_ALLOW if request.method in ("GET", "HEAD") else ORG_WRITE_ALLOW
    if not _allowed(url_path, allow):
        return JSONResponse(_NOT_FOUND, status_code=404)
    have_accounts, acct = _session_account(request)
    request.state.account = acct
    if have_accounts and url_path not in _PUBLIC:
        if acct is None:
            return JSONResponse({"detail": "Sign in"}, status_code=401)
        if not url_path.startswith("/api/archive/"):
            # A writer has no business in the staff file views; only an admin
            # changes settings.
            if acct["role"] == "writer" or (
                acct["role"] != "admin" and request.method not in ("GET", "HEAD")
            ):
                return JSONResponse(_NOT_FOUND, status_code=404)
    for name in _PATH_PARAMS:
        for value in request.query_params.getlist(name):
            if url_path == "/api/tree/dir":
                # A directory is not an item; its children are filtered.
                ok = value.strip("/") == "library" or value.startswith("library/")
            else:
                ok = staff_may_see(value)
            if not ok:
                return JSONResponse(_NOT_FOUND, status_code=404)
    return await call_next(request)
