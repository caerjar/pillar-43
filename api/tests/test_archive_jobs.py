"""E1: jobs. Editorial history, teaching packet and rights answer are folders
assembled by code from consent- and label-filtered items of the synthetic
press, with a manifest naming every item, its labels and its ledger receipt.
`stats.json` and `COLOPHON.md` are counted by code. No model call is made
unless a cover note is asked for."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests import archive_fixtures as fx

PRESS = Path("/fixtures/synthetic-press")
TITLE = "The Drowned Orchard"

CONTRACT = "library/contracts/t_2014_vasconcelo-reis_orchard_RIGHTS+TRANSLATOR.pdf"
FERRYMEN = "library/contracts/Pellerin-Okafor Weather for Ferrymen CONTRACT signed.pdf"
DOCX = "library/manuscripts/drowned-orchard_reissue_revisions_tallowfield_2026-06.docx"
L_REQUEST = (
    "library/correspondence/letters/2026-03-02_vasconcelo-reis_reversion-request.txt"
)
L_REPLY = "library/correspondence/letters/2026-03-09_reply_to_estate_receipt.txt"
L_COVER = "library/correspondence/letters/inv_wenlock_cover_2026-05-21.txt"
L_ESTATE = "library/correspondence/letters/estate_consent_reissue_2026-05-04.pdf"
CATALOG = "library/catalog/catalog.csv"
ALL = [CONTRACT, FERRYMEN, DOCX, L_REQUEST, L_REPLY, L_COVER, L_ESTATE, CATALOG]


def _text(p: Path) -> str:
    from services.vault.extraction import _extract_docx_text, _extract_pdf_text

    if p.suffix == ".pdf":
        return _extract_pdf_text(p, p.name)
    if p.suffix == ".docx":
        return _extract_docx_text(p)
    return p.read_text(encoding="utf-8")


@pytest.fixture
def world(tmp_path, monkeypatch):
    if not PRESS.exists():
        pytest.skip("fixtures not mounted")
    import config

    fx.settings(tmp_path, monkeypatch)
    monkeypatch.setattr(config.settings, "library_root", PRESS)
    from services.archive import items, labels
    from services.db import get_db

    conn = get_db()
    try:
        for rel in ALL:
            abs_path = PRESS / rel.removeprefix("library/")
            fx.seed(rel, _text(abs_path), None)
            items.register_item(conn, rel, abs_path)
        for rel in (CONTRACT, FERRYMEN, DOCX, L_REQUEST, L_REPLY, L_COVER, CATALOG):
            items.set_consent(conn, rel, "model", by="test")
        # L_ESTATE stays private (intake default for a letter).
        labels.set_labels(conn, L_REQUEST, ["ask_the_estate"], by="test")
        labels.set_labels(conn, DOCX, ["teaching_only"], by="test")
        labels.set_labels(
            conn, L_COVER, ["teaching_only", "attribution_required"], by="test"
        )
    finally:
        conn.close()
    return tmp_path


def _conn():
    from services.db import get_db

    return get_db()


def _everything(folder: Path) -> str:
    return "\n".join(
        f.read_text(errors="ignore") for f in sorted(folder.rglob("*")) if f.is_file()
    )


def _names(folder: Path) -> str:
    return "\n".join(str(f.relative_to(folder)) for f in folder.rglob("*"))


def _manifest(folder: Path) -> dict:
    return json.loads((folder / "manifest.json").read_text())


def _paths(m: dict) -> list[str]:
    return [i["path"] for i in m["items"]]


def test_rights_answer_quotes_the_clauses_of_one_title_verbatim(world):
    from services.archive import jobs

    conn = _conn()
    try:
        out = jobs.rights_answer(conn, TITLE)
    finally:
        conn.close()
    m = _manifest(out)
    assert _paths(m) == [CONTRACT]
    body = (out / "rights-answer.md").read_text()
    reversion = (
        "If the Work is out of print in all formats granted in Clause 2, the Grantor may\n"
        "request in writing that the rights revert."
    )
    assert reversion in body
    assert "7. Reversion" in body
    assert "Weather for Ferrymen" not in body
    # the item carries its label string and a ledger receipt
    item = m["items"][0]
    assert item["labels"] == [] and item["aipref"] == ""
    assert item["receipt"]["seq"] >= 1 and len(item["receipt"]["hash"]) == 64


def test_teaching_packet_holds_only_teaching_only_items_of_the_title(world):
    from services.archive import jobs

    conn = _conn()
    try:
        out = jobs.teaching_packet(conn, TITLE)
    finally:
        conn.close()
    m = _manifest(out)
    assert sorted(_paths(m)) == sorted([DOCX, L_COVER])
    by = {i["path"]: i for i in m["items"]}
    assert by[L_COVER]["labels"] == ["attribution_required", "teaching_only"]
    assert "ai-use=n" in by[L_COVER]["aipref"]
    assert CONTRACT not in _paths(m)
    assert (out / "items").is_dir() and len(list((out / "items").iterdir())) == 2


def test_editorial_history_has_the_tracked_changes_and_the_letters(world):
    from services.archive import jobs

    conn = _conn()
    try:
        # the working copy is "teaching only", which allows editorial history
        out2 = jobs.editorial_history(conn, TITLE)
    finally:
        conn.close()
    m2 = _manifest(out2)
    assert m2["purpose"] == "editorial-history"
    assert _paths(m2) == sorted(_paths(m2))  # original order
    assert DOCX in _paths(m2) and L_REPLY in _paths(m2)
    body = (out2 / "editorial-history.md").read_text()
    assert "inserted" in body and "deleted" in body
    assert "Wren Tallowfield" in body or "Ines Quillfeather" in body


def test_private_withdrawn_and_label_denied_items_never_appear(world):
    from services.archive import items, jobs, labels, withdraw

    conn = _conn()
    try:
        withdraw.withdraw(conn, L_REPLY, by="test")
        labels.set_labels(conn, DOCX, [], by="test")
        built = [
            jobs.rights_answer(conn, TITLE),
            jobs.teaching_packet(conn, TITLE),
            jobs.editorial_history(conn, TITLE),
        ]
        items.set_consent(conn, DOCX, "model", by="test")
    finally:
        conn.close()
    forbidden = {
        "private": L_ESTATE,
        "withdrawn": L_REPLY,
        "label denies every job": L_REQUEST,
    }
    denied_words = (
        (PRESS / L_REQUEST.removeprefix("library/")).read_text().split("\n\n")[2][:60]
    )
    assert len(denied_words) > 20
    for folder in built:
        text = _everything(folder)
        for why, p in forbidden.items():
            assert p not in _paths(_manifest(folder)), why
            assert Path(p).name not in text + _names(folder), f"{why} leaked: {p}"
        assert denied_words not in text


def test_a_job_adds_a_ledger_line_and_the_chain_still_holds(world):
    from services.archive import jobs, ledger

    conn = _conn()
    try:
        before = ledger.verify(conn)["entries"]
        out = jobs.rights_answer(conn, TITLE)
        after = ledger.verify(conn)
        line = ledger.entry(conn, after["entries"])
    finally:
        conn.close()
    assert after["ok"] and after["entries"] == before + 1
    assert line["kind"] == "job" and line["data"]["job"] == "rights-answer"
    assert _manifest(out)["ledger_line"] == line["seq"]


def test_no_model_call_by_default_and_a_cover_note_cites_the_manifest(
    world, monkeypatch
):
    from services.archive import ask as ask_mod
    from services.archive import jobs

    calls = []

    def fake(*a, **k):
        calls.append(a)
        return {
            "message": {
                "content": json.dumps(
                    {"note": "Reversion is in clause 7.", "cites": [1]}
                )
            }
        }

    monkeypatch.setattr(ask_mod, "call_ollama", fake)
    conn = _conn()
    try:
        plain = jobs.rights_answer(conn, TITLE)
        assert calls == [] and not (plain / "cover-note.md").exists()
        noted = jobs.rights_answer(conn, TITLE, cover_note=True)
    finally:
        conn.close()
    assert len(calls) == 1
    assert "Reversion is in clause 7. [1]" in (noted / "cover-note.md").read_text()


def test_stats_are_counted_by_code(world):
    from services.archive import jobs

    conn = _conn()
    try:
        out = jobs.write_stats(conn)
    finally:
        conn.close()
    s = json.loads(out.read_text())
    assert s["titles_by_year"]["2015"] == 1 and sum(s["titles_by_year"].values()) == 12
    assert s["translations_by_language"] == {
        "Norwegian": 2,
        "Polish": 2,
        "Portuguese": 1,
    }
    assert s["items_by_consent"] == {"model": 7, "private": 1}
    assert s["items_by_kind_and_consent"]["contract:model"] == 2
    assert "recordings" in s and "readings" in s


def test_colophon_names_models_consent_withholding_and_ledger_head(world):
    from services.archive import jobs, ledger

    conn = _conn()
    try:
        out = jobs.write_colophon(conn)
        head = conn.execute(
            "SELECT hash FROM ledger ORDER BY seq DESC LIMIT 1"
        ).fetchone()[0]
        ok = ledger.verify(conn)["ok"]
    finally:
        conn.close()
    text = out.read_text()
    assert ok and head in text
    assert "qwen3:8b" in text and "qwen2.5vl:7b" in text
    assert "private: 1" in text
    assert "draft-ietf-aipref-vocab-08" in text
    assert "Signed by" in text
    assert Path(L_ESTATE).name not in text  # counts, never contents


# ── E1b: without a cover note no model reads anything, so staff-level items
# enter; with one, the job is built from model-level items only. ─────────────


def test_a_staff_level_contract_is_quoted_when_no_model_reads_it(world):
    from services.archive import items, jobs

    conn = _conn()
    try:
        items.set_consent(conn, CONTRACT, "staff", by="test")
        out = jobs.rights_answer(conn, TITLE)
    finally:
        conn.close()
    m = _manifest(out)
    assert _paths(m) == [CONTRACT]
    assert m["audience"] == "staff"
    assert m["items"][0]["consent"] == "staff"
    body = (out / "rights-answer.md").read_text()
    assert "7. Reversion" in body
    assert "request in writing that the rights revert." in body


def test_a_cover_note_keeps_staff_level_items_out_of_the_job(world, monkeypatch):
    from services.archive import ask as ask_mod
    from services.archive import items, jobs

    calls = []
    monkeypatch.setattr(ask_mod, "call_ollama", lambda *a, **k: calls.append(a))
    conn = _conn()
    try:
        items.set_consent(conn, CONTRACT, "staff", by="test")
        out = jobs.rights_answer(conn, TITLE, cover_note=True)
    finally:
        conn.close()
    m = _manifest(out)
    assert CONTRACT not in _paths(m)
    assert m["audience"] == "model"
    assert Path(CONTRACT).name not in _everything(out) + _names(out)
    assert calls == []  # nothing left for the model to read


def test_staff_jobs_still_refuse_private_withdrawn_and_label_denied(world):
    from services.archive import items, jobs

    conn = _conn()
    try:
        # staff level is not private: an item the writer kept private stays out
        items.set_consent(conn, L_REQUEST, "staff", by="test")
        built = [jobs.editorial_history(conn, TITLE), jobs.rights_answer(conn, TITLE)]
    finally:
        conn.close()
    for folder in built:
        assert L_ESTATE not in _paths(_manifest(folder))  # private
        assert L_REQUEST not in _paths(_manifest(folder))  # label denies every job


# ── E1c: editorial history is its own purpose, so a label can allow or refuse
# it separately from the teaching packet and from export. ────────────────────


def _with_label(monkeypatch, lid: str, **rule):
    import dataclasses

    from services.archive import labels as labels_mod
    from services.archive.org import LabelRule, load_org

    org = load_org()
    extra = {**org.labels, lid: LabelRule(id=lid, name=lid, **rule)}
    patched = dataclasses.replace(org, labels=extra)
    monkeypatch.setattr(labels_mod, "load_org", lambda: patched)


def test_teaching_only_no_longer_keeps_an_item_out_of_editorial_history(world):
    from services.archive import jobs

    conn = _conn()
    try:
        out = jobs.editorial_history(conn, TITLE)
    finally:
        conn.close()
    m = _manifest(out)
    by = {i["path"]: i for i in m["items"]}
    assert DOCX in by and by[DOCX]["labels"] == ["teaching_only"]
    assert "inserted" in (out / "editorial-history.md").read_text()


def test_a_label_denying_editorial_history_keeps_the_item_out(world, monkeypatch):
    from services.archive import jobs, labels

    _with_label(monkeypatch, "no_editorial_history", deny=("editorial-history",))
    conn = _conn()
    try:
        labels.set_labels(conn, DOCX, ["no_editorial_history"], by="test")
        labels.set_labels(conn, L_COVER, ["no_editorial_history"], by="test")
        history = jobs.editorial_history(conn, TITLE)
        rights = jobs.rights_answer(conn, TITLE)
    finally:
        conn.close()
    paths = _paths(_manifest(history))
    assert DOCX not in paths and L_COVER not in paths
    assert L_REPLY in paths  # unlabelled letters still come
    assert Path(DOCX).name not in _everything(history) + _names(history)
    # the same label leaves other purposes alone
    assert _paths(_manifest(rights)) == [CONTRACT]


def test_a_label_allowing_only_editorial_history_admits_it_there_alone(
    world, monkeypatch
):
    from services.archive import jobs, labels

    _with_label(monkeypatch, "history_only", only=("editorial-history",))
    conn = _conn()
    try:
        labels.set_labels(conn, L_REPLY, ["history_only"], by="test")
        history = jobs.editorial_history(conn, TITLE)
        for_ask = labels.select_for(conn, "ask")
        for_export = labels.select_for(conn, "export")
    finally:
        conn.close()
    assert L_REPLY in _paths(_manifest(history))
    assert L_REPLY not in for_ask and L_REPLY not in for_export
