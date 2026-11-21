"""Desktop mode — the native app's runtime differences from Docker.

`settings.desktop_mode` is an explicit signal from the Tauri shell, not a
guess. The two runtimes genuinely differ, and the difference that matters most
is extra libraries: under Docker a library reaches the app through a bind
mount, so adding one needs a regenerated compose file and a restart; natively
the path in `libraries.conf` *is* the path on disk and takes effect at once.

The test worth reading twice is `test_extra_library_is_still_read_only`. Under
Docker the `:ro` flag on the mount meant the kernel refused writes even if the
app's own guard were wrong. Natively that backstop is gone and
`vault/io._check_writable` is the only thing standing between a user and their
read-only archive.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from config import settings


@pytest.fixture
def desktop(monkeypatch):
    monkeypatch.setattr(settings, "desktop_mode", True)


@pytest.fixture
def docker(monkeypatch):
    monkeypatch.setattr(settings, "desktop_mode", False)


@pytest.fixture
def libraries(tmp_path, monkeypatch):
    """A libraries.conf plus real directories for it to point at."""
    conf = tmp_path / "libraries.conf"
    monkeypatch.setenv("LIBRARIES_CONFIG_PATH", str(conf))
    monkeypatch.setenv("DOCKER_OVERRIDE_PATH", str(tmp_path / "override.yml"))

    # Pending path changes persist in pillar43.config.json, which is shared
    # state — without this the assertions below see other xdist workers'
    # staged paths. BOTH paths must be isolated: the file lives in
    # `generated/` under Docker and in `data_path` natively (see
    # `Settings._config_path`), and this fixture is used by tests of both
    # modes. Isolating only one leaves the other mode writing to the real
    # shared file, which is how the 2026-08-18 poisoned-suite hour happened.
    gen = tmp_path / "generated"
    gen.mkdir(exist_ok=True)
    monkeypatch.setattr(settings, "generated_path", gen)

    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    monkeypatch.setattr(settings, "data_path", data)

    books = tmp_path / "Books"
    papers = tmp_path / "Papers"
    books.mkdir()
    papers.mkdir()
    conf.write_text(f"books = {books}\npapers = {papers}\n")

    # The Docker-side discovery root, deliberately holding something different
    # so the two modes cannot accidentally agree.
    mountdir = tmp_path / "libraries"
    (mountdir / "mounted").mkdir(parents=True)
    monkeypatch.setattr(settings, "extra_libraries_dir", mountdir)
    return {"conf": conf, "books": books, "papers": papers, "mountdir": mountdir}


# ── where extra libraries come from ──────────────────────────────────────────


def test_desktop_reads_libraries_conf_directly(desktop, libraries):
    mounts = settings.extra_library_mounts
    assert set(mounts) == {"books", "papers"}
    assert mounts["books"] == libraries["books"]


def test_docker_still_lists_the_mount_directory(docker, libraries):
    """Unchanged behaviour — the conf file is not read at runtime under Docker."""
    assert set(settings.extra_library_mounts) == {"mounted"}


def test_desktop_drops_paths_that_do_not_exist(desktop, libraries, tmp_path):
    """Matches what Docker does with a missing mount: the library is absent
    rather than present-and-broken."""
    libraries["conf"].write_text(f"gone = {tmp_path / 'nope'}\n")
    assert settings.extra_library_mounts == {}


def test_desktop_library_appears_without_a_restart(desktop, libraries, tmp_path):
    """The property is evaluated per call precisely so this works."""
    assert "later" not in settings.extra_library_mounts
    (tmp_path / "Later").mkdir()
    libraries["conf"].write_text(
        libraries["conf"].read_text() + f"later = {tmp_path / 'Later'}\n"
    )
    assert "later" in settings.extra_library_mounts


def test_extra_libraries_reach_all_mounts(desktop, libraries):
    assert "books" in settings.all_mounts
    assert settings.all_mounts["books"] == libraries["books"]


# ── the guard that used to be the kernel's job ───────────────────────────────


def test_extra_library_is_still_read_only(desktop, libraries):
    """Docker enforced this with `:ro` on the bind mount. Natively there is no
    mount, so the app's own check is the only protection left."""
    from services.vault.io import _check_writable

    with pytest.raises(PermissionError, match="read-only"):
        _check_writable("books/whatever.md", Path("/unused"))


def test_notes_stays_writable(desktop, libraries):
    from services.vault.io import _check_writable

    _check_writable("notes/fine.md", Path("/unused"))  # must not raise


# ── data path ────────────────────────────────────────────────────────────────


def test_desktop_data_path_defaults_under_application_support(monkeypatch):
    from config import _default_data_path

    monkeypatch.delenv("DATA_PATH", raising=False)
    monkeypatch.setenv("PILLAR43_DESKTOP", "1")
    assert _default_data_path() == str(
        Path.home() / "Library" / "Application Support" / "Pillar-43"
    )


def test_explicit_data_path_always_wins(monkeypatch):
    from config import _default_data_path

    monkeypatch.setenv("PILLAR43_DESKTOP", "1")
    monkeypatch.setenv("DATA_PATH", "/somewhere/else")
    assert _default_data_path() == "/somewhere/else"


def test_docker_data_path_is_unchanged(monkeypatch):
    from config import _default_data_path

    monkeypatch.delenv("PILLAR43_DESKTOP", raising=False)
    monkeypatch.delenv("DATA_PATH", raising=False)
    monkeypatch.setenv("GENERATED_PATH", "/generated")
    assert _default_data_path() == "/generated"


# ── the routes a user actually touches ───────────────────────────────────────


@pytest.fixture
async def client():
    from httpx import AsyncClient, ASGITransport
    from main import app

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


async def test_adding_a_library_writes_no_compose_file(client, desktop, libraries):
    """The regression that would reintroduce Docker into the native app."""
    override = Path(libraries["conf"]).parent / "override.yml"
    if override.exists():
        override.unlink()

    r = await client.post(
        "/api/settings/stage-path",
        json={"mount": "extra", "host_path": str(libraries["books"])},
    )
    assert r.status_code == 200
    assert not override.exists(), "desktop mode must not generate a compose override"


async def test_adding_a_library_asks_for_no_restart(client, desktop, libraries):
    r = await client.post(
        "/api/settings/stage-path",
        json={"mount": "extra", "host_path": str(libraries["books"])},
    )
    body = r.json()
    # Nothing staged and no command: it is already live.
    assert body["restart_command"] == ""
    assert "extra" not in body["pending"]


async def test_docker_still_writes_the_override_and_asks_for_a_restart(
    client, docker, libraries
):
    override = Path(libraries["conf"]).parent / "override.yml"
    r = await client.post(
        "/api/settings/stage-path",
        json={"mount": "extra", "host_path": str(libraries["books"])},
    )
    body = r.json()
    assert override.exists()
    assert "docker compose up" in body["restart_command"]
    assert body["pending"]["extra"] == str(libraries["books"])


async def test_core_path_change_still_stages_in_desktop_mode(
    client, desktop, libraries, tmp_path
):
    """Core mounts are read from env at startup either way, so they DO need a
    restart — just not a docker one."""
    r = await client.post(
        "/api/settings/stage-path",
        json={"mount": "notes", "host_path": str(tmp_path)},
    )
    body = r.json()
    assert body["pending"]["notes"] == str(tmp_path)
    assert body["restart_command"] == ""  # "quit and reopen", rendered by the UI


# ── the toggle must not reach extra sources ──────────────────────────────────


def test_library_toggle_does_not_unlock_extra_sources(desktop, libraries, monkeypatch):
    """The hole the `:ro` bind mount used to cover.

    `_check_writable` has always said extra vault sources are "always
    read-only", while `write_file` used to include them in the set the
    "Library read-only" toggle unlocks. Under Docker that contradiction was
    invisible — the kernel refused the write regardless. Natively `write_file`
    is the only guard, so flipping the toggle off would have started writing
    into a read-only archive.
    """
    from services.vault.io import write_file

    monkeypatch.setattr(settings, "effective_library_readonly", lambda: False)

    with pytest.raises(PermissionError, match="always"):
        write_file("books/intruder.md", "should never land")

    assert not (libraries["books"] / "intruder.md").exists()


def test_library_toggle_still_unlocks_the_library_mount(
    desktop, libraries, tmp_path, monkeypatch
):
    """...but the toggle must keep doing its actual job."""
    from services.vault.io import write_file

    lib = tmp_path / "library"
    lib.mkdir(exist_ok=True)
    monkeypatch.setattr(settings, "library_root", lib)
    monkeypatch.setattr(settings, "effective_library_readonly", lambda: False)

    write_file("library/allowed.md", "fine")
    assert (lib / "allowed.md").exists()


async def test_host_paths_are_the_real_paths_in_desktop_mode(
    client, desktop, libraries
):
    """Under Docker these come from HOST_* env vars because the container's own
    paths mean nothing outside it. Natively the translation is the identity."""
    r = await client.get("/api/settings")
    body = r.json()
    assert body["host_paths"]["notes"] == body["paths"]["notes_path"]


async def test_host_paths_still_come_from_env_under_docker(client, docker, monkeypatch):
    monkeypatch.setattr(settings, "host_notes_path", "/Users/someone/notes")
    r = await client.get("/api/settings")
    assert r.json()["host_paths"]["notes"] == "/Users/someone/notes"


# ── where the runtime config file lives ──────────────────────────────────────
#
# pillar43.config.json holds every API key, OAuth refresh token, SMTP password
# and bot token, plus pending_path_changes. Inside `generated/` it was the one
# file that could not survive relocating `generated/` — the move would orphan
# the whole credential store, and the record of a pending move would live
# inside the mount it describes. Natively it now lives in `data_path`, which
# the shell computes before it knows where the vault is.


def test_config_file_lives_outside_the_vault_in_desktop_mode(desktop, libraries):
    assert settings._config_path == settings.data_path / "pillar43.config.json"
    assert settings.generated_path not in settings._config_path.parents


def test_config_file_stays_in_the_vault_under_docker(docker, libraries):
    assert settings._config_path == settings.generated_path / "pillar43.config.json"


def test_relocating_generated_does_not_orphan_the_keys(desktop, libraries, tmp_path):
    """The regression this move exists to prevent: a user relocates generated/
    and their saved settings are still there afterwards."""
    settings.save_overrides({"ollama_model": "kept-model"})

    elsewhere = tmp_path / "somewhere-else"
    elsewhere.mkdir()
    settings.generated_path = elsewhere  # what applying a path change does

    assert settings.effective_ollama_model() == "kept-model"


def test_legacy_config_is_migrated_out_of_the_vault(desktop, libraries):
    """An install predating the move keeps its settings."""
    legacy = settings.generated_path / "pillar43.config.json"
    legacy.write_text('{"ollama_model": "from-the-old-place"}')
    assert not settings._config_path.exists()

    assert settings.effective_ollama_model() == "from-the-old-place"
    assert settings._config_path.exists()
    # Copied, not moved — a rollback to an older build must still find it.
    assert legacy.exists()


def test_migration_never_overwrites_a_newer_config(desktop, libraries):
    """Second launch: the vault copy is stale, and must not win."""
    (settings.generated_path / "pillar43.config.json").write_text(
        '{"ollama_model": "stale"}'
    )
    settings._config_path.write_text('{"ollama_model": "current"}')

    assert settings.migrate_config_file() is False
    assert settings.effective_ollama_model() == "current"


def test_migration_does_not_run_under_docker(docker, libraries):
    """Docker's config file is already in the right place; data_path there is
    a named volume for the DB, not a config home."""
    assert settings.migrate_config_file() is False


def test_migration_survives_an_unreadable_legacy_file(desktop, libraries):
    """A failure here degrades to 'no overrides yet', never to a boot failure."""
    legacy = settings.generated_path / "pillar43.config.json"
    legacy.write_text("{not json at all")

    # Copied verbatim (the copy step cannot know it is malformed), then parsed
    # as empty rather than raising.
    assert isinstance(settings.effective_ollama_model(), str)
