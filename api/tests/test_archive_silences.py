"""C5: what the archive could not say, computed by code from the database and
returned with every answer: items closed by their writers (a count),
correspondents whose own letters are absent, and years in the question's scope
with no records. Logged per answer; aggregated for the Gaps view."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from services.archive import ask as ask_mod
from tests import archive_fixtures as fx

CONTRACT = "library/contracts/orchard-2014.pdf"
LETTER = "library/letters/2016-to-ana.md"
CLOSED = "library/letters/closed.md"


def _sql(sql, args=()):
    from services.db import get_db

    conn = get_db()
    try:
        conn.execute(sql, args)
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def world(tmp_path, monkeypatch):
    fx.settings(tmp_path, monkeypatch)
    fx.seed(CONTRACT, "The grant reverts after nine months in 2014.", "model")
    fx.seed(LETTER, "Ana asked about reversion in 2016.", "model", kind="letter")
    fx.seed(CLOSED, "closed reversion letter", "private", kind="letter")
    _sql(
        "UPDATE item SET year=2014, people=? WHERE path=?",
        (json.dumps([{"name": "Ana R.", "role": "correspondent"}]), CONTRACT),
    )
    _sql("UPDATE item SET year=2016 WHERE path=?", (LETTER,))
    _sql("UPDATE item SET year=2015 WHERE path=?", (CLOSED,))
    fx.lexical_only(monkeypatch, [CONTRACT, LETTER, CLOSED])
    fx.fake_model(monkeypatch, cites=(1,))
    return tmp_path


@pytest.fixture
def client():
    from main import app

    return TestClient(app, base_url="http://localhost")


def test_silences_name_closed_items_absent_correspondents_and_empty_years(world):
    out = ask_mod.ask("What happened to the reversion between 2012 and 2014?")
    s = out["silences"]
    assert s["closed"] == 1
    assert s["missing_correspondents"] == ["Ana R."]
    assert s["empty_years"] == [2012, 2013]
    assert s["line"] == (
        "1 item closed by default (no one has opened it to the AI); Ana R.'s replies are not in the archive; "
        "nothing from 2012–2013"
    )


def test_a_correspondent_whose_own_letter_is_present_is_not_missing(world):
    _sql(
        "UPDATE item SET people=? WHERE path=?",
        (json.dumps([{"name": "Ana R.", "role": "author"}]), LETTER),
    )
    out = ask_mod.ask("reversion?")
    assert out["silences"]["missing_correspondents"] == []


def test_a_year_with_only_closed_items_is_not_empty(world):
    out = ask_mod.ask("What was said in 2015?")
    assert out["silences"]["empty_years"] == []
    assert out["silences"]["closed"] == 1


def test_no_silences_gives_an_empty_line(world):
    _sql("UPDATE item SET consent='model' WHERE path=?", (CLOSED,))
    _sql("UPDATE item SET people='[]' WHERE path=?", (CONTRACT,))
    out = ask_mod.ask("reversion?")
    assert out["silences"] == {
        "closed": 0,
        "closed_by": {"writer": 0, "default": 0, "staff": 0},
        "missing_correspondents": [],
        "empty_years": [],
        "line": "",
    }


def test_silences_are_logged_and_gaps_aggregate_them(world, client):
    ask_mod.ask("reversion between 2012 and 2014?")
    ask_mod.ask("reversion in 2013?")
    gaps = client.get("/api/archive/gaps").json()
    assert gaps["questions"] == 2
    assert {"name": "Ana R.", "questions": 2} in gaps["missing_correspondents"]
    years = {g["year"]: g["questions"] for g in gaps["empty_years"]}
    assert years == {2012: 1, 2013: 2}


def test_the_silences_ride_the_api_response(world, client):
    r = client.post("/api/archive/ask", json={"question": "reversion in 2013?"})
    assert r.status_code == 200
    assert r.json()["silences"]["empty_years"] == [2013]


def test_intake_reads_the_year_from_the_path(world, tmp_path):
    from services.archive.items import register_item
    from services.db import get_db

    f = tmp_path / "library" / "letters"
    f.mkdir(parents=True, exist_ok=True)
    (f / "lw-2019-ana.md").write_text("hello")
    conn = get_db()
    try:
        register_item(conn, "library/letters/lw-2019-ana.md", f / "lw-2019-ana.md")
        y = conn.execute(
            "SELECT year FROM item WHERE path='library/letters/lw-2019-ana.md'"
        ).fetchone()[0]
    finally:
        conn.close()
    assert y == 2019
