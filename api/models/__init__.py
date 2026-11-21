"""Pydantic response models for API contracts.

These models attach to FastAPI routes via `response_model=` so the OpenAPI
schema published at `/docs` is the single source of truth for the
frontend `web/src/types/api.ts`.

Models are written to match the existing dict shapes 1:1 — they document,
not redesign, the wire format. Optional / sometimes-missing fields are
typed `T | None = None`.
"""

from .responses import (
    CatalogBreakdown,
    CatalogBreakdownMount,
    CatalogStats,
    CatalogStatus,
    ConnectionCountOut,
    MountStatusOut,
    TaskOut,
    TasksResponse,
    ThreadOut,
    ThreadsResponse,
    TreeNode,
    TreeResponse,
)

__all__ = [
    "CatalogBreakdown",
    "CatalogBreakdownMount",
    "CatalogStats",
    "CatalogStatus",
    "ConnectionCountOut",
    "MountStatusOut",
    "TaskOut",
    "TasksResponse",
    "ThreadOut",
    "ThreadsResponse",
    "TreeNode",
    "TreeResponse",
]
