"""B2 — GET /api/catalog/stats must not disguise a DB failure as an empty vault.

Before: any DB error returned file_count=0 with no signal, so the UI showed the
"index your vault" banner to a user whose full vault was simply unreadable. Now
the response carries an `error` field the UI treats as "unknown", not "empty".
"""

import os
import sqlite3

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("TESTING", "1")


@pytest.fixture()
def client(tmp_path, monkeypatch):
    import config as cfg

    gen = tmp_path / "generated"
    gen.mkdir()
    monkeypatch.setattr(cfg.settings, "generated_path", gen)
    from main import app

    return TestClient(app)


def test_stats_reports_unavailable_on_db_failure(client, monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("db exploded")

    monkeypatch.setattr("services.db.get_db", _boom)
    res = client.get("/api/catalog/stats")
    assert res.status_code == 200  # never 500 — the poll must keep working
    body = res.json()
    assert body["error"] == "unavailable"
    assert body["file_count"] == 0


def test_stats_reports_busy_on_operational_error(client, monkeypatch):
    class _LockedConn:
        def execute(self, *a, **k):
            raise sqlite3.OperationalError("database is locked")

        def close(self):
            pass

    monkeypatch.setattr("services.db.get_db", lambda: _LockedConn())
    res = client.get("/api/catalog/stats")
    assert res.status_code == 200
    body = res.json()
    assert body["error"] == "busy"


def test_stats_has_null_error_on_success(client):
    # Healthy read (empty seeded DB) → error is null, file_count present.
    res = client.get("/api/catalog/stats")
    assert res.status_code == 200
    body = res.json()
    assert body["error"] is None
    assert "file_count" in body
