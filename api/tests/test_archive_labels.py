"""C3: writers' terms. Labels are defined in org.yaml, stored on the item,
mapped to the IETF AI-preferences vocabulary, and enforced at retrieval and
in training-set selection (not just displayed)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from services.archive import ask as ask_mod
from tests import archive_fixtures as fx

NEVER_TRAIN = "library/letters/never-train.md"
TEACH = "library/letters/teach.md"
ESTATE = "library/letters/estate.md"
TRANSL = "library/letters/transl.md"
PLAIN = "library/letters/plain.md"
ALL = [NEVER_TRAIN, TEACH, ESTATE, TRANSL, PLAIN]


@pytest.fixture
def world(tmp_path, monkeypatch):
    fx.settings(tmp_path, monkeypatch)
    fx.seed(
        NEVER_TRAIN, "reversion never train", "model", labels=["never_for_training"]
    )
    fx.seed(TEACH, "reversion teaching", "model", labels=["teaching_only"])
    fx.seed(ESTATE, "reversion estate", "model", labels=["ask_the_estate"])
    fx.seed(TRANSL, "reversion translators", "model", labels=["translators_only"])
    fx.seed(PLAIN, "reversion plain", "model")
    fx.lexical_only(monkeypatch, ALL)
    return tmp_path


@pytest.fixture
def client():
    from main import app

    return TestClient(app, base_url="http://localhost")


def _paths(**kw):
    from services.retrieval import fetch_materials_counted

    mats, withheld = fetch_materials_counted("reversion", **kw)
    return sorted(m.rel_path for m in mats), withheld


def test_ask_reads_only_what_labels_allow(world):
    got, withheld = _paths()
    assert got == sorted([NEVER_TRAIN, PLAIN])
    assert withheld == 3


def test_teaching_only_is_retrievable_by_the_teaching_packet_alone(world):
    got, _ = _paths(purpose="teaching-packet")
    assert TEACH in got
    assert ESTATE not in got and TRANSL not in got
    assert TEACH not in _paths()[0]


def test_translators_only_needs_the_role(world):
    assert TRANSL not in _paths()[0]
    assert TRANSL not in _paths(role="editor")[0]
    assert TRANSL in _paths(role="translator")[0]


def test_never_for_training_is_excluded_from_the_training_set(world):
    from services.archive.labels import select_for
    from services.db import get_db

    conn = get_db()
    try:
        train = select_for(conn, "training")
        asking = select_for(conn, "ask")
    finally:
        conn.close()
    assert NEVER_TRAIN not in train and PLAIN in train
    assert TEACH not in train and ESTATE not in train
    assert NEVER_TRAIN in asking


def test_a_closed_item_is_never_in_a_training_set(world):
    from services.archive.items import set_consent
    from services.archive.labels import select_for
    from services.db import get_db

    conn = get_db()
    try:
        set_consent(conn, PLAIN, "staff", by="ana")
        assert PLAIN not in select_for(conn, "training")
    finally:
        conn.close()


def test_labels_map_to_aipref_and_the_most_restrictive_wins(world):
    from services.archive.labels import aipref_terms, aipref_string

    assert aipref_terms(["never_for_training"]) == {"train-ai": "n"}
    t = aipref_terms(["never_for_training", "teaching_only"])
    assert t == {"train-ai": "n", "ai-use": "n"}
    assert aipref_string(["never_for_training"]) == "train-ai=n"
    assert aipref_terms([]) == {}
    # a label the vocabulary cannot express adds nothing
    assert aipref_terms(["attribution_required"]) == {}


def test_org_yaml_labels_use_only_the_recorded_vocabulary():
    from services.archive.org import load_org

    org = load_org()
    assert org.aipref_draft.startswith("draft-ietf-aipref-vocab-")
    assert {
        "teaching_only",
        "ask_the_estate",
        "translators_only",
        "never_for_training",
        "attribution_required",
    } <= set(org.labels)
    for lab in org.labels.values():
        for k, v in lab.aipref.items():
            assert k in ("train-ai", "ai-use", "search") and v in ("y", "n")


def test_set_labels_validates_logs_and_shows_terms(world, client):
    from services.archive.labels import set_labels
    from services.db import get_db

    conn = get_db()
    try:
        with pytest.raises(ValueError):
            set_labels(conn, PLAIN, ["no_such_label"], by="ana")
        set_labels(conn, PLAIN, ["never_for_training"], by="ana")
        kinds = [r[0] for r in conn.execute("SELECT kind FROM ledger ORDER BY seq")]
        assert kinds == ["labels"]
    finally:
        conn.close()
    rows = {r["path"]: r for r in client.get("/api/archive/items/reads").json()}
    assert rows[PLAIN]["labels"] == ["never_for_training"]
    assert rows[PLAIN]["aipref"] == "train-ai=n"


def test_ask_still_answers_from_a_never_for_training_item(world, monkeypatch):
    # The answer has to share terms with its passage, or the validator (A1/A4)
    # drops it and this test would pass or fail for the wrong reason.
    fx.fake_model(monkeypatch, sentence="reversion never train")
    out = ask_mod.ask("reversion?")
    assert out["answer"]
    assert out["withheld_from_ai"] == 3
