"""B3 — fail-fast startup config validation.

A missing/unwritable mount or absent key should surface as a clear log line at
boot (and, in strict/production mode, refuse to start) rather than an opaque
error at first use.
"""

import os

import pytest

os.environ.setdefault("TESTING", "1")


def _setup(tmp_path, monkeypatch):
    import config as cfg

    notes = tmp_path / "notes"
    gen = tmp_path / "generated"
    notes.mkdir()
    gen.mkdir()
    monkeypatch.setattr(cfg.settings, "notes_path", notes)
    monkeypatch.setattr(cfg.settings, "generated_path", gen)
    return cfg.settings


def test_healthy_mounts_report_no_hard_problems(tmp_path, monkeypatch):
    settings = _setup(tmp_path, monkeypatch)
    assert settings.validate_startup(strict=True) == []


def test_missing_notes_mount_is_a_hard_problem(tmp_path, monkeypatch):
    settings = _setup(tmp_path, monkeypatch)
    monkeypatch.setattr(settings, "notes_path", tmp_path / "does-not-exist")
    problems = settings.validate_startup(strict=False)
    assert any("notes mount does not exist" in p for p in problems)


def test_strict_mode_refuses_to_start_on_hard_problem(tmp_path, monkeypatch):
    settings = _setup(tmp_path, monkeypatch)
    monkeypatch.setattr(settings, "generated_path", tmp_path / "nope")
    with pytest.raises(RuntimeError, match="cannot start"):
        settings.validate_startup(strict=True)
