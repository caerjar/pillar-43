"""The writer's terms view: one row per item the writer owns.

The backend decides what a writer sees: only items linked to their account.
The access log is the ledger's `model_call` and `job` lines that carried the
item's bytes; each line is a date, a purpose in plain words and the receipt
(the ledger line's number). The question text is never part of it (D5 is
unanswered).
"""

from __future__ import annotations

import json
import sqlite3

from services.archive.labels import aipref_string
from services.archive.org import LabelRule, load_org

_PURPOSE_WORDS = {
    "ask": "answering a staff question",
    "explore": "summarising a topic for staff",
    "jobs": "building a packet",
}


def label_meaning(rule: LabelRule) -> str:
    """What a label allows, in plain words, from its rule."""
    if rule.only is not None and not rule.only:
        parts = ["The AI may not use this work. Ask the estate."]
    elif rule.only is not None:
        parts = ["The AI may use this work only for: " + ", ".join(rule.only) + "."]
    elif rule.deny:
        parts = ["The AI may not use this work for: " + ", ".join(rule.deny) + "."]
    else:
        parts = []
    if rule.roles:
        parts.append("Only " + " or ".join(rule.roles) + "s may ask.")
    if rule.attribution:
        parts.append("Whoever uses it must credit the writer.")
    return " ".join(parts) or "No limit on use."


def label_catalogue() -> list[dict]:
    return [
        {
            "id": lid,
            "name": r.name,
            "meaning": label_meaning(r),
            "aipref": aipref_string([lid]),
        }
        for lid, r in load_org().labels.items()
    ]


def _purpose(actor: str, kind: str, data: dict) -> str:
    if kind == "job":
        return str(data.get("purpose") or "building a packet")
    return _PURPOSE_WORDS.get(actor, actor)


def access_log(conn: sqlite3.Connection, sha: str) -> list[dict]:
    """Every ledger line that carried these bytes, newest first. No question."""
    if not sha:
        return []
    out = []
    for seq, at, kind, actor, data in conn.execute(
        "SELECT DISTINCT l.seq, l.at, l.kind, l.actor, l.data "
        "FROM ledger l, json_each(l.data, '$.items') j "
        "WHERE l.kind IN ('model_call', 'job') "
        "AND json_extract(j.value, '$.sha256') = ? ORDER BY l.seq DESC",
        (sha,),
    ):
        out.append(
            {
                "at": at,
                "purpose": _purpose(actor, kind, json.loads(data)),
                "receipt": seq,
            }
        )
    return out


def my_work(conn: sqlite3.Connection, account_id: int) -> list[dict]:
    from services.archive.accounts import owned_paths
    from services.retrieval import _humanize_title

    rules = load_org().labels
    rows = {
        r[0]: r
        for r in conn.execute(
            "SELECT path, sha256, kind, consent, labels, withdrawn_at FROM item"
        )
    }
    out = []
    for path in sorted(owned_paths(conn, account_id)):
        r = rows.get(path)
        if r is None:
            continue
        labels = json.loads(r[4] or "[]")
        out.append(
            {
                "path": path,
                "title": _humanize_title(path),
                "kind": r[2],
                "consent": r[3],
                "labels": [
                    {
                        "id": lid,
                        "name": rules[lid].name if lid in rules else lid,
                        "meaning": label_meaning(rules[lid])
                        if lid in rules
                        else "Unknown label: closed to every use.",
                        "aipref": aipref_string([lid]),
                    }
                    for lid in labels
                ],
                "withdrawn_at": r[5],
                "reads": access_log(conn, r[1]),
            }
        )
    return out
