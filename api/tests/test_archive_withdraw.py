"""C1: withdrawing an item. Tombstone + forget_file; re-intake refused; earlier
answers that cited it are marked, never silently rewritten."""

from __future__ import annotations

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


def test_withdraw_removes_item_from_ask_search_and_files(world, client):
    from services.archive.withdraw import withdraw

    before = ask_mod.ask("When do rights revert?")
    assert before["answer"], "fixture should answer before withdrawal"

    conn = _conn()
    try:
        withdraw(conn, PATH, by="ana")
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM files WHERE rel_path=?", (PATH,)
            ).fetchone()[0]
            == 0
        )
        assert conn.execute("SELECT COUNT(*) FROM file_chunks").fetchone()[0] == 0
    finally:
        conn.close()

    after = ask_mod.ask("When do rights revert?")
    assert after["answer"] == [] and after["not_answered"] is True
    assert client.get("/api/file/raw", params={"path": PATH}).status_code == 404
    assert client.get("/api/search", params={"q": "revert"}).json()["results"] == []


def test_reintake_of_withdrawn_bytes_is_refused_under_any_path(world):
    from services.archive.items import TombstonedError, register_item
    from services.archive.withdraw import withdraw

    conn = _conn()
    try:
        conn.execute("DELETE FROM item")
        conn.commit()
        register_item(conn, PATH, world / "library" / "contracts" / "orchard.pdf")
        withdraw(conn, PATH, by="ana")
        copy = world / "library" / "renamed.pdf"
        copy.write_bytes(b"orchard bytes")
        with pytest.raises(TombstonedError):
            register_item(conn, "library/renamed.pdf", copy)
    finally:
        conn.close()


def test_earlier_answers_citing_it_are_marked(world, client):
    from services.archive.withdraw import withdraw

    out = ask_mod.ask("When do rights revert?")
    aid = out["answer_id"]
    r = client.get(f"/api/archive/answers/{aid}")
    assert r.status_code == 200
    assert r.json()["withdrawn_sources"] == []

    conn = _conn()
    try:
        res = withdraw(conn, PATH, by="ana")
    finally:
        conn.close()
    assert res["answers_marked"] == [aid]

    body = client.get(f"/api/archive/answers/{aid}").json()
    assert body["withdrawn_sources"] == [PATH]
    assert body["answer"], "the answer text is kept, marked, not rewritten"


def test_withdraw_route_and_cli_verb(world, client):
    # no account yet: withdrawing is refused until the admin exists
    assert client.post("/api/archive/withdraw", json={"path": PATH}).status_code == 403
    client.post(
        "/api/archive/accounts",
        json={"name": "root", "role": "admin", "password": "correct horse"},
    )
    client.post(
        "/api/archive/login", json={"name": "root", "password": "correct horse"}
    )
    r = client.post("/api/archive/withdraw", json={"path": PATH, "by": "ana"})
    assert r.status_code == 200 and r.json()["path"] == PATH
    missing = client.post(
        "/api/archive/withdraw", json={"path": "library/nope.pdf", "by": "x"}
    )
    assert missing.status_code == 404
    from scripts import archive_cli

    assert callable(archive_cli.withdraw)
