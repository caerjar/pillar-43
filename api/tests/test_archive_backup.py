"""Backup and restore of the governance state (consent, tombstones, accounts, ledger)."""

import sqlite3

import pytest

from services.archive import backup as bk
from services.archive import ledger
from services.db import get_db
from tests import archive_fixtures as fx


@pytest.fixture
def live(tmp_path, monkeypatch):
    fx.settings(tmp_path, monkeypatch)
    fx.seed("a.pdf", "alpha", "model")
    fx.seed("b.pdf", "beta", "private")
    conn = get_db()
    conn.execute(
        "INSERT INTO tombstone (sha256, withdrawn_by, at) VALUES ('dead', 'eon', 'now')"
    )
    conn.execute(
        "INSERT INTO account (name, role, password_hash, created_at) "
        "VALUES ('eon', 'admin', 'h', 'now')"
    )
    conn.commit()
    for i in range(3):
        ledger.append(conn, "consent", "eon", f"a{i}.pdf", {"to": "model"})
    yield conn
    conn.close()


def _dest(tmp_path):
    return tmp_path / "out" / "gov.sqlite"


def test_backup_holds_governance_tables_and_verifies(live, tmp_path):
    s = bk.write_backup(live, _dest(tmp_path))
    assert s["ledger_seq"] == 3 and s["chain"]["ok"]
    c = sqlite3.connect(_dest(tmp_path))
    names = {
        r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert {"item", "tombstone", "ledger", "account", "backup_meta"} <= names
    assert "files" not in names  # the rebuildable index is not copied
    assert c.execute("SELECT COUNT(*) FROM tombstone").fetchone()[0] == 1
    assert not list(_dest(tmp_path).parent.glob("*.partial"))
    assert bk.check_backup(_dest(tmp_path))["ledger_seq"] == 3


def test_backup_refuses_a_broken_ledger_and_keeps_nothing(live, tmp_path):
    live.execute("UPDATE ledger SET actor='mallory' WHERE seq=2")
    live.commit()
    with pytest.raises(bk.BackupError, match="does not verify"):
        bk.write_backup(live, _dest(tmp_path))
    assert not _dest(tmp_path).exists()
    assert not list(_dest(tmp_path).parent.glob("*"))


def test_check_rejects_a_tampered_backup(live, tmp_path):
    bk.write_backup(live, _dest(tmp_path))
    c = sqlite3.connect(_dest(tmp_path))
    c.execute("UPDATE ledger SET subject='x' WHERE seq=2")
    c.commit()
    c.close()
    with pytest.raises(bk.BackupError, match="does not verify"):
        bk.check_backup(_dest(tmp_path))


def test_check_rejects_a_file_that_is_not_a_backup(tmp_path):
    f = tmp_path / "junk"
    f.write_bytes(b"not sqlite at all")
    with pytest.raises(bk.BackupError):
        bk.check_backup(f)
    with pytest.raises(bk.BackupError, match="missing or empty"):
        bk.check_backup(tmp_path / "nope")


def test_restore_brings_back_what_was_lost(live, tmp_path):
    bk.write_backup(live, _dest(tmp_path))
    live.execute("DELETE FROM tombstone")
    live.execute("DELETE FROM account")
    live.execute("UPDATE item SET consent='private'")
    live.commit()
    r = bk.restore_backup(live, _dest(tmp_path))
    assert r["chain"]["ok"]
    assert live.execute("SELECT COUNT(*) FROM tombstone").fetchone()[0] == 1
    assert live.execute("SELECT COUNT(*) FROM account").fetchone()[0] == 1
    assert (
        live.execute("SELECT consent FROM item WHERE path='a.pdf'").fetchone()[0]
        == "model"
    )
    assert ledger.verify(live)["ok"]


def test_restore_into_an_empty_database(live, tmp_path):
    bk.write_backup(live, _dest(tmp_path))
    for t in ("item", "tombstone", "ledger", "account"):
        live.execute(f"DELETE FROM {t}")
    live.commit()
    bk.restore_backup(live, _dest(tmp_path))  # nothing to protect: no force needed
    assert ledger.verify(live) == {"ok": True, "entries": 3, "first_bad_seq": None}


def test_restore_refuses_to_overwrite_a_longer_ledger(live, tmp_path):
    bk.write_backup(live, _dest(tmp_path))
    ledger.append(live, "withdraw", "eon", "a.pdf")
    with pytest.raises(bk.BackupError, match="would lose 1 ledger"):
        bk.restore_backup(live, _dest(tmp_path))
    assert ledger.verify(live)["entries"] == 4  # untouched
    bk.restore_backup(live, _dest(tmp_path), force=True)
    assert ledger.verify(live)["entries"] == 3


def test_restore_refuses_a_different_history_of_the_same_length(live, tmp_path):
    bk.write_backup(live, _dest(tmp_path))
    live.execute("DELETE FROM ledger")
    live.commit()
    for i in range(3):
        ledger.append(live, "consent", "someone-else", f"z{i}", {})
    with pytest.raises(bk.BackupError, match="not the same history"):
        bk.restore_backup(live, _dest(tmp_path))
    bk.restore_backup(live, _dest(tmp_path), force=True)
    assert ledger.entry(live, 1)["actor"] == "eon"


def test_restore_rolls_back_when_the_chain_does_not_hold_afterwards(
    live, tmp_path, monkeypatch
):
    bk.write_backup(live, _dest(tmp_path))
    live.execute("UPDATE item SET consent='private'")
    live.commit()
    real = bk.ledger.verify
    calls = []

    def flaky(c):  # good while the backup is checked, bad after the copy
        calls.append(1)
        return (
            real(c)
            if len(calls) == 1
            else {"ok": False, "entries": 0, "first_bad_seq": 1}
        )

    monkeypatch.setattr(bk.ledger, "verify", flaky)
    with pytest.raises(bk.BackupError, match="nothing was changed"):
        bk.restore_backup(live, _dest(tmp_path), force=True)
    monkeypatch.undo()
    assert (
        live.execute("SELECT consent FROM item WHERE path='a.pdf'").fetchone()[0]
        == "private"
    )
