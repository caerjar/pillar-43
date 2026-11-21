"""Explore and People: the two whole-archive views of the organization edition.

Both are for staff and admins, like ask.
Consent is applied inside the services, before any search (see
`services/archive/explore.py`); writer accounts are refused here because these
views read across everyone's items.
"""

from __future__ import annotations

import asyncio
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from routes.archive import _acct, staff_up

router = APIRouter(prefix="/api/archive", tags=["archive"])

Connection = Literal["signed", "wrote", "received", "mentioned"]


class ExploreRequest(BaseModel):
    query: str = Field(min_length=1, max_length=300)
    summarize: bool = True


class PassageBase(BaseModel):
    n: int
    path: str
    name: str
    kind: str
    titles: list[str]
    date: str | None = None
    year: int | None = None
    chunk_id: int
    ordinal: int
    page: int | None = None
    char_start: int
    char_end: int
    text: str


class ExplorePassage(PassageBase):
    how: Literal["phrase", "terms"]
    matched: list[str]


class ExploreLine(BaseModel):
    text: str
    cites: list[int]
    date: str | None = None


class NotOpenReason(BaseModel):
    reason: Literal["private", "staff", "label"]
    kind: str
    count: int
    line: str


class NotOpen(BaseModel):
    count: int
    reasons: list[NotOpenReason]


class TimelineRow(BaseModel):
    title: str | None = None
    isbn: str | None = None
    label: str
    passages: list[int]


class ExploreResponse(BaseModel):
    query: str
    passages: list[ExplorePassage]
    rows: list[TimelineRow]
    summary: list[ExploreLine]
    summary_status: Literal["ok", "empty", "none_valid", "model_unavailable", "skipped"]
    summary_shown: int
    not_open: NotOpen
    model: str
    prompt_version: str
    receipt_id: int | None = None
    timing: dict[str, float]


def _reader_role(request: Request) -> str | None:
    a = _acct(request)
    return a["role"] if a else None


@router.post(
    "/explore",
    response_model=ExploreResponse,
    dependencies=[Depends(staff_up)],
)
async def post_explore(body: ExploreRequest, request: Request) -> ExploreResponse:
    """Every passage open to the AI on a topic, with a dated summary that cites
    them and the count of matching items that are not open to it."""
    from services.archive.explore import explore, topic_terms

    if not topic_terms(body.query):
        raise HTTPException(status_code=422, detail="Give a topic: a word or a phrase.")
    out = await asyncio.to_thread(
        explore,
        body.query.strip(),
        summarize_it=body.summarize,
        role=_reader_role(request),
    )
    out["passages"] = [p.__dict__ for p in out["passages"]]
    return ExploreResponse(**out)


class PersonTitle(BaseModel):
    title: str
    isbn: str | None = None
    role: str
    pub_date: str | None = None


class PersonSummary(BaseModel):
    name: str
    relationship: list[str]
    titles: list[str]
    # Documents open to the reader that connect to the person, and the span of
    # their dates (an ISO date or a bare year); None when none is dated.
    document_count: int = 0
    first_date: str | None = None
    last_date: str | None = None


class PersonItem(PassageBase):
    connection: Connection
    connections: list[Connection]


class PersonRecord(BaseModel):
    name: str
    relationship: list[str]
    titles: list[PersonTitle]
    items: list[PersonItem]
    rows: list[TimelineRow]
    not_open: NotOpen
    # The earliest and latest date among the items shown (an ISO date, or a
    # bare year when that is all the item has). None when no item is dated.
    first_date: str | None = None
    last_date: str | None = None


@router.get(
    "/people",
    response_model=list[PersonSummary],
    dependencies=[Depends(staff_up)],
)
def get_people(request: Request) -> list[PersonSummary]:
    """The people the catalog credits, with their relationship to the press and
    how many documents open to the reader connect to them, and from when to when."""
    from services.archive.people import people_list
    from services.db import get_db

    conn = get_db()
    try:
        return [PersonSummary(**p) for p in people_list(conn, _reader_role(request))]
    finally:
        conn.close()


@router.get(
    "/people/{name}",
    response_model=PersonRecord,
    dependencies=[Depends(staff_up)],
)
def get_person(name: str, request: Request) -> PersonRecord:
    """Every item open to the AI that connects to one person, each marked
    signed, wrote, received or mentioned, plus the count of connected items
    that are not open to it."""
    from services.archive.people import date_span, record
    from services.db import get_db

    conn = get_db()
    try:
        rec = record(conn, name, _reader_role(request))
    finally:
        conn.close()
    if rec is None:
        raise HTTPException(
            status_code=404, detail="Nothing in the archive on this name."
        )
    items = []
    for hit, conns in rec["items"]:
        d = dict(hit.__dict__)
        d.pop("how", None)
        d.pop("matched", None)
        items.append(PersonItem(**d, connection=conns[0], connections=conns))
    dates = date_span(items)
    return PersonRecord(
        **{**rec, "items": items},
        first_date=dates[0] if dates else None,
        last_date=dates[-1] if dates else None,
    )
