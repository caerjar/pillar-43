"""C4: annotations (the right of reply). A person attaches a dated, signed note
to an item or to one of its passages. Ask returns it beside the passage it is
attached to; the model never reads it."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from services.archive import ask as ask_mod
from tests import archive_fixtures as fx

PATH = "library/contracts/orchard.pdf"
OTHER = "library/contracts/ferrymen.pdf"
TEXT = "Rights revert to the grantor after nine months."


@pytest.fixture
def world(tmp_path, monkeypatch):
    fx.settings(tmp_path, monkeypatch)
    fx.seed(PATH, TEXT, "model")
    fx.seed(OTHER, "Ferrymen reversion terms differ.", "model")
    fx.lexical_only(monkeypatch, [PATH, OTHER])
    fx.fake_model(monkeypatch)
    return tmp_path


@pytest.fixture
def client():
    from main import app

    return TestClient(app, base_url="http://localhost")


def test_ask_returns_the_annotation_beside_its_passage(world, client):
    r = client.post(
        "/api/archive/annotations",
        json={
            "path": PATH,
            "ordinal": 0,
            "body": "The translator disputes this reading; see letter of 2015.",
            "by": "Wren Tallowfield",
            "role": "translator",
        },
    )
    assert r.status_code == 200, r.text
    out = ask_mod.ask("When do rights revert?")
    by_path = {p["path"]: p for p in out["passages"]}
    ann = by_path[PATH]["annotations"]
    assert [a["body"] for a in ann] == [
        "The translator disputes this reading; see letter of 2015."
    ]
    assert ann[0]["by"] == "Wren Tallowfield" and ann[0]["role"] == "translator"
    assert ann[0]["at"]
    assert by_path[OTHER]["annotations"] == []


def test_an_annotation_on_another_passage_does_not_attach(world, client):
    client.post(
        "/api/archive/annotations",
        json={"path": PATH, "ordinal": 7, "body": "elsewhere", "by": "x"},
    )
    out = ask_mod.ask("When do rights revert?")
    assert [p["annotations"] for p in out["passages"] if p["path"] == PATH] == [[]]


def test_a_whole_item_annotation_attaches_to_every_passage_of_it(world, client):
    client.post(
        "/api/archive/annotations",
        json={"path": PATH, "body": "About the whole contract.", "by": "x"},
    )
    out = ask_mod.ask("When do rights revert?")
    p = next(p for p in out["passages"] if p["path"] == PATH)
    assert [a["body"] for a in p["annotations"]] == ["About the whole contract."]


def test_the_model_never_reads_annotations(world, client, monkeypatch):
    prompts = fx.fake_model(monkeypatch)
    client.post(
        "/api/archive/annotations",
        json={"path": PATH, "ordinal": 0, "body": "SECRETNOTE", "by": "x"},
    )
    ask_mod.ask("When do rights revert?")
    assert prompts and all("SECRETNOTE" not in p for p in prompts)


def test_retracted_annotation_is_hidden_and_everything_is_in_the_ledger(world, client):
    aid = client.post(
        "/api/archive/annotations",
        json={"path": PATH, "ordinal": 0, "body": "mistaken", "by": "ana"},
    ).json()["id"]
    r = client.post(f"/api/archive/annotations/{aid}/retract", json={"by": "ana"})
    assert r.status_code == 200
    out = ask_mod.ask("When do rights revert?")
    p = next(p for p in out["passages"] if p["path"] == PATH)
    assert p["annotations"] == []
    from services.db import get_db

    conn = get_db()
    try:
        kinds = [r[0] for r in conn.execute("SELECT kind FROM ledger ORDER BY seq")]
    finally:
        conn.close()
    assert kinds[:2] == ["annotation", "annotation_retract"]


def test_cannot_annotate_unknown_or_closed_items(world, client):
    fx.seed("library/letters/p.md", "closed", "private", kind="letter")
    for path in ("library/nope.pdf", "library/letters/p.md"):
        r = client.post(
            "/api/archive/annotations", json={"path": path, "body": "x", "by": "a"}
        )
        assert r.status_code == 404, path
    r = client.post(
        "/api/archive/annotations", json={"path": PATH, "body": "  ", "by": "a"}
    )
    assert r.status_code == 422


def test_list_annotations_for_an_item(world, client):
    client.post(
        "/api/archive/annotations", json={"path": PATH, "body": "one", "by": "a"}
    )
    rows = client.get("/api/archive/annotations", params={"path": PATH}).json()
    assert [r["body"] for r in rows] == ["one"]
