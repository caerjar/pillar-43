#!/usr/bin/env python3
"""Rebuild fixtures/synthetic-press/ deterministically.

Everything here is invented: the press (Lantern Wharf Editions), people, titles,
dates, places and text. No real press, author or published text.

Standard library only (hand-written PDF, DOCX and SVG writers). Audio uses
macOS `say` + `afconvert`; if they are missing the recordings are skipped.

    python3 fixtures/make_synthetic_press.py            # writes next to this file
    python3 fixtures/make_synthetic_press.py OUT_DIR
"""

import csv
import datetime as dt
import email.utils
import json
import random
import shutil
import subprocess
import sys
import tempfile
import textwrap
import wave
import zipfile
from email.message import EmailMessage
from pathlib import Path
from xml.sax.saxutils import escape as xesc

SEED = 20261117
random.seed(SEED)
HERE = Path(__file__).resolve().parent
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "synthetic-press"
# Answer keys (expected clause text, what the recordings say) are not archive
# items: intake would take them in and the model could read what it is scored
# against. They go beside the questions, never under OUT.
KEYS = HERE / "press-eval" / "answer-keys"

PRESS = "Lantern Wharf Editions"
PRESS_ADDR = "3 Tallow Steps, Port Alder"


# ---------------------------------------------------------------- helpers
def isbn13(body12: str) -> str:
    s = sum(int(c) * (1 if i % 2 == 0 else 3) for i, c in enumerate(body12))
    return body12 + str((10 - s % 10) % 10)


def fmt_isbn(i: str) -> str:
    return f"{i[:3]}-{i[3]}-{i[4:8]}-{i[8:12]}-{i[12]}"


def w(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, bytes):
        path.write_bytes(data)
    else:
        path.write_text(data, encoding="utf-8")


def long_date(iso: str) -> str:
    d = dt.date.fromisoformat(iso)
    return f"{d.day} {d.strftime('%B %Y')}"


# ---------------------------------------------------------------- PDF writer
class Pdf:
    def __init__(self):
        self.pages = [[]]
        self.y = 720

    def line(self, text, size=10.5, bold=False, x=72, lead=None):
        lead = lead or size * 1.4
        if self.y < 80:
            self.pages.append([])
            self.y = 720
        assert text.isascii(), text
        self.pages[-1].append((bold, size, x, self.y, text))
        self.y -= lead

    def keep(self, text, indent=0, size=10.5, extra=2):
        """Start a new page unless heading + this paragraph fit on the current one."""
        cols = int((468 - indent) / (size * 0.52))
        n = (
            sum(
                len(
                    textwrap.wrap(
                        line, cols, break_long_words=False, break_on_hyphens=False
                    )
                    or [""]
                )
                for line in text.split("\n")
            )
            + extra
        )
        if self.y - n * size * 1.4 < 80:
            self.pages.append([])
            self.y = 720

    def para(self, text, size=10.5, bold=False, indent=0, after=6):
        cols = int((468 - indent) / (size * 0.52))
        for ln in text.split("\n"):
            for part in textwrap.wrap(
                ln, cols, break_long_words=False, break_on_hyphens=False
            ) or [""]:
                self.line(part, size, bold, 72 + indent)
        self.y -= after

    def save(self, path: Path, title: str):
        def esc(s):
            return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

        n = len(self.pages)
        objs = [None] * (5 + 2 * n)
        objs[0] = b"<< /Type /Catalog /Pages 2 0 R >>"
        kids = " ".join(f"{6 + 2 * i} 0 R" for i in range(n))
        objs[1] = f"<< /Type /Pages /Kids [{kids}] /Count {n} >>".encode()
        objs[2] = (
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"
        )
        objs[3] = (
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>"
        )
        objs[4] = (
            f"<< /Title ({esc(title)}) /Producer (synthetic-press generator) "
            f"/CreationDate (D:20261117090000Z) >>"
        ).encode()
        for i, items in enumerate(self.pages):
            ops = []
            for bold, size, x, y, t in items:
                ops.append(
                    f"BT /{'F2' if bold else 'F1'} {size} Tf {x} {y:.1f} Td ({esc(t)}) Tj ET"
                )
            ops.append(
                f"BT /F1 8 Tf 72 40 Td ({esc(PRESS)} - {esc(title)} - page {i + 1} of {n}) Tj ET"
            )
            stream = "\n".join(ops).encode("latin-1")
            objs[5 + 2 * i] = (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                f"/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> "
                f"/Contents {7 + 2 * i} 0 R >>"
            ).encode()
            objs[6 + 2 * i] = (
                b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream"
            )
        out = bytearray(b"%PDF-1.4\n")
        offs = []
        for i, o in enumerate(objs):
            offs.append(len(out))
            out += f"{i + 1} 0 obj\n".encode() + o + b"\nendobj\n"
        xr = len(out)
        out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
        for o in offs:
            out += f"{o:010d} 00000 n \n".encode()
        out += (
            f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R /Info 5 0 R >>\n"
            f"startxref\n{xr}\n%%EOF\n"
        ).encode()
        w(path, bytes(out))


def text_pdf(path: Path, title: str, text: str):
    p = Pdf()
    p.para(PRESS.upper(), 9, True, after=0)
    p.para(PRESS_ADDR, 9, after=14)
    for block in text.strip().split("\n\n"):
        p.para(block)
    p.save(path, title)


# ---------------------------------------------------------------- DOCX writer
W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


class Docx:
    """Segments: ("t",txt) ("i",txt,author,date) ("d",txt,author,date) ("c",cid,txt)."""

    def __init__(self):
        self.body = []
        self.comments = []
        self.rid = 100

    def comment(self, author, date, text):
        cid = len(self.comments)
        self.comments.append((cid, author, date, text))
        return cid

    def _run(self, t, bold=False, size=None, deleted=False):
        rpr = ""
        if bold or size:
            rpr = (
                "<w:rPr>"
                + ("<w:b/>" if bold else "")
                + (f'<w:sz w:val="{size}"/>' if size else "")
                + "</w:rPr>"
            )
        tag = "w:delText" if deleted else "w:t"
        return f'<w:r>{rpr}<{tag} xml:space="preserve">{xesc(t)}</{tag}></w:r>'

    def para(self, segs, bold=False, size=None):
        if isinstance(segs, str):
            segs = [("t", segs)]
        x = []
        for s in segs:
            k = s[0]
            if k == "t":
                x.append(self._run(s[1], bold, size))
            elif k in ("i", "d"):
                self.rid += 1
                tag = "w:ins" if k == "i" else "w:del"
                x.append(
                    f'<{tag} w:id="{self.rid}" w:author="{xesc(s[2])}" w:date="{s[3]}T10:00:00Z">'
                    f"{self._run(s[1], bold, size, deleted=(k == 'd'))}</{tag}>"
                )
            elif k == "c":
                cid = s[1]
                x.append(
                    f'<w:commentRangeStart w:id="{cid}"/>{self._run(s[2], bold, size)}'
                    f'<w:commentRangeEnd w:id="{cid}"/><w:r><w:commentReference w:id="{cid}"/></w:r>'
                )
        self.body.append("<w:p>" + "".join(x) + "</w:p>")

    def save(self, path: Path):
        doc = (
            f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<w:document xmlns:w="{W_NS}"><w:body>{"".join(self.body)}</w:body></w:document>'
        )
        parts = {
            "[Content_Types].xml": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            + (
                '<Override PartName="/word/comments.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml"/>'
                if self.comments
                else ""
            )
            + "</Types>",
            "_rels/.rels": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
            "</Relationships>",
            "word/_rels/document.xml.rels": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            + (
                '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments" Target="comments.xml"/>'
                if self.comments
                else ""
            )
            + "</Relationships>",
            "word/document.xml": doc,
        }
        if self.comments:
            cs = "".join(
                f'<w:comment w:id="{cid}" w:author="{xesc(a)}" w:date="{d}T11:00:00Z" w:initials="{"".join(p[0] for p in a.split())}">'
                f'<w:p><w:r><w:t xml:space="preserve">{xesc(t)}</w:t></w:r></w:p></w:comment>'
                for cid, a, d, t in self.comments
            )
            parts["word/comments.xml"] = (
                f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                f'<w:comments xmlns:w="{W_NS}">{cs}</w:comments>'
            )
        path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(path, "w") as z:
            for name, data in parts.items():
                zi = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
                zi.compress_type = zipfile.ZIP_DEFLATED
                z.writestr(zi, data.encode("utf-8"))


# ---------------------------------------------------------------- people
P = {
    "marguerite": ("Marguerite Oyelaran-Voss", "marguerite@lanternwharf.example"),
    "tobias": ("Tobias Hallenbeck", "tobias@lanternwharf.example"),
    "ines": ("Ines Quillfeather", "ines@lanternwharf.example"),
    "dariusz": ("Dariusz Wenlock", "dariusz@wenlock-design.example"),
    "halvard": ("Halvard Peake", "halvard@peake-chambers.example"),
    "ottoline": ("Ottoline Marsh", "ottoline@marsh-accounts.example"),
    "lucia": ("Lucia Vasconcelo-Reis", "lucia@vasconcelo-reis-estate.example"),
    "wren": ("Wren Tallowfield", "wren@tallowfield.example"),
    "saskia": ("Saskia Dunmore", "saskia@dunmore.example"),
    "ilse": ("Ilse Brandvold", "ilse@brandvold.example"),
    "beatrix": ("Beatrix Calloway-Ng", "beatrix@fenwickdray.example"),
    "cassia": ("Cassia Merrowby", "cassia@merrowby.example"),
    "maud": ("Maud Ferriday", "maud@ferriday.example"),
    "jonas": ("Jonas Pellerin-Okafor", "jonas@pellerin-okafor.example"),
    "ruth": ("Ruth Ashdown-Pike", "grants@harrowcoast-arts.example"),
    "nell": ("Nell Cartwright-Boyd", "metadata@bramblegate-dist.example"),
    "ewan": ("Ewan Ricketts", "proofs@corvane-print.example"),
    "priya": ("Priya Dacosta", "bookings@tallowroom.example"),
    "gunnhild": ("Gunnhild Aasebo", "rights@nordlys-agency.example"),
}


def who(k):
    return f"{P[k][0]} <{P[k][1]}>"


# ---------------------------------------------------------------- catalog
# key, title, contributors, lang, pub, format, status, price, body11 index
TITLES = [
    (
        "salt",
        "The Salt Ledger",
        "Cassia Merrowby",
        "English",
        "2013-04-09",
        "paperback",
        "in print",
        "15.00",
    ),
    (
        "ferry",
        "Weather for Ferrymen",
        "Jonas Pellerin-Okafor",
        "English",
        "2017-03-21",
        "paperback",
        "in print",
        "16.00",
    ),
    (
        "field",
        "A Field Guide to Closing Time",
        "Maud Ferriday",
        "English",
        "2020-09-15",
        "paperback",
        "in print",
        "17.00",
    ),
    (
        "orchard",
        "The Drowned Orchard",
        "Teodoro Vasconcelo-Reis; Wren Tallowfield",
        "Portuguese",
        "2015-05-12",
        "paperback",
        "out of print",
        "16.00",
    ),
    (
        "lanterns",
        "Lanterns for the Second Winter",
        "Zofia Kaminrowska; Saskia Dunmore",
        "Polish",
        "2020-11-03",
        "paperback",
        "in print",
        "17.00",
    ),
    (
        "harbour",
        "The Harbour Does Not Answer",
        "Eirik Solvang-Hald; Ilse Brandvold",
        "Norwegian",
        "2022-03-08",
        "hardcover",
        "in print",
        "24.00",
    ),
    (
        "tides",
        "Ninety Tides",
        "Cassia Merrowby",
        "English",
        "2021-06-01",
        "paperback",
        "in print",
        "16.00",
    ),
    (
        "keeper",
        "Letters to the Lighthouse Keeper's Daughter",
        "Maud Ferriday",
        "English",
        "2023-10-17",
        "paperback",
        "in print",
        "17.00",
    ),
    (
        "mercies",
        "Almanac of Small Mercies",
        "Jonas Pellerin-Okafor",
        "English",
        "2019-04-23",
        "paperback",
        "in print",
        "15.00",
    ),
    (
        "choir",
        "The Copper Choir",
        "Zofia Kaminrowska; Saskia Dunmore",
        "Polish",
        "2023-05-09",
        "paperback",
        "in print",
        "17.00",
    ),
    (
        "pilots",
        "Winter Pilots",
        "Eirik Solvang-Hald; Ilse Brandvold",
        "Norwegian",
        "2024-11-12",
        "paperback",
        "in print",
        "18.00",
    ),
    (
        "anthology",
        "Wharf Anthology 2019: New Voices",
        "Various; Ines Quillfeather (editor)",
        "English",
        "2019-11-05",
        "paperback",
        "out of print",
        "14.00",
    ),
]
BOOK = {}
for n, t in enumerate(TITLES):
    BOOK[t[0]] = dict(
        zip(
            ("key", "title", "contrib", "lang", "pub", "format", "status", "price"),
            t,
            strict=True,
        ),
        isbn=isbn13("979890" + f"{10000 + n * 137:06d}"),
    )

# ---------------------------------------------------------------- contracts
OOP_DEF = (
    "The Work is out of print when no edition of it is available for sale through ordinary trade "
    "channels. A print-on-demand edition listed with the Publisher's distributor counts as available."
)


def reversion_text(n_words, n, clause_grant):
    return (
        f"If the Work is out of print in all formats granted in Clause {clause_grant}, the Grantor may request in "
        f"writing that the rights revert. If, within {n_words} ({n}) months after the Publisher's receipt of that "
        f"written request, the Publisher has not made the Work available again in at least one format granted in "
        f"Clause {clause_grant}, all rights granted under this Agreement revert to the Grantor automatically and "
        f"without further notice. {OOP_DEF}"
    )


NUM_WORDS = {6: "six", 9: "nine", 12: "twelve"}

CONTRACTS = [
    dict(
        id="LWE-A-2012-01",
        kind="author",
        book="salt",
        file="contract_merrowby_SaltLedger_2012.pdf",
        grantor="Cassia Merrowby",
        grantor_role="the Author",
        signed="2012-09-14",
        territory="the world",
        formats="paperback and ebook",
        term="for the full term of copyright",
        months=6,
        royalty="10 percent of net receipts on paperback sales and 25 percent of net receipts on ebook sales",
        sub="Serial, anthology and audio rights are held by the Publisher, with proceeds divided equally between the Author and the Publisher.",
        witness="Tobias Hallenbeck",
        signer_press="Marguerite Oyelaran-Voss",
    ),
    dict(
        id="LWE-A-2016-02",
        kind="author",
        book="ferry",
        file="Pellerin-Okafor Weather for Ferrymen CONTRACT signed.pdf",
        grantor="Jonas Pellerin-Okafor",
        grantor_role="the Author",
        signed="2016-05-03",
        territory="the United States, its territories and Canada",
        formats="paperback",
        term="for seven years from first publication, renewing automatically for successive periods of three years unless either party gives written notice of termination",
        months=12,
        royalty="8 percent of net receipts on all sales",
        sub="Anthology and audio rights are held by the Publisher, with proceeds divided equally between the Author and the Publisher.",
        witness="Ines Quillfeather",
        signer_press="Marguerite Oyelaran-Voss",
    ),
    dict(
        id="LWE-A-2019-03",
        kind="author",
        book="field",
        file="ferriday_fieldguide_agreement_2019-10-21.pdf",
        grantor="Maud Ferriday",
        grantor_role="the Author",
        signed="2019-10-21",
        territory="the world excluding the member states of the European Union",
        formats="paperback, hardcover and ebook",
        term="for ten years from the date of signature",
        months=9,
        royalty="10 percent of net receipts on all sales",
        sub="Audio and anthology rights are held by the Author. The Publisher holds first refusal on stage and broadcast adaptation for sixty days.",
        witness="Tobias Hallenbeck",
        signer_press="Marguerite Oyelaran-Voss",
    ),
    dict(
        id="LWE-T-2014-01",
        kind="translation",
        book="orchard",
        file="t_2014_vasconcelo-reis_orchard_RIGHTS+TRANSLATOR.pdf",
        grantor="Estate of Teodoro Vasconcelo-Reis, represented by Lucia Vasconcelo-Reis, executor",
        grantor_role="the Rights Holder",
        signed="2014-06-09",
        translator="Wren Tallowfield",
        orig_lang="Portuguese",
        territory="the United States, Canada, the United Kingdom, Ireland, Australia and New Zealand",
        formats="paperback and ebook",
        term="for ten years from first publication, renewable by written agreement",
        months=9,
        royalty="7 percent of net receipts on all sales, paid to the Rights Holder, with 2 percent of net receipts paid to the Translator",
        sub="Anthology and serial rights in the English translation are held by the Publisher, with proceeds divided equally between the Rights Holder and the Translator.",
        fee="USD 1,800",
        witness="Ines Quillfeather",
        signer_press="Marguerite Oyelaran-Voss",
    ),
    dict(
        id="LWE-T-2020-01",
        kind="translation",
        book="lanterns",
        file="Kaminrowska_Lanterns_translation-contract_signed-2020-02-17.pdf",
        grantor="Zofia Kaminrowska",
        grantor_role="the Rights Holder",
        signed="2020-02-17",
        translator="Saskia Dunmore",
        orig_lang="Polish",
        territory="the United States and its territories",
        formats="paperback",
        term="for eight years from first publication",
        months=6,
        royalty="8 percent of net receipts on all sales, paid to the Rights Holder, with 2 percent of net receipts paid to the Translator",
        sub="Serial rights are held by the Rights Holder. Anthology rights in the English translation are held by the Publisher, with proceeds divided equally.",
        fee="USD 2,400",
        witness="Tobias Hallenbeck",
        signer_press="Marguerite Oyelaran-Voss",
    ),
    dict(
        id="LWE-T-2021-01",
        kind="translation",
        book="harbour",
        file="solvang-hald harbour 2021 contract (nordlys).pdf",
        grantor="Nordlys Literary Agency, for Eirik Solvang-Hald",
        grantor_role="the Rights Holder",
        signed="2021-11-30",
        translator="Ilse Brandvold",
        orig_lang="Norwegian",
        territory="the United States, its territories and Canada",
        formats="hardcover, paperback and ebook",
        term="for the full term of copyright in the translation",
        months=12,
        royalty="9 percent of net receipts on all sales, paid to the Rights Holder, with 2 percent of net receipts paid to the Translator",
        sub="Anthology and audio rights in the English translation are held by the Publisher, with proceeds divided equally between the Rights Holder and the Translator.",
        fee="USD 3,000",
        witness="Ines Quillfeather",
        signer_press="Marguerite Oyelaran-Voss",
    ),
]


def contract_sections(c):
    b = BOOK[c["book"]]
    isbn = fmt_isbn(b["isbn"])
    tr = c["kind"] == "translation"
    grantor, role = c["grantor"], c["grantor_role"]
    parties = (
        f'This Agreement No. {c["id"]} is made on {long_date(c["signed"])} between {grantor} ("the Grantor", '
        f'also called {role}) and {PRESS} of {PRESS_ADDR} ("the Publisher"), concerning the work titled '
        f'"{b["title"]}" (ISBN {isbn}) ("the Work")'
    )
    if tr:
        parties += (
            f", being an English-language translation from the {c['orig_lang']} by {c['translator']} "
            f'("the Translator")'
        )
    parties += "."
    grant = (
        f"The Grantor grants to the Publisher the exclusive right to publish the Work in the English language, in "
        f"the following territory: {c['territory']}, in the following formats: {c['formats']}."
    )
    term = f"This grant of rights continues {c['term']}."
    royalty = f"The Publisher shall pay the Grantor royalties of {c['royalty']}. Royalties are accounted for twice a year."
    sub = c["sub"]
    n = c["months"]
    gclause = 2
    if tr:
        engage = (
            f"The Publisher engages the Translator to prepare the English translation and shall pay the Translator a "
            f"fee of {c['fee']}, half on signature and half on delivery and acceptance of the manuscript. "
            f"The Translator signs this Agreement to confirm the engagement and to confirm that the translation "
            f"is the Translator's own work."
        )
    rev = reversion_text(NUM_WORDS[n], n, gclause)
    if tr:
        perm = (
            "The Publisher may grant permission to reprint single poems or extracts of up to fifty lines from the Work in "
            "anthologies, only with the prior written consent of the Rights Holder and the Translator. Permission fees "
            "are divided equally between the Rights Holder and the Translator."
        )
    else:
        perm = (
            "The Publisher may grant permission to reprint single poems or extracts of up to fifty lines from the Work in "
            "anthologies, only with the prior written consent of the Author. Permission fees are divided equally "
            "between the Author and the Publisher."
        )
    warr = (
        "The Grantor warrants that the Grantor holds the rights granted and that the Work does not infringe any "
        "third-party right. The Publisher shall credit the Grantor on every edition of the Work."
    )
    law = "This Agreement is governed by the law of the Republic of Harrowmere, an invented jurisdiction used for this fixture."
    secs = [
        ("parties", "Parties and Work", parties),
        ("grant", "Grant of Rights", grant),
        ("term", "Term", term),
        ("royalties", "Royalties", royalty),
        ("subsidiary", "Subsidiary Rights", sub),
    ]
    if tr:
        secs.append(("engagement", "Translator's Engagement", engage))
    secs += [
        ("reversion", "Reversion", rev),
        ("permissions", "Permissions", perm),
        ("warranties", "Warranties and Credit", warr),
        ("law", "Governing Law", law),
    ]
    return secs


def make_contracts():
    truth = {
        "_note": "Compare clause text after collapsing all whitespace; the PDFs wrap lines. "
        "reversion_trigger is the event, reversion_notice_months the cure period after written request.",
        "contracts": [],
    }
    for c in CONTRACTS:
        b = BOOK[c["book"]]
        secs = contract_sections(c)
        p = Pdf()
        p.para(PRESS.upper(), 9, True, after=0)
        p.para(PRESS_ADDR, 9, after=10)
        kind = (
            "TRANSLATION RIGHTS AND ENGAGEMENT AGREEMENT"
            if c["kind"] == "translation"
            else "AUTHOR AGREEMENT"
        )
        p.para(kind, 14, True, after=2)
        p.para(f"Agreement No. {c['id']}", 10, after=12)
        clauses = {}
        for i, (key, head, body) in enumerate(secs, 1):
            p.keep(body, 14)
            p.para(f"{i}. {head}", 11, True, after=2)
            p.para(body, indent=14, after=8)
            clauses[key] = {"clause_number": i, "heading": head, "text": body}
        n = len(secs) + 1
        p.para(f"{n}. Signatures", 11, True, after=2)
        p.para(f"Signed on {long_date(c['signed'])}.", indent=14, after=6)
        gname = c["grantor"]
        sign_as = {
            "Nordlys Literary Agency, for Eirik Solvang-Hald": "Gunnhild Aasebo for Nordlys Literary Agency",
            "Estate of Teodoro Vasconcelo-Reis, represented by Lucia Vasconcelo-Reis, executor": "Lucia Vasconcelo-Reis, executor",
        }.get(gname, gname)
        p.para(f"For the Grantor: {gname}", indent=14, after=1)
        p.para(f"Signature: /s/ {sign_as}", indent=14, after=6)
        if c["kind"] == "translation":
            p.para(
                f"For the Translator: {c['translator']}    Signature: /s/ {c['translator']}",
                indent=14,
                after=6,
            )
        p.para(
            f"For the Publisher: {c['signer_press']}, Publisher    Signature: /s/ {c['signer_press']}",
            indent=14,
            after=6,
        )
        p.para(f"Witness: {c['witness']}", indent=14, after=6)
        p.save(OUT / "contracts" / c["file"], f"Agreement {c['id']}")
        grantee = PRESS
        truth["contracts"].append(
            {
                "file": c["file"],
                "agreement_no": c["id"],
                "kind": c["kind"],
                "isbn": b["isbn"],
                "title": b["title"],
                "language": "English",
                "language_original": c.get("orig_lang", "English"),
                "territory": c["territory"],
                "formats": [
                    f.strip() for f in c["formats"].replace(" and ", ", ").split(",")
                ],
                "term": c["term"],
                "reversion_trigger": "out of print after written request and cure period",
                "reversion_notice_months": c["months"],
                "grantor": c["grantor"],
                "grantee": grantee,
                "translator": c.get("translator"),
                "signed_on": c["signed"],
                "clauses": clauses,
            }
        )
    w(
        KEYS / "contracts_truth.json",
        json.dumps(truth, indent=2, ensure_ascii=False) + "\n",
    )


# ---------------------------------------------------------------- catalog
def make_catalog():
    p = OUT / "catalog" / "catalog.csv"
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", newline="", encoding="utf-8") as f:
        cw = csv.writer(f)
        cw.writerow(
            [
                "isbn13",
                "title",
                "contributors",
                "language_original",
                "pub_date",
                "format",
                "status",
                "price_usd",
            ]
        )
        for t in TITLES:
            b = BOOK[t[0]]
            cw.writerow(
                [
                    b["isbn"],
                    b["title"],
                    b["contrib"],
                    b["lang"],
                    b["pub"],
                    b["format"],
                    b["status"],
                    b["price"],
                ]
            )


# ---------------------------------------------------------------- poems (all invented)
POEM_QUAY = [
    "The tide has gone to bargain somewhere else.",
    "The boats lean on their elbows in the mud.",
    "A gull inspects the rope like an auditor.",
    "Nobody here is waiting. We are all",
    "waiting. The bell on the pontoon",
    "counts nothing, and counts it carefully.",
]
POEM_CHANDLERY = [
    "They sold us rope, and then the knots to go with it.",
    "They sold us lamps, and then the dark to hang them in.",
    "Close the ledger gently, Mr. Pryce.",
    "The harbour kept its tide of small lamps.",
]
POEM_ORCHARD = [
    "The water left in March, as water does,",
    "taking the fences and a child's red boot.",
    "What stayed: the pear trees, standing to their knees",
    "in silt the colour of a closed eye.",
    "My father counted branches. Counted them again.",
    "Nothing had changed except the number.",
]
POEM_GRAFT = [
    "Cut here, the old man said, and not before the frost.",
    "A knife, a strip of cloth, a patience",
    "that looks from outside like doing nothing.",
    "In spring the foreign branch will wake",
    "and speak the language of the root.",
]
POEM_SLACK = [
    "Between the flood and the ebb there is a minute",
    "when the river forgets which way it is going.",
    "The ferryman lets the oars rest.",
    "Everything we owe is held, for that minute,",
    "at its exact weight.",
]
POEM_TIMETABLE = [
    "Winter service: the six o'clock does not run.",
    "Someone has chalked an apology on the slip.",
    "We read it as we read weather,",
    "and walk home the long way, by the bridge.",
]
POEM_GLASS = [
    "He breathes a window into being,",
    "then counts the windows he has not made.",
    "The sum is always more than the house.",
    "Arithmetic is a kind of mercy",
    "when you stop at the correct number.",
]
POEM_INVENTORY = [
    "Three windows facing east, one facing a wall.",
    "A frame without its glass. A glass without its frame.",
    "The light is not on the list.",
    "It comes in anyway, unpriced.",
]


def make_manuscripts():
    M = OUT / "manuscripts"
    # 1: Drowned Orchard reissue revisions
    d = Docx()
    c0 = d.comment(
        "Tobias Hallenbeck",
        "2026-06-02",
        "Check the Portuguese: does the original repeat the verb for counting, or is the repetition ours?",
    )
    c1 = d.comment(
        "Wren Tallowfield",
        "2026-06-04",
        "Original repeats it. I keep the repetition. Sentence rhythm is the poem.",
    )
    c2 = d.comment(
        "Ines Quillfeather",
        "2026-06-09",
        "Lucia asked that 'closed eye' stay in the reissue. Please confirm it matches the 2015 text.",
    )
    d.para("The Drowned Orchard: reissue revisions", True, 32)
    d.para(
        "Poems by Teodoro Vasconcelo-Reis, translated by Wren Tallowfield. Working copy for the reissue, June 2026."
    )
    d.para("The Orchard After the Flood", True)
    d.para([("t", "The water left in March, as water does,")])
    d.para(
        [
            ("d", "taking", "Tobias Hallenbeck", "2026-06-02"),
            ("i", "carrying off", "Tobias Hallenbeck", "2026-06-02"),
            ("t", " the fences and a "),
            ("i", "single ", "Wren Tallowfield", "2026-06-04"),
            ("t", "child's red boot."),
        ]
    )
    d.para("What stayed: the pear trees, standing to their knees")
    d.para([("t", "in silt the colour of a "), ("c", c2, "closed eye"), ("t", ".")])
    d.para(
        [
            ("c", c0, "My father counted branches."),
            ("t", " "),
            ("c", c1, "Counted them again."),
        ]
    )
    d.para("Nothing had changed except the number.")
    d.para("Grafting", True)
    for ln in POEM_GRAFT[:3]:
        d.para(ln)
    d.para(
        [
            ("t", "In spring the foreign branch will "),
            ("d", "wake", "Wren Tallowfield", "2026-06-04"),
            ("i", "wake up", "Wren Tallowfield", "2026-06-04"),
            ("t", " and speak the language of the root."),
        ]
    )
    d.save(M / "drowned-orchard_reissue_revisions_tallowfield_2026-06.docx")
    # 2: Slack Water
    d = Docx()
    c0 = d.comment(
        "Ines Quillfeather",
        "2026-07-14",
        "The minute is the poem. Could the second stanza break earlier, before 'weight'?",
    )
    c1 = d.comment(
        "Cassia Merrowby", "2026-07-16", "I will try. Not sure about moving 'weight'."
    )
    d.para("Slack Water (draft 3)", True, 32)
    d.para("Poems by Cassia Merrowby. Forthcoming. Not yet in the catalog.")
    d.para("Slack Water", True)
    d.para(
        [
            ("t", "Between the flood and the ebb there is a "),
            ("c", c0, "minute"),
            ("t", ""),
        ]
    )
    d.para([("t", "when the river forgets which way it is going.")])
    d.para(
        [
            (
                "d",
                "The ferryman lets the oars rest.",
                "Ines Quillfeather",
                "2026-07-14",
            ),
            ("i", "The ferryman ships his oars.", "Cassia Merrowby", "2026-07-16"),
        ]
    )
    d.para([("t", "Everything we owe is held, for that minute,")])
    d.para([("c", c1, "at its exact weight.")])
    d.para("Ferry Timetable, Winter", True)
    for ln in POEM_TIMETABLE[:2]:
        d.para(ln)
    d.para(
        [
            ("t", "We read it as we read "),
            ("d", "weather", "Ines Quillfeather", "2026-07-14"),
            ("i", "tide tables", "Cassia Merrowby", "2026-07-16"),
            ("t", ","),
        ]
    )
    d.para("and walk home the long way, by the bridge.")
    d.save(M / "merrowby_slack-water_draft3.docx")
    # 3: Kaminrowska sample
    d = Docx()
    c0 = d.comment(
        "Saskia Dunmore",
        "2025-12-02",
        "Polish line 3 puns on 'suma' and 'sum'. I have kept 'sum' and lost the second sense. Flagging for the author.",
    )
    c1 = d.comment(
        "Ines Quillfeather",
        "2025-12-05",
        "Fine to lose the pun if the poem still lands. Ask Zofia what she prefers.",
    )
    d.para("The Glassblower's Arithmetic: sample translation", True, 32)
    d.para(
        "Poems by Zofia Kaminrowska, translated by Saskia Dunmore. Sample for the next book, December 2025."
    )
    d.para("The Glassblower's Arithmetic", True)
    d.para("He breathes a window into being,")
    d.para([("t", "then counts the windows he has not made.")])
    d.para([("t", "The "), ("c", c0, "sum"), ("t", " is always more than the house.")])
    d.para(
        [
            ("d", "Arithmetic is a kind of mercy", "Saskia Dunmore", "2025-12-02"),
            ("i", "Counting is a kind of mercy", "Ines Quillfeather", "2025-12-05"),
        ]
    )
    d.para([("c", c1, "when you stop at the correct number.")])
    d.para("Inventory of Windows", True)
    for ln in POEM_INVENTORY:
        d.para(ln)
    d.para(
        [
            ("t", "It comes in anyway, "),
            ("d", "unpriced", "Saskia Dunmore", "2025-12-02"),
            ("i", "without a price", "Saskia Dunmore", "2025-12-02"),
            ("t", "."),
        ]
    )
    d.save(M / "kaminrowska-dunmore_glassblower_sample_v2.docx")
    # 4: Ferriday errata
    d = Docx()
    c0 = d.comment(
        "Maud Ferriday",
        "2026-08-05",
        "Page 41, line 4 of the poem: the first printing says 'tied'. It must read 'tide'.",
    )
    c1 = d.comment(
        "Ewan Ricketts",
        "2026-08-12",
        "Corrected in the second printing file. New proof PDF follows.",
    )
    d.para("A Field Guide to Closing Time: second printing corrections", True, 32)
    d.para(f"ISBN {fmt_isbn(BOOK['field']['isbn'])}. Page 41 of the first printing.")
    d.para("Last Orders at the Chandlery", True)
    for ln in POEM_CHANDLERY[:3]:
        d.para(ln)
    d.para(
        [
            ("t", "The harbour kept its "),
            ("d", "tied", "Tobias Hallenbeck", "2026-08-11"),
            ("i", "tide", "Tobias Hallenbeck", "2026-08-11"),
            ("t", " of "),
            ("c", c0, "small lamps"),
            ("t", "."),
        ]
    )
    d.para([("c", c1, "Second printing: see errata sheet.")])
    d.save(M / "ferriday_closing-time_2nd-printing_errata-edits.docx")


# ---------------------------------------------------------------- board
def make_board():
    B = OUT / "board"
    d = Docx()
    d.para(f"{PRESS}: Board of Directors, minutes of 14 April 2026", True, 32)
    d.para(
        "Present: Halvard Peake (chair), Ottoline Marsh (treasurer), Marguerite Oyelaran-Voss (publisher). Apologies: none. In attendance: Tobias Hallenbeck (editor), recording. Place: the Tallow Room, Port Alder."
    )
    d.para("Item 1. Call to order and minutes of 3 February 2026", True)
    d.para(
        "1.1 The chair called the meeting to order at 18:05. 1.2 The minutes of 3 February 2026 were approved without change."
    )
    d.para("Item 2. Treasurer's report", True)
    d.para(
        "2.1 Ottoline Marsh reported a cash balance of USD 31,420 and no overdue printer invoices."
    )
    d.para("Item 3. Catalog status", True)
    d.para(
        "3.1 Twelve titles are in the catalog; two are out of print: The Drowned Orchard and Wharf Anthology 2019: New Voices."
    )
    d.para("Item 4. The Drowned Orchard: reversion request", True)
    d.para(
        f"4.1 The publisher reported that Lucia Vasconcelo-Reis, executor of the Estate of Teodoro Vasconcelo-Reis, sent a written reversion request dated 2 March 2026 under Clause 7 of Agreement LWE-T-2014-01 (ISBN {fmt_isbn(BOOK['orchard']['isbn'])}), received on 5 March 2026."
    )
    d.para(
        "4.2 Clause 7 gives the Publisher nine months from receipt to make the Work available again. The cure period therefore ends on 5 December 2026."
    )
    d.para(
        "Motion M-2026-04-03: To reissue The Drowned Orchard, paperback and ebook, in a new edition with a preface by the translator, to be available through the distributor no later than 30 November 2026, and so cure the out-of-print condition under Clause 7. Proposed: Halvard Peake. Seconded: Ottoline Marsh. Carried 3 to 0."
    )
    d.para(
        "4.3 The publisher will write to the Estate to seek consent to the new preface and cover. Action: Marguerite Oyelaran-Voss, by 30 April 2026."
    )
    d.para("Item 5. Grant application", True)
    d.para(
        "5.1 The Harrow Coast Arts Council translation series fund is open until 30 April 2026."
    )
    d.para(
        "Motion M-2026-04-04: To apply to the Harrow Coast Arts Council translation series fund for up to USD 18,000 to support the Dunmore and Brandvold translation work. Proposed: Marguerite Oyelaran-Voss. Seconded: Halvard Peake. Carried 3 to 0."
    )
    d.para("Item 6. Close", True)
    d.para("6.1 The meeting closed at 19:20. Next meeting: 22 September 2026.")
    d.save(B / "Minutes April 14 2026 (final).docx")

    md = f"""# {PRESS}: Board of Directors, minutes of 22 September 2026

Present: Halvard Peake (chair), Ottoline Marsh (treasurer), Marguerite Oyelaran-Voss (publisher).
In attendance: Tobias Hallenbeck (editor), Ines Quillfeather (editor), recording.
Place: the Tallow Room, Port Alder.

## Item 1. Call to order and minutes of 14 April 2026
1.1 The chair called the meeting to order at 18:00.
1.2 The minutes of 14 April 2026 were approved without change.

## Item 2. Treasurer's report
2.1 Ottoline Marsh reported a cash balance of USD 27,905 and the receipt of the first half of the grant described in Item 3.

## Item 3. Harrow Coast Arts Council grant
3.1 The Council awarded USD 18,000 under reference HCAC-T-2026-117, by letter of 30 June 2026. Half was paid on acceptance and half is payable after the interim report.
3.2 The interim report is due on 31 October 2026.

**Motion M-2026-09-02:** To accept the terms of grant HCAC-T-2026-117 and authorise the publisher to submit the interim report by 31 October 2026. Proposed: Ottoline Marsh. Seconded: Halvard Peake. Carried 3 to 0.

## Item 4. The Drowned Orchard reissue
4.1 The Estate consented to the new preface and cover in a letter of 4 May 2026. The cover (version 3) was approved on 19 May 2026.
4.2 The distributor listing is expected by 15 October 2026. The cure period under Clause 7 of Agreement LWE-T-2014-01 ends on 5 December 2026.
4.3 No new motion. Action: Tobias Hallenbeck to confirm the listing in writing and file the evidence.

## Item 5. Launch reading
5.1 The launch reading for the reissue is booked at the Tallow Room for 19 November 2026.

## Item 6. Close
6.1 The meeting closed at 19:10.
"""
    w(B / "minutes_2026-09-22.md", md)


# ---------------------------------------------------------------- letters
def make_letters():
    L = OUT / "correspondence" / "letters"
    ob = BOOK["orchard"]
    isbn_o = fmt_isbn(ob["isbn"])
    salt_isbn = fmt_isbn(BOOK["salt"]["isbn"])
    txt = {}
    txt["2026-03-02_vasconcelo-reis_reversion-request.txt"] = f"""Lucia Vasconcelo-Reis
Executor, Estate of Teodoro Vasconcelo-Reis
14 Corvid Lane, Meriden Sound

2 March 2026

Marguerite Oyelaran-Voss
{PRESS}
{PRESS_ADDR}

Re: THE DROWNED ORCHARD (ISBN {isbn_o}), Agreement No. LWE-T-2014-01 dated 9 June 2014

Dear Marguerite,

I write as executor of the Estate of Teodoro Vasconcelo-Reis. The title has been unavailable from every retailer I can find since January 2026.

Under Clause 7 (Reversion) of the Agreement, this letter is the Estate's written request that the rights granted to {PRESS} revert to the Estate. I understand that the Agreement allows the Publisher nine months from receipt of this request to make the Work available again in at least one format.

Please confirm in writing the date on which you receive this letter.

With regards,
Lucia Vasconcelo-Reis
"""
    txt["2026-03-09_reply_to_estate_receipt.txt"] = f"""{PRESS}
{PRESS_ADDR}

9 March 2026

Lucia Vasconcelo-Reis
14 Corvid Lane, Meriden Sound

Re: THE DROWNED ORCHARD (ISBN {isbn_o}), Agreement No. LWE-T-2014-01

Dear Lucia,

Thank you for your letter of 2 March. It was received at our office on 5 March 2026. We are treating it as the written request contemplated by Clause 7.

On that date the nine-month period under Clause 7 began; it ends on 5 December 2026. The board meets on 14 April and I will write to you after that meeting with its decision. We would much prefer to bring the book back than to lose it.

Yours,
Marguerite Oyelaran-Voss
Publisher
"""
    txt["2026-05-20_tobias_to_calloway-ng_permission-granted.txt"] = f"""{PRESS}
{PRESS_ADDR}

20 May 2026

Beatrix Calloway-Ng
Fenwick & Dray Books, Hollin Cross

Re: Permission to reprint "Low Water at Quay Nine" in THE SALT ALMANAC: POEMS OF TIDAL PLACES

Dear Beatrix,

Thank you for your letter of 11 May. The poem appears in THE SALT LEDGER by Cassia Merrowby (ISBN {salt_isbn}, 2013), page 22.

Under Clause 7 (Permissions) of Agreement No. LWE-A-2012-01 we may grant this permission only with the Author's prior written consent. I have asked Cassia and will confirm as soon as I hear from her. If she consents, the fee is USD 150, divided equally between the Author and the Press, and the credit line must read: "Low Water at Quay Nine" from The Salt Ledger by Cassia Merrowby (Lantern Wharf Editions, 2013). Reprinted by permission.

Yours,
Tobias Hallenbeck
Editor
"""
    txt["2025-11-04_dunmore_translator-fee.txt"] = f"""Saskia Dunmore
Translator

4 November 2025

Ines Quillfeather
{PRESS}

Re: Sample translation of Zofia Kaminrowska, "The Glassblower's Arithmetic"

Dear Ines,

Thank you for commissioning the sample. I would like to propose a fee of USD 60 per page for the 48 pages of the sample, which comes to USD 2,880, half on signature and half on delivery. This is higher than my fee on Lanterns for the Second Winter (USD 2,400 for the book) because the poems are denser, and I am happy to talk it through.

Saskia
"""
    txt[
        "2026-06-30_harrow-coast-arts-council_award.txt"
    ] = f"""Harrow Coast Arts Council
Translation Series Fund

30 June 2026

Marguerite Oyelaran-Voss
{PRESS}
{PRESS_ADDR}

Award reference: HCAC-T-2026-117

Dear Marguerite,

The Council is pleased to award {PRESS} USD 18,000 to support translation work under the Translation Series Fund. Half of the award is paid on acceptance of the terms. The second half is paid after receipt and approval of an interim report, due on 31 October 2026.

Please return the signed terms by 15 July 2026.

Ruth Ashdown-Pike
Programme Officer
"""
    txt["inv_wenlock_cover_2026-05-21.txt"] = f"""Dariusz Wenlock
Cover and book design

21 May 2026

To: {PRESS}

Invoice 2026-014
The Drowned Orchard, reissue cover (three versions: 24 March, 30 April, 19 May 2026; version 3 approved 19 May 2026)
Design fee: USD 900
Payment terms: 30 days

Thank you,
Dariusz Wenlock
"""
    txt["2026-02-12_nordlys_canada-query.txt"] = f"""Nordlys Literary Agency

12 February 2026

Marguerite Oyelaran-Voss
{PRESS}

Re: THE HARBOUR DOES NOT ANSWER (ISBN {fmt_isbn(BOOK["harbour"]["isbn"])}), Agreement No. LWE-T-2021-01

Dear Marguerite,

A Canadian festival has asked about copies of the hardcover. Could you confirm whether your grant under the Agreement covers Canada?

Gunnhild Aasebo
Rights Manager
"""
    for name, body in txt.items():
        w(L / name, body)
    # PDFs
    text_pdf(
        L / "scan_0003.pdf",
        "Letter 2026-05-11 permission request",
        f"""Beatrix Calloway-Ng
Fenwick & Dray Books, Hollin Cross

11 May 2026

Tobias Hallenbeck
{PRESS}
{PRESS_ADDR}

Re: Request for permission to reprint one poem

Dear Mr. Hallenbeck,

I am editing THE SALT ALMANAC: POEMS OF TIDAL PLACES, to be published by Fenwick & Dray Books in spring 2027, in print (3,000 copies) and as an ebook, for the English language, world rights.

I request permission to reprint "Low Water at Quay Nine" by Cassia Merrowby, from THE SALT LEDGER (ISBN {salt_isbn}, {PRESS}, 2013), in full, in the anthology. I will pay any fee you require and use any credit line you specify.

Yours sincerely,
Beatrix Calloway-Ng
Anthologist""",
    )
    text_pdf(
        L / "merrowby_consent_2026-05-27.pdf",
        "Letter 2026-05-27 author consent",
        f"""Cassia Merrowby

27 May 2026

Tobias Hallenbeck
{PRESS}

Re: "Low Water at Quay Nine" in THE SALT ALMANAC

Dear Tobias,

Under Clause 7 of my Agreement No. LWE-A-2012-01, I consent to the reprinting of "Low Water at Quay Nine" in THE SALT ALMANAC: POEMS OF TIDAL PLACES, edited by Beatrix Calloway-Ng, on the terms in your letter of 20 May 2026 (fee USD 150, divided equally, credit line as specified).

Cassia""",
    )
    text_pdf(
        L / "estate_consent_reissue_2026-05-04.pdf",
        "Letter 2026-05-04 estate consent",
        f"""Lucia Vasconcelo-Reis
Executor, Estate of Teodoro Vasconcelo-Reis
14 Corvid Lane, Meriden Sound

4 May 2026

Marguerite Oyelaran-Voss
{PRESS}

Re: THE DROWNED ORCHARD (ISBN {isbn_o}), Agreement No. LWE-T-2014-01

Dear Marguerite,

Thank you for your letter of 22 April and for the board's decision of 14 April to reissue the book. The Estate consents to the new edition, to the translator's new preface and to the revised cover.

The Estate agrees that if the book is available again in paperback or ebook through your distributor before 5 December 2026, the Estate will treat the nine-month period under Clause 7 as satisfied and will withdraw its request of 2 March 2026. Please send the distributor's written confirmation when the listing is live.

Lucia Vasconcelo-Reis""",
    )


# ---------------------------------------------------------------- mbox
ATT = {
    "reissue-schedule.txt": (
        "text/plain",
        f"""Reissue schedule: The Drowned Orchard (ISBN {fmt_isbn(BOOK["orchard"]["isbn"])})
2026-04-14  board motion M-2026-04-03
2026-05-04  estate consent received
2026-05-19  cover v3 approved
2026-06-15  revised translation due from Wren Tallowfield
2026-09-15  files to printer and distributor
2026-11-02  distributor listing live (target)
2026-11-30  board deadline
2026-12-05  end of Clause 7 cure period (9 months from receipt on 2026-03-05)
""",
    ),
    "cover-approval-v3.pdf": ("application/pdf", None),
    "permissions-fee-schedule.txt": (
        "text/plain",
        """Permissions fee schedule (internal)
Single poem, anthology up to 5,000 copies: USD 150
Single poem, anthology over 5,000 copies: USD 250
Fees are divided equally between the author and the press.
""",
    ),
    "grant-report-draft.pdf": ("application/pdf", None),
    "onix-diff.txt": (
        "text/plain",
        f"""ONIX correction request, Bramblegate Distribution
ISBN {BOOK["tides"]["isbn"]}  PriceAmount: 18.00 -> 16.00 (USD)
ISBN {BOOK["orchard"]["isbn"]}  ProductAvailability: 51 -> 20
Both changes effective on next feed.
""",
    ),
}


def att_pdf(name, tmp):
    p = tmp / name
    if name == "cover-approval-v3.pdf":
        text_pdf(
            p,
            "Cover approval sheet",
            f"""Cover approval sheet
Title: The Drowned Orchard (ISBN {fmt_isbn(BOOK["orchard"]["isbn"])})
Designer: Dariusz Wenlock
Version approved: v3 (dated 2026-05-19)
Approved by: Lucia Vasconcelo-Reis for the Estate, and Marguerite Oyelaran-Voss for the Press.
Approval date: 19 May 2026""",
        )
    else:
        text_pdf(
            p,
            "Grant interim report (draft)",
            f"""Interim report (draft), award HCAC-T-2026-117
Grantee: {PRESS}
Period: 1 July to 30 September 2026
Funds received: USD 9,000 (first half).
Activity: Saskia Dunmore delivered the sample translation of "The Glassblower's Arithmetic". Ilse Brandvold delivered the first 30 poems of the next Solvang-Hald translation.
Spending to date: USD 6,310 on translator fees and USD 900 on design.""",
        )
    return p.read_bytes()


# thread: (id, subject, [(from, [to], "date time", body, attachment-or-None)])
THREADS = [
    (
        "A",
        "Reissue of The Drowned Orchard: cure period",
        [
            (
                "marguerite",
                ["tobias", "ines"],
                "2026-04-15 09:12",
                "The board carried M-2026-04-03 yesterday: reissue The Drowned Orchard, paperback and ebook, available no later than 30 November. The Estate's reversion request was received on 5 March, so the nine months under Clause 7 end on 5 December. Schedule attached.",
                "reissue-schedule.txt",
            ),
            (
                "tobias",
                ["marguerite", "ines"],
                "2026-04-16 10:40",
                "Schedule looks right. I suggest a print-on-demand edition through Bramblegate plus a short offset run of 300 for the launch. Distributor listing needs files by mid-September.",
                None,
            ),
            (
                "marguerite",
                ["lucia"],
                "2026-04-22 14:05",
                "Dear Lucia, the board has decided to reissue The Drowned Orchard. We would like the Estate's consent to a new preface by Wren Tallowfield and a revised cover. A formal letter follows by post.",
                None,
            ),
            (
                "lucia",
                ["marguerite"],
                "2026-05-04 08:30",
                "The Estate consents. My letter of today's date is in the post. If the book is listed again before 5 December I will withdraw the March request.",
                None,
            ),
            (
                "wren",
                ["tobias"],
                "2026-06-12 17:48",
                "Revisions to the two poems are in the shared folder, with tracked changes. I kept the repeated verb in 'The Orchard After the Flood'. Preface draft follows next week.",
                None,
            ),
            (
                "tobias",
                ["marguerite", "lucia", "wren"],
                "2026-11-04 11:15",
                "Bramblegate confirmed the listing live on 2 November 2026, in paperback and ebook. That is inside the Clause 7 period. I have filed the confirmation with the contract.",
                None,
            ),
        ],
    ),
    (
        "B",
        "Cover approval: Drowned Orchard",
        [
            (
                "dariusz",
                ["ines", "tobias"],
                "2026-05-12 09:00",
                "Cover version 2 attached to the folder. Version 3 changes the water band to a deeper teal and moves the translator credit under the title.",
                None,
            ),
            (
                "ines",
                ["dariusz"],
                "2026-05-13 13:20",
                "V3 reads best at thumbnail size. Please send the final to Lucia for approval.",
                None,
            ),
            (
                "dariusz",
                ["lucia", "marguerite"],
                "2026-05-15 10:05",
                "Lucia, Marguerite: version 3 of the Drowned Orchard cover, for your approval.",
                None,
            ),
            (
                "lucia",
                ["dariusz", "marguerite"],
                "2026-05-19 07:55",
                "Version 3 approved. The orchard grid is exactly what my uncle drew in the margins of his notebooks.",
                None,
            ),
            (
                "marguerite",
                ["dariusz", "lucia", "ines"],
                "2026-05-20 09:30",
                "Approved on 19 May 2026 by the Estate and by me. Approval sheet attached for the file.",
                "cover-approval-v3.pdf",
            ),
        ],
    ),
    (
        "C",
        "Permission request: Low Water at Quay Nine",
        [
            (
                "beatrix",
                ["tobias"],
                "2026-05-11 12:00",
                "I would like to reprint 'Low Water at Quay Nine' in The Salt Almanac, due from Fenwick & Dray in spring 2027. A letter with the details is attached to the post today.",
                None,
            ),
            (
                "tobias",
                ["beatrix"],
                "2026-05-20 15:30",
                "Under Clause 7 of Cassia's agreement we need her consent first. If she agrees, the fee is USD 150, split equally. I attach our fee schedule for reference.",
                "permissions-fee-schedule.txt",
            ),
            (
                "tobias",
                ["cassia"],
                "2026-05-20 15:40",
                "Cassia, an anthologist has asked to reprint 'Low Water at Quay Nine'. Clause 7 of your agreement requires your written consent. Are you willing?",
                None,
            ),
            (
                "cassia",
                ["tobias"],
                "2026-05-27 20:10",
                "Yes. Consent letter is in the post. Please tell her that line five should keep its break, after 'The bell on the pontoon'.",
                None,
            ),
            (
                "tobias",
                ["beatrix", "cassia"],
                "2026-06-03 10:00",
                "Permission granted on the terms in my letter of 20 May. Beatrix, please keep the line break Cassia asked for.",
                None,
            ),
        ],
    ),
    (
        "D",
        "Interim grant report HCAC-T-2026-117",
        [
            (
                "ruth",
                ["marguerite"],
                "2026-10-14 09:00",
                "A reminder that the interim report for HCAC-T-2026-117 is due on 31 October 2026. Please use the attached template.",
                None,
            ),
            (
                "marguerite",
                ["halvard", "ottoline"],
                "2026-10-19 16:20",
                "The board authorised the report at the September meeting (M-2026-09-02). Draft attached. Ottoline, please check the spending figures.",
                "grant-report-draft.pdf",
            ),
            (
                "ottoline",
                ["marguerite"],
                "2026-10-21 12:45",
                "The figures match the ledger. Add that USD 9,000 has been received so far.",
                None,
            ),
            (
                "halvard",
                ["marguerite"],
                "2026-10-26 18:00",
                "Approved from my side. Send it.",
                None,
            ),
            (
                "marguerite",
                ["ruth"],
                "2026-10-29 10:30",
                "The interim report is attached to the portal submission, made on 28 October. Thank you for the reminder.",
                None,
            ),
        ],
    ),
    (
        "E",
        "Launch reading, 19 November",
        [
            (
                "priya",
                ["marguerite"],
                "2026-10-06 11:00",
                "The Tallow Room is free on 19 November for 7 pm. Capacity 60, seated.",
                None,
            ),
            (
                "marguerite",
                ["priya", "tobias"],
                "2026-10-07 09:15",
                "Book it. Wren Tallowfield will read from The Drowned Orchard, with an introduction from me.",
                None,
            ),
            (
                "tobias",
                ["marguerite", "wren"],
                "2026-10-09 14:00",
                "Wren, you have twenty minutes. I suggest the two poems from the reissue revisions.",
                None,
            ),
            (
                "wren",
                ["tobias", "marguerite"],
                "2026-10-12 19:25",
                "Twenty minutes is perfect. I would like to read 'The Orchard After the Flood' last.",
                None,
            ),
            (
                "priya",
                ["marguerite", "tobias"],
                "2026-10-20 10:10",
                "Confirmed for 19 November, 7 pm, chairs and microphone included.",
                None,
            ),
        ],
    ),
    (
        "F",
        "Translator's fee: Glassblower sample",
        [
            (
                "saskia",
                ["ines"],
                "2025-11-03 16:00",
                "Following my letter, I propose USD 60 per page for the sample.",
                None,
            ),
            (
                "ines",
                ["saskia", "marguerite"],
                "2025-11-07 09:50",
                "Marguerite, Saskia asks for USD 60 a page, 48 pages. That is USD 2,880. Can we afford it before the grant decision?",
                None,
            ),
            (
                "marguerite",
                ["ines", "saskia"],
                "2025-11-10 13:30",
                "Agreed at USD 2,880, half on signature and half on delivery.",
                None,
            ),
            (
                "saskia",
                ["ines", "marguerite"],
                "2025-11-12 08:05",
                "Thank you. I will deliver by 1 December.",
                None,
            ),
            (
                "ines",
                ["saskia"],
                "2025-11-20 17:00",
                "Contract draft is in your inbox.",
                None,
            ),
        ],
    ),
    (
        "G",
        "Errata: A Field Guide to Closing Time",
        [
            (
                "maud",
                ["tobias"],
                "2026-08-04 20:00",
                "A reader found a misprint on page 41: line 4 of the poem reads 'tied of small lamps'. It should be 'tide'.",
                None,
            ),
            (
                "tobias",
                ["maud"],
                "2026-08-05 09:10",
                "Confirmed in the first printing. We will correct it in the second printing and publish an errata slip.",
                None,
            ),
            (
                "tobias",
                ["ewan"],
                "2026-08-11 11:25",
                "Ewan, please change 'tied' to 'tide' on page 41 for the second printing of A Field Guide to Closing Time.",
                None,
            ),
            (
                "ewan",
                ["tobias"],
                "2026-08-12 15:35",
                "Corrected in the file. Proof PDF follows tomorrow.",
                None,
            ),
            (
                "maud",
                ["tobias", "ewan"],
                "2026-08-18 09:00",
                "Thank you both. I have the proof and it reads correctly.",
                None,
            ),
        ],
    ),
    (
        "H",
        "ONIX correction request",
        [
            (
                "nell",
                ["tobias"],
                "2026-10-27 10:00",
                "Our retailer feed shows Ninety Tides at USD 18.00 and The Drowned Orchard as withdrawn from sale. Please confirm the correct values.",
                None,
            ),
            (
                "tobias",
                ["nell"],
                "2026-10-28 09:40",
                "Ninety Tides is USD 16.00. The Drowned Orchard is being reissued and should be available. Corrections attached.",
                "onix-diff.txt",
            ),
            (
                "nell",
                ["tobias"],
                "2026-11-02 14:00",
                "Both corrections applied in this morning's feed. The Drowned Orchard now shows as available, paperback and ebook.",
                None,
            ),
            (
                "tobias",
                ["marguerite"],
                "2026-11-03 10:05",
                "Bramblegate applied the ONIX corrections on 2 November. I have attached the confirmation to the Clause 7 file.",
                None,
            ),
        ],
    ),
]


def make_mbox():
    tmp = Path(tempfile.mkdtemp())
    msgs = []
    n_att = 0
    for tid, subj, mails in THREADS:
        ids = []
        for k, (frm, to, when, body, att) in enumerate(mails, 1):
            mid = f"<lwe-{tid.lower()}{k}@lanternwharf.example>"
            m = EmailMessage()
            m["Message-ID"] = mid
            d = dt.datetime.fromisoformat(when).replace(
                tzinfo=dt.timezone(dt.timedelta(hours=-5))
            )
            m["Date"] = email.utils.format_datetime(d)
            m["From"] = who(frm)
            m["To"] = ", ".join(who(t) for t in to)
            m["Subject"] = subj if k == 1 else f"Re: {subj}"
            if ids:
                m["In-Reply-To"] = ids[-1]
                m["References"] = " ".join(ids)
            ids.append(mid)
            assert "\nFrom " not in body
            m.set_content(body + "\n")
            if att:
                mime, data = ATT[att]
                data = att_pdf(att, tmp) if data is None else data.encode()
                mt, st = mime.split("/")
                m.add_attachment(data, maintype=mt, subtype=st, filename=att)
                m.set_boundary(f"=_lwe_{tid}{k}_boundary")
                n_att += 1
            msgs.append((d, m, P[frm][1]))
    shutil.rmtree(tmp)
    assert len(msgs) == 40 and n_att == 5, (len(msgs), n_att)
    msgs.sort(key=lambda x: x[0])
    out = bytearray()
    for d, m, sender in msgs:
        out += f"From {sender} {d:%a %b} {d.day:2d} {d:%H:%M:%S %Y}\n".encode()
        out += m.as_bytes()
        out += b"\n"
    w(OUT / "correspondence" / "mail-export.mbox", bytes(out))


# ---------------------------------------------------------------- recordings
RECS = [
    dict(
        file="01_reading_quay-nine_and_chandlery.m4a",
        kind="reading",
        fmt="m4a",
        segments=[
            ("Karen", "Karen", "Reading at the Tallow Room. Two poems."),
            (
                "Karen",
                "Karen",
                "Low Water at Quay Nine, by Cassia Merrowby. " + " ".join(POEM_QUAY),
            ),
            (
                "Karen",
                "Karen",
                "Last Orders at the Chandlery, by Maud Ferriday. "
                + " ".join(POEM_CHANDLERY),
            ),
        ],
    ),
    dict(
        file="02_interview_tallowfield_translator.m4a",
        kind="interview",
        fmt="m4a",
        segments=[
            (
                "Interviewer",
                "Daniel",
                "Wren, why bring The Drowned Orchard back into print?",
            ),
            (
                "Wren Tallowfield",
                "Samantha",
                "Because Teodoro Vasconcelo-Reis wrote about water the way other poets write about God, and the book had been missing since January.",
            ),
            ("Interviewer", "Daniel", "What was hardest to translate?"),
            (
                "Wren Tallowfield",
                "Samantha",
                "One word. Saudade does not stay still, so in one poem I wrote absence, and in another I left it alone.",
            ),
        ],
    ),
    dict(
        file="03_launch-intro_marguerite.wav",
        kind="launch intro",
        fmt="wav",
        segments=[
            (
                "Marguerite Oyelaran-Voss",
                "Moira",
                (
                    "Good evening, and welcome to the Tallow Room. I am Marguerite Oyelaran-Voss, publisher of Lantern Wharf Editions. "
                    "On November nineteenth we celebrate the return of The Drowned Orchard, poems by Teodoro Vasconcelo-Reis, translated by Wren Tallowfield. "
                    "The book was out of print. It is back because his estate asked, and because we listened. Please welcome Wren."
                ),
            ),
        ],
    ),
]


def make_recordings():
    R = OUT / "recordings"
    R.mkdir(parents=True, exist_ok=True)
    if not (shutil.which("say") and shutil.which("afconvert")):
        print("WARNING: say/afconvert missing; recordings skipped")
        return
    tmp = Path(tempfile.mkdtemp())
    script = {
        "_note": "text is exactly what was spoken, segment by segment, in order; voices are macOS say voices",
        "recordings": [],
    }
    for r in RECS:
        wavs = []
        for i, (_speaker, voice, text) in enumerate(r["segments"]):
            a, ww = tmp / f"{i}.aiff", tmp / f"{r['file']}.{i}.wav"
            subprocess.run(
                ["say", "-v", voice, "-r", "165", "-o", str(a), text], check=True
            )
            subprocess.run(
                [
                    "afconvert",
                    "-f",
                    "WAVE",
                    "-d",
                    "LEI16@22050",
                    "-c",
                    "1",
                    str(a),
                    str(ww),
                ],
                check=True,
            )
            wavs.append(ww)
        joined = tmp / (r["file"] + ".joined.wav")
        with wave.open(str(joined), "wb") as o:
            o.setnchannels(1)
            o.setsampwidth(2)
            o.setframerate(22050)
            for ww in wavs:
                with wave.open(str(ww), "rb") as i_:
                    o.writeframes(i_.readframes(i_.getnframes()))
                o.writeframes(b"\x00\x00" * int(22050 * 0.5))
        dest = R / r["file"]
        if r["fmt"] == "wav":
            shutil.copy(joined, dest)
        else:
            subprocess.run(
                [
                    "afconvert",
                    "-f",
                    "m4af",
                    "-d",
                    "aac",
                    "-b",
                    "48000",
                    str(joined),
                    str(dest),
                ],
                check=True,
            )
        with wave.open(str(joined), "rb") as i_:
            dur = round(i_.getnframes() / i_.getframerate(), 1)
        assert dur < 40, (r["file"], dur)
        script["recordings"].append(
            {
                "file": r["file"],
                "kind": r["kind"],
                "approx_seconds": dur,
                "segments": [
                    {"speaker": s, "voice": v, "text": t} for s, v, t in r["segments"]
                ],
                "full_text": " ".join(t for _, _, t in r["segments"]),
            }
        )
    shutil.rmtree(tmp)
    w(
        KEYS / "recordings_script.json",
        json.dumps(script, indent=2, ensure_ascii=False) + "\n",
    )


# ---------------------------------------------------------------- design
def make_covers():
    D = OUT / "design" / "cover-drowned-orchard"
    title = "The Drowned Orchard"
    versions = [
        ("v1", "2026-03-24", "#1b2a49", "#f2e9d0", "plain"),
        ("v2", "2026-04-30", "#efe6cf", "#7a2e1d", "circles"),
        ("v3", "2026-05-19", "#0e5a63", "#f4f0e4", "grid"),
    ]
    for v, date, bg, fg, style in versions:
        art = ""
        if style == "circles":
            for i in range(12):
                art += f'<circle cx="{110 + (i % 4) * 130}" cy="{420 + (i // 4) * 130}" r="{38 - (i % 3) * 6}" fill="{fg}" opacity="0.55"/>'
        elif style == "grid":
            for r_ in range(4):
                for c_ in range(5):
                    art += f'<rect x="{80 + c_ * 100}" y="{360 + r_ * 70}" width="14" height="46" fill="{fg}" opacity="0.8"/>'
                    art += f'<circle cx="{87 + c_ * 100}" cy="{350 + r_ * 70}" r="22" fill="{fg}" opacity="0.35"/>'
            art += '<rect x="0" y="640" width="600" height="260" fill="#073b41" opacity="0.8"/>'
            for k in range(5):
                art += f'<path d="M0 {680 + k * 40} Q150 {660 + k * 40} 300 {680 + k * 40} T600 {680 + k * 40}" stroke="{fg}" fill="none" opacity="0.5"/>'
        else:
            art = f'<line x1="60" y1="300" x2="540" y2="300" stroke="{fg}" stroke-width="2"/>'
        credit_y = 120 if v == "v3" else 780
        svg = (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="600" height="900" viewBox="0 0 600 900">'
            f'<rect width="600" height="900" fill="{bg}"/>{art}'
            f'<text x="60" y="{200 if v != "v2" else 140}" font-family="Helvetica" font-size="48" fill="{fg}">{title}</text>'
            f'<text x="60" y="{credit_y}" font-family="Helvetica" font-size="22" fill="{fg}">Teodoro Vasconcelo-Reis</text>'
            f'<text x="60" y="{credit_y + 30}" font-family="Helvetica" font-size="18" fill="{fg}">translated by Wren Tallowfield</text>'
            f'<text x="60" y="870" font-family="Helvetica" font-size="14" fill="{fg}">{PRESS}</text>'
            f"<!-- cover {v}, dated {date} --></svg>"
        )
        w(D / f"drowned-orchard_cover_{v}_{date}.svg", svg)


# ---------------------------------------------------------------- the yellow thread
# Six documents, 2019-2026, about one colour on the press's covers: a brief,
# a printer's proof note, a designer's letter, a board minute, an author's
# letter and a reissue note. Three tie to a title, three to the press. The
# author's letter is the one a writer would close: letters start private.
# The four files with "yellow" in their name are the ones the demo opens to
# the AI (Makefile, `archive` target); the author's letter does not carry the
# word in its name, so it stays closed.
YELLOW_FILES = [
    "design/yellow-spine-brief_2019-03-12.md",
    "design/yellow-proof-note_ninety-tides_2021-06-08.txt",
    "correspondence/letters/2022-09-19_wenlock_harbour-jacket-yellow.txt",
    "board/minutes_2023-02-14_cover-yellow.md",
    "correspondence/letters/2024-05-06_merrowby_spine-colour.txt",
    "design/yellow-reissue-note_drowned-orchard_2026-08-24.md",
]


def make_yellow():
    tides = fmt_isbn(BOOK["tides"]["isbn"])
    harbour = fmt_isbn(BOOK["harbour"]["isbn"])
    orchard = fmt_isbn(BOOK["orchard"]["isbn"])
    w(
        OUT / YELLOW_FILES[0],
        f"""# Cover colour brief: poetry list, spring 2019

From: Ines Quillfeather, editor (poetry)
To: Dariusz Wenlock, designer
Date: 12 March 2019

Every poetry paperback gets a band on the spine, one colour a season. This season's band is yellow.

1. The yellow must read from three metres on a shelf, so it is a pale, warm yellow and not a lemon.
2. Print it as process yellow with 10 percent magenta. No metallic and no spot ink.
3. The band is 18 mm and runs the full height of the spine. The title and author sit on it in black.
4. Send two proofs on the uncoated cover stock before anything goes to {PRESS}'s printer.

Ines Quillfeather
""",
    )
    w(
        OUT / YELLOW_FILES[1],
        f"""Corvane Print
Proof note 21-0608

8 June 2021

To: Tobias Hallenbeck, {PRESS}
From: Ewan Ricketts, Corvane Print

Re: NINETY TIDES (ISBN {tides}), cover proof, paperback

Tobias,

The proof of the Ninety Tides cover is enclosed. The yellow spine band prints greener on the uncoated stock than on the coated sample you sent: the band reads as a pale lime beside the cover board.

We suggest raising the magenta in the yellow from 10 to 18 percent, which brings the band back to the colour in the brief. We have not changed the file. A second proof on the same stock follows on 15 June if you agree.

Ewan Ricketts
Corvane Print
""",
    )
    w(
        OUT / YELLOW_FILES[2],
        f"""Dariusz Wenlock
Cover and book design

19 September 2022

Ines Quillfeather
{PRESS}

Re: THE HARBOUR DOES NOT ANSWER (ISBN {harbour}), hardcover jacket

Dear Ines,

The jacket is dark blue cloth with the title in white. I tried the yellow spine band on it and it does not work: on cloth the yellow goes flat and brown next to the blue. I recommend leaving the band off the hardcover and keeping yellow for the paperbacks, where the proof from Corvane in June last year settled it.

If you agree I will note it in the design file so the exception is not lost.

Thank you,
Dariusz Wenlock
""",
    )
    w(
        OUT / YELLOW_FILES[3],
        f"""# {PRESS}: Board of Directors, minutes of 14 February 2023

Present: Halvard Peake (chair), Ottoline Marsh (treasurer), Marguerite Oyelaran-Voss (publisher).
In attendance: Tobias Hallenbeck (editor), Ines Quillfeather (editor), recording.
Place: the Tallow Room, Port Alder.

## Item 1. Call to order
1.1 The chair called the meeting to order at 18:00.

## Item 2. Cover standard for the poetry list
2.1 Ines Quillfeather reported that the yellow spine band has been used on every poetry paperback since spring 2019, and that the printer's proof in June 2021 changed the magenta in the yellow from 10 to 18 percent.
2.2 The designer advised in September 2022 that the band does not hold on cloth, so hardcovers are left without it.

**Motion M-2023-02-01:** To adopt the yellow as the press's standard spine band for poetry paperbacks, named Wharf yellow, printed as process yellow with 18 percent magenta, and to leave hardcovers without a band. Proposed: Ottoline Marsh. Seconded: Halvard Peake. Carried 3 to 0.

## Item 3. Close
3.1 The meeting closed at 18:40.
""",
    )
    w(
        OUT / YELLOW_FILES[4],
        f"""Cassia Merrowby

6 May 2024

Marguerite Oyelaran-Voss
{PRESS}

Re: NINETY TIDES (ISBN {tides}), second printing

Dear Marguerite,

For the second printing I would like the spine without the yellow band. The yellow was chosen for the list and not for this book, and I have never been happy with how it sits against the sea photograph on the front.

I know the board has made the yellow the standard. I am asking for an exception for this title only, and I would rather this stayed between us until you have decided.

Cassia
""",
    )
    w(
        OUT / YELLOW_FILES[5],
        f"""# Reissue note: The Drowned Orchard, cover and spine

Author of note: Tobias Hallenbeck, editor
Date: 24 August 2026

Title: THE DROWNED ORCHARD (ISBN {orchard}), paperback and ebook reissue.

1. The cover is version 3 (approved 19 May 2026): teal ground, cream type.
2. The spine carries the Wharf yellow band set by the board in February 2023: process yellow with 18 percent magenta, 18 mm, full height. Dariusz Wenlock has placed it below the translator's credit so it does not touch the teal.
3. The Estate's consent of 4 May 2026 covers the cover and the preface. The band is part of the spine and was shown to the Estate with version 3.
4. Corvane Print has the file. The yellow is to be matched to the 2021 proof for Ninety Tides, not to the screen.
""",
    )


# ---------------------------------------------------------------- handwritten + README
def make_handwritten():
    w(
        OUT / "handwritten" / "README.md",
        """# handwritten/

Three phone photos will be added of handwritten notes here (JPEG or HEIC, any file names).
The content is invented for this fixture. Copy each text out by hand, as written below, one note per page.

## Note 1: editor's margin note on a poem
(Ines Quillfeather, in the margin beside "Slack Water", stanza 2)

    Break the line after "minute"? Weight lands harder alone.
    Ask Cassia. Not before Thursday.

## Note 2: phone-call note about a rights question
(Tobias Hallenbeck, call with Gunnhild Aasebo, Nordlys Literary Agency)

    12 Feb, 10.40. Nordlys. Canada?
    Check cl. 2 of LWE-T-2021-01. US + territories + Canada: yes.
    Reply by Fri. Hardcover only for the festival.

## Note 3: to-do list for a launch
(Marguerite Oyelaran-Voss, for the 19 November reading at the Tallow Room)

    - chairs x60 (Priya)
    - 40 copies, Drowned Orchard
    - Wren: read last
    - mic check 6.15
    - Lucia: seat in row 1
    - wine, water, tea

Questions these notes can answer once transcribed: where did the Nordlys call say Canada is covered; who sits in row 1; which poem has a margin note about a line break.
""",
    )


def make_readme():
    ob = BOOK["orchard"]
    contracts = {c["id"]: c for c in CONTRACTS}
    T1, T2, A1 = (
        contracts["LWE-T-2014-01"],
        contracts["LWE-T-2020-01"],
        contracts["LWE-A-2012-01"],
    )

    def clause_no(c, key):
        return [k for k, *_ in contract_sections(c)].index(key) + 1

    people = [
        ("Marguerite Oyelaran-Voss", "publisher", f"{PRESS}"),
        ("Tobias Hallenbeck", "editor (managing)", f"{PRESS}"),
        ("Ines Quillfeather", "editor (poetry)", f"{PRESS}"),
        ("Dariusz Wenlock", "designer", "freelance cover and book design"),
        ("Halvard Peake", "board member (chair)", f"{PRESS}"),
        ("Ottoline Marsh", "board member (treasurer)", f"{PRESS}"),
        ("Cassia Merrowby", "author", "The Salt Ledger; Ninety Tides"),
        (
            "Jonas Pellerin-Okafor",
            "author",
            "Weather for Ferrymen; Almanac of Small Mercies",
        ),
        (
            "Maud Ferriday",
            "author",
            "A Field Guide to Closing Time; Letters to the Lighthouse Keeper's Daughter",
        ),
        ("Wren Tallowfield", "translator (Portuguese)", "The Drowned Orchard"),
        (
            "Saskia Dunmore",
            "translator (Polish)",
            "Lanterns for the Second Winter; The Copper Choir",
        ),
        (
            "Ilse Brandvold",
            "translator (Norwegian)",
            "The Harbour Does Not Answer; Winter Pilots",
        ),
        (
            "Lucia Vasconcelo-Reis",
            "estate (executor, Estate of Teodoro Vasconcelo-Reis)",
            "rights holder, The Drowned Orchard",
        ),
        (
            "Zofia Kaminrowska",
            "original author, Polish",
            "rights holder, Lanterns for the Second Winter",
        ),
        (
            "Beatrix Calloway-Ng",
            "anthologist",
            "The Salt Almanac: Poems of Tidal Places (Fenwick & Dray Books)",
        ),
        (
            "Gunnhild Aasebo",
            "agent, Nordlys Literary Agency",
            "rights, The Harbour Does Not Answer",
        ),
        (
            "Ruth Ashdown-Pike",
            "programme officer, Harrow Coast Arts Council",
            "grant HCAC-T-2026-117",
        ),
        (
            "Nell Cartwright-Boyd",
            "metadata contact, Bramblegate Distribution",
            "distributor",
        ),
        ("Ewan Ricketts", "printer contact, Corvane Print", "printer"),
        ("Priya Dacosta", "bookings, the Tallow Room", "venue"),
    ]
    prow = "\n".join(f"| {a} | {b} | {c} |" for a, b, c in people)
    qs = f"""
1. **In which territory may the Press publish Lanterns for the Second Winter?**
   `contracts/{T2["file"]}`, Clause {clause_no(T2, "grant")} (Grant of Rights): "the United States and its territories". Paperback only. Answer key (not part of the archive): `fixtures/press-eval/answer-keys/contracts_truth.json`.
2. **How long is the cure period before rights revert on The Drowned Orchard?**
   Nine months. `contracts/{T1["file"]}`, Clause {clause_no(T1, "reversion")} (Reversion), counted from the Publisher's receipt of the written request.
3. **When does that cure period end, and why?**
   5 December 2026. Request letter `correspondence/letters/2026-03-02_vasconcelo-reis_reversion-request.txt`; receipt on 5 March 2026 stated in `correspondence/letters/2026-03-09_reply_to_estate_receipt.txt`.
4. **Whose consent is needed before reprinting "Low Water at Quay Nine" in an anthology, and what is the fee?**
   The Author's (Cassia Merrowby), under `contracts/{A1["file"]}`, Clause {clause_no(A1, "permissions")} (Permissions). Fee USD 150, split equally: `correspondence/letters/2026-05-20_tobias_to_calloway-ng_permission-granted.txt`; consent in `correspondence/letters/merrowby_consent_2026-05-27.pdf`; thread C in `correspondence/mail-export.mbox`.
5. **What did the board decide about The Drowned Orchard?**
   Motion M-2026-04-03, Item 4, to reissue in paperback and ebook, available by 30 November 2026, carried 3 to 0: `board/Minutes April 14 2026 (final).docx`. Progress in `board/minutes_2026-09-22.md`, Item 4.
6. **Which line in the reading recording mentions an auditor?**
   "A gull inspects the rope like an auditor." in `recordings/01_reading_quay-nine_and_chandlery.m4a`; exact text in `fixtures/press-eval/answer-keys/recordings_script.json` (not part of the archive).
7. **Which cover version of the reissue was approved, and when?**
   Version 3, on 19 May 2026: `design/cover-drowned-orchard/drowned-orchard_cover_v3_2026-05-19.svg`; thread B and attachment `cover-approval-v3.pdf` in `correspondence/mail-export.mbox`.
8. **When did the distributor list the reissue, and what ONIX values were corrected?**
   Listing confirmed on 2 November 2026 (inside the Clause 7 period). ONIX: Ninety Tides price 18.00 to 16.00; The Drowned Orchard ProductAvailability 51 to 20. Thread H and attachment `onix-diff.txt` in `correspondence/mail-export.mbox`; Estate's consent conditions in `correspondence/letters/estate_consent_reissue_2026-05-04.pdf`.
"""
    w(
        OUT / "README.md",
        f"""# Synthetic press archive: {PRESS}

A fully invented small-press drive for testing an offline archive app. Every press, person, title, ISBN, date, place and text is invented. No real press, author or published text is used. Rebuild with `python3 fixtures/make_synthetic_press.py` (seeded, standard library only; recordings need macOS `say` and `afconvert`).

## The press
{PRESS} is a small poetry and translation press at {PRESS_ADDR}, founded 2011. It publishes English-language poetry and translations from Portuguese, Polish and Norwegian. The catalog snapshot in `catalog/catalog.csv` is dated 17 February 2026, before the reversion request. Folders are deliberately laid out as a working drive, not by topic, and file names are inconsistent on purpose.

The one thread that runs through the whole drive: **The Drowned Orchard** (ISBN {fmt_isbn(ob["isbn"])}), out of print since January 2026. The Estate's written reversion request (2 March 2026, received 5 March), Clause {clause_no(T1, "reversion")} of Agreement LWE-T-2014-01 (nine months), the board motion M-2026-04-03, the reissue email thread, the cover versions, the estate consent, the distributor listing and the launch intro recording all refer to the same contract clause. Jurisdiction in the contracts ("Republic of Harrowmere") is invented.

## People
| Name | Role | Connection |
|---|---|---|
{prow}

## Layout
- `catalog/catalog.csv`: 12 titles with valid ISBN-13 check digits.
- `contracts/`: 6 text-extractable PDF contracts (3 author, 3 translation) (expected fields and verbatim clause text are in `fixtures/press-eval/answer-keys/contracts_truth.json`, outside the archive).
- `correspondence/letters/`: 12 letters (9 .txt, 3 .pdf).
- `correspondence/mail-export.mbox`: 40 messages in 8 threads, 5 attachments, with Message-ID, In-Reply-To and References.
- `manuscripts/`: 4 .docx with tracked insertions and deletions (w:ins, w:del) and comments (comments.xml).
- `board/`: minutes of 14 April 2026 (.docx), 22 September 2026 (.md) and 14 February 2023 (.md).
- `recordings/`: 3 recordings (two .m4a, one .wav) (the exact spoken text is in `fixtures/press-eval/answer-keys/recordings_script.json`, outside the archive).
- `design/cover-drowned-orchard/`: three cover versions (SVG) with dates in the file names.
- `design/`: three notes on the yellow spine band (see the yellow thread below).
- `handwritten/`: README for three phone photos to be added.

## The yellow thread
Six documents, 2019 to 2026, on one colour: the yellow spine band on the poetry list. They are in four folders and have no title in common, which is the point: a search for "yellow" has to cross the press.

| Date | File | Ties to | Starts as |
|---|---|---|---|
| 12 March 2019 | `design/yellow-spine-brief_2019-03-12.md` (design brief) | the press | staff |
| 8 June 2021 | `design/yellow-proof-note_ninety-tides_2021-06-08.txt` (printer's proof note) | Ninety Tides | staff |
| 19 September 2022 | `correspondence/letters/2022-09-19_wenlock_harbour-jacket-yellow.txt` (letter, Wenlock to Quillfeather) | The Harbour Does Not Answer | private |
| 14 February 2023 | `board/minutes_2023-02-14_cover-yellow.md` (board minute, motion M-2023-02-01) | the press | staff |
| 6 May 2024 | `correspondence/letters/2024-05-06_merrowby_spine-colour.txt` (letter, Merrowby to Oyelaran-Voss) | Ninety Tides | private, stays closed |
| 24 August 2026 | `design/yellow-reissue-note_drowned-orchard_2026-08-24.md` (reissue note) | The Drowned Orchard | staff |

The four files with "yellow" in their name are opened to the AI by `make archive`. Cassia Merrowby's letter is the one a writer would keep to herself: it carries the word "yellow" but not in its name, so it is not opened, and an Explore search for "yellow" counts it as closed by its writer without showing it. No question in `fixtures/press-eval/questions.jsonl` depends on these six.

## Questions staff could ask
{qs}
""",
    )


# ---------------------------------------------------------------- main
def main():
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    make_catalog()
    make_contracts()
    make_letters()
    make_mbox()
    make_manuscripts()
    make_board()
    make_yellow()
    make_recordings()
    make_covers()
    make_handwritten()
    make_readme()
    print("wrote", OUT)


if __name__ == "__main__":
    main()
