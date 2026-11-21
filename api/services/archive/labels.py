"""Writers' terms: labels on items, enforced and mapped to IETF aipref.

Enforcement points:
  - retrieval: `items.allowed_paths(..., audience="model", purpose=, role=)`
    drops an item a label does not permit for that purpose, before hydration;
  - jobs and training: `select_for(conn, purpose)` is the only way a job or a
    training set should pick items.
An item that carries a label id org.yaml does not define is closed to every
purpose (fail closed).

`aipref_terms` maps labels to the IETF AI-preferences vocabulary
(`org.aipref_draft` names the draft). Where several labels set the same key,
`n` wins.
"""

from __future__ import annotations

import json
import sqlite3

from services.archive import ledger
from services.archive.org import load_org


def labels_permit(labels: list[str], purpose: str, role: str | None = None) -> bool:
    rules = load_org().labels
    for lid in labels:
        rule = rules.get(lid)
        if rule is None or not rule.permits(purpose, role):
            return False
    return True


def aipref_terms(labels: list[str]) -> dict[str, str]:
    rules = load_org().labels
    out: dict[str, str] = {}
    for lid in labels:
        rule = rules.get(lid)
        if rule is None:
            continue
        for k, v in rule.aipref.items():
            if out.get(k) != "n":
                out[k] = v
    return out


def aipref_string(labels: list[str]) -> str:
    """The terms as a preference line, e.g. `ai-use=n, train-ai=n`."""
    return ", ".join(f"{k}={v}" for k, v in sorted(aipref_terms(labels).items()))


def set_labels(
    conn: sqlite3.Connection, rel_path: str, labels: list[str], *, by: str
) -> None:
    unknown = [lid for lid in labels if lid not in load_org().labels]
    if unknown:
        raise ValueError(f"unknown label(s): {', '.join(unknown)}")
    old = conn.execute("SELECT labels FROM item WHERE path = ?", (rel_path,)).fetchone()
    if old is None:
        raise KeyError(rel_path)
    new = sorted(set(labels))
    with conn:
        conn.execute(
            "UPDATE item SET labels = ? WHERE path = ?", (json.dumps(new), rel_path)
        )
    ledger.append(
        conn,
        "labels",
        by,
        rel_path,
        {"from": json.loads(old[0] or "[]"), "to": new},
    )


def select_for(
    conn: sqlite3.Connection,
    purpose: str,
    role: str | None = None,
    *,
    audience: str = "model",
) -> list[str]:
    """Paths of the items `audience` may use for `purpose`: at a consent level
    the audience reaches, not withdrawn, and permitted by every label.

    `model` (default) is what the AI may read. `staff` is for code-only jobs
    that no model touches: staff-level items enter too, labels still apply."""
    from services.archive.items import AUDIENCE_LEVELS

    levels = sorted(AUDIENCE_LEVELS.get(audience, frozenset()))
    if not levels:
        return []
    rows = conn.execute(
        "SELECT path, labels FROM item "
        f"WHERE consent IN ({','.join('?' * len(levels))}) "
        "AND withdrawn_at IS NULL ORDER BY path",
        levels,
    ).fetchall()
    return [
        p for p, lab in rows if labels_permit(json.loads(lab or "[]"), purpose, role)
    ]
