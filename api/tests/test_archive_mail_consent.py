"""D1b: each email under its own consent, and a correspondent's consent
carries to every message they sent (including ones ingested later).

Invented mailbox: ann sends 3 messages, bob 2, cara 1. Retrieval is
lexical-only and returns every message path, so what comes back is exactly
what consent lets through.
"""

from __future__ import annotations

import json

import pytest

import config
from tests.archive_fixtures import fake_model, lexical_only

MESSAGES = [
    ("a1", "ann", "bob", "Fee", "Ann proposes a fee of USD 60 a page.", 5),
    ("a2", "ann", "bob", "Cover", "Ann approves the cover.", 6),
    ("a3", "ann", "cara", "Dates", "Ann sets the reissue for June.", 7),
    ("b1", "bob", "ann", "Fee", "Bob accepts the fee of USD 60.", 8),
    ("b2", "bob", "ann", "Cover", "Bob prints the cover in May.", 9),
    ("c1", "cara", "bob", "Fee", "Cara asks about the fee Bob accepted.", 10),
]


def _msg(mid, sender, to, subject, body, day):
    return (
        "From x@example Mon Jan  5 09:00:00 2026\n"
        f"From: {sender.title()} <{sender}@press.example>\n"
        f"To: {to}@press.example\n"
        f"Subject: {subject}\n"
        f"Date: {day:02d} Jan 2026 09:00:00 +0000\n"
        f"Message-ID: <{mid}@press.example>\n"
        "MIME-Version: 1.0\nContent-Type: text/plain; charset=utf-8\n\n"
        f"{body}\n\n"
    )


def _write(path, extra=()):
    path.write_text("".join(_msg(*m) for m in [*MESSAGES, *extra]))


@pytest.fixture
def vault(tmp_path, monkeypatch):
    for name in ("notes", "library", "generated"):
        (tmp_path / name).mkdir()
    monkeypatch.setattr(config.settings, "notes_path", tmp_path / "notes")
    monkeypatch.setattr(config.settings, "library_root", tmp_path / "library")
    monkeypatch.setattr(config.settings, "generated_path", tmp_path / "generated")
    d = tmp_path / "library" / "correspondence"
    d.mkdir()
    _write(d / "team.mbox")
    from scripts import archive_cli

    archive_cli.intake()
    return d / "team.mbox"


def _paths(sender=None):
    from services.db import get_db

    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT path, people FROM item WHERE kind='email' AND path LIKE '%#%'"
        ).fetchall()
    finally:
        conn.close()
    out = []
    for p, people in rows:
        s = [x["address"] for x in json.loads(people) if x.get("sender")]
        if sender is None or s == [f"{sender}@press.example"]:
            out.append(p)
    return sorted(out)


def _cited(monkeypatch, audience, question="fee"):
    from services.retrieval import fetch_materials_counted

    lexical_only(monkeypatch, _paths())
    mats, _ = fetch_materials_counted(question, audience=audience)
    return sorted(m.rel_path for m in mats)


def test_nothing_citable_before_consent(vault, monkeypatch):
    assert len(_paths()) == 6
    assert _cited(monkeypatch, "model") == []


def test_one_message_consent_cites_only_that_message(vault, monkeypatch):
    from scripts import archive_cli

    one = _paths("bob")[0]
    archive_cli.consent(one, "model", "reviewer")
    assert _cited(monkeypatch, "model") == [one]


def test_person_consent_cites_exactly_their_messages(vault, monkeypatch):
    from scripts import archive_cli

    n = archive_cli.consent("person:Ann@Press.example", "model", "ann")
    assert n == 3
    assert len(_paths("ann")) == 3
    assert _cited(monkeypatch, "model") == _paths("ann")


def test_person_consent_reaches_ask(vault, monkeypatch):
    from scripts import archive_cli
    from services.archive.ask import ask

    archive_cli.consent("person:ann@press.example", "model", "ann")
    lexical_only(monkeypatch, _paths())
    prompts = fake_model(monkeypatch, sentence="Ann proposes a fee of USD 60 a page.")
    ask("fee", constrained=False)
    assert prompts, "the model saw Ann's messages"
    assert "Ann proposes a fee" in prompts[0]
    assert "Bob accepts" not in prompts[0] and "Cara asks" not in prompts[0]


def test_later_message_from_consenting_person_inherits(vault, monkeypatch):
    from scripts import archive_cli

    archive_cli.consent("person:ann@press.example", "model", "ann")
    _write(vault, extra=[("a4", "ann", "bob", "Late", "Ann adds a late note.", 20)])
    archive_cli.intake()
    assert len(_paths("ann")) == 4
    assert _cited(monkeypatch, "model") == _paths("ann")


def test_attachment_follows_its_message_unless_it_has_its_own(vault):
    from scripts import archive_cli
    from services.db import get_db

    msg = _paths("ann")[0]
    conn = get_db()
    try:
        for name, sha, consent in (
            ("1-s.txt", "s1", "private"),
            ("2-own.txt", "s2", "staff"),
        ):
            conn.execute(
                "INSERT INTO item (path, sha256, kind, consent) VALUES (?,?,?,?)",
                (f"{msg}/{name}", sha, "attachment", consent),
            )
        conn.commit()
    finally:
        conn.close()
    archive_cli.consent("person:ann@press.example", "model", "ann")
    conn = get_db()
    try:
        got = dict(
            conn.execute("SELECT path, consent FROM item WHERE kind='attachment'")
        )
    finally:
        conn.close()
    assert got[f"{msg}/1-s.txt"] == "model"
    assert got[f"{msg}/2-own.txt"] == "staff"


def test_withdrawing_a_person_withdraws_all_their_messages(vault, monkeypatch):
    from scripts import archive_cli

    archive_cli.consent("person:ann@press.example", "model", "ann")
    archive_cli.consent("person:bob@press.example", "model", "bob")
    assert len(_cited(monkeypatch, "model")) == 5
    out = archive_cli.withdraw("person:ann@press.example", "ann")
    assert out["withdrawn"] == 3
    assert _cited(monkeypatch, "model") == _paths("bob")
    archive_cli.intake()  # a re-run does not bring them back
    assert _cited(monkeypatch, "model") == _paths("bob")
    assert _cited(monkeypatch, "staff") == _paths("bob")


def test_staff_listing_sees_only_consented_messages(vault):
    from scripts import archive_cli
    from services.archive.access import filter_results

    archive_cli.consent("person:cara@press.example", "staff", "cara")
    hits = [{"path": p} for p in _paths()]
    assert [h["path"] for h in filter_results(hits)] == _paths("cara")
