"""End-to-end tests for the Add/Remove Library flow.

Sprint 98: the previous flow emitted a useless `EXTRA_LIBRARY_FOO=...
docker compose up -d` command and never wrote the override file. After
this sprint POST /api/settings/stage-path must write libraries.conf AND
regenerate docker-compose.override.yml so the next restart actually mounts
the library.
"""

import pytest
from httpx import AsyncClient, ASGITransport

import config as config_mod
from main import app


@pytest.fixture
def tmp_libraries(tmp_path, monkeypatch):
    """Point libraries_config at tmp paths + isolate the settings store."""
    conf = tmp_path / "libraries.conf"
    override = tmp_path / "docker-compose.override.yml"
    monkeypatch.setenv("LIBRARIES_CONFIG_PATH", str(conf))
    monkeypatch.setenv("DOCKER_OVERRIDE_PATH", str(override))
    # Isolate settings paths so save_overrides doesn't write to a real path.
    active = tmp_path / "notes"
    active.mkdir()
    vault = tmp_path / "library"
    vault.mkdir()
    generated = tmp_path / "generated"
    generated.mkdir()
    monkeypatch.setattr(config_mod.settings, "notes_path", active)
    monkeypatch.setattr(config_mod.settings, "library_root", vault)
    monkeypatch.setattr(config_mod.settings, "generated_path", generated)
    return conf, override


@pytest.fixture
async def client(tmp_libraries):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


@pytest.mark.asyncio
async def test_stage_path_extra_library_writes_conf_and_override(client, tmp_libraries):
    conf, override = tmp_libraries
    resp = await client.post(
        "/api/settings/stage-path",
        json={"mount": "books", "host_path": "/Volumes/Books"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "staged"

    # libraries.conf has the new entry
    assert conf.exists()
    text = conf.read_text()
    assert "books = /Volumes/Books" in text

    # docker-compose.override.yml exists and references the new library
    assert override.exists()
    ot = override.read_text()
    assert "/Volumes/Books:/libraries/books:ro" in ot
    # One block: `worker` was folded into the api service 2026-08-18.
    assert ot.count("/Volumes/Books:/libraries/books:ro") == 1


@pytest.mark.asyncio
async def test_stage_path_returns_simple_restart_command(client, tmp_libraries):
    """For extra libraries, the restart command is `docker compose up
    --build -d` — no per-library env var (the docker-compose.override.yml
    is what wires the mount in)."""
    resp = await client.post(
        "/api/settings/stage-path",
        json={"mount": "books", "host_path": "/Volumes/Books"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["restart_command"] == "docker compose up --build -d"
    # Must NOT include the legacy EXTRA_LIBRARY_BOOKS=... prefix.
    assert "EXTRA_LIBRARY_BOOKS" not in body["restart_command"]


@pytest.mark.asyncio
async def test_stage_path_rejects_relative_path(client, tmp_libraries):
    resp = await client.post(
        "/api/settings/stage-path",
        json={"mount": "books", "host_path": "relative/path"},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_stage_path_rejects_invalid_name(client, tmp_libraries):
    resp = await client.post(
        "/api/settings/stage-path",
        json={"mount": "bad name", "host_path": "/Volumes/X"},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_stage_path_core_mount_still_uses_env_var(client, tmp_libraries):
    """Core mounts (library/notes/generated) still need HOST_* env vars.
    Their restart command should mention HOST_NOTES_PATH=..."""
    resp = await client.post(
        "/api/settings/stage-path",
        json={"mount": "notes", "host_path": "/Users/me/new-notes"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "HOST_NOTES_PATH=/Users/me/new-notes" in body["restart_command"]
    assert "docker compose up --build -d" in body["restart_command"]
    # Core mounts don't touch libraries.conf.
    conf, _ = tmp_libraries
    if conf.exists():
        assert "notes = " not in conf.read_text()


@pytest.mark.asyncio
async def test_remove_library_clears_conf_and_override(client, tmp_libraries):
    conf, override = tmp_libraries
    # Add then remove
    await client.post(
        "/api/settings/stage-path",
        json={"mount": "books", "host_path": "/Volumes/Books"},
    )
    assert conf.exists() and "books = /Volumes/Books" in conf.read_text()
    assert override.exists()

    resp = await client.post(
        "/api/settings/remove-library",
        json={"mount": "books", "host_path": "/ignored"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "staged"
    assert "books" in body["pending_removals"]

    # libraries.conf no longer has the entry
    assert "books = " not in conf.read_text()
    # The override is EMPTIED, not removed: it is a bind-mounted file, so the
    # container cannot unlink it (EBUSY), and a missing mount source makes
    # Docker create a directory at that path. See regenerate_override.
    assert override.exists()
    assert "/Volumes/Books" not in override.read_text()


@pytest.mark.asyncio
async def test_remove_core_mount_rejected(client, tmp_libraries):
    for core in ("library", "notes", "generated"):
        resp = await client.post(
            "/api/settings/remove-library",
            json={"mount": core, "host_path": "/x"},
        )
        assert resp.status_code == 400, f"core mount {core} should not be removable"


@pytest.mark.asyncio
async def test_add_two_libraries_then_remove_one(client, tmp_libraries):
    """Two libraries → remove one → override still has the other."""
    conf, override = tmp_libraries
    await client.post(
        "/api/settings/stage-path",
        json={"mount": "books", "host_path": "/Volumes/Books"},
    )
    await client.post(
        "/api/settings/stage-path",
        json={"mount": "papers", "host_path": "/Volumes/Papers"},
    )
    ot = override.read_text()
    assert "/Volumes/Books:/libraries/books:ro" in ot
    assert "/Volumes/Papers:/libraries/papers:ro" in ot

    await client.post(
        "/api/settings/remove-library",
        json={"mount": "books", "host_path": "/ignored"},
    )
    # Override regenerated without books
    ot = override.read_text()
    assert "/Volumes/Books:/libraries/books:ro" not in ot
    assert "/Volumes/Papers:/libraries/papers:ro" in ot


@pytest.mark.asyncio
@pytest.mark.parametrize("mount", ["evil", "notes"])
async def test_stage_path_refuses_a_path_that_smuggles_a_bind_mount(
    client, tmp_libraries, mount
):
    """H2: `/:/hostroot:rw #` made a read-write mount of the host root, and a
    core mount's path is echoed into a shell command the user is told to run."""
    conf, override = tmp_libraries
    resp = await client.post(
        "/api/settings/stage-path",
        json={"mount": mount, "host_path": "/:/hostroot:rw #"},
    )
    assert resp.status_code == 400, resp.text
    assert not conf.exists()
    assert not override.exists()
