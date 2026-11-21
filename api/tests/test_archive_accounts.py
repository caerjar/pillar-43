"""C6: local accounts and roles (admin / staff / writer), loopback only.

Until the first account exists the archive is open, as it has been (a fresh
install has to be able to create its admin). From then on every archive route
needs a session, and a writer reaches only the items linked to them."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests import archive_fixtures as fx

ANA_ITEM = "library/letters/ana-letter.md"
BO_ITEM = "library/letters/bo-letter.md"
STAFF_ITEM = "library/minutes/board.md"


@pytest.fixture
def world(tmp_path, monkeypatch):
    fx.settings(tmp_path, monkeypatch)
    fx.seed(ANA_ITEM, "ana private reversion", "private", kind="letter")
    fx.seed(BO_ITEM, "bo reversion", "model", kind="letter")
    fx.seed(STAFF_ITEM, "board reversion", "staff", kind="minutes")
    (tmp_path / "library" / "minutes").mkdir(parents=True)
    (tmp_path / "library" / "minutes" / "board.md").write_text("board reversion")
    fx.lexical_only(monkeypatch, [ANA_ITEM, BO_ITEM, STAFF_ITEM])
    fx.fake_model(monkeypatch)
    return tmp_path


def _client():
    from main import app

    return TestClient(app, base_url="http://localhost")


@pytest.fixture
def client():
    return _client()


@pytest.fixture
def team(world, client):
    """admin + staff + two writers; ana owns ANA_ITEM, bo owns BO_ITEM.
    Returns {name: logged-in client}."""
    r = client.post(
        "/api/archive/accounts",
        json={"name": "root", "role": "admin", "password": "correct horse"},
    )
    assert r.status_code == 200, r.text
    assert (
        client.post(
            "/api/archive/login", json={"name": "root", "password": "correct horse"}
        ).status_code
        == 200
    )
    for name, role in (("sam", "staff"), ("ana", "writer"), ("bo", "writer")):
        assert (
            client.post(
                "/api/archive/accounts",
                json={"name": name, "role": role, "password": "pw-" + name + "-12345"},
            ).status_code
            == 200
        )
    assert (
        client.post(
            "/api/archive/accounts/ana/items", json={"paths": [ANA_ITEM]}
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/archive/accounts/bo/items", json={"paths": [BO_ITEM]}
        ).status_code
        == 200
    )
    out = {"root": client}
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


def test_open_until_the_first_account_then_closed(world, client):
    assert client.get("/api/archive/items/reads").status_code == 200
    client.post(
        "/api/archive/accounts",
        json={"name": "root", "role": "admin", "password": "correct horse"},
    )
    assert client.get("/api/archive/items/reads").status_code == 401
    assert client.post("/api/archive/ask", json={"question": "x"}).status_code == 401
    # the first account must be an admin
    from main import app

    other = TestClient(app, base_url="http://localhost")
    assert (
        other.post(
            "/api/archive/accounts",
            json={"name": "late", "role": "staff", "password": "pw-late-1"},
        ).status_code
        == 401
    )


def test_first_account_must_be_an_admin(world, client):
    r = client.post(
        "/api/archive/accounts",
        json={"name": "sam", "role": "staff", "password": "pw-sam-123"},
    )
    assert r.status_code == 422


def test_password_is_not_stored_and_wrong_password_fails(world, client):
    client.post(
        "/api/archive/accounts",
        json={"name": "root", "role": "admin", "password": "correct horse"},
    )
    from services.db import get_db

    conn = get_db()
    try:
        row = conn.execute("SELECT password_hash FROM account").fetchone()[0]
    finally:
        conn.close()
    assert "correct horse" not in row
    assert (
        client.post(
            "/api/archive/login", json={"name": "root", "password": "nope"}
        ).status_code
        == 401
    )


def test_a_writer_sees_only_their_own_items_and_controls(team):
    rows = team["ana"].get("/api/archive/items/reads").json()
    assert [r["path"] for r in rows] == [ANA_ITEM]
    assert rows[0]["consent"] == "private"  # their own closed item is theirs to see
    assert [r["path"] for r in team["bo"].get("/api/archive/items/reads").json()] == [
        BO_ITEM
    ]
    staff_view = {r["path"] for r in team["sam"].get("/api/archive/items/reads").json()}
    assert ANA_ITEM not in staff_view and {BO_ITEM, STAFF_ITEM} <= staff_view


def test_a_writer_sets_consent_only_on_their_own_item(team):
    ana = team["ana"]
    ok = ana.post(
        "/api/archive/items/consent", json={"path": ANA_ITEM, "level": "model"}
    )
    assert ok.status_code == 200
    assert (
        ana.post(
            "/api/archive/items/consent", json={"path": BO_ITEM, "level": "private"}
        ).status_code
        == 403
    )
    from services.db import get_db

    conn = get_db()
    try:
        assert tuple(
            conn.execute(
                "SELECT consent, consent_by FROM item WHERE path=?", (ANA_ITEM,)
            ).fetchone()
        ) == ("model", "ana")
        assert tuple(
            conn.execute("SELECT consent FROM item WHERE path=?", (BO_ITEM,)).fetchone()
        ) == ("model",)
    finally:
        conn.close()


def test_the_actor_is_the_session_not_the_request_body(team):
    team["ana"].post(
        "/api/archive/items/labels",
        json={"path": ANA_ITEM, "labels": ["never_for_training"], "by": "bo"},
    )
    from services.db import get_db

    conn = get_db()
    try:
        assert tuple(
            conn.execute("SELECT actor FROM ledger WHERE kind='labels'").fetchone()
        ) == ("ana",)
    finally:
        conn.close()


def test_a_writer_withdraws_only_their_own_item(team):
    assert (
        team["ana"].post("/api/archive/withdraw", json={"path": BO_ITEM}).status_code
        == 403
    )
    assert (
        team["ana"].post("/api/archive/withdraw", json={"path": ANA_ITEM}).status_code
        == 200
    )


def test_roles_gate_the_routes(team):
    assert (
        team["sam"]
        .post("/api/archive/ask", json={"question": "reversion?"})
        .status_code
        == 200
    )
    assert (
        team["ana"]
        .post("/api/archive/ask", json={"question": "reversion?"})
        .status_code
        == 403
    )
    assert team["ana"].get("/api/archive/gaps").status_code == 403
    assert team["ana"].get("/api/archive/ledger/verify").status_code == 403
    assert (
        team["sam"]
        .post("/api/archive/items/consent", json={"path": BO_ITEM, "level": "private"})
        .status_code
        == 403
    )
    assert team["sam"].get("/api/archive/accounts").status_code == 403
    assert {a["name"] for a in team["root"].get("/api/archive/accounts").json()} == {
        "root",
        "sam",
        "ana",
        "bo",
    }
    assert "password_hash" not in str(team["root"].get("/api/archive/accounts").json())


def test_the_other_screens_follow_the_session(team, client):
    anon = _client()
    assert anon.get("/api/file/raw", params={"path": STAFF_ITEM}).status_code == 401
    assert (
        team["sam"].get("/api/file/raw", params={"path": STAFF_ITEM}).status_code == 200
    )
    # a writer has no business in the staff file views
    assert (
        team["ana"].get("/api/file/raw", params={"path": STAFF_ITEM}).status_code == 404
    )
    # the profile stays readable so the app can draw its sign-in
    assert anon.get("/api/archive/profile").status_code == 200


def test_login_works_behind_the_web_proxy_host(world, client):
    """The web container's proxy sends Host: api. Sign-in must not 404 there;
    account administration still does."""
    client.post(
        "/api/archive/accounts",
        json={"name": "root", "role": "admin", "password": "correct horse"},
    )
    r = client.post(
        "/api/archive/login",
        json={"name": "root", "password": "correct horse"},
        headers={"host": "api:8000"},
    )
    assert r.status_code == 200, r.text


def test_account_routes_refuse_a_non_loopback_host(world, client):
    r = client.post(
        "/api/archive/accounts",
        json={"name": "root", "role": "admin", "password": "correct horse"},
        headers={"host": "192.168.1.5"},
    )
    assert r.status_code != 200
    from services.archive.accounts import is_loopback_host

    assert is_loopback_host("localhost:8000") and is_loopback_host("127.0.0.1")
    assert is_loopback_host("[::1]:8000")
    assert not is_loopback_host("192.168.1.5") and not is_loopback_host("press.example")


def test_logout_ends_the_session(team):
    ana = team["ana"]
    assert ana.get("/api/archive/me").json()["name"] == "ana"
    ana.post("/api/archive/logout")
    assert ana.get("/api/archive/items/reads").status_code == 401


# --- code audit 2026-11-20 M1 and M3 -----------------------------------------


def test_withdrawn_item_cannot_be_reopened_by_consent(team):
    """M1: set_consent had no withdrawn_at guard, so an admin (or the writer)
    could flip a withdrawn item back to `model` and its bytes were served."""
    bo, root, sam = team["bo"], team["root"], team["sam"]
    assert (
        bo.post("/api/archive/withdraw", json={"path": BO_ITEM, "by": "bo"}).status_code
        == 200
    )
    for who in (root, bo):
        r = who.post(
            "/api/archive/items/consent", json={"path": BO_ITEM, "level": "model"}
        )
        assert r.status_code == 409, r.text
    from services.db import get_db

    conn = get_db()
    try:
        consent, at = conn.execute(
            "SELECT consent, withdrawn_at FROM item WHERE path = ?", (BO_ITEM,)
        ).fetchone()
    finally:
        conn.close()
    assert consent == "private" and at is not None
    assert sam.get("/api/file/raw", params={"path": BO_ITEM}).status_code != 200
    reads = {i["path"] for i in root.get("/api/archive/items/reads").json()}
    assert BO_ITEM not in reads or all(
        i["consent"] == "private"
        for i in root.get("/api/archive/items/reads").json()
        if i["path"] == BO_ITEM
    )


def test_consent_on_a_live_item_still_works_after_the_guard(team):
    r = team["bo"].post(
        "/api/archive/items/consent", json={"path": BO_ITEM, "level": "staff"}
    )
    assert r.status_code == 200, r.text


def test_writer_cannot_read_annotations_on_items_they_do_not_own(team):
    """M3: GET /annotations only checked staff_may_see(path), so a writer saw
    staff notes on an item that GET /api/file hides from them."""
    sam, ana = team["sam"], team["ana"]
    r = sam.post(
        "/api/archive/annotations",
        json={"path": STAFF_ITEM, "body": "internal note on the minutes", "by": "sam"},
    )
    assert r.status_code == 200, r.text
    r = ana.get("/api/archive/annotations", params={"path": STAFF_ITEM})
    assert r.status_code == 403, r.text
    assert "internal note" not in r.text


def test_staff_admin_and_the_owner_still_read_annotations(team):
    sam, bo, root = team["sam"], team["bo"], team["root"]
    sam.post(
        "/api/archive/annotations",
        json={"path": STAFF_ITEM, "body": "staff note", "by": "sam"},
    )
    bo.post(
        "/api/archive/annotations",
        json={"path": BO_ITEM, "body": "my reply", "by": "bo"},
    )
    for who, path, text in (
        (sam, STAFF_ITEM, "staff note"),
        (root, STAFF_ITEM, "staff note"),
        (bo, BO_ITEM, "my reply"),
    ):
        r = who.get("/api/archive/annotations", params={"path": path})
        assert r.status_code == 200, r.text
        assert text in r.text


# --- the ledger line route: staff read receipts they may see, nothing else ---


def _ledger_line(kind: str, subject: str, data: dict) -> int:
    from services.archive import ledger
    from services.db import get_db

    conn = get_db()
    try:
        return ledger.append(conn, kind, "test", subject, data)
    finally:
        conn.close()


def test_staff_read_a_receipt_only_for_items_they_may_see(team):
    ok = _ledger_line("model_call", "", {"items": [{"path": BO_ITEM, "sha256": "aa"}]})
    hidden = _ledger_line(
        "model_call",
        "",
        {
            "items": [
                {"path": BO_ITEM, "sha256": "aa"},
                {"path": ANA_ITEM, "sha256": "bb"},
            ]
        },
    )
    assert team["sam"].get(f"/api/archive/ledger/{ok}").status_code == 200
    # one private item in the prompt hides the whole receipt from staff
    assert team["sam"].get(f"/api/archive/ledger/{hidden}").status_code == 404
    # admins read both
    assert team["root"].get(f"/api/archive/ledger/{ok}").status_code == 200
    assert team["root"].get(f"/api/archive/ledger/{hidden}").status_code == 200


def test_staff_cannot_read_withdraw_owner_or_consent_lines(team):
    w = _ledger_line("withdraw", ANA_ITEM, {"sha256": "cc"})
    o = _ledger_line("owner", ANA_ITEM, {"account": "ana"})
    assert team["sam"].get(f"/api/archive/ledger/{w}").status_code == 404
    assert team["sam"].get(f"/api/archive/ledger/{o}").status_code == 404
    # same answer as a line that does not exist
    assert team["sam"].get("/api/archive/ledger/99999").status_code == 404
    body = team["root"].get(f"/api/archive/ledger/{w}")
    assert body.status_code == 200 and body.json()["subject"] == ANA_ITEM
    # writers never reach the route
    assert team["ana"].get(f"/api/archive/ledger/{w}").status_code == 403


# --- the window before the first account: reads open, changes refused ---


def test_no_account_yet_refuses_withdraw_and_consent_changes(world, client):
    for url, body in (
        ("/api/archive/withdraw", {"path": BO_ITEM}),
        ("/api/archive/items/consent", {"path": BO_ITEM, "level": "private"}),
        ("/api/archive/items/labels", {"path": BO_ITEM, "labels": []}),
    ):
        r = client.post(url, json=body)
        assert r.status_code == 403, (url, r.text)
        assert "administrator account" in r.json()["detail"]
    # reads stay open, and nothing changed
    assert client.get("/api/archive/items/reads").status_code == 200
    from services.db import get_db

    conn = get_db()
    try:
        row = conn.execute(
            "SELECT consent FROM item WHERE path=?", (BO_ITEM,)
        ).fetchone()
    finally:
        conn.close()
    assert row[0] == "model"


def test_after_the_admin_exists_the_same_writes_work(team):
    r = team["root"].post(
        "/api/archive/items/consent", json={"path": BO_ITEM, "level": "staff"}
    )
    assert r.status_code == 200
