"""The writer's terms view: GET /api/archive/my-work.

Only the caller's own items, label notices in plain words, and the dated
access log from the ledger with no question text."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests import archive_fixtures as fx

ANA_ITEM = "library/contracts/ana-contract.md"
ANA_LABELLED = "library/letters/ana-letter.md"
BO_ITEM = "library/contracts/bo-contract.md"
QUESTION = "What does the reversion clause say about ana-contract?"


def _client():
    from main import app

    return TestClient(app, base_url="http://localhost")


@pytest.fixture
def team(tmp_path, monkeypatch):
    fx.settings(tmp_path, monkeypatch)
    fx.seed(ANA_ITEM, "reversion clause ana", "model")
    fx.seed(
        ANA_LABELLED,
        "letter reversion ana",
        "private",
        kind="letter",
        labels=["teaching_only"],
    )
    fx.seed(BO_ITEM, "reversion clause bo", "model")
    fx.lexical_only(monkeypatch, [ANA_ITEM, BO_ITEM])
    fx.fake_model(monkeypatch)
    root = _client()
    root.post(
        "/api/archive/accounts",
        json={"name": "root", "role": "admin", "password": "correct horse"},
    )
    root.post("/api/archive/login", json={"name": "root", "password": "correct horse"})
    for name, role in (("sam", "staff"), ("ana", "writer"), ("bo", "writer")):
        root.post(
            "/api/archive/accounts",
            json={"name": name, "role": role, "password": "pw-" + name + "-12345"},
        )
    root.post(
        "/api/archive/accounts/ana/items", json={"paths": [ANA_ITEM, ANA_LABELLED]}
    )
    root.post("/api/archive/accounts/bo/items", json={"paths": [BO_ITEM]})
    out = {"root": root}
    for name in ("sam", "ana", "bo"):
        c = _client()
        assert (
            c.post(
                "/api/archive/login",
                json={"name": name, "password": "pw-" + name + "-12345"},
            ).status_code
            == 200
        )
        out[name] = c
    return out


def test_a_writer_sees_only_their_own_items(team):
    body = team["ana"].get("/api/archive/my-work").json()
    assert [i["path"] for i in body["items"]] == [ANA_ITEM, ANA_LABELLED]
    assert BO_ITEM not in [i["path"] for i in body["items"]]
    assert team["bo"].get("/api/archive/my-work").json()["items"][0]["path"] == BO_ITEM


def test_staff_and_admin_have_no_terms_view(team):
    assert team["sam"].get("/api/archive/my-work").status_code == 403
    assert team["root"].get("/api/archive/my-work").status_code == 403
    assert _client().get("/api/archive/my-work").status_code == 401


def test_rows_carry_a_title_and_label_notices_in_words(team):
    items = {
        i["path"]: i for i in team["ana"].get("/api/archive/my-work").json()["items"]
    }
    assert items[ANA_ITEM]["title"] == "Ana Contract"
    notice = items[ANA_LABELLED]["labels"][0]
    assert notice["id"] == "teaching_only"
    assert notice["name"] == "teaching only"
    assert "only for: teaching-packet, editorial-history" in notice["meaning"]
    assert notice["aipref"] == "ai-use=n, train-ai=n"
    options = team["ana"].get("/api/archive/my-work").json()["label_options"]
    assert {o["id"] for o in options} >= {"teaching_only", "attribution_required"}


def test_access_log_has_date_purpose_receipt_and_never_the_question(team):
    r = team["sam"].post("/api/archive/ask", json={"question": QUESTION})
    assert r.status_code == 200, r.text
    receipt = r.json()["receipt_id"]
    resp = team["ana"].get("/api/archive/my-work")
    items = {i["path"]: i for i in resp.json()["items"]}
    reads = items[ANA_ITEM]["reads"]
    assert [x["receipt"] for x in reads] == [receipt]
    assert reads[0]["purpose"] == "answering a staff question"
    assert reads[0]["at"]
    assert items[ANA_LABELLED]["reads"] == []
    assert QUESTION not in resp.text
    assert "reversion" not in resp.text
    # bo's receipt for the same answer is bo's own, and does not list ana's item
    bo = team["bo"].get("/api/archive/my-work").json()["items"]
    assert [x["receipt"] for x in bo[0]["reads"]] == [receipt]


def test_a_withdrawn_item_stays_as_a_row_that_says_so(team):
    assert (
        team["ana"].post("/api/archive/withdraw", json={"path": ANA_ITEM}).status_code
        == 200
    )
    items = {
        i["path"]: i for i in team["ana"].get("/api/archive/my-work").json()["items"]
    }
    assert items[ANA_ITEM]["withdrawn_at"]
    assert items[ANA_ITEM]["consent"] == "private"
