"""D1c: a reply's quoted '>' blocks are someone else's words. They are not
citable under the replying sender's consent: the message is indexed and cited
by its own words only. The quoted person's words are citable only through
their own message, under their own consent.

Invented mailbox: Bob (no consent) writes to Ann; Ann (consent = model)
replies quoting him, inline and below an "On ... wrote:" line.
"""

from __future__ import annotations

import pytest

import config
from tests.archive_fixtures import fake_model, lexical_only

BOB = (
    "Bob says the printer quote is USD 90 a page.\n"
    "Bob says keep the estate letter private."
)
ANN_REPLY = (
    "Ann answers that the fee stays at USD 60.\n"
    "\n"
    "> Bob says the printer quote is USD 90 a page.\n"
    "\n"
    "Ann adds that the reissue ships in June.\n"
    "\n"
    "On Mon, 5 Jan 2026 at 09:00, Bob <bob@press.example> wrote:\n"
    "> Bob says the printer quote is USD 90 a page.\n"
    ">\n"
    "> Bob says keep the estate letter private.\n"
)


def _msg(mid, sender, to, subject, body, day, reply_to=""):
    irt = f"In-Reply-To: <{reply_to}@press.example>\n" if reply_to else ""
    return (
        "From x@example Mon Jan  5 09:00:00 2026\n"
        f"From: {sender.title()} <{sender}@press.example>\n"
        f"To: {to}@press.example\n"
        f"Subject: {subject}\n"
        f"Date: {day:02d} Jan 2026 09:00:00 +0000\n"
        f"Message-ID: <{mid}@press.example>\n{irt}"
        "MIME-Version: 1.0\nContent-Type: text/plain; charset=utf-8\n\n"
        f"{body}\n\n"
    )


@pytest.fixture
def vault(tmp_path, monkeypatch):
    for name in ("notes", "library", "generated"):
        (tmp_path / name).mkdir()
    monkeypatch.setattr(config.settings, "notes_path", tmp_path / "notes")
    monkeypatch.setattr(config.settings, "library_root", tmp_path / "library")
    monkeypatch.setattr(config.settings, "generated_path", tmp_path / "generated")
    d = tmp_path / "library" / "correspondence"
    d.mkdir()
    (d / "team.mbox").write_text(
        _msg("b1", "bob", "ann", "Printer", BOB, 5)
        + _msg("a1", "ann", "bob", "Re: Printer", ANN_REPLY, 6, reply_to="b1")
    )
    from scripts import archive_cli

    archive_cli.intake()
    archive_cli.consent("person:ann@press.example", "model", "ann")
    return d / "team.mbox"


def _email_paths():
    from services.db import get_db

    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT path FROM item WHERE kind='email' AND path LIKE '%#%'"
        ).fetchall()
    finally:
        conn.close()
    return sorted(r[0] for r in rows)


def test_ask_sees_the_reply_without_the_quoted_correspondent(vault, monkeypatch):
    from services.archive.ask import ask

    lexical_only(monkeypatch, _email_paths())
    prompts = fake_model(
        monkeypatch, sentence="Ann answers that the fee stays at USD 60."
    )
    ask("printer fee", constrained=False)
    assert prompts, "the model saw Ann's reply"
    assert "Ann answers that the fee stays at USD 60." in prompts[0]
    assert "Ann adds that the reissue ships in June." in prompts[0]
    assert "USD 90" not in prompts[0]
    assert "estate letter" not in prompts[0]
    assert "wrote:" not in prompts[0]


def test_search_text_of_the_reply_holds_only_its_own_words(vault):
    from services.db import get_db

    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT f.rel_path, f.extracted_text FROM files f "
            "WHERE f.rel_path LIKE '%team.mbox#%'"
        ).fetchall()
        chunks = conn.execute(
            "SELECT c.text FROM file_chunks c JOIN files f ON f.id = c.file_id "
            "WHERE f.rel_path LIKE '%team.mbox#%'"
        ).fetchall()
    finally:
        conn.close()
    texts = dict(rows)
    reply = next(t for t in texts.values() if "Ann answers" in t)
    original = next(t for t in texts.values() if "Ann answers" not in t)
    assert "USD 90" not in reply and "estate letter" not in reply
    assert "USD 90" in original  # Bob's words stay in Bob's own message
    ann_chunks = [c[0] for c in chunks if "Ann" in c[0]]
    assert ann_chunks and not any("USD 90" in c for c in ann_chunks)


@pytest.mark.parametrize(
    "body, own, gone",
    [
        ("Yes.\n> no\n>> never", "Yes.", "no"),
        ("Yes.\n  > indented quote", "Yes.", "indented"),
        (
            "Agreed.\n\nOn 5 Jan 2026, at 09:00, Bob Smith <bob@x.example>\nwrote:\n> old",
            "Agreed.",
            "Bob Smith",
        ),
        (
            "Agreed.\n\n-----Original Message-----\nFrom: Bob\nSent: Monday\n\nOld text.",
            "Agreed.",
            "Old text",
        ),
        (
            "Agreed.\n\n________________________________\nFrom: Bob <b@x>\nSent: Monday\nTo: Ann\nSubject: x\n\nOld text.",
            "Agreed.",
            "Old text",
        ),
        ("Price > cost, so yes.", "Price > cost, so yes.", None),
    ],
)
def test_own_words(body, own, gone):
    from services.archive.mail import own_words

    got = own_words(body)
    assert got.strip() == own
    if gone:
        assert gone not in got
