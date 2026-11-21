"""Ask names who closed things, and does not borrow another title's clauses.

Feature audit 2026-11-20:
  H1  "N items closed by their writers" was hardcoded; most items are closed
      by the intake default and no writer had acted.
  H3  A question about a withdrawn title was answered from another title's
      contract, with no closure named.
  H4b A question about a title that has no contract was answered with three
      other titles' royalty clauses.
"""

from __future__ import annotations

import json

import pytest

from services.archive import ask as ask_mod
from tests import archive_fixtures as fx

CLAUSE = (
    "The Grantor grants to the Publisher the exclusive right to publish the "
    "Work in the following formats: paperback, hardcover and ebook."
)
LANTERNS = "library/contracts/Kaminrowska_Lanterns_translation-contract.pdf"
FERRIDAY = "library/contracts/ferriday_fieldguide_agreement.pdf"


def _sql(sql, args=()):
    from services.db import get_db

    conn = get_db()
    try:
        conn.execute(sql, args)
        conn.commit()
    finally:
        conn.close()


def _accounts():
    """root (admin), sam (staff), ana (writer, owns nothing yet)."""
    for name, role in (("root", "admin"), ("sam", "staff"), ("ana", "writer")):
        _sql(
            "INSERT INTO account (name, role, password_hash, created_at) "
            "VALUES (?,?,?,?)",
            (name, role, "x", "2026-11-20T00:00:00+00:00"),
        )


def _closed_by(path, who):
    _sql("UPDATE item SET consent_by = ? WHERE path = ?", (who, path))


@pytest.fixture
def org(tmp_path, monkeypatch):
    fx.settings(tmp_path, monkeypatch)
    return tmp_path


# ── H1: who closed ──────────────────────────────────────────────────────────


def test_the_line_says_who_closed_each_group(org, monkeypatch):
    _accounts()
    a, b, c, d = (f"library/letters/l{i}.md" for i in range(4))
    fx.seed("library/contracts/open.pdf", "The grant reverts in nine months.", "model")
    for p in (a, b, c, d):
        fx.seed(p, "reverts letter " + p, "private", kind="letter")
    _closed_by(a, "intake")
    _closed_by(b, "setup")
    _closed_by(c, "ana")  # a writer account
    _closed_by(d, "root")  # an administrator
    fx.lexical_only(monkeypatch, ["library/contracts/open.pdf", a, b, c, d])
    fx.fake_model(monkeypatch)
    s = ask_mod.ask("When does the grant revert?")["silences"]
    assert s["closed"] == 4
    assert s["closed_by"] == {"writer": 1, "default": 2, "staff": 1}
    assert s["line"].split("; ") == [
        "1 item closed by its writer",
        "2 items closed by default (no one has opened them to the AI)",
        "1 item closed by staff or an administrator",
    ]


def test_items_closed_only_by_default_never_say_writer(org, monkeypatch):
    fx.seed("library/contracts/open.pdf", "The grant reverts in nine months.", "model")
    for i in range(3):
        p = f"library/letters/l{i}.md"
        fx.seed(p, "reverts letter", "private", kind="letter")
        _closed_by(p, "intake")
    fx.lexical_only(
        monkeypatch,
        ["library/contracts/open.pdf"] + [f"library/letters/l{i}.md" for i in range(3)],
    )
    fx.fake_model(monkeypatch)
    s = ask_mod.ask("When does the grant revert?")["silences"]
    assert s["line"] == "3 items closed by default (no one has opened them to the AI)"


def test_an_unregistered_file_counts_as_closed_by_default(org, monkeypatch):
    fx.seed("library/contracts/open.pdf", "The grant reverts in nine months.", "model")
    fx.seed("library/letters/raw.md", "reverts raw", None, kind="letter")
    fx.lexical_only(
        monkeypatch, ["library/contracts/open.pdf", "library/letters/raw.md"]
    )
    fx.fake_model(monkeypatch)
    s = ask_mod.ask("When does the grant revert?")["silences"]
    assert s["closed_by"] == {"writer": 0, "default": 1, "staff": 0}


def test_a_withdrawal_counts_as_the_writer(org, monkeypatch):
    from services.archive.withdraw import withdraw
    from services.db import get_db

    fx.seed("library/contracts/open.pdf", "The grant reverts in nine months.", "model")
    fx.seed("library/letters/gone.md", "reverts gone", "model", kind="letter")
    conn = get_db()
    try:
        withdraw(conn, "library/letters/gone.md", by="ana")
    finally:
        conn.close()
    fx.lexical_only(
        monkeypatch, ["library/contracts/open.pdf", "library/letters/gone.md"]
    )
    fx.fake_model(monkeypatch)
    s = ask_mod.ask("When does the grant revert?")["silences"]
    assert s["closed_by"]["writer"] == 1
    assert s["line"] == "1 item closed by its writer"


# ── H3: a withdrawn title ───────────────────────────────────────────────────


def _lanterns_world(monkeypatch):
    fx.seed(
        LANTERNS,
        'LANTERN WHARF EDITIONS concerning the work titled "Lanterns for the '
        'Second Winter" (ISBN 979-8-9001-0548-2). ' + CLAUSE,
        "model",
    )
    fx.seed(
        FERRIDAY,
        'LANTERN WHARF EDITIONS concerning the work titled "A Field Guide to '
        'Closing Time" (ISBN 979-8-9001-0274-0). ' + CLAUSE,
        "model",
    )
    fx.lexical_only(monkeypatch, [LANTERNS, FERRIDAY])
    return fx.fake_model(monkeypatch)


Q = "Where are we allowed to sell the Lanterns book, and is it paperback only?"


def test_control_the_open_lanterns_contract_answers(org, monkeypatch):
    prompts = _lanterns_world(monkeypatch)
    out = ask_mod.ask(Q)
    assert len(prompts) == 1 and out["closed_named"] == []


def test_a_withdrawn_title_is_named_not_answered_from_another_title(org, monkeypatch):
    from services.archive.withdraw import withdraw
    from services.db import get_db

    prompts = _lanterns_world(monkeypatch)
    conn = get_db()
    try:
        withdraw(conn, LANTERNS, by="ana")
    finally:
        conn.close()
    out = ask_mod.ask(Q)
    assert prompts == [], "the model must not be asked"
    assert out["answer"] == [] and out["not_answered"] is True
    assert [c["path"] for c in out["closed_named"]] == [LANTERNS]
    assert out["closed_named"][0]["state"] == "withdrawn"
    line = out["silences"]["line"]
    assert "Lanterns" in line and "withdrawn by its writer" in line
    assert out["silences"]["closed_named"][0]["reason"] == "withdrawn by its writer"


def test_a_question_about_another_title_is_not_blocked_by_a_withdrawal(
    org, monkeypatch
):
    from services.archive.withdraw import withdraw
    from services.db import get_db

    prompts = _lanterns_world(monkeypatch)
    conn = get_db()
    try:
        withdraw(conn, LANTERNS, by="ana")
    finally:
        conn.close()
    out = ask_mod.ask("Is the Field Guide book available as an ebook?")
    assert len(prompts) == 1 and out["closed_named"] == []


def test_a_closed_title_names_who_closed_it(org, monkeypatch):
    _accounts()
    prompts = _lanterns_world(monkeypatch)
    _sql(
        "UPDATE item SET consent='staff', consent_by='intake' WHERE path=?", (LANTERNS,)
    )
    out = ask_mod.ask(Q)
    assert prompts == []
    assert out["closed_named"][0]["state"] == "closed"
    assert "closed by its writer" not in out["silences"]["line"]
    assert "closed by default" in out["silences"]["line"]
    _sql("UPDATE item SET consent_by='ana' WHERE path=?", (LANTERNS,))
    out = ask_mod.ask(Q)
    assert "Lanterns" in out["silences"]["line"]
    assert "closed by its writer" in out["silences"]["line"]


# ── H4b: a title with no document of the asked kind ─────────────────────────


def _tides_world(monkeypatch):
    royalty = "Royalties are ten percent of net receipts, payable within ninety days."
    contracts = []
    for slug, title in (
        ("saltledger", "Saltledger Almanac"),
        ("solvang", "Solvang Hald Poems"),
    ):
        p = f"library/contracts/{slug}_agreement.pdf"
        contracts.append(p)
        fx.seed(
            p,
            f'LANTERN WHARF EDITIONS concerning the work titled "{title}" '
            f"(ISBN 979-8-9001-0{len(slug)}00-0). {royalty}",
            "model",
        )
    note = "library/design/yellow-proof-note_ninety-tides_2021-06-08.txt"
    fx.seed(
        note,
        "Proof note for Ninety Tides: the spine is yellow.",
        "model",
        kind="design",
    )
    fx.lexical_only(monkeypatch, [*contracts, note])
    return fx.fake_model(monkeypatch), contracts


def test_a_title_with_no_contract_says_so_and_borrows_nothing(org, monkeypatch):
    prompts, _ = _tides_world(monkeypatch)
    out = ask_mod.ask("What did the Ninety Tides contract say about royalties?")
    assert prompts == [], "the model must not be asked"
    assert out["answer"] == [] and out["not_answered"] is True
    assert out["no_document"] == {"title": "Ninety Tides", "kind": "contract"}
    assert out["would_answer"] == "a contract for Ninety Tides"
    assert "no contract for Ninety Tides" in out["silences"]["line"]


def test_the_contract_for_phrasing_is_caught_too(org, monkeypatch):
    prompts, _ = _tides_world(monkeypatch)
    out = ask_mod.ask("Which royalties does the contract for Ninety Tides set?")
    assert prompts == [] and out["no_document"]["title"] == "Ninety Tides"


def test_a_title_that_has_a_contract_is_answered(org, monkeypatch):
    prompts, _ = _tides_world(monkeypatch)
    out = ask_mod.ask("What did the Saltledger contract say about royalties?")
    assert len(prompts) == 1 and not out.get("no_document")


def test_a_question_that_asks_for_no_kind_is_not_checked(org, monkeypatch):
    prompts, _ = _tides_world(monkeypatch)
    out = ask_mod.ask("What colour is the spine of Ninety Tides?")
    assert not out.get("no_document")


def test_no_document_rides_the_log(org, monkeypatch):
    _tides_world(monkeypatch)
    out = ask_mod.ask("What did the Ninety Tides contract say about royalties?")
    from services.db import get_db

    conn = get_db()
    try:
        (raw,) = conn.execute(
            "SELECT silences FROM answer WHERE id = ?", (out["answer_id"],)
        ).fetchone()
    finally:
        conn.close()
    assert "no contract for Ninety Tides" in json.loads(raw)["line"]


def test_a_title_carried_only_by_the_file_name_counts_as_held(org, monkeypatch):
    """Live stack: the Saltledger contract's path is
    contract_merrowby_SaltLedger_2012.pdf; underscores keep it one token."""
    p = "library/contracts/contract_merrowby_SaltLedger_2012.pdf"
    fx.seed(p, "Royalties are ten percent of net receipts.", "model")
    fx.lexical_only(monkeypatch, [p])
    prompts = fx.fake_model(monkeypatch)
    out = ask_mod.ask("What did the Saltledger contract say about royalties?")
    assert not out.get("no_document") and len(prompts) == 1
