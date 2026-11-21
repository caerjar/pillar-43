"""The startup and shutdown work actually runs.

`@app.on_event` was replaced by a `lifespan` context manager on 2026-08-17 to
clear 244 deprecation warnings per test run. The risk in that swap is not that
it breaks loudly — it is that it breaks *silently*: forget `lifespan=lifespan`
on the `FastAPI(...)` call and every test still passes, every route still
serves, and orphaned jobs simply stop being cleaned up on restart. The user
sees Run buttons disabled after a crash and there is nothing in the logs.

`reclassify_running_jobs_as_interrupted` was already tested directly in
`test_job_store.py`, which proves the primitive works and cannot notice that
nobody calls it. So these tests assert the WIRING: enter the app's
lifespan for real and check the far end of the chain was reached.

`with TestClient(app)` is load-bearing. A bare `TestClient(app)` never enters
the lifespan at all, which is why most of the suite would not catch this.
"""

import os

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("TESTING", "1")

from main import app


@pytest.fixture
def spied(monkeypatch):
    """Record the far end of each half, not the wrapper."""
    calls: list[str] = []

    monkeypatch.setattr(
        "services.job_store.reclassify_running_jobs_as_interrupted",
        lambda: calls.append("reclassify") or 0,
    )
    monkeypatch.setattr(
        "services.job_store.cleanup_old_jobs",
        lambda *a, **kw: calls.append("cleanup"),
    )
    return calls


def test_startup_half_runs(spied):
    """If this fails, `lifespan=` is not wired onto the app."""
    with TestClient(app):
        pass
    assert "reclassify" in spied, (
        "startup orphan cleanup never ran — the lifespan is not attached, and "
        "nothing else in the suite would notice"
    )
    assert "cleanup" in spied


def test_startup_failure_does_not_prevent_serving(monkeypatch):
    """Each half swallows its own exceptions, and must keep doing so.

    Orphan cleanup is housekeeping. A failure there must never be the reason
    the API will not start — that would turn a cosmetic problem into an outage.
    """

    def _boom():
        raise RuntimeError("db unavailable")

    monkeypatch.setattr(
        "services.job_store.reclassify_running_jobs_as_interrupted", _boom
    )

    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
