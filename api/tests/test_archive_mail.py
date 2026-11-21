"""Email stage 2b: one item per message, threaded, attachments as children,
private by default, and no MIME/base64 in what the catalog indexes.

The mailbox is built here from invented text (no real correspondence). It has
7 messages in 3 threads: a thread of three linked by In-Reply-To, a thread of
two where the third link is only in References, one message with a base64
text attachment, and a lone message with a quoted-printable body.
"""

from __future__ import annotations

import base64
import json

import pytest

import config

ATTACH = "Schedule: reissue due June.\n"


def _msg(mid, subject, body, *, reply=None, refs=None, date, attach=None, qp=False):
    lines = [
        "From: Ann <ann@press.example>",
        "To: Ben <ben@press.example>",
        f"Subject: {subject}",
        f"Date: {date}",
        f"Message-ID: <{mid}@press.example>",
    ]
    if reply:
        lines.append(f"In-Reply-To: <{reply}@press.example>")
    if refs:
        lines.append("References: " + " ".join(f"<{r}@press.example>" for r in refs))
    lines.append("MIME-Version: 1.0")
    if attach:
        lines += [
            'Content-Type: multipart/mixed; boundary="BB"',
            "",
            "--BB",
            "Content-Type: text/plain; charset=utf-8",
            "",
            body,
            "--BB",
            "Content-Type: text/plain",
            "Content-Transfer-Encoding: base64",
            'Content-Disposition: attachment; filename="schedule.txt"',
            "",
            base64.encodebytes(attach.encode()).decode().strip(),
            "--BB--",
        ]
    elif qp:
        lines += [
            "Content-Type: text/plain; charset=utf-8",
            "Content-Transfer-Encoding: quoted-printable",
            "",
            body,
        ]
    else:
        lines += ["Content-Type: text/plain; charset=utf-8", "", body]
    return (
        "From ann@press.example Mon Jan  5 09:00:00 2026\n" + "\n".join(lines) + "\n\n"
    )


def _mbox_text() -> str:
    return "".join(
        [
            _msg(
                "a1",
                "Fee",
                "Proposed fee is USD 60 a page.",
                date="Mon, 05 Jan 2026 09:00:00 +0000",
            ),
            _msg(
                "a2",
                "Re: Fee",
                "Agreed on USD 60.",
                reply="a1",
                refs=["a1"],
                date="Tue, 06 Jan 2026 09:00:00 +0000",
            ),
            _msg(
                "a3",
                "Re: Fee",
                "Contract follows.",
                reply="a2",
                refs=["a1", "a2"],
                date="Wed, 07 Jan 2026 09:00:00 +0000",
            ),
            _msg(
                "b1",
                "Cover",
                "Cover v3 approved.",
                date="Mon, 12 Jan 2026 09:00:00 +0000",
            ),
            # b2 replies to b1 and b3 only names b1 in References.
            _msg(
                "b2",
                "Re: Cover",
                "Printing schedule attached.",
                reply="b1",
                refs=["b1"],
                date="Tue, 13 Jan 2026 09:00:00 +0000",
                attach=ATTACH,
            ),
            _msg(
                "b3",
                "Re: Cover",
                "Thanks.",
                refs=["b1"],
                date="Wed, 14 Jan 2026 09:00:00 +0000",
            ),
            _msg(
                "c1",
                "Permissions",
                "Caf=C3=A9 poem, fee USD 150.",
                date="Thu, 15 Jan 2026 09:00:00 +0000",
                qp=True,
            ),
        ]
    )


@pytest.fixture
def library(tmp_path, monkeypatch):
    for name in ("notes", "library", "generated"):
        (tmp_path / name).mkdir()
    monkeypatch.setattr(config.settings, "notes_path", tmp_path / "notes")
    monkeypatch.setattr(config.settings, "library_root", tmp_path / "library")
    monkeypatch.setattr(config.settings, "generated_path", tmp_path / "generated")
    d = tmp_path / "library" / "correspondence"
    d.mkdir()
    (d / "mail-export.mbox").write_text(_mbox_text())
    return d / "mail-export.mbox"


def _rows():
    from services.db import get_db

    conn = get_db()
    try:
        return conn.execute(
            "SELECT path, kind, consent, sha256, people FROM item ORDER BY path"
        ).fetchall()
    finally:
        conn.close()


def test_intake_makes_one_item_per_message(library):
    from scripts import archive_cli

    out = archive_cli.intake()

    assert out["mail"] == {"messages": 7, "threads": 3, "attachments": 1, "refused": 0}
    msgs = [r for r in _rows() if r[1] == "email" and "#" in r[0]]
    assert len(msgs) == 7


def test_threads_follow_message_id_in_reply_to_and_references(library):
    from scripts import archive_cli

    archive_cli.intake()
    threads: dict[str, int] = {}
    for path, kind, *_ in _rows():
        if kind == "email" and "#" in path:
            tid = path.split("#")[1].split("/")[0]
            threads[tid] = threads.get(tid, 0) + 1
    assert sorted(threads.values()) == [1, 3, 3]


def test_attachment_is_a_child_of_its_message_and_private(library):
    from scripts import archive_cli

    archive_cli.intake()
    rows = _rows()
    att = [r for r in rows if r[1] == "attachment"]
    assert len(att) == 1
    parent = att[0][0].rsplit("/", 1)[0]
    assert parent in {r[0] for r in rows}, "child path starts with its message's path"
    assert att[0][2] == "private"


def test_every_email_item_is_private_and_links_correspondents(library):
    from scripts import archive_cli

    archive_cli.intake()
    for path, _kind, consent, *_rest in _rows():
        if "#" in path:
            assert consent == "private", path
    msg = next(r for r in _rows() if r[1] == "email" and "#" in r[0])
    assert {p["address"] for p in json.loads(msg[4])} == {
        "ann@press.example",
        "ben@press.example",
    }


def test_rerun_keeps_consent_and_adds_nothing(library):
    from scripts import archive_cli

    archive_cli.intake()
    first = next(r for r in _rows() if r[1] == "email" and "#" in r[0])
    archive_cli.consent(first[0], "staff", "reviewer")
    before = len(_rows())

    out = archive_cli.intake()

    assert len(_rows()) == before
    assert out["mail"]["messages"] == 7
    again = next(r for r in _rows() if r[0] == first[0])
    assert again[2] == "staff"


def test_withdrawn_message_is_refused_on_reintake(library):
    from scripts import archive_cli
    from services.db import get_db

    archive_cli.intake()
    victim = next(r for r in _rows() if r[1] == "email" and "#" in r[0])
    conn = get_db()
    try:
        conn.execute("DELETE FROM item WHERE path = ?", (victim[0],))
        conn.execute(
            "INSERT INTO tombstone (sha256, withdrawn_by, at) VALUES (?, 'test', 'now')",
            (victim[3],),
        )
        conn.commit()
    finally:
        conn.close()

    out = archive_cli.intake()

    assert out["mail"]["refused"] == 1
    assert victim[0] not in {r[0] for r in _rows()}


def test_catalog_text_has_no_mime_headers_or_base64(library):
    from services.archive.ask import split_sentences
    from services.catalog.extract import extract_text_for_catalog

    text = extract_text_for_catalog(library, "library/correspondence/mail-export.mbox")

    assert text is not None
    for junk in (
        "Content-Transfer-Encoding",
        "Content-Type",
        "MIME-Version",
        "boundary",
        "c2NoZWR1bGU",
    ):
        assert junk not in text, junk
    assert "Proposed fee is USD 60 a page." in text
    assert "Café poem" in text, "quoted-printable decoded"
    assert not any("Content-" in s for s in split_sentences(text))
