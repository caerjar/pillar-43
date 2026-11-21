"""Email as items: one per message, threaded, attachments as children.

Stdlib only (`mailbox`, `email`). A mailbox is read as messages, never as one
long text: the MIME headers and base64 bodies that a raw read puts in front of
the sentence splitter are decoded here or left out.

Identity without a migration. Messages and attachments are `item` rows whose
`path` is the mailbox path plus a fragment, so the parent pointer, the thread
and the message are all in a column that already exists:

    library/correspondence/mail-export.mbox                      the file item
    library/correspondence/mail-export.mbox#<thread>/<msg>       one message
    library/correspondence/mail-export.mbox#<thread>/<msg>/<n>-<file>
                                                                 an attachment,
                                                                 child of <msg>

`<thread>` and `<msg>` are short hashes of Message-ID, so a re-run of intake
finds the same rows and leaves their consent alone. `sha256` on a message row
is the hash of its raw bytes, on an attachment its payload: a withdrawal of
one message (a tombstone on that hash) keeps it out on re-intake.

Everything here is private. Email involves people who never agreed to
anything; staff review before anything opens.
"""

from __future__ import annotations

import email
import hashlib
import mailbox
import re
from dataclasses import dataclass, field
from email import policy
from email.message import EmailMessage
from email.utils import getaddresses, parsedate_to_datetime
from pathlib import Path

MAIL_EXTENSIONS = (".mbox", ".eml")
_MSG_ID = re.compile(r"<[^<>\s]+>")


@dataclass
class Attachment:
    filename: str
    content_type: str
    payload: bytes


@dataclass
class Mail:
    message_id: str
    in_reply_to: str
    references: list[str]
    subject: str
    date: str
    sender: tuple[str, str]  # (name, address)
    recipients: list[tuple[str, str]]
    body: str
    attachments: list[Attachment]
    raw_sha256: str
    thread: str = ""
    key: str = ""


def _h(s: str, n: int = 10) -> str:
    return hashlib.sha1(s.encode("utf-8", "replace")).hexdigest()[:n]


def _body(msg: EmailMessage) -> str:
    part = msg.get_body(preferencelist=("plain", "html"))
    if part is None:
        return ""
    try:
        text = part.get_content()
    except (LookupError, UnicodeError):
        return ""
    if part.get_content_type() == "text/html":
        text = re.sub(r"<[^>]+>", " ", text)
    return text.strip()


def _parse(msg: EmailMessage, raw: bytes) -> Mail:
    def addrs(header: str) -> list[tuple[str, str]]:
        return [
            (n, a)
            for n, a in getaddresses([str(v) for v in msg.get_all(header, [])])
            if a
        ]

    mid = (_MSG_ID.findall(str(msg.get("Message-ID", ""))) or [""])[0]
    sender = (addrs("From") or [("", "")])[0]
    atts: list[Attachment] = []
    for part in msg.iter_attachments():
        payload = part.get_payload(decode=True)
        if not isinstance(payload, bytes):
            continue
        atts.append(
            Attachment(
                part.get_filename() or "attachment",
                part.get_content_type(),
                payload,
            )
        )
    return Mail(
        message_id=mid,
        in_reply_to=(_MSG_ID.findall(str(msg.get("In-Reply-To", ""))) or [""])[0],
        references=_MSG_ID.findall(str(msg.get("References", ""))),
        subject=str(msg.get("Subject", "")).strip(),
        date=str(msg.get("Date", "")),
        sender=sender,
        recipients=addrs("To") + addrs("Cc"),
        body=_body(msg),
        attachments=atts,
        raw_sha256=hashlib.sha256(raw).hexdigest(),
    )


def _date_key(m: Mail) -> float:
    try:
        return parsedate_to_datetime(m.date).timestamp()
    except (TypeError, ValueError):
        return 0.0


def _thread(mails: list[Mail]) -> None:
    """Group by Message-ID / In-Reply-To / References (union-find: two messages
    that name any id in common are one thread). The thread id hashes the
    earliest message's id, so adding later replies never renames a thread."""
    parent = list(range(len(mails)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    owner: dict[str, int] = {}
    for i, m in enumerate(mails):
        for mid in [m.message_id, m.in_reply_to, *m.references]:
            if not mid:
                continue
            if mid in owner:
                parent[find(i)] = find(owner[mid])
            else:
                owner[mid] = i
    groups: dict[int, list[int]] = {}
    for i in range(len(mails)):
        groups.setdefault(find(i), []).append(i)
    for members in groups.values():
        first = min(members, key=lambda i: (_date_key(mails[i]), mails[i].message_id))
        tid = _h(mails[first].message_id or mails[first].raw_sha256, 8)
        for i in members:
            mails[i].thread = tid


def read_mails(path: Path) -> list[Mail]:
    """Every message in an .mbox, or the one message in an .eml."""
    raws: list[bytes] = []
    if path.suffix.lower() == ".mbox":
        box = mailbox.mbox(str(path))
        try:
            raws = [box.get_bytes(k) for k in box.iterkeys()]
        finally:
            box.close()
    else:
        raws = [path.read_bytes()]
    mails = [
        _parse(email.message_from_bytes(r, policy=policy.default), r)  # type: ignore[arg-type]
        for r in raws
    ]
    _thread(mails)
    seen: set[str] = set()
    for m in mails:
        key = _h(m.message_id or m.raw_sha256)
        while key in seen:  # same Message-ID twice in one export
            key = _h(key + m.raw_sha256)
        seen.add(key)
        m.key = key
    return mails


def render_text(path: Path) -> str:
    """What the catalog indexes for a mailbox: each message as headers that
    mean something plus its decoded body. No MIME headers, no encoded
    attachments (those are their own items)."""
    out: list[str] = []
    for m in read_mails(path):
        who = m.sender[0] or m.sender[1]
        to = ", ".join(n or a for n, a in m.recipients)
        head = [f"From: {who}", f"To: {to}", f"Date: {m.date}", f"Subject: {m.subject}"]
        out.append("\n".join(head) + "\n\n" + m.body)
    return "\n\n".join(out)


@dataclass
class MailItems:
    messages: int = 0
    attachments: int = 0
    threads: set[str] = field(default_factory=set)
    refused: int = 0


def _safe(name: str) -> str:
    return re.sub(r"[^\w.\- ]", "_", name)[:80] or "attachment"


# Where an earlier message starts inside a reply. Everything from here on is
# someone else's words: an Outlook "Original Message" rule, or the underscore
# rule Outlook puts above a From:/Sent: block.
_FORWARD_TAIL = re.compile(
    r"^\s*(-{3,}\s*Original Message\s*-{3,}|_{10,}\s*\n\s*From:)",
    re.IGNORECASE | re.MULTILINE,
)
# "On <date>, <name> wrote:", which clients wrap over up to three lines.
_ATTRIBUTION = re.compile(r"^On\b.{0,300}?\bwrote:\s*$", re.DOTALL)


def own_words(body: str) -> str:
    """The sender's own words: quoted '>' lines, the "On ... wrote:" line that
    introduces them, and an Outlook-style quoted tail are left out (D1c).

    A quote is someone else's words. Under the sender's consent it is not
    citable; the quoted person's words are citable only through their own
    message, under their own consent."""
    m = _FORWARD_TAIL.search(body)
    if m:
        body = body[: m.start()]
    lines = body.splitlines()
    keep = [not ln.lstrip().startswith(">") for ln in lines]
    # Drop the attribution: up to three non-quoted lines ending "wrote:",
    # just above a quoted line (blank lines between allowed).
    for i, ln in enumerate(lines):
        if not ln.rstrip().endswith("wrote:"):
            continue
        for start in range(i, max(-1, i - 3), -1):
            if _ATTRIBUTION.match("\n".join(x.strip() for x in lines[start : i + 1])):
                for j in range(start, i + 1):
                    keep[j] = False
                break
    out = "\n".join(ln for ln, k in zip(lines, keep, strict=True) if k)
    return re.sub(r"\n{3,}", "\n\n", out).strip()


def _message_text(m: Mail) -> str:
    """What one message is indexed and cited by: meaningful headers and the
    sender's own words (`own_words`), never text quoted from other people."""
    who = m.sender[0] or m.sender[1]
    to = ", ".join(n or a for n, a in m.recipients)
    head = [f"From: {who}", f"To: {to}", f"Date: {m.date}", f"Subject: {m.subject}"]
    return "\n".join(head) + "\n\n" + own_words(m.body)


def _index_message(conn, rel_path: str, abs_path: Path, m: Mail) -> None:
    """A catalog row and chunks for one message, so retrieval can cite it by
    its own path (and consent can be decided per message). `abs_path` is the
    mailbox's, so the scan's prune keeps the row while the mailbox exists."""
    import time

    from services.catalog.chunk import rechunk_file

    text = _message_text(m)
    row = conn.execute(
        "SELECT id FROM files WHERE rel_path = ?", (rel_path,)
    ).fetchone()
    now = time.time()
    with conn:
        if row:
            conn.execute(
                "UPDATE files SET extracted_text = ?, summary = ?, sha256 = ? WHERE id = ?",
                (text, m.subject, m.raw_sha256, row[0]),
            )
            fid = row[0]
        else:
            fid = conn.execute(
                "INSERT INTO files (rel_path, mount, abs_path, sha256, size_bytes, mtime, "
                "ext, extracted_text, summary, topics, cataloged_at, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    rel_path,
                    "library",
                    str(abs_path),
                    m.raw_sha256,
                    len(text),
                    now,
                    ".eml",
                    text,
                    m.subject,
                    "[]",
                    now,
                    now,
                ),
            ).lastrowid
    rechunk_file(conn, fid, text, ".eml")


def register_mail(
    conn, rel_path: str, abs_path: Path, *, by: str = "intake"
) -> MailItems:
    """One item per message and one per attachment. New rows are private unless
    the sender has recorded consent (`correspondents`), in which case they start
    at that level; existing rows keep theirs (see `register_virtual`)."""
    from services.archive.correspondents import consent_for
    from services.archive.items import register_virtual

    stats = MailItems()
    for m in read_mails(abs_path):
        base = f"{rel_path}#{m.thread}/{m.key}"
        people = [
            {"name": n or a, "address": a, "role": "author", "sender": True}
            for n, a in [m.sender]
            if a
        ] + [
            {"name": n or a, "address": a, "role": "correspondent"}
            for n, a in m.recipients
            if a
        ]
        level = (consent_for(conn, m.sender[1]) if m.sender[1] else None) or "private"
        r = register_virtual(
            conn,
            base,
            m.raw_sha256,
            "email",
            people=people,
            consent=level,
            by=by,
        )
        if r is None:
            stats.refused += 1
            continue
        _index_message(conn, base, abs_path, m)
        stats.messages += 1
        stats.threads.add(m.thread)
        for n, att in enumerate(m.attachments, 1):
            a = register_virtual(
                conn,
                f"{base}/{n}-{_safe(att.filename)}",
                hashlib.sha256(att.payload).hexdigest(),
                "attachment",
                people=people,
                consent=level,
                by=by,
            )
            if a is None:
                stats.refused += 1
            else:
                stats.attachments += 1
    return stats
