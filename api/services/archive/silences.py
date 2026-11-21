"""What the archive could not say. Computed by code from the database, never by
the model, and returned with every answer.

Three silences:
  closed                 items on the question that are closed to the AI (a count
                         only, never what they are), split by who closed them:
                         `closed_by` = writer / default (the intake default, or
                         never registered) / staff (an administrator or staff)
  missing_correspondents people named as correspondents on a retrieved item
                         whose own letters are absent: no letter or email in the
                         archive lists them as its author
  empty_years            years in the question's scope with no item at all

Decision (agent, needs maintainer review): "scope" is the years the question names
(a year, or a range such as 2012-2014); "absent" is judged against every item
that is not withdrawn, whatever its consent, so a year with only closed items
is not reported as empty (those items are counted under `closed`).
"""

from __future__ import annotations

import json
import re
import sqlite3

_RANGE = re.compile(
    r"(?<!\d)((?:1[5-9]|20)\d\d)\s*(?:-|–|—|to|and|through)\s*((?:1[5-9]|20)\d\d)(?!\d)"
)
_YEAR = re.compile(r"(?<!\d)((?:1[5-9]|20)\d\d)(?!\d)")
_MAX_SPAN = 60


def years_in_scope(question: str) -> list[int]:
    years: set[int] = set()
    for a, b in _RANGE.findall(question):
        lo, hi = sorted((int(a), int(b)))
        if hi - lo <= _MAX_SPAN:
            years.update(range(lo, hi + 1))
    years.update(int(y) for y in _YEAR.findall(question))
    return sorted(years)


def _collapse(years: list[int]) -> str:
    runs: list[list[int]] = []
    for y in years:
        if runs and y == runs[-1][-1] + 1:
            runs[-1].append(y)
        else:
            runs.append([y])
    return ", ".join(str(r[0]) if len(r) == 1 else f"{r[0]}–{r[-1]}" for r in runs)


def _people(raw: str | None) -> list[dict]:
    try:
        v = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return []
    return [p for p in v if isinstance(p, dict)]


# consent_by values the system writes itself: nobody chose them.
_DEFAULT_ACTORS = {None, "", "intake", "setup"}


def closer_buckets(conn: sqlite3.Connection, paths: list[str]) -> dict[str, str]:
    """Who closed each path: "writer", "default" or "staff".

    writer   the item was withdrawn, or the one who last set its consent is a
             writer account or one of the item's owners
    default  the intake or setup default is still in force, or the file was
             never registered as an item (nobody has opened it)
    staff    anyone else: an administrator, a staff account, a named person
    """
    out = {p: "default" for p in paths}
    if not paths:
        return out
    roles = {n: r for n, r in conn.execute("SELECT name, role FROM account")}
    owners: dict[str, set[str]] = {}
    for path, name in conn.execute(
        "SELECT o.path, a.name FROM item_owner o JOIN account a ON a.id = o.account_id"
    ):
        owners.setdefault(path, set()).add(name)
    ph = ",".join("?" * len(paths))
    for path, by, withdrawn_at in conn.execute(
        f"SELECT path, consent_by, withdrawn_at FROM item WHERE path IN ({ph})", paths
    ):
        if (
            withdrawn_at is not None
            or by in owners.get(path, set())
            or roles.get(by) == "writer"
        ):
            out[path] = "writer"
        elif by in _DEFAULT_ACTORS:
            out[path] = "default"
        else:
            out[path] = "staff"
    return out


def tally(buckets: dict[str, str]) -> dict[str, int]:
    out = {"writer": 0, "default": 0, "staff": 0}
    for b in buckets.values():
        out[b] += 1
    return out


def _items(n: int) -> str:
    return "1 item" if n == 1 else f"{n} items"


def closed_line(closed_by: dict[str, int]) -> list[str]:
    """One plain phrase per group of closed items, each truthful about who."""
    parts = []
    w, d, s = (closed_by.get(k, 0) for k in ("writer", "default", "staff"))
    if w:
        parts.append(
            f"{_items(w)} closed by {'its writer' if w == 1 else 'their writers'}"
        )
    if d:
        parts.append(
            f"{_items(d)} closed by default (no one has opened "
            f"{'it' if d == 1 else 'them'} to the AI)"
        )
    if s:
        parts.append(f"{_items(s)} closed by staff or an administrator")
    return parts


def closed_reason(c: dict) -> str:
    """Why a named item is closed, from its `state` and `by`."""
    if c.get("state") == "withdrawn":
        return "withdrawn by its writer"
    return {
        "writer": "closed by its writer",
        "staff": "closed by staff or an administrator",
    }.get(c.get("by", "default"), "closed by default, not opened to the AI")


def compute(
    conn: sqlite3.Connection,
    question: str,
    retrieved_paths: list[str],
    closed: int,
    closed_named: list[dict] | None = None,
    closed_by: dict[str, int] | None = None,
    no_document: dict | None = None,
) -> dict:
    missing: list[str] = []
    if retrieved_paths:
        ph = ",".join("?" * len(retrieved_paths))
        named = []
        for (raw,) in conn.execute(
            f"SELECT people FROM item WHERE path IN ({ph})", retrieved_paths
        ):
            for p in _people(raw):
                if p.get("role") == "correspondent" and p.get("name"):
                    named.append(p["name"])
        if named:
            authors: set[str | None] = set()
            for (raw,) in conn.execute(
                "SELECT people FROM item WHERE kind IN ('letter','email') "
                "AND withdrawn_at IS NULL"
            ):
                authors.update(
                    p.get("name") for p in _people(raw) if p.get("role") == "author"
                )
            for n in named:
                if n not in authors and n not in missing:
                    missing.append(n)

    empty: list[int] = []
    scope = years_in_scope(question)
    if scope:
        have = {
            r[0]
            for r in conn.execute(
                "SELECT DISTINCT year FROM item WHERE year IS NOT NULL AND withdrawn_at IS NULL"
            )
        }
        empty = [y for y in scope if y not in have]

    parts = []
    if closed:
        if closed_by is not None and sum(closed_by.values()) == closed:
            parts += closed_line(closed_by)
        else:
            # Who closed them was not recorded for this count: say only what is
            # known rather than guess "by their writers".
            parts.append(f"{_items(closed)} closed to the AI")
    named_out = [{**c, "reason": closed_reason(c)} for c in closed_named or []]
    for c in named_out:
        parts.append(f"the question is about {c['title']}, {c['reason']}")
    if no_document:
        parts.append(
            f"there is no {no_document['kind']} for {no_document['title']} in the archive"
        )
    parts += [f"{n}'s replies are not in the archive" for n in missing]
    if empty:
        parts.append(f"nothing from {_collapse(empty)}")
    out = {
        "closed": closed,
        "missing_correspondents": missing,
        "empty_years": empty,
        "line": "; ".join(parts),
    }
    if closed_by is not None:
        out["closed_by"] = closed_by
    if named_out:
        out["closed_named"] = named_out
    if no_document:
        out["no_document"] = no_document
    return out


def gaps(conn: sqlite3.Connection) -> dict:
    """Aggregate the logged silences: what the press might collect next."""
    people: dict[str, int] = {}
    years: dict[int, int] = {}
    n = 0
    for (raw,) in conn.execute(
        "SELECT silences FROM answer WHERE silences IS NOT NULL"
    ):
        s = json.loads(raw)
        n += 1
        for name in s.get("missing_correspondents", []):
            people[name] = people.get(name, 0) + 1
        for y in s.get("empty_years", []):
            years[y] = years.get(y, 0) + 1
    return {
        "questions": n,
        "missing_correspondents": [
            {"name": k, "questions": v}
            for k, v in sorted(people.items(), key=lambda kv: (-kv[1], kv[0]))
        ],
        "empty_years": [
            {"year": k, "questions": v}
            for k, v in sorted(years.items(), key=lambda kv: (-kv[1], kv[0]))
        ],
    }
