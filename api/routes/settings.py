"""Expose and mutate runtime configuration flags."""

from typing import Any, Callable
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from config import settings
from services.embeddings import MODEL_DIMS

router = APIRouter(prefix="/api")

AVAILABLE_EMBEDDING_MODELS = list(MODEL_DIMS.keys())


def _settings_response() -> dict:
    return {
        "library_readonly": settings.effective_library_readonly(),
        "move_confirm": settings.effective_move_confirm(),
        "ollama_base_url": settings.effective_ollama_base_url(),
        "ollama_model": settings.effective_ollama_model(),
        "embedding_model": settings.effective_embedding_model(),
        "voice_language": settings.effective_voice_language(),
        "available_embedding_models": AVAILABLE_EMBEDDING_MODELS,
        "paths": {
            "library_root": str(settings.library_root),
            "notes_path": str(settings.notes_path),
            "generated_path": str(settings.generated_path),
        },
        # Host-side paths, used by the UI for "reveal in Finder" and copy-path.
        # Under Docker these come from HOST_* env vars, because the container's
        # own paths (/notes, /library) are meaningless outside it. Natively the
        # translation is the identity — the app already runs on the host — so
        # report the real paths rather than the empty strings the env would
        # give. (The frontend falls back to `paths` when these are blank, so
        # this is honesty in the API rather than a bug fix.)
        "host_paths": {
            "library": str(settings.library_root)
            if settings.desktop_mode
            else settings.host_library_root,
            "notes": str(settings.notes_path)
            if settings.desktop_mode
            else settings.host_notes_path,
            "generated": str(settings.generated_path)
            if settings.desktop_mode
            else settings.host_generated_path,
        },
        "extra_libraries": {
            name: str(path) for name, path in settings.extra_library_mounts.items()
        },
        "excluded_extensions": sorted(settings.effective_excluded_extensions()),
        "tree_dim_extensions": sorted(settings.effective_tree_dim_extensions()),
        "local_whisper_model": settings.effective_local_whisper_model(),
        "auto_transcribe_on_catalog_run": settings.effective_auto_transcribe_on_catalog_run(),
        "video_frame_sampling": settings.effective_video_frame_sampling(),
        "transcription_max_frames_per_video": settings.effective_transcription_max_frames_per_video(),
        "available_local_whisper_models": sorted(settings._LOCAL_WHISPER_MODELS),
        "pending_path_changes": settings.pending_path_changes(),
        "pending_library_removals": settings.pending_library_removals(),
        # Which runtime this is. The UI used to infer it from an empty
        # `restart_command`, which answered a different question by accident:
        # the folder picker, the copy on the paths banner and whether
        # apply-path is even reachable all turn on this, and none of them is
        # about restarts. Explicit signal, same as `settings.desktop_mode`
        # itself (never inferred — see the maintainer notes § Desktop mode).
        "desktop_mode": settings.desktop_mode,
        # The folder the three mounts sit under when none is relocated. Empty
        # under Docker, where there is no such folder — the mounts arrive
        # independently as bind mounts.
        "vault_root": settings.vault_root_display(),
    }


class PathsBlock(BaseModel):
    library_root: str
    notes_path: str
    generated_path: str


class HostPathsBlock(BaseModel):
    library: str
    notes: str
    generated: str


class SettingsResponse(BaseModel):
    """Shape of GET /api/settings and POST /api/settings.

    Mirrors `_settings_response()` exactly so openapi-typescript can generate
    the matching TS type. Frontend imports via `components["schemas"]["SettingsResponse"]`
    in web/src/lib/api/_generated.ts — never hand-roll this shape in TS.
    """

    library_readonly: bool
    move_confirm: str
    ollama_base_url: str
    ollama_model: str
    embedding_model: str
    voice_language: str
    available_embedding_models: list[str]
    paths: PathsBlock
    host_paths: HostPathsBlock
    extra_libraries: dict[str, str]
    excluded_extensions: list[str]
    tree_dim_extensions: list[str]
    local_whisper_model: str
    auto_transcribe_on_catalog_run: bool
    video_frame_sampling: bool
    transcription_max_frames_per_video: int
    available_local_whisper_models: list[str]
    pending_path_changes: dict[str, str]
    pending_library_removals: list[str]
    desktop_mode: bool
    vault_root: str


@router.get("/settings", response_model=SettingsResponse)
async def get_settings():
    from fastapi.responses import JSONResponse

    return JSONResponse(
        content=_settings_response(),
        headers={"Cache-Control": "max-age=10, private"},
    )


class SettingsUpdate(BaseModel):
    library_readonly: bool | None = None
    move_confirm: str | None = None
    ollama_model: str | None = None
    embedding_model: str | None = None
    voice_language: str | None = None
    excluded_extensions: list[str] | None = None
    tree_dim_extensions: list[str] | None = None
    local_whisper_model: str | None = None
    auto_transcribe_on_catalog_run: bool | None = None
    video_frame_sampling: bool | None = None
    transcription_max_frames_per_video: int | None = None


# ── Field tables for update_settings ─────────────────────────────────────────
#
# Fields with no validation beyond "was it supplied". Order is irrelevant;
# each is copied straight through when not None.
# (field, transform). The transform is what the hand-written branch did to the
# value before storing it — almost always `.strip()`, because these arrive from
# text inputs and a trailing space in an API key or base URL is a support
# ticket. `None` means store it as given.
#
# This started life as a bare tuple of names, which silently dropped the
# transform on 10 of the 14 fields. One existing test caught it
# (voice_language); the other nine had no guard. Hence the explicit column:
# the shape of the table now makes "does this field transform?" a thing you
# have to answer.
_PASSTHROUGH_FIELDS: tuple[tuple[str, Callable[[Any], Any] | None], ...] = (
    ("library_readonly", None),
    ("ollama_model", str.strip),
    ("voice_language", str.strip),
    ("auto_transcribe_on_catalog_run", None),
    ("video_frame_sampling", None),
)

# (field, allowed-values, error-detail). Both callables are deferred rather
# than evaluated at import: settings._LOCAL_WHISPER_MODELS
# can change at runtime, and freezing them into a module-level tuple would
# silently validate against whatever was true when the module first loaded.
# The messages are reproduced verbatim from the branches these replaced —
# they are user-facing and asserted on in tests.
_ENUM_FIELDS: tuple[tuple[str, Callable[[], Any], Callable[[], str]], ...] = (
    (
        "move_confirm",
        lambda: ("confirm", "silent"),
        lambda: "move_confirm must be 'confirm' or 'silent'",
    ),
    (
        "embedding_model",
        lambda: AVAILABLE_EMBEDDING_MODELS,
        lambda: (
            f"embedding_model must be one of: {', '.join(AVAILABLE_EMBEDDING_MODELS)}"
        ),
    ),
    (
        "local_whisper_model",
        lambda: settings._LOCAL_WHISPER_MODELS,
        lambda: (
            "local_whisper_model must be one of: "
            f"{', '.join(sorted(settings._LOCAL_WHISPER_MODELS))}"
        ),
    ),
)


# (field, minimum, maximum, message). None means unbounded on that side.
# Three near-identical range checks; the messages are user-facing and asserted
# on in tests, so they are reproduced verbatim.
_RANGE_FIELDS: tuple[tuple[str, int | None, int | None, str], ...] = (
    (
        "transcription_max_frames_per_video",
        1,
        50,
        "transcription_max_frames_per_video must be between 1 and 50",
    ),
)

# Fields holding a list of file extensions, normalised the same way.
_EXTENSION_LIST_FIELDS: tuple[str, ...] = (
    "excluded_extensions",
    "tree_dim_extensions",
)


def _normalise_extensions(raw: list[str]) -> list[str]:
    """Lowercase, trim, drop blanks, and ensure a leading dot.

    So a user typing "PDF, .Png,  " gets [".pdf", ".png"] rather than three
    entries that never match anything.
    """
    exts = [e.strip().lower() for e in raw if e.strip()]
    return [e if e.startswith(".") else f".{e}" for e in exts]


@router.post("/settings", response_model=SettingsResponse)
async def update_settings(body: SettingsUpdate):
    updates: dict = {}

    # Declarative, not a branch each. These two tables replaced 21 hand-written
    # `if body.X is not None:` blocks — 14 passthrough and 7 near-identical
    # enum checks — which is most of why this handler scored 51 on mccabe.
    # Adding a field is now a table row, and a field cannot be silently
    # dropped by a copy-paste that forgets its assignment.
    for field, transform in _PASSTHROUGH_FIELDS:
        value = getattr(body, field)
        if value is not None:
            updates[field] = transform(value) if transform else value

    for field, lo, hi, message in _RANGE_FIELDS:
        value = getattr(body, field)
        if value is not None:
            if (lo is not None and value < lo) or (hi is not None and value > hi):
                raise HTTPException(status_code=400, detail=message)
            updates[field] = value

    for field in _EXTENSION_LIST_FIELDS:
        value = getattr(body, field)
        if value is not None:
            updates[field] = _normalise_extensions(value)

    for field, allowed, describe in _ENUM_FIELDS:
        value = getattr(body, field)
        if value is not None:
            if value not in allowed():
                raise HTTPException(status_code=400, detail=describe())
            updates[field] = value

    if updates:
        try:
            settings.save_overrides(updates)
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e)) from e

    return _settings_response()


# ── Path management ───────────────────────────────────────────────────────────


CORE_MOUNTS = ("library", "notes", "generated")
# Map core mount → host-side env var. Extra libraries no longer use env
# vars — they are written into libraries.conf and bind-mounted via
# docker-compose.override.yml. See services.libraries_config.
_CORE_MOUNT_ENV = {
    "library": "HOST_LIBRARY_ROOT",
    "notes": "HOST_NOTES_PATH",
    "generated": "HOST_GENERATED_PATH",
}


def _restart_command_for_core_changes(pending: dict, removed: list[str]) -> str:
    """Build the user-facing restart command line.

    Core mount changes (library/notes/generated) still flow through env
    vars because that's how docker-compose.yml references the host paths.
    Extra libraries do NOT contribute to this command — they're already
    committed to libraries.conf + docker-compose.override.yml by the time
    the user reads the banner. The override file is consumed automatically
    by `docker compose up --build -d`.
    """
    if settings.desktop_mode:
        # No command to give: there is no compose file and no container to
        # recreate. The paths are read from config at startup, so the whole
        # instruction is "quit and reopen". The UI shows that when this is
        # empty rather than rendering an empty <code> block.
        return ""

    env_vars: list[str] = []
    for mount, host_path in pending.items():
        if mount in removed:
            continue
        env_name = _CORE_MOUNT_ENV.get(mount)
        if env_name is None:
            # Extra library — already handled via libraries.conf.
            continue
        env_vars.append(f"{env_name}={host_path}")
    base = "docker compose up --build -d"
    return (" ".join(env_vars) + " " + base) if env_vars else base


class PathChangeRequest(BaseModel):
    mount: str  # "library" | "notes" | "generated" | <extra-library-name>
    host_path: str


@router.post("/settings/stage-path")
async def stage_path_change(req: PathChangeRequest):
    """Stage a path change. For extra libraries, writes libraries.conf and
    regenerates docker-compose.override.yml so the next `docker compose up
    --build -d` actually mounts the new library. For core mounts, the
    change is staged in `pending_path_changes` and the user must restart
    with the relevant `HOST_*` env var.

    Sprint 98 fix: previously emitted `EXTRA_LIBRARY_<NAME>=...` env-var
    commands that docker-compose.yml didn't reference. The command looked
    sensible, restarted nothing meaningful, and the library never showed
    up. See `plans/LIBRARY_ADD_RESTART_BUG.md`.
    """
    from services import libraries_config

    # Every mount: the path ends up in a bind-mount string (extra libraries) or
    # in a shell command the user is told to run (core mounts).
    try:
        libraries_config.validate_host_path(req.host_path)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e

    if req.mount in CORE_MOUNTS:
        settings.stage_path_change(req.mount, req.host_path)
    else:
        # Extra library: validate name, then write libraries.conf +
        # docker-compose.override.yml. Stage so the UI banner appears
        # (the user still needs to restart for the mount to take effect).
        try:
            libraries_config.validate_name(req.mount)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        try:
            libraries_config.add_entry(req.mount, req.host_path)
            if not settings.desktop_mode:
                # Docker only: the library reaches the container through a bind
                # mount, so the compose override has to be regenerated and the
                # stack restarted before it exists. Natively the path in
                # libraries.conf IS the path, and `extra_library_mounts` reads
                # it per call — the library is usable the moment this returns.
                libraries_config.regenerate_override()
        except OSError as e:
            detail = f"Failed to write libraries.conf: {e}"
            if not settings.desktop_mode:
                detail += " Is the project root bind-mounted into the api container?"
            raise HTTPException(500, detail) from e
        if not settings.desktop_mode:
            settings.stage_path_change(req.mount, req.host_path)

    pending = settings.pending_path_changes()
    removed = settings.pending_library_removals()
    command = _restart_command_for_core_changes(pending, removed)

    return {
        "status": "staged",
        "pending": pending,
        "pending_removals": removed,
        "restart_command": command,
    }


@router.post("/settings/clear-pending-paths")
async def clear_pending_paths():
    """Clear pending path changes (user has applied them via restart)."""
    settings.clear_pending_path_changes()
    return {"status": "cleared", "pending": {}}


@router.post("/settings/remove-library")
async def remove_library(req: PathChangeRequest):
    """Remove an extra library by dropping its entry from libraries.conf.

    Under Docker the mount survives until the stack is recreated, so the
    removal is staged and the banner asks for a restart. Natively the entry is
    the only thing that made the library visible, so it disappears from the
    tree immediately and nothing is staged.

    Only works for extra libraries (not core mounts: library, notes,
    generated).
    """
    from services import libraries_config

    if req.mount in CORE_MOUNTS:
        raise HTTPException(
            400, "Cannot remove core mounts (library, notes, generated)"
        )

    try:
        libraries_config.remove_entry(req.mount)
        if not settings.desktop_mode:
            libraries_config.regenerate_override()
    except OSError as e:
        detail = f"Failed to write libraries.conf: {e}"
        if not settings.desktop_mode:
            detail += " Is the project root bind-mounted into the api container?"
        raise HTTPException(500, detail) from e

    if not settings.desktop_mode:
        settings.stage_library_removal(req.mount)

    pending = settings.pending_path_changes()
    removed = settings.pending_library_removals()
    command = _restart_command_for_core_changes(pending, removed)

    return {
        "status": "staged",
        "pending": pending,
        "pending_removals": removed,
        "restart_command": command,
    }
