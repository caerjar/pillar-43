"""Applying a vault path change, natively.

Split from `routes/settings.py` (already ~600 lines) rather than added to it.

**Why this is separate from `stage-path`.** Staging writes a note saying "the
app must restart before this takes effect", which is the honest answer under
Docker: the mounts are bind mounts, so the path only changes when someone
edits `.env` and recreates the container.

Natively that answer was a trap. `main.rs` re-derived the paths from
`$HOME/Pillar-43` on every launch and never read the staged note, so quitting
and reopening did **not** apply anything — while `services/vault/tree.py`
answered 503 for the staged mount until it was cancelled. The user was told to
restart, restarted, and got the same broken tree (US-122).

Applying now means two things, in this order:

1. **Record it where the shell reads it** — `locations.json`, in the app-support
   directory. See `Settings.write_locations`.
2. **Take effect.** Before the vault is initialised there is nothing to move,
   so the running process just adopts the new path. Afterwards there is a git
   repo, live SQLite, a vector cache and a running scheduler, so the honest
   answer is still a restart — but now it is a restart that works.
"""

from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from config import settings

router = APIRouter(prefix="/api")

# The mounts a user can relocate. `library` is here too: an existing archive
# living somewhere else is the common case, and it is what "multiple library
# vaults" starts from. Extra libraries are NOT here — they go through
# libraries.conf via stage-path, which is already live natively.
APPLICABLE_MOUNTS = ("notes", "generated", "library")


class ApplyPathRequest(BaseModel):
    mount: str
    host_path: str


class ApplyPathResponse(BaseModel):
    applied: bool
    restart_required: bool
    mount: str
    host_path: str
    reindex_required: bool
    message: str


def _probe_writable(path: Path) -> bool:
    """Can we actually create files here?

    Write and unlink rather than `os.access`, which consults the mode bits and
    is wrong on exactly the volumes people pick for a vault — network shares
    and iCloud, where the mode says yes and the write fails.
    """
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".pillar43-write-probe"
        probe.write_text("")
        probe.unlink()
        return True
    except OSError:
        return False


def _validate(mount: str, host_path: str) -> Path:
    """Reject what cannot work, with a reason the user can act on."""
    if mount not in APPLICABLE_MOUNTS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"'{mount}' is not a relocatable mount. "
                f"Expected one of: {', '.join(APPLICABLE_MOUNTS)}. "
                "Extra libraries are added through stage-path instead."
            ),
        )

    candidate = Path(host_path)
    if not candidate.is_absolute():
        raise HTTPException(
            status_code=400, detail=f"Path must be absolute: {host_path!r}"
        )

    resolved = candidate.expanduser().resolve()

    if resolved == Path.home():
        raise HTTPException(
            status_code=400,
            detail=(
                "Refusing to use your home folder directly — Pillar-43 would "
                "index everything in it. Choose or create a folder inside it."
            ),
        )

    # Nesting check. `generated` inside `notes` means git versions every AI
    # artifact and the catalog counts each file twice; `notes` inside `library`
    # puts a writable mount inside a read-only one, so the two guards disagree
    # about the same file. Both look fine until they very much do not.
    for other in APPLICABLE_MOUNTS:
        if other == mount:
            continue
        try:
            other_path = Path(settings.all_mounts[other]).resolve()
        except (KeyError, OSError):
            continue
        if resolved == other_path:
            raise HTTPException(
                status_code=400,
                detail=f"That folder is already the '{other}' mount.",
            )
        if other_path in resolved.parents:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"'{mount}' cannot live inside '{other}' ({other_path}). "
                    "Nested mounts double-count files and cross the "
                    "read-only boundary."
                ),
            )
        if resolved in other_path.parents:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"'{other}' ({other_path}) is inside that folder. "
                    "Choose one that does not contain another mount."
                ),
            )

    if not _probe_writable(resolved):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot write to {resolved} — check permissions, or pick another folder.",
        )

    return resolved


def _vault_is_initialised() -> bool:
    """Has this vault got content the app cannot simply walk away from?

    The same three signals `routes/vault.py` uses for `git_ready`, and for the
    same reason: they are what distinguishes "the user is still choosing" from
    "there is a repo, a catalog and a scheduler pointed at this".
    """
    from routes.vault import INIT_MARKER, _indexed_count

    if (settings.notes_path / ".git").exists():
        return True
    if (settings.generated_path / INIT_MARKER).exists():
        return True
    try:
        return (_indexed_count("notes") + _indexed_count("library")) > 0
    except Exception:
        # Unreadable DB: assume initialised. Wrongly staging a restart is
        # recoverable; wrongly reassigning paths under a live catalog is not.
        return True


@router.post("/settings/apply-path", response_model=ApplyPathResponse)
async def apply_path(req: ApplyPathRequest):
    """Point a core mount at a new folder, and make it true.

    409 under Docker — there the path is a bind mount and only `.env` plus a
    compose recreate can change it, which is what `stage-path` already says.
    """
    if not settings.desktop_mode:
        raise HTTPException(
            status_code=409,
            detail=(
                "Core mount paths are bind mounts under Docker and cannot be "
                "applied from the app. Stage the change instead, then set "
                "HOST_NOTES_PATH / HOST_LIBRARY_ROOT / HOST_GENERATED_PATH in "
                ".env and run: docker compose up --build -d"
            ),
        )

    resolved = _validate(req.mount, req.host_path)
    settings.write_locations(mounts={req.mount: str(resolved)})

    if _vault_is_initialised():
        # Deliberately still staged. `_OV_CACHE`, the git repo, the SQLite
        # connections and the scheduler all hold the old path; reassigning
        # underneath them is how you get a half-migrated vault.
        settings.stage_path_change(req.mount, str(resolved))
        return ApplyPathResponse(
            applied=False,
            restart_required=True,
            mount=req.mount,
            host_path=str(resolved),
            reindex_required=True,
            message=(
                f"'{req.mount}' will move to {resolved} when you quit and "
                "reopen Pillar-43. Your catalog still points at the old folder, "
                "so re-index after restarting."
            ),
        )

    # Nothing exists yet, so nothing has to move. This is the first-run case,
    # and it is the reason the wizard needs no restart.
    #
    # Assigning to these attributes rather than making them properties is
    # deliberate: ~170 tests monkeypatch them via setattr, which a property
    # would break. See the plan and the maintainer notes § test-patch-coupling.
    setattr(
        settings,
        {
            "notes": "notes_path",
            "generated": "generated_path",
            "library": "library_root",
        }[req.mount],
        resolved,
    )

    # NOT `generated/.initialized` — that marker is one of the three git_ready
    # signals, and writing it here would end the first-run wizard mid-flow.
    resolved.mkdir(parents=True, exist_ok=True)

    return ApplyPathResponse(
        applied=True,
        restart_required=False,
        mount=req.mount,
        host_path=str(resolved),
        reindex_required=False,
        message=f"'{req.mount}' is now {resolved}.",
    )
