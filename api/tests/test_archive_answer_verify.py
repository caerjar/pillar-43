"""A stored answer can be walked back, from storage alone, from a quote to the
passage it numbered, the item and sha256 behind it, and the item's text now.

Before the passage list was kept, `answer_json` held only numbers (`cites`,
`quote.passage`) and `answer_citation` held path and sha256: nothing said which
passage "2" had been, so no stored quote could be checked.
"""

from __future__ import annotations

import json

import pytest

from services.archive import ask as ask_mod
from services.archive.answers import answer_view, verify_answer
from tests import archive_fixtures as fx

PATH = "library/contracts/orchard.pdf"
TEXT = "Rights revert to the grantor after nine months."


@pytest.fixture
def world(tmp_path, monkeypatch):
    fx.settings(tmp_path, monkeypatch)
    fx.seed(PATH, TEXT, "model")
    fx.lexical_only(monkeypatch, [PATH])
    fx.fake_model(monkeypatch)
    return tmp_path


def _conn():
    from services.db import get_db

    return get_db()


def _ask() -> int:
    out = ask_mod.ask("When do rights revert?")
    assert out["answer"] and out["answer"][0]["quote"], "fixture should quote"
    assert out["answer_id"]
    return out["answer_id"]


def test_the_numbered_passage_list_is_kept_with_the_answer(world):
    aid = _ask()
    conn = _conn()
    try:
        rows = conn.execute(
            "SELECT n, path, sha256, ordinal, char_start, char_end, passage_sha256 "
            "FROM answer_passage WHERE answer_id=?",
            (aid,),
        ).fetchall()
    finally:
        conn.close()
    assert len(rows) == 1
    n, path, sha, ordinal, start, end, psha = rows[0]
    assert (n, path, sha, ordinal) == (1, PATH, "sha-" + PATH, 0)
    assert (start, end) == (0, len(TEXT))
    assert len(psha) == 64


def test_a_stored_quote_is_re_verified_from_storage_alone(world):
    aid = _ask()
    conn = _conn()
    try:
        v = verify_answer(conn, aid)
        assert v["all_verified"] is True
        assert [(c["passage"], c["path"], c["reason"]) for c in v["quotes"]] == [
            (1, PATH, "ok")
        ]
        assert answer_view(conn, aid)["verification"]["all_verified"] is True
    finally:
        conn.close()


def test_a_quote_that_is_not_in_the_item_does_not_verify(world):
    aid = _ask()
    conn = _conn()
    try:
        stored = json.loads(
            conn.execute(
                "SELECT answer_json FROM answer WHERE id=?", (aid,)
            ).fetchone()[0]
        )
        stored[0]["quote"]["text"] = "Rights revert at once, without notice."
        conn.execute(
            "UPDATE answer SET answer_json=? WHERE id=?", (json.dumps(stored), aid)
        )
        conn.commit()
        v = verify_answer(conn, aid)
    finally:
        conn.close()
    assert v["all_verified"] is False
    assert v["quotes"][0]["reason"] == "quote_not_in_item"


def test_a_changed_item_no_longer_verifies(world):
    aid = _ask()
    conn = _conn()
    try:
        conn.execute("UPDATE item SET sha256='changed' WHERE path=?", (PATH,))
        conn.commit()
        v = verify_answer(conn, aid)
    finally:
        conn.close()
    assert v["quotes"][0]["reason"] == "item_changed"


def test_a_withdrawn_item_cannot_be_verified(world):
    from services.archive.withdraw import withdraw

    aid = _ask()
    conn = _conn()
    try:
        withdraw(conn, PATH, by="ana")
        v = verify_answer(conn, aid)
    finally:
        conn.close()
    assert v["all_verified"] is False
    assert v["quotes"][0]["reason"] == "item_withdrawn"


def test_an_answer_recorded_before_passages_were_kept_says_so(world):
    aid = _ask()
    conn = _conn()
    try:
        conn.execute("DELETE FROM answer_passage WHERE answer_id=?", (aid,))
        conn.commit()
        v = verify_answer(conn, aid)
    finally:
        conn.close()
    assert v["quotes"][0]["reason"] == "no_passage_record"
    assert v["all_verified"] is False
