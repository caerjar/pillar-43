"""_retry_on_locked: scan write resilience to transient SQLite locks."""

from __future__ import annotations

import sqlite3

import pytest


def test_retries_then_succeeds(monkeypatch):
    import services.catalog.scan as scan

    monkeypatch.setattr(scan.time, "sleep", lambda *_: None)

    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise sqlite3.OperationalError("database is locked")
        return "ok"

    assert scan._retry_on_locked(flaky) == "ok"
    assert calls["n"] == 3


def test_non_lock_error_raises_immediately(monkeypatch):
    import services.catalog.scan as scan

    monkeypatch.setattr(scan.time, "sleep", lambda *_: None)

    calls = {"n": 0}

    def boom():
        calls["n"] += 1
        raise sqlite3.OperationalError("no such table: files")

    with pytest.raises(sqlite3.OperationalError):
        scan._retry_on_locked(boom)
    assert calls["n"] == 1  # no retries for a non-lock error


def test_persistent_lock_raises_after_attempts(monkeypatch):
    import services.catalog.scan as scan

    monkeypatch.setattr(scan.time, "sleep", lambda *_: None)

    calls = {"n": 0}

    def stuck():
        calls["n"] += 1
        raise sqlite3.OperationalError("database is locked")

    with pytest.raises(sqlite3.OperationalError):
        scan._retry_on_locked(stuck, attempts=4)
    assert calls["n"] == 4  # tried the full budget, then gave up (caller skips)
