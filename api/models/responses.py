"""Pydantic v2 response models for the top-5 read endpoints.

Modelled 1:1 against the route's current dict shape. All response models
use `extra='forbid'` — any unmodeled field that escapes the route's
return statement raises ValidationError, which surfaces as a 500 in
dev. This is the catch-net the response_model discipline exists to
provide; without it, drift between backend and frontend types stays
silent until manually diffed against `web/src/types/api.ts`.

If you need to add a new field to a route's return: add it to the
matching model here AND to `web/src/types/api.ts` in the same commit.
The schema and the TS interfaces are paired by hand (no codegen) —
keep them in sync.
"""

from __future__ import annotations


from pydantic import BaseModel, ConfigDict, RootModel


# ── Threads ───────────────────────────────────────────────────────────────────


class ThreadOut(BaseModel):
    """One row in the active threads index.

    Mirrors the dict produced by `routes/threads.py:list_threads`.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    topic: str
    status: str | None = None
    status_override: str | None = None
    file_count: int
    last_active: float | None = None
    files: list[str] = []
    path: str | None = None
    has_file: bool = False
    updated_at: float | None = None
    source: str = "ai"
    priority: str = "normal"


class ThreadsResponse(BaseModel):
    threads: list[ThreadOut]


# ── Tasks ─────────────────────────────────────────────────────────────────────


class TaskOut(BaseModel):
    """One mined task — checkbox-derived or DB-sourced.

    Mirrors the dict produced by `services.task_miner.mine_tasks`.
    """

    model_config = ConfigDict(extra="forbid")

    path: str
    line: int
    text: str
    done: bool
    writable: bool
    # created_at / completed_at are stored as ISO-8601 strings in the
    # tasks table (db/tasks_store.py declares them TEXT). Accept float as
    # well because some legacy rows and the baseline_schema declaration
    # (_schema_baseline.py) carry REAL timestamps.
    created_at: str | float | None = None
    completed_at: str | float | None = None
    priority: str | None = None
    category: str | None = None
    due_date: str | None = None
    recurrence: str | None = None
    source: str = "checkbox"


class TasksResponse(BaseModel):
    tasks: list[TaskOut]


# ── Tree ──────────────────────────────────────────────────────────────────────


class TreeNode(BaseModel):
    """One file or directory node in the vault tree.

    `children` is a list when the node is expanded, None when it's a
    directory whose children haven't been loaded yet, and absent for
    files. `message` is populated for `type="unavailable"` mount-root
    nodes returned when a mount has a pending path change.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    path: str
    type: str  # 'file' | 'directory' | 'unavailable'
    mtime: float = 0.0
    ctime: float = 0.0
    children: list["TreeNode"] | None = None
    message: str | None = None


class TreeResponse(RootModel[list[TreeNode]]):
    """`GET /api/tree` returns a bare list of root mount nodes.

    Wrapped in a RootModel so the response_model annotation can document
    the shape without inventing a `tree` envelope that doesn't exist on
    the wire.
    """


# ── Catalog ───────────────────────────────────────────────────────────────────


class MountStatusOut(BaseModel):
    """Per-mount catalog row produced by `GROUP BY mount`."""

    model_config = ConfigDict(extra="forbid")

    mount: str
    file_count: int
    last_summarized: float | None = None


class ConnectionCountOut(BaseModel):
    """Per-kind file_connections row produced by `GROUP BY kind`."""

    model_config = ConfigDict(extra="forbid")

    kind: str
    count: int


class CatalogStatus(BaseModel):
    """Response for `GET /api/catalog/status`.

    The route returns either a full status dict or — when the DB query
    raises — a degraded stub with `total_files=0, mounts=[], connections=[]`
    and an `error` string. Both shapes share these keys, so we model them
    on a single class with optional fields for the rest.
    """

    model_config = ConfigDict(extra="forbid")

    total_files: int
    mounts: list[MountStatusOut] = []
    connections: list[ConnectionCountOut] = []
    thread_count: int | None = None
    last_scan: float | str | None = None
    interrupted: bool | None = None
    error: str | None = None


class CatalogStats(BaseModel):
    """Response for `GET /api/catalog/stats` — lightweight startup banner."""

    model_config = ConfigDict(extra="forbid")

    file_count: int
    last_indexed: str | float | None = None
    interrupted: bool
    # Non-null when stats could not be read (DB busy/unavailable). The UI must
    # treat this as "unknown", NOT as "0 files / empty vault" — otherwise a
    # transient DB error masquerades as a fresh, un-indexed vault.
    error: str | None = None


class CatalogBreakdownMount(BaseModel):
    """Per-mount slice for CatalogBreakdown."""

    model_config = ConfigDict(extra="forbid")

    mount: str
    total: int
    summarized: int
    extracted: int


class CatalogBreakdown(BaseModel):
    """Response for `GET /api/catalog/breakdown` — replaces the single
    'files indexed' count in the Maintain health bar with the real
    breakdown (rows / summarized / extracted / per-mount). See
    MAINTAIN_PANEL_PLAN.md §1.5 — the user's vault has 32k rows but
    only ~5% summarized, so the old single-number display was misleading.
    """

    model_config = ConfigDict(extra="forbid")

    total: int
    summarized: int
    extracted: int
    last_indexed: str | float | None = None
    interrupted: bool
    by_mount: list[CatalogBreakdownMount]


# Forward-ref resolution for self-referencing TreeNode.
TreeNode.model_rebuild()


# ── Saved Searches (Sprint 92 Day 1) ─────────────────────────────────────────


class SavedSearchOut(BaseModel):
    """One row from `saved_searches` — a per-vault named query.

    `name` is unique; POST UPSERTs by name. `ai` and `semantic` are
    surfaced as ints (0/1) at the SQL layer; the route maps them to
    bool here for cleaner TypeScript mirroring. They are
    mutually exclusive at the UI level (semantic search is a different
    code path from AI rerank), but the backend doesn't enforce that —
    rare future need for both.
    """

    model_config = ConfigDict(extra="forbid")

    id: int
    name: str
    query: str
    scope: str
    ai: bool
    semantic: bool
    created_at: float
    last_used_at: float | None = None
    use_count: int


class SavedSearchesResponse(BaseModel):
    searches: list[SavedSearchOut]


# ── Wikilinks / Backlinks (Sprint 92 Day 3) ──────────────────────────────────


class BacklinkEdge(BaseModel):
    """One inbound or outbound wikilink edge for a given file.

    `path` is the OTHER end of the edge (so for inbound, this is the
    source file linking IN; for outbound, it's the target file being
    linked TO). `line` is the source-file line where the wikilink
    appears. `summary` is short (or NULL) — copied from `files.summary`
    so the frontend can render context without a second query.
    """

    model_config = ConfigDict(extra="forbid")

    path: str
    line: int
    summary: str | None = None


class BacklinksResponse(BaseModel):
    """Response for `GET /api/file/backlinks?path=X`.

    `inbound`: files that wikilink TO `path`.
    `outbound`: files that `path` wikilinks TO.
    `catalogued`: whether the file has been indexed (false = empty results expected).
    """

    model_config = ConfigDict(extra="forbid")

    path: str
    inbound: list[BacklinkEdge] = []
    outbound: list[BacklinkEdge] = []
    catalogued: bool = True
