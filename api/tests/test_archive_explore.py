"""Explore and People: every passage open to the AI on a topic, a dated summary
whose lines cite them, the count of what was not open, and one person's
connected items.

The guard that matters is the last block of `test_a_closed_*`: a closed letter
that matches the topic never appears as a passage, in the summary prompt, in
the ledger receipt or anywhere in the response; it is only counted.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from services.archive import ask as ask_mod
from services.archive import explore, people
from services.db import get_db
from tests import archive_fixtures as fx

CATALOG = "library/catalog/catalog.csv"
BRIEF = "library/design/yellow-spine-brief_2019-03-12.md"
PROOF = "library/design/yellow-proof-note_ninety-tides_2021-06-08.txt"
MINUTES = "library/board/minutes_2023-02-14_cover-yellow.md"
CLOSED = "library/correspondence/letters/2024-05-06_merrowby_spine-colour.txt"
STAFF = "library/contracts/orchard-2014.pdf"
CONSENT = "library/correspondence/letters/merrowby_consent_2026-05-27.pdf"

CSV = (
    "isbn13,title,contributors,language_original,pub_date,format,status,price_usd\n"
    "9798900100005,The Salt Ledger,Cassia Merrowby,English,2013-04-09,paperback,in print,15.00\n"
    "9798900108223,Ninety Tides,Cassia Merrowby,English,2021-06-01,paperback,in print,16.00\n"
    "9798900104119,The Drowned Orchard,Teodoro Vasconcelo-Reis; Wren Tallowfield,Portuguese,2015-05-12,paperback,out of print,16.00\n"
    "9798900113708,Winter Pilots,Eirik Solvang-Hald; Ilse Brandvold,Norwegian,2024-11-12,paperback,in print,18.00\n"
)

BRIEF_TEXT = "Every poetry paperback gets a band on the spine. This season's band is yellow.\n\nInes Quillfeather"
PROOF_TEXT = (
    "Re: NINETY TIDES (ISBN 979-8-9001-0822-3), cover proof\n\n"
    "The yellow spine band prints greener on the uncoated stock. Raise the magenta from 10 to 18 percent.\n\n"
    "Ewan Ricketts"
)
MINUTES_TEXT = (
    "# Press: Board of Directors, minutes of 14 February 2023\n\n"
    "Motion M-2023-02-01: To adopt the yellow as the standard spine band, named Wharf yellow. Carried 3 to 0."
)
CLOSED_TEXT = (
    "Cassia Merrowby\n\n6 May 2024\n\nMarguerite Oyelaran-Voss\n\n"
    "Re: NINETY TIDES (ISBN 979-8-9001-0822-3), second printing\n\nDear Marguerite,\n\n"
    "For the second printing I would like the spine without the yellow band.\n\nCassia"
)


def _sql(sql, args=()):
    conn = get_db()
    try:
        conn.execute(sql, args)
        conn.commit()
    finally:
        conn.close()


def _add_chunk(path: str, ordinal: int, text: str) -> None:
    conn = get_db()
    try:
        fid = conn.execute("SELECT id FROM files WHERE rel_path=?", (path,)).fetchone()[
            0
        ]
        conn.execute(
            "INSERT INTO file_chunks (file_id, ordinal, text, char_start, char_end, heading, chunk_hash) "
            "VALUES (?,?,?,?,?,?,?)",
            (fid, ordinal, text, 0, len(text), None, f"h{ordinal}-{path}"),
        )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def world(tmp_path, monkeypatch):
    fx.settings(tmp_path, monkeypatch)
    cat = tmp_path / "library" / "catalog"
    cat.mkdir(parents=True)
    (cat / "catalog.csv").write_text(CSV, encoding="utf-8")
    fx.seed(CATALOG, CSV, "model", kind="catalog")
    fx.seed(BRIEF, BRIEF_TEXT, "model", kind="design")
    fx.seed(PROOF, PROOF_TEXT, "model", kind="design")
    fx.seed(MINUTES, MINUTES_TEXT, "model", kind="minutes")
    fx.seed(CLOSED, CLOSED_TEXT, "private", kind="letter")
    fx.seed(STAFF, "The Drowned Orchard contract. The cover shall be yellow.", "staff")
    fx.seed(
        CONSENT,
        "Cassia Merrowby\n27 May 2026\nTobias Hallenbeck\nDear Tobias,\nI consent to the reprint.\nCassia\n"
        "Lantern Wharf Editions - Letter 2026-05-27 author consent - page 1 of 1",
        "model",
        kind="letter",
    )
    return tmp_path


@pytest.fixture
def client():
    from main import app

    return TestClient(app, base_url="http://localhost")


def summary_model(monkeypatch, lines=None, error: Exception | None = None):
    """Replace Ollama; returns the prompts it saw."""
    seen: list[str] = []

    def fake(system, user, schema, model, timeout=300):
        seen.append(system + "\n" + user)
        if error:
            raise error
        return {
            "message": {
                "content": json.dumps({"lines": lines if lines is not None else []})
            },
            "_elapsed_s": 0.1,
        }

    monkeypatch.setattr(ask_mod, "call_ollama", fake)
    return seen


# ── search ──────────────────────────────────────────────────────────────────


def test_it_returns_every_match_not_a_top_k(world):
    for i in range(30):
        fx.seed(
            f"library/design/yellow-note-{i:02d}_2020-01-{i % 28 + 1:02d}.md",
            f"Note {i}: the yellow band was checked.",
            "model",
            kind="design",
        )
    conn = get_db()
    try:
        hits, _ = explore.search(conn, "yellow")
    finally:
        conn.close()
    # 30 notes + brief + proof + minutes; ask would have stopped at 8 passages.
    assert len(hits) == 33
    assert [h.n for h in hits] == list(range(1, 34))


def test_every_chunk_of_an_item_is_its_own_passage_with_how_it_matched(world):
    _add_chunk(BRIEF, 1, "A second page: yellow again, and a phrase, Wharf yellow.")
    conn = get_db()
    try:
        hits, _ = explore.search(conn, "wharf yellow")
    finally:
        conn.close()
    assert [(h.path, h.ordinal, h.how) for h in hits] == [
        (BRIEF, 1, "phrase"),
        (MINUTES, 0, "phrase"),
    ]
    assert hits[0].matched == ["wharf", "yellow"]


def test_terms_that_do_not_stand_together_match_as_terms(world):
    conn = get_db()
    try:
        hits, _ = explore.search(conn, "magenta yellow")
    finally:
        conn.close()
    assert [h.path for h in hits] == [PROOF]
    assert hits[0].how == "terms"


def test_a_passage_has_item_title_date_and_page(world):
    conn = get_db()
    try:
        hits, _ = explore.search(conn, "yellow")
    finally:
        conn.close()
    by = {h.path: h for h in hits}
    assert by[BRIEF].titles == [] and by[BRIEF].date == "2019-03-12"
    assert by[PROOF].titles == ["Ninety Tides"] and by[PROOF].date == "2021-06-08"
    assert by[MINUTES].date == "2023-02-14" and by[MINUTES].year == 2023
    assert [h.date for h in hits] == sorted(h.date for h in hits)  # oldest first


def test_rows_are_one_per_title_and_a_press_row_in_catalog_order(world):
    conn = get_db()
    try:
        hits, _ = explore.search(conn, "yellow")
        rows = explore.rows_for(hits, explore.catalog_titles(conn))
    finally:
        conn.close()
    assert [r["label"] for r in rows] == ["Ninety Tides", "Press"]
    press = next(r for r in rows if r["title"] is None)
    assert len(press["passages"]) == 2  # the brief and the minutes
    assert not any(h.kind == "catalog" for h in hits if h.titles)


def test_an_item_that_names_many_titles_is_about_the_press(world):
    many = (
        "The Salt Ledger, Ninety Tides, The Drowned Orchard and Winter Pilots all carry the yellow band. "
        * 1
    )
    fx.seed("library/design/yellow-list_2022-02-02.md", many, "model", kind="design")
    conn = get_db()
    try:
        hits, _ = explore.search(conn, "yellow")
    finally:
        conn.close()
    h = next(h for h in hits if h.path.endswith("yellow-list_2022-02-02.md"))
    assert h.titles == []


# ── what was not open ───────────────────────────────────────────────────────


def test_not_open_is_counted_by_reason_and_names_nothing(world):
    fx.seed(
        "library/design/labelled_2021-01-01.md",
        "The yellow band, held by its writer's term.",
        "model",
        kind="design",
        labels=["ask_the_estate"],
    )
    conn = get_db()
    try:
        hits, closed = explore.search(conn, "yellow")
    finally:
        conn.close()
    lines = sorted(r["line"] for r in closed["reasons"])
    assert closed["count"] == 3
    assert lines == [
        "1 contract at staff level",
        "1 design file held by a label (ask the estate)",
        "1 letter closed by its writer",
    ]
    assert not any("labelled" in h.path for h in hits)


def test_a_closed_letter_is_never_a_passage_only_a_count(world, monkeypatch, client):
    prompts = summary_model(
        monkeypatch,
        lines=[
            {
                "text": "The yellow band was set in 2019 and changed in 2021.",
                "cites": [1, 2],
            }
        ],
    )
    r = client.post("/api/archive/explore", json={"query": "yellow"})
    assert r.status_code == 200
    body = r.json()
    paths = [p["path"] for p in body["passages"]]
    assert CLOSED not in paths and STAFF not in paths
    assert body["not_open"]["count"] == 2
    assert "1 letter closed by its writer" in [
        x["line"] for x in body["not_open"]["reasons"]
    ]
    # Nowhere in the response, the model's prompt or the ledger: not its path,
    # not its words.
    blob = json.dumps(body) + "\n".join(prompts)
    conn = get_db()
    try:
        blob += json.dumps([tuple(r) for r in conn.execute("SELECT data FROM ledger")])
    finally:
        conn.close()
    for leak in (
        "spine-colour",
        "second printing",
        "second printing",
        "until you have",
        "Merrowby_",
    ):
        assert leak not in blob
    assert "without the yellow band" not in blob
    assert "cover shall be yellow" not in blob


def test_a_withdrawn_item_is_neither_a_passage_nor_counted(world):
    _sql("UPDATE item SET withdrawn_at='2026-01-01' WHERE path=?", (CLOSED,))
    _sql("UPDATE item SET withdrawn_at='2026-01-01' WHERE path=?", (BRIEF,))
    conn = get_db()
    try:
        hits, closed = explore.search(conn, "yellow")
    finally:
        conn.close()
    assert BRIEF not in [h.path for h in hits]
    assert closed["count"] == 1  # the staff contract only


# ── the summary ─────────────────────────────────────────────────────────────


def _hits(*specs):
    return [
        explore.Hit(
            n=n,
            path=f"library/x{n}.md",
            name=f"x{n}.md",
            kind="note",
            titles=[],
            date=date,
            year=int(date[:4]) if date else None,
            chunk_id=n,
            ordinal=0,
            page=None,
            char_start=0,
            char_end=len(text),
            text=text,
            how="phrase",
            matched=[],
        )
        for n, date, text in specs
    ]


PASSAGES = _hits(
    (1, "2019-03-12", "The band is yellow. Print it as process yellow."),
    (
        2,
        "2021-06-08",
        "The proof shows the yellow greener. Raise the magenta to 18 percent.",
    ),
)


def test_a_line_citing_a_passage_that_was_not_returned_is_dropped():
    v = explore.validate_summary(
        {
            "lines": [
                {"text": "The band was set in 2019 as yellow.", "cites": [1]},
                {"text": "The band was recoloured in a later proof.", "cites": [2, 9]},
            ]
        },
        PASSAGES,
    )
    assert [ln["cites"] for ln in v.lines] == [[1]]
    assert v.dropped == ["cite_not_in_passages"]


def test_a_line_without_a_cite_or_a_sentence_is_dropped():
    v = explore.validate_summary(
        {
            "lines": [
                {"text": "The yellow band changed over time.", "cites": []},
                {"text": "ok", "cites": [1]},
                {"text": "The yellow band changed over time.", "cites": "1"},
            ]
        },
        PASSAGES,
    )
    assert v.lines == []
    assert v.dropped == ["no_cite", "not_a_sentence", "no_cite"]


def test_a_year_the_cited_passages_do_not_contain_is_dropped():
    v = explore.validate_summary(
        {
            "lines": [
                {"text": "The yellow was changed in 2023.", "cites": [2]},
                {"text": "The yellow was proofed in 2021.", "cites": [2]},
            ]
        },
        PASSAGES,
    )
    assert [ln["text"] for ln in v.lines] == ["The yellow was proofed in 2021."]
    assert v.dropped == ["unsupported_year"]


def test_a_quotation_that_is_not_in_the_cited_passage_is_dropped():
    v = explore.validate_summary(
        {
            "lines": [
                {
                    "text": 'The proof said "the yellow is now perfectly balanced".',
                    "cites": [2],
                },
                {"text": 'The brief says "Print it as process yellow".', "cites": [1]},
            ]
        },
        PASSAGES,
    )
    assert [ln["cites"] for ln in v.lines] == [[1]]
    assert v.dropped == ["unverified_quote"]


def test_lines_are_dated_by_what_they_cite_and_ordered_by_it():
    v = explore.validate_summary(
        {
            "lines": [
                {"text": "The proof raised the magenta in the yellow.", "cites": [2]},
                {"text": "The brief asked for process yellow.", "cites": [1]},
                {"text": "Both name the same yellow band.", "cites": [2, 1]},
            ]
        },
        PASSAGES,
    )
    assert [(ln["date"], ln["cites"]) for ln in v.lines] == [
        ("2019-03-12", [1]),
        ("2019-03-12", [1, 2]),
        ("2021-06-08", [2]),
    ]


def test_the_summary_prompt_holds_only_open_passages_and_a_receipt_names_them(
    world, monkeypatch, client
):
    prompts = summary_model(
        monkeypatch, lines=[{"text": "The yellow band began in 2019.", "cites": [1]}]
    )
    body = client.post("/api/archive/explore", json={"query": "yellow"}).json()
    assert body["summary_status"] == "ok"
    assert body["summary"][0]["date"] == "2019-03-12"
    assert body["prompt_version"] == "explore-v1"
    assert "spine without" not in prompts[0] and "cover shall be" not in prompts[0]
    conn = get_db()
    try:
        data = json.loads(
            conn.execute("SELECT data FROM ledger WHERE kind='model_call'").fetchone()[
                0
            ]
        )
    finally:
        conn.close()
    assert sorted(i["path"] for i in data["items"]) == sorted([BRIEF, PROOF, MINUTES])


def test_a_model_that_is_not_running_still_returns_every_passage(
    world, monkeypatch, client
):
    summary_model(monkeypatch, error=ConnectionRefusedError())
    r = client.post("/api/archive/explore", json={"query": "yellow"})
    assert r.status_code == 200
    body = r.json()
    assert body["summary_status"] == "model_unavailable"
    assert len(body["passages"]) == 3


def test_no_match_says_empty_and_never_calls_the_model(world, monkeypatch, client):
    prompts = summary_model(monkeypatch)
    body = client.post("/api/archive/explore", json={"query": "turquoise"}).json()
    assert body["passages"] == [] and body["summary_status"] == "empty"
    assert prompts == []


def test_a_query_of_only_filler_words_is_refused(world, client):
    assert (
        client.post("/api/archive/explore", json={"query": "all the"}).status_code
        == 422
    )


def test_the_ask_prompt_is_still_ask_v5():
    assert ask_mod.PROMPT_VERSION == "ask-v5"


# ── dates ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "path,text,year,want",
    [
        ("library/a/2026-03-02_x.txt", "", None, "2026-03-02"),
        ("library/board/Minutes April 14 2026 (final).docx", "", None, "2026-04-14"),
        ("library/x/untitled.txt", "Dated 9 June 2014. Rest.", None, "2014-06-09"),
        ("library/x/untitled.txt", "June 9, 2014 and more", None, "2014-06-09"),
        ("library/contracts/t_2014_x.pdf", "no date here", None, "2014"),
        ("library/x/none.txt", "nothing", None, None),
        ("library/x/2026-13-45_bad.txt", "", None, "2026"),
    ],
)
def test_item_date(path, text, year, want):
    assert explore.item_date(path, text, year) == want


# ── people ──────────────────────────────────────────────────────────────────

CONTRACT_TAIL = (
    "10. Signatures\nSigned on 14 September 2012.\nFor the Grantor: Cassia Merrowby\n"
    "Signature: /s/ Cassia Merrowby\nFor the Publisher: Marguerite Oyelaran-Voss\n"
    "Lantern Wharf Editions - Agreement LWE-A-2012-01 - page 2 of 2"
)


def test_connections_signed_wrote_received_mentioned():
    name = "Cassia Merrowby"
    assert people.connections(name, CONTRACT_TAIL, "contract") == ["signed"]
    assert "wrote" in people.connections(name, CLOSED_TEXT, "letter")
    consent = "Tobias Hallenbeck\n\n27 May 2026\n\nCassia Merrowby\n\nDear Cassia,\n\nThe fee is USD 150.\n\nTobias"
    assert people.connections(name, consent, "letter") == ["received"]
    permission = "I request permission to reprint 'Low Water' by Cassia Merrowby, from THE SALT LEDGER."
    assert people.connections(name, permission, "letter") == ["mentioned"]
    assert people.connections(name, "Nothing about her.", "letter") == []


def test_an_email_sender_wrote_and_its_recipient_received():
    ppl = [
        {"name": "Cassia Merrowby", "role": "author", "sender": True},
        {"name": "Tobias Hallenbeck", "role": "correspondent"},
    ]
    assert people.connections("Cassia Merrowby", "x", "email", ppl) == ["wrote"]
    assert people.connections("Tobias Hallenbeck", "x", "email", ppl) == ["received"]


def test_the_relationship_to_the_press_comes_from_the_catalog(world):
    conn = get_db()
    try:
        titles = explore.catalog_titles(conn)
        lst = people.people_list(conn)
    finally:
        conn.close()
    assert [r["role"] for r in people.relationship("Wren Tallowfield", titles)] == [
        "translator"
    ]
    assert [
        r["role"] for r in people.relationship("Teodoro Vasconcelo-Reis", titles)
    ] == ["author"]
    cassia = next(p for p in lst if p["name"] == "Cassia Merrowby")
    assert cassia["relationship"] == ["author of The Salt Ledger, Ninety Tides"]


def test_a_person_record_has_open_items_with_how_and_counts_the_closed(world, client):
    r = client.get("/api/archive/people/Cassia Merrowby")
    assert r.status_code == 200
    body = r.json()
    assert body["relationship"] == ["author of The Salt Ledger, Ninety Tides"]
    by = {i["path"]: i for i in body["items"]}
    assert by[CONSENT]["connection"] == "wrote"
    assert by[CONSENT]["date"] == "2026-05-27"
    # The closed letter is counted by reason and never listed.
    assert CLOSED not in by
    assert body["not_open"]["count"] == 1
    assert body["not_open"]["reasons"][0]["line"] == "1 letter closed by its writer"
    assert "second printing" not in json.dumps(body)
    assert [r["label"] for r in body["rows"]] == ["Press"]
    # The date range is the earliest and latest date among the items shown.
    ds = sorted(
        i["date"] or str(i["year"]) for i in body["items"] if i["date"] or i["year"]
    )
    assert body["first_date"] == ds[0] and body["last_date"] == ds[-1]
    assert body["first_date"] <= body["last_date"]


def test_people_lists_the_catalog_contributors(world, client):
    r = client.get("/api/archive/people")
    assert r.status_code == 200
    names = [p["name"] for p in r.json()]
    assert "Wren Tallowfield" in names and "Cassia Merrowby" in names


def test_the_people_list_carries_each_persons_document_count_and_date_range(
    world, client
):
    rows = {p["name"]: p for p in client.get("/api/archive/people").json()}
    for name in ("Cassia Merrowby", "Wren Tallowfield"):
        rec = client.get(f"/api/archive/people/{name}").json()
        row = rows[name]
        assert row["document_count"] == len(rec["items"])
        assert (row["first_date"], row["last_date"]) == (
            rec["first_date"],
            rec["last_date"],
        )
    # The closed letter is not counted: the count is what is open to the reader.
    assert rows["Cassia Merrowby"]["document_count"] >= 1


def test_a_name_the_archive_has_nothing_on_is_404(world, client):
    assert client.get("/api/archive/people/Nobody Here").status_code == 404
