"""Scoring rules for the open test archive (services/archive/score.py)."""

from services.archive.score import score_one, summarize

C = "library/contracts/orchard.pdf"
L = "library/letters/receipt.txt"
OTHER = "library/contracts/other.pdf"

Q = {
    "id": "q001",
    "job": "rights",
    "question": "How long does the press have to reissue the Orchard?",
    "expect_any": ["nine (9) months"],
    "must_cite": [C],
    "needs": [],
}


def _out(answer, passages=None, not_answered=False, dropped=None):
    return {
        "answer": answer,
        "not_answered": not_answered,
        "passages": passages or [{"n": 1, "path": C}, {"n": 2, "path": OTHER}],
        "dropped": dropped or {},
        "timing": {"retrieve_s": 0.5, "model_s": 20.0},
    }


def _sent(text, cites, quote=None):
    return {"text": text, "cites": cites, "quote": quote}


def test_correct_needs_fact_and_the_right_cite():
    out = _out([_sent("The press has nine (9) months.", [1])])
    s = score_one(Q, out, {C: "model"})
    assert s.expected == "answer" and s.correct and s.seconds == 20.5


def test_fact_in_quoted_text_counts():
    quote = {"passage": 1, "sentence": 2, "text": "within nine (9) months after"}
    out = _out([_sent("Clause 7 sets the period.", [1], quote)])
    assert score_one(Q, out, {C: "model"}).correct


def test_right_fact_wrong_source_is_wrong():
    out = _out([_sent("The press has nine (9) months.", [2])])
    s = score_one(Q, out, {C: "model"})
    assert not s.correct and s.off_target_cites == 1


def test_closed_source_expects_not_answered():
    # The contract is staff-only: answering from another item is not credit.
    out = _out([_sent("The press has nine (9) months.", [2])])
    s = score_one(Q, out, {C: "staff"})
    assert s.expected == "not_answered" and s.why_not == [f"closed:{C}"]
    assert not s.correct
    assert score_one(Q, _out([], not_answered=True), {C: "staff"}).correct


def test_two_item_question_needs_both_open():
    q = {**Q, "must_cite": [C, L]}
    s = score_one(q, _out([], not_answered=True), {C: "model", L: "private"})
    assert s.expected == "not_answered" and s.correct


def test_missing_stage_and_no_answer_in_archive():
    q = {**Q, "needs": ["transcribe"]}
    assert score_one(q, _out([], not_answered=True), {C: "model"}).why_not == [
        "needs:transcribe"
    ]
    q2 = {**Q, "must_cite": [], "expect_any": []}
    s = score_one(q2, _out([], not_answered=True), {})
    assert s.why_not == ["archive_has_no_answer"] and s.correct


def test_misquote_from_validator_drops():
    out = _out(
        [_sent("The press has nine (9) months.", [1])],
        dropped={"unverified_inline_quote": 1},
    )
    s = score_one(Q, out, {C: "model"})
    assert s.misquote and s.correct  # what survived is still right


def test_summary_rates():
    good = score_one(Q, _out([_sent("nine (9) months.", [1])]), {C: "model"})
    bad = score_one(Q, _out([_sent("six months.", [1])]), {C: "model"})
    s = summarize([good, bad])
    assert s["accuracy"] == 0.5 and s["answerable_now"] == 2
    assert s["by_job"] == {"rights": {"n": 2, "correct": 1}}


# ── alternative source sets (A5) ────────────────────────────────────────────

M = "library/board/minutes_2026-09-22.md"
LETTER = "library/correspondence/letters/estate.txt"


def _alt(*sets):
    q = {k: v for k, v in Q.items() if k not in ("must_cite", "needs")}
    q["sources"] = [{"paths": p, "needs": n} for p, n in sets]
    return q


def test_a_fact_restated_in_open_minutes_is_answerable_from_them():
    # The estate letter is closed, but the minutes restate the fact.
    q = _alt(([C, LETTER], []), ([M], []))
    consent = {C: "model", LETTER: "private", M: "model"}
    out = _out(
        [_sent("The press has nine (9) months.", [1])],
        passages=[{"n": 1, "path": M}],
    )
    s = score_one(q, out, consent)
    assert s.expected == "answer" and s.correct and s.cite_hit
    assert s.off_target_cites == 0


def test_every_set_closed_expects_not_answered_and_says_why_for_the_nearest():
    q = _alt(([C, LETTER], []), ([M], ["email"]))
    consent = {C: "model", LETTER: "private", M: "model"}
    s = score_one(q, _out([], not_answered=True), consent)
    assert s.expected == "not_answered" and s.correct
    # one set's reasons are reported, not both sets' together
    assert len(s.why_not) == 1


def test_a_set_that_needs_an_unbuilt_stage_does_not_count():
    q = _alt(([C], ["transcribe"]), ([M], []))
    assert score_one(q, _out([], not_answered=True), {C: "model", M: "private"}).correct
    s = score_one(q, _out([], not_answered=True), {C: "model", M: "model"})
    assert s.expected == "answer" and not s.correct


def test_a_cite_outside_every_set_is_off_target():
    q = _alt(([C], []), ([M], []))
    out = _out([_sent("The press has nine (9) months.", [1, 2])])  # C and OTHER
    s = score_one(q, out, {C: "model", M: "model"})
    assert s.off_target_cites == 1 and s.cite_hit


def test_no_sets_means_the_archive_has_no_answer():
    q = {k: v for k, v in Q.items() if k not in ("must_cite", "needs")}
    q["sources"] = []
    assert score_one(q, _out([], not_answered=True), {}).why_not == [
        "archive_has_no_answer"
    ]


def test_saved_results_rescore_without_the_model():
    from services.archive.score import score_saved

    q = _alt(([C, LETTER], []), ([M], []))
    saved = {
        "score": {
            "cited_paths": [M],
            "answered": True,
            "dropped": {},
            "seconds": 12.5,
        },
        "answer": [{"text": "nine (9) months", "cites": [1], "quote": None}],
        "not_answered": False,
    }
    s = score_saved(q, saved, {C: "model", LETTER: "private", M: "model"})
    assert s.expected == "answer" and s.correct and s.seconds == 12.5
