"""Migration 0018 — the Counter-Archive and Roundtable tables are gone.

Replaces `test_migration_0005.py`, which asserted the Counter-Archive Phase 2
tables and indexes were *present*. That file was correct when the engine
existed; after the engine was removed it went on certifying schema for code
that wasn't in the tree, and it is what made the nine orphan tables look
load-bearing to anyone grepping the tests.

The direction of the assertion is the whole point. A migration that drops
tables has no observable effect on any code path — nothing reads them either
way — so the only thing that can catch a botched drop, or a later migration
quietly recreating one, is asserting their absence directly.

Indexes are not checked separately: SQLite drops a table's indexes with the
table, so a surviving `idx_ca_*` would imply a surviving table.
"""

from __future__ import annotations

from pathlib import Path

# Every table dropped by 0018. Kept as a literal rather than imported from the
# migration so that editing the migration's list cannot silently edit the
# assertion along with it.
DROPPED = {
    "ca_figures",
    "ca_ghosts",
    "ca_gaps",
    "ca_detritus",
    "ca_sessions",
    "ca_interactions",
    "ca_potentials",
    "roundtable_posts",
    "roundtable_sessions",
}


def _make_settings(tmp_path: Path, monkeypatch):
    notes = tmp_path / "notes"
    notes.mkdir()
    library = tmp_path / "library"
    library.mkdir()
    generated = tmp_path / "generated"
    generated.mkdir()
    monkeypatch.setenv("NOTES_PATH", str(notes))
    monkeypatch.setenv("LIBRARY_ROOT", str(library))
    monkeypatch.setenv("GENERATED_PATH", str(generated))
    import config

    monkeypatch.setattr(config.settings, "notes_path", notes)
    monkeypatch.setattr(config.settings, "library_root", library)
    monkeypatch.setattr(config.settings, "generated_path", generated)


def _table_names() -> set[str]:
    from services.db import get_db

    conn = get_db()
    try:
        return {
            r["name"]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    finally:
        conn.close()


def test_removed_feature_tables_absent_after_init(tmp_path, monkeypatch):
    """A fresh DB migrated to head must carry none of the nine."""
    _make_settings(tmp_path, monkeypatch)
    survivors = DROPPED & _table_names()
    assert not survivors, (
        f"migration 0018 should have dropped these: {sorted(survivors)}. "
        "0005/0007/0010/0011 still create them on the way up, so a survivor "
        "means 0018 did not run or its table list has drifted."
    )


def test_live_tables_untouched(tmp_path, monkeypatch):
    """0018 drops nine specific tables and nothing adjacent.

    `ca_*` is a short prefix and the drop list is hand-written, so the failure
    worth guarding is an over-broad drop taking a live table with it. `files`
    and `file_chunks` are the ones whose loss would be quietest — retrieval
    degrades to empty rather than erroring.
    """
    _make_settings(tmp_path, monkeypatch)
    tables = _table_names()
    for name in ("files", "file_chunks", "commons_channels", "jobs"):
        assert name in tables, f"0018 must not have dropped {name}"


def test_migration_is_idempotent_on_warm_db(tmp_path, monkeypatch):
    """Re-running against an already-migrated DB must not error.

    `DROP TABLE IF EXISTS` makes this trivially true, which is the reason it
    is written that way — a second `./pillar43` start must not fail because
    the tables are already gone.
    """
    from services.db import get_db

    _make_settings(tmp_path, monkeypatch)
    conn = get_db()
    try:
        assert not (DROPPED & _table_names())
    finally:
        conn.close()
