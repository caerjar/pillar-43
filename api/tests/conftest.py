import pytest


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def _reset_module_caches():
    """Clear module-level caches between tests to prevent inter-test state leak."""
    import config as cfg

    cfg._OV_CACHE.clear()
    yield
    cfg._OV_CACHE.clear()


@pytest.fixture(autouse=True)
def _isolate_db_per_test(tmp_path, monkeypatch):
    """Give every test a fresh, worker-local SQLite DB.

    Without this, pytest-xdist workers race on the shared
    `settings.db_path` and cleanup_old_jobs() reaps each worker's
    jobs mid-test. Phase 1's `settings.testing` guard in
    `_migrate_db_from_bind_mount` keeps the migration from copying the
    legacy generated/pillar43.db fixture into our tmp path, so Alembic
    runs cleanly against an empty file. See plans/TEST_DB_ISOLATION_SPRINT.md.
    """
    import config as cfg
    import services.db as db_mod

    data = tmp_path / "data"
    data.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("DATA_PATH", str(data))
    monkeypatch.setattr(cfg.settings, "data_path", data)
    db_key = str((data / "pillar43.db").resolve())
    db_mod._initialized_paths.discard(db_key)
    yield
    db_mod._initialized_paths.discard(db_key)


@pytest.fixture(autouse=True)
def _gate_open_outside_archive_tests(request, monkeypatch):
    """The access gate answers 404 for every route the archive screens do not
    use (it stays on until W6 opens transcription and handwriting through
    consent). Route tests for those modules need it open; the archive and
    removed-route tests exercise the real gate, so they opt out by name or
    with `pytestmark = pytest.mark.real_gate`."""
    name = request.module.__name__.rsplit(".", 1)[-1]
    if name.startswith("test_archive") or request.node.get_closest_marker("real_gate"):
        return
    from services.archive import access

    monkeypatch.setattr(access, "ORG_GET_ALLOW", ("/api/",))
    monkeypatch.setattr(access, "ORG_WRITE_ALLOW", ("/api/",))
    monkeypatch.setattr(access, "_PATH_PARAMS", ())
    monkeypatch.setattr(access, "_session_account", lambda request: (False, None))
