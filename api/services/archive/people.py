"""People: for one person, every item that connects to them and how.

Same discipline as Explore (`explore.py`): consent first, then search, then a
count of what was not open. Nothing here calls a model.

How an item connects, in the order they are tried (an item can have several;
`connection` is the first that holds):

  signed     they sign it: a signature line (`/s/ Name`, `Signature: Name`) in
             its closing lines
  wrote      they are its author: the sender of an email, the name that ends a
             letter or note, a `From:` or `By` line, or the byline of a
             manuscript
  received   it is addressed to them: `Dear Name`, `To:`, or the addressee of
             an email
  mentioned  their name appears anywhere else in it

These are read from the text and from the item's own `people` record (emails).
They are rules over what a document says, not a judgement of what it means.

A person's relationship to the press comes from the catalog (contributors per
title, in order: for a translation the first is the original author and the
rest translators). A name the catalog does not list gets no relationship.
"""

from __future__ import annotations

import json
import re

from services.archive.explore import (
    Hit,
    catalog_titles,
    closed_reason,
    display_name,
    item_date,
    open_paths,
    reason_line,
    rows_for,
    titles_for,
    year_of,
)

CONNECTIONS = ("signed", "wrote", "received", "mentioned")
_FOOTER = re.compile(r"^.* - (?:Agreement|Letter) .* - page \d+ of \d+$|^\[Page \d+\]$")
_ZONE_LINES = 10
_TITLE_WORDS = r"(?:Mr|Mrs|Ms|Mx|Dr|Prof)\.?"


def _tokens(name: str) -> list[str]:
    return [t for t in re.split(r"\s+", name.strip()) if t]


def name_patterns(name: str) -> dict[str, re.Pattern]:
    """Regexes for a full name, its surname and its first name."""
    toks = _tokens(name)
    first, last = toks[0], toks[-1]
    full = r"\s+".join(re.escape(t) for t in toks)
    return {
        "full": re.compile(rf"\b{full}\b", re.I),
        "last": re.compile(rf"\b{re.escape(last)}\b", re.I),
        "first": re.compile(rf"\b{re.escape(first)}\b", re.I),
        "dear": re.compile(
            rf"^\s*Dear\s+(?:{_TITLE_WORDS}\s+)?(?:{re.escape(first)}|{re.escape(last)}"
            rf"|{full})\b",
            re.I | re.M,
        ),
        "to": re.compile(rf"^\s*To:.*\b(?:{full}|{re.escape(last)})\b", re.I | re.M),
        "from": re.compile(
            rf"^\s*(?:From:|By\s|Prepared by|Written by|Author:)\s*.*\b(?:{full}|{re.escape(last)})\b",
            re.I | re.M,
        ),
        "sig": re.compile(rf"(?:/s/\s*(?:{full})|Signature:.*(?:{full}))", re.I),
    }


def _zone(text: str) -> list[str]:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    lines = [ln for ln in lines if not _FOOTER.match(ln)]
    return lines[-_ZONE_LINES:]


def connections(
    name: str, text: str, kind: str, people: list[dict] | None = None
) -> list[str]:
    """How `name` connects to an item, from its text and its people record.
    Empty if it does not."""
    pats = name_patterns(name)
    toks = _tokens(name)
    first = toks[0].lower()
    found: set[str] = set()
    people = people or []
    mine = [
        p
        for p in people
        if isinstance(p, dict)
        and (p.get("name") or "").strip().lower() == name.strip().lower()
    ]
    zone = _zone(text)
    zone_text = "\n".join(zone)

    # signed
    if pats["sig"].search(zone_text):
        found.add("signed")

    # wrote
    if any(p.get("role") == "author" or p.get("sender") for p in mine):
        found.add("wrote")
    if pats["from"].search(text[:1500]):
        found.add("wrote")
    if kind in ("letter", "email", "note", "attachment"):
        # The name or first name that closes a letter: its own line, followed
        # by at most a short role line or two ("Publisher").
        for i, ln in enumerate(zone):
            after = zone[i + 1 :]
            if (
                re.fullmatch(
                    rf"(?:{pats['full'].pattern}|{re.escape(first)})[.,]?", ln, re.I
                )
                and len(after) <= 2
                and all(len(a.split()) <= 4 for a in after)
            ):
                found.add("wrote")
    if kind == "document":
        head = "\n".join(ln for ln in text.splitlines() if ln.strip())[:200]
        if pats["full"].search(head):
            found.add("wrote")

    # received
    if pats["dear"].search(text[:2500]) or pats["to"].search(text[:1500]):
        found.add("received")
    if any(p.get("role") == "correspondent" for p in mine):
        found.add("received")

    # mentioned
    if (
        pats["full"].search(text) or (len(toks) > 1 and pats["last"].search(text))
    ) and not found:
        found.add("mentioned")
    if not found and mine:
        found.add("mentioned")
    return [c for c in CONNECTIONS if c in found]


def _prefilter_sql(name: str) -> tuple[str, list[str]]:
    toks = _tokens(name)
    last, first = toks[-1].lower(), toks[0].lower()
    return (
        (
            "(instr(lower(f.extracted_text), ?) > 0 OR instr(lower(f.extracted_text), ?) > 0 "
            "OR instr(lower(i.people), ?) > 0)"
        ),
        [last, f"dear {first}", last],
    )


def _candidates(conn, name: str) -> list[tuple]:
    where, args = _prefilter_sql(name)
    return conn.execute(
        "SELECT i.path, i.kind, i.consent, i.labels, i.people, i.year, i.title_isbn, "
        "f.extracted_text, f.summary "
        "FROM item i JOIN files f ON f.rel_path = i.path "
        f"WHERE i.withdrawn_at IS NULL AND {where} ORDER BY i.path",
        args,
    ).fetchall()


def relationship(name: str, titles: list[dict]) -> list[dict]:
    """The person's catalog titles: [{title, isbn, role, pub_date}]."""
    out = []
    key = name.strip().lower()
    for t in titles:
        parts = [p.strip() for p in t["contributors"].split(";") if p.strip()]
        names = [re.sub(r"\s*\((editor)\)\s*$", "", p, flags=re.I) for p in parts]
        translation = t["language"] and t["language"].lower() != "english"
        for i, (raw, nm) in enumerate(zip(parts, names, strict=True)):
            if nm.lower() != key or nm.lower() == "various":
                continue
            if "(editor)" in raw.lower():
                role = "editor"
            elif translation and i > 0:
                role = "translator"
            else:
                role = "author"
            out.append(
                {
                    "title": t["title"],
                    "isbn": t["isbn"],
                    "role": role,
                    "pub_date": t["pub_date"],
                }
            )
    return out


def date_span(items) -> list[str]:
    """The sorted dates of items (objects with .date and .year): an ISO date,
    or a bare year when that is all an item has."""
    return sorted(
        d
        for d in (
            i.date or (str(i.year) if i.year is not None else None) for i in items
        )
        if d
    )


def people_list(conn, role: str | None = None) -> list[dict]:
    """Everyone the catalog credits: [{name, relationship, titles,
    document_count, first_date, last_date}], counting only items open to `role`."""
    titles = catalog_titles(conn)
    seen: dict[str, dict] = {}
    for t in titles:
        for raw in t["contributors"].split(";"):
            nm = re.sub(r"\s*\((editor)\)\s*$", "", raw.strip(), flags=re.I)
            if nm and nm.lower() != "various":
                seen.setdefault(nm, {"name": nm})
    out = []
    for nm in sorted(seen, key=lambda s: s.rsplit(" ", 1)[-1].lower()):
        rel = relationship(nm, titles)
        rec = record(conn, nm, role)
        hits = [h for h, _ in rec["items"]] if rec else []
        dates = date_span(hits)
        out.append(
            {
                "name": nm,
                "relationship": _relationship_lines(rel),
                "titles": [r["title"] for r in rel],
                "document_count": len(hits),
                "first_date": dates[0] if dates else None,
                "last_date": dates[-1] if dates else None,
            }
        )
    return out


def _relationship_lines(rel: list[dict]) -> list[str]:
    by_role: dict[str, list[str]] = {}
    for r in rel:
        by_role.setdefault(r["role"], []).append(r["title"])
    return [f"{role} of {', '.join(ts)}" for role, ts in by_role.items()]


def record(conn, name: str, role: str | None = None) -> dict | None:
    """The authority record for `name`, or None if the archive has nothing on
    them (no catalog title, no open item, no closed item)."""
    from services.archive.pages import chunk_pages

    name = re.sub(r"\s+", " ", name).strip()
    if not _tokens(name):
        return None
    titles = catalog_titles(conn)
    rel = relationship(name, titles)
    allowed = open_paths(conn, role)  # consent first

    open_items: list[tuple] = []
    closed: dict[tuple[str, str, str | None], int] = {}
    closed_n = 0
    for path, kind, consent, labels, people, year, tisbn, text, summary in _candidates(
        conn, name
    ):
        text = text or ""
        ppl = json.loads(people or "[]")
        conns = connections(name, text, kind, ppl)
        if not conns:
            continue
        if path in allowed:
            open_items.append((path, kind, year, tisbn, text, summary, conns))
        else:
            closed_n += 1
            reason, label = closed_reason(consent, json.loads(labels or "[]"))
            k = (reason, kind, label)
            closed[k] = closed.get(k, 0) + 1
    if not rel and not open_items and not closed_n:
        return None

    pats = name_patterns(name)
    items: list[dict] = []
    hits: list[Hit] = []
    for path, kind, year, tisbn, text, summary, conns in open_items:
        chunk = _locate(conn, path, pats)
        if chunk is None:
            continue
        cid, ordinal, ctext, cs, ce = chunk
        d = item_date(path, text, year)
        hit = Hit(
            n=0,
            path=path,
            name=display_name(path, summary),
            kind=kind,
            titles=titles_for(titles, path, text, kind, tisbn),
            date=d,
            year=year_of(d),
            chunk_id=cid,
            ordinal=ordinal,
            page=None,
            char_start=cs or 0,
            char_end=ce or 0,
            text=ctext,
            how=conns[0],
            matched=[],
        )
        hits.append(hit)
        items.append({"hit": hit, "connections": conns})
    hits.sort(key=lambda h: (h.date or "9999", h.path))
    for i, h in enumerate(hits, 1):
        h.n = i
    pages = chunk_pages(conn, [h.chunk_id for h in hits])
    for h in hits:
        h.page = pages.get(h.chunk_id)
    by_hit = {id(i["hit"]): i["connections"] for i in items}
    reasons = [
        {"reason": r, "kind": k, "count": n, "line": reason_line(r, k, n, label)}
        for (r, k, label), n in sorted(
            closed.items(), key=lambda kv: (-kv[1], kv[0][0], kv[0][1])
        )
    ]
    return {
        "name": name,
        "relationship": _relationship_lines(rel),
        "titles": rel,
        "items": [(h, by_hit[id(h)]) for h in hits],
        "rows": rows_for(hits, titles),
        "not_open": {"count": closed_n, "reasons": reasons},
    }


def _locate(conn, path: str, pats: dict[str, re.Pattern]):
    """The chunk to open for an item: the first that carries the person's name,
    a salutation to them, or else the last chunk (a signature closes a text)."""
    rows = conn.execute(
        "SELECT fc.id, fc.ordinal, fc.text, fc.char_start, fc.char_end "
        "FROM file_chunks fc JOIN files f ON f.id = fc.file_id "
        "WHERE f.rel_path = ? ORDER BY fc.ordinal",
        (path,),
    ).fetchall()
    if not rows:
        return None
    for r in rows:
        if (
            pats["full"].search(r[2])
            or pats["last"].search(r[2])
            or pats["dear"].search(r[2])
        ):
            return r
    return rows[-1]
