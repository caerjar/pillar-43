"""C2: the hash-chained ledger and the receipts. Every intake, consent change,
withdrawal and model call is a line; `verify` proves nothing was edited."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from services.archive import ask as ask_mod
from tests import archive_fixtures as fx

PATH = "library/contracts/orchard.pdf"
TEXT = "Rights revert to the grantor after nine months."


@pytest.fixture
def world(tmp_path, monkeypatch):
    fx.settings(tmp_path, monkeypatch)
    (tmp_path / "library" / "contracts").mkdir()
    (tmp_path / "library" / "contracts" / "orchard.pdf").write_bytes(b"orchard bytes")
    fx.seed(PATH, TEXT, "model")
    fx.lexical_only(monkeypatch, [PATH])
    fx.fake_model(monkeypatch)
    return tmp_path


@pytest.fixture
def client():
    from main import app

    return TestClient(app, base_url="http://localhost")


def _conn():
    from services.db import get_db

    return get_db()


def _kinds(conn):
    return [r[0] for r in conn.execute("SELECT kind FROM ledger ORDER BY seq")]


def test_every_event_is_a_ledger_line_and_the_chain_verifies(world):
    from services.archive.items import register_item, set_consent
    from services.archive.ledger import verify
    from services.archive.withdraw import withdraw

    conn = _conn()
    try:
        conn.execute("DELETE FROM item")
        conn.commit()
        register_item(conn, PATH, world / "library" / "contracts" / "orchard.pdf")
        register_item(conn, PATH, world / "library" / "contracts" / "orchard.pdf")
        set_consent(conn, PATH, "model", by="ana")
        out = ask_mod.ask("When do rights revert?")
        withdraw(conn, PATH, by="ana")
        # a re-run of intake on an existing item is not a new intake line
        assert _kinds(conn) == ["intake", "consent", "model_call", "withdraw"]
        assert out["receipt_id"] == 3
        res = verify(conn)
        assert res["ok"] is True and res["entries"] == 4
        item = conn.execute(
            "SELECT ledger_seq FROM item WHERE path=?", (PATH,)
        ).fetchone()
        assert item[0] == 1
    finally:
        conn.close()


def test_a_one_byte_edit_is_detected(world):
    from services.archive.items import set_consent
    from services.archive.ledger import verify

    conn = _conn()
    try:
        set_consent(conn, PATH, "staff", by="ana")
        set_consent(conn, PATH, "model", by="ana")
        set_consent(conn, PATH, "private", by="ana")
        assert verify(conn)["ok"] is True
        row = conn.execute("SELECT data FROM ledger WHERE seq=2").fetchone()[0]
        edited = row.replace("model", "modeI")  # one character
        assert edited != row
        conn.execute("UPDATE ledger SET data=? WHERE seq=2", (edited,))
        conn.commit()
        bad = verify(conn)
        assert bad["ok"] is False and bad["first_bad_seq"] == 2
    finally:
        conn.close()


def test_deleting_a_line_is_detected(world):
    from services.archive.items import set_consent
    from services.archive.ledger import verify

    conn = _conn()
    try:
        for lvl in ("staff", "model", "private"):
            set_consent(conn, PATH, lvl, by="ana")
        conn.execute("DELETE FROM ledger WHERE seq=2")
        conn.commit()
        bad = verify(conn)
        assert bad["ok"] is False and bad["first_bad_seq"] == 3
    finally:
        conn.close()


def test_answer_carries_a_receipt_that_names_what_the_model_read(world, client):
    out = ask_mod.ask("When do rights revert?")
    seq = out["receipt_id"]
    r = client.get(f"/api/archive/ledger/{seq}")
    assert r.status_code == 200
    body = r.json()
    assert body["kind"] == "model_call"
    d = body["data"]
    assert d["answer_id"] == out["answer_id"]
    assert d["prompt_sha256"] == out["prompt_sha256"]
    assert [i["path"] for i in d["items"]] == [PATH]
    assert client.get("/api/archive/ledger/9999").status_code == 404
    assert client.get("/api/archive/ledger/verify").json()["ok"] is True


def test_items_report_how_many_times_the_ai_read_them(world, client):
    fx.seed("library/minutes/board.md", "staff only", "staff", kind="minutes")
    for _ in range(3):
        ask_mod.ask("When do rights revert?")
    rows = {r["path"]: r for r in client.get("/api/archive/items/reads").json()}
    assert rows[PATH]["read_by_ai"] == 3
    assert rows["library/minutes/board.md"]["read_by_ai"] == 0
    # a private item is not listed to staff at all
    fx.seed("library/letters/p.md", "private", "private", kind="letter")
    paths = [r["path"] for r in client.get("/api/archive/items/reads").json()]
    assert "library/letters/p.md" not in paths


def test_receipt_data_is_json_in_the_ledger(world):
    out = ask_mod.ask("When do rights revert?")
    conn = _conn()
    try:
        data = json.loads(
            conn.execute(
                "SELECT data FROM ledger WHERE seq=?", (out["receipt_id"],)
            ).fetchone()[0]
        )
        assert data["model"] == out["model"]
    finally:
        conn.close()
