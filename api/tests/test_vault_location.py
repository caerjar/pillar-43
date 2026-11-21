"""Choosing where the vault lives, and making that choice true.

The bug this file exists for (US-122): staging a core path change natively
wrote a note saying "restart to apply", `main.rs` never read that note, and
`services/vault/tree.py` answered 503 for the staged mount until someone
cancelled it. The user was told to restart, restarted, and got the same broken
tree.

Two halves fix it. `POST /api/settings/apply-path` writes `locations.json`,
which the shell now reads at launch — and before the vault is initialised it
skips the restart entirely, because nothing exists yet to move. The startup
reconcile drops any note the running mounts already satisfy, so a stale one
cannot outlive the restart that satisfied it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from config import settings


@pytest.fixture
def vault(tmp_path, monkeypatch):
    """An isolated native vault: three mounts, a data dir, nothing initialised.

    Every path the endpoint can touch is monkeypatched. `data_path` matters as
    much as the rest — pillar43.config.json and locations.json both live there
    natively, and leaving either shared lets one xdist worker read another's
    staged paths.
    """
    monkeypatch.setattr(settings, "desktop_mode", True)

    root = tmp_path / "Pillar-43"
    for name in ("notes", "generated", "library"):
        (root / name).mkdir(parents=True, exist_ok=True)
    # exist_ok: the shared conftest already puts a `data` dir in tmp_path.
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)

    monkeypatch.setattr(settings, "notes_path", root / "notes")
    monkeypatch.setattr(settings, "generated_path", root / "generated")
    monkeypatch.setattr(settings, "library_root", root / "library")
    monkeypatch.setattr(settings, "data_path", data)
    monkeypatch.setenv("PILLAR43_LOCATIONS_PATH", str(data / "locations.json"))
    monkeypatch.setattr(settings, "extra_libraries_dir", tmp_path / "no-extras")
    return {"root": root, "data": data, "tmp": tmp_path}


@pytest.fixture
def docker_vault(vault, monkeypatch):
    monkeypatch.setattr(settings, "desktop_mode", False)
    return vault


@pytest.fixture
async def client():
    from httpx import AsyncClient, ASGITransport
    from main import app

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


async def _apply(client, mount, path):
    return await client.post(
        "/api/settings/apply-path", json={"mount": mount, "host_path": str(path)}
    )


# ── the first-run case: no restart, because nothing exists yet ───────────────


async def test_apply_takes_effect_immediately_before_initialisation(client, vault):
    """The whole point of the wizard step: pick a folder, and it is the folder."""
    chosen = vault["tmp"] / "Documents" / "MyNotes"
    r = await _apply(client, "notes", chosen)

    assert r.status_code == 200
    body = r.json()
    assert body["applied"] is True
    assert body["restart_required"] is False
    assert settings.notes_path == chosen.resolve()
    assert chosen.exists()


async def test_apply_records_the_choice_where_the_shell_reads_it(client, vault):
    """The shell cannot ask over HTTP — it needs the answer before it spawns
    the backend. locations.json is that handoff."""
    chosen = vault["tmp"] / "Elsewhere"
    await _apply(client, "notes", chosen)

    record = json.loads((vault["data"] / "locations.json").read_text())
    assert record["version"] == 1
    assert record["notes"] == str(chosen.resolve())


async def test_apply_does_not_end_the_wizard(client, vault):
    """`generated/.initialized` is one of the three git_ready signals. Writing
    it here would drop a user who refreshes mid-wizard into the main app with a
    half-configured vault."""
    from routes.vault import INIT_MARKER

    await _apply(client, "notes", vault["tmp"] / "Somewhere")
    assert not (settings.generated_path / INIT_MARKER).exists()


async def test_applying_leaves_no_pending_change_behind(client, vault):
    """An applied change must not also be staged — a surviving note is exactly
    what makes the tree answer 503."""
    await _apply(client, "notes", vault["tmp"] / "Fresh")
    assert settings.is_path_pending_change("notes") is False


# ── the relocation case: a restart, but one that now works ───────────────────


async def test_apply_stages_a_restart_once_the_vault_is_initialised(client, vault):
    """Live SQLite, a git repo, a vector cache and a scheduler all hold the old
    path. Reassigning underneath them is how you get a half-migrated vault."""
    (settings.notes_path / ".git").mkdir()
    before = settings.notes_path

    r = await _apply(client, "notes", vault["tmp"] / "NewHome")
    body = r.json()

    assert body["applied"] is False
    assert body["restart_required"] is True
    assert body["reindex_required"] is True
    assert settings.notes_path == before, "must not move under a live vault"


async def test_relocation_still_records_the_choice(client, vault):
    """Staged or not, the shell must learn the new path — that is what makes
    quit-and-reopen actually apply it."""
    (settings.notes_path / ".git").mkdir()
    chosen = vault["tmp"] / "NewHome"
    await _apply(client, "notes", chosen)

    record = json.loads((vault["data"] / "locations.json").read_text())
    assert record["notes"] == str(chosen.resolve())


# ── the trap itself ──────────────────────────────────────────────────────────


def test_a_satisfied_pending_change_is_not_pending(vault):
    """US-122 in one assertion. The note says 'restart to apply'; the mount is
    already there, so the note is stale and must not answer 503."""
    settings.stage_path_change("notes", str(settings.notes_path))
    assert settings.is_path_pending_change("notes") is False


def test_an_unsatisfied_pending_change_still_is(vault):
    """The guard above must not simply disable the mechanism."""
    settings.stage_path_change("notes", str(vault["tmp"] / "NotThereYet"))
    assert settings.is_path_pending_change("notes") is True


def test_startup_reconcile_clears_what_the_restart_satisfied(vault):
    settings.stage_path_change("notes", str(settings.notes_path))
    settings.stage_path_change("library", str(vault["tmp"] / "StillMoving"))

    cleared = settings.reconcile_pending_path_changes()

    assert cleared == ["notes"]
    assert "notes" not in settings.pending_path_changes()
    assert "library" in settings.pending_path_changes(), "unsatisfied must survive"


async def test_the_tree_recovers_after_the_restart_that_applied_it(client, vault):
    """End to end: the 503 clears itself instead of needing a button in the
    panel whose tree it broke."""
    settings.stage_path_change("notes", str(settings.notes_path))
    settings.reconcile_pending_path_changes()

    r = await client.get("/api/vault/tree", params={"path": "notes"})
    assert r.status_code != 503


# ── what must be refused ─────────────────────────────────────────────────────


async def test_docker_refuses_to_apply(client, docker_vault):
    """There the path is a bind mount; only .env plus a compose recreate
    changes it, which is what stage-path already says."""
    r = await _apply(client, "notes", docker_vault["tmp"] / "wherever")
    assert r.status_code == 409
    assert "docker compose up" in r.json()["detail"]


async def test_relative_paths_are_refused(client, vault):
    r = await _apply(client, "notes", "relative/path")
    assert r.status_code == 400
    assert "absolute" in r.json()["detail"].lower()


async def test_the_home_folder_is_refused(client, vault):
    """Indexing an entire home directory is never what someone meant."""
    r = await _apply(client, "notes", Path.home())
    assert r.status_code == 400
    assert "home folder" in r.json()["detail"].lower()


async def test_a_mount_inside_another_is_refused(client, vault):
    """generated/ inside notes/ means git versions every AI artifact and the
    catalog counts each file twice."""
    r = await _apply(client, "generated", settings.notes_path / "output")
    assert r.status_code == 400
    assert "inside" in r.json()["detail"].lower()


async def test_a_mount_containing_another_is_refused(client, vault):
    r = await _apply(client, "generated", vault["root"])
    assert r.status_code == 400


async def test_an_unwritable_folder_is_refused(client, vault):
    """Probed by writing, not by asking the mode bits — which lie on exactly
    the network and iCloud volumes people pick for a vault."""
    locked = vault["tmp"] / "locked"
    locked.mkdir()
    locked.chmod(0o500)
    try:
        r = await _apply(client, "notes", locked / "child")
        assert r.status_code == 400
        assert "cannot write" in r.json()["detail"].lower()
    finally:
        locked.chmod(0o700)


async def test_an_unknown_mount_is_refused(client, vault):
    r = await _apply(client, "books", vault["tmp"] / "Books")
    assert r.status_code == 400
    assert "stage-path" in r.json()["detail"]


# ── what the UI is told ──────────────────────────────────────────────────────


async def test_settings_reports_desktop_mode_explicitly(client, vault):
    """The UI used to infer this from an empty restart_command, which answers a
    different question by accident."""
    r = await client.get("/api/settings")
    assert r.json()["desktop_mode"] is True


async def test_settings_reports_no_vault_root_under_docker(client, docker_vault):
    """There is no enclosing folder under Docker — the mounts arrive
    independently as bind mounts, so naming one would be a fiction."""
    r = await client.get("/api/settings")
    assert r.json()["vault_root"] == ""


async def test_vault_root_is_the_common_parent_when_nothing_is_relocated(client, vault):
    r = await client.get("/api/settings")
    assert r.json()["vault_root"] == str(vault["root"])


async def test_vault_root_prefers_what_was_recorded(client, vault):
    settings.write_locations(vault=str(vault["tmp"] / "Chosen"))
    r = await client.get("/api/settings")
    assert r.json()["vault_root"] == str(vault["tmp"] / "Chosen")


# ── locations.json itself ────────────────────────────────────────────────────


def test_a_malformed_locations_file_degrades_to_defaults(vault):
    """Never a boot failure. The Rust side has the same rule and the two must
    agree, or the app launches with the shell and backend disagreeing about
    where the vault is."""
    (vault["data"] / "locations.json").write_text("{ not json")
    assert settings.read_locations() == {}


def test_a_mount_can_be_reset_to_inside_the_vault(vault):
    """null means '<vault>/<mount>' — that is what makes 'one folder by
    default, each mount relocatable' one concept rather than two."""
    settings.write_locations(mounts={"notes": "/somewhere/else"})
    record = settings.write_locations(mounts={"notes": None})
    assert record["notes"] is None


def test_extra_libraries_cannot_be_written_here(vault):
    """They belong in libraries.conf, which the running backend re-reads per
    call. This file is only the three mounts the shell needs before boot."""
    with pytest.raises(ValueError, match="not a relocatable mount"):
        settings.write_locations(mounts={"books": "/wherever"})
