"""Press archive routes: profile, ask, items."""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from services.archive.org import load_org

router = APIRouter(prefix="/api/archive", tags=["archive"])


def _acct(request: Request) -> dict | None:
    """The signed-in account; None while the archive is still open (no
    accounts yet)."""
    return getattr(request.state, "account", None)


def staff_up(request: Request) -> None:
    a = _acct(request)
    if a is not None and a["role"] not in ("admin", "staff"):
        raise HTTPException(status_code=403, detail="Not allowed")


def admin_only(request: Request) -> None:
    a = _acct(request)
    if a is not None and a["role"] != "admin":
        raise HTTPException(status_code=403, detail="Not allowed")


def loopback_only(request: Request) -> None:
    from services.archive.accounts import is_loopback_host

    if not is_loopback_host(request.headers.get("host", "")):
        raise HTTPException(status_code=404, detail="Not found")


def _actor(request: Request, by: str | None) -> str:
    a = _acct(request)
    return a["name"] if a else (by or "admin")


def _require_account(request: Request) -> None:
    """403 while no account exists. Reads stay open on a fresh install so the
    first admin can be made, but nobody may withdraw an item or change what the
    model may read until someone is accountable for it."""
    if _acct(request) is None:
        raise HTTPException(
            status_code=403,
            detail="Create the administrator account first: withdrawing items "
            "and changing consent need a signed-in account.",
        )


def _may_control(request: Request, conn, path: str, *, staff_ok: bool = False) -> None:
    """403 unless the caller may act on this item: an admin, a writer who owns
    it, or (when `staff_ok`) staff. Open archive: anyone."""
    from services.archive.accounts import owns

    a = _acct(request)
    if a is None or a["role"] == "admin":
        return
    if a["role"] == "staff" and staff_ok:
        return
    if a["role"] == "writer" and owns(conn, a["id"], path):
        return
    raise HTTPException(status_code=403, detail="Not allowed")


# Only views that exist. The rest (titles, people, collections, recordings,
# intake, ledger) are added with their screens, not before.
ORG_NAV = ["ask", "files", "settings"]


class ProfileResponse(BaseModel):
    title: str | None = None
    org_name: str | None = None
    nav: list[str] = Field(default_factory=list)
    answer_model: str | None = None


@router.get("/profile", response_model=ProfileResponse)
def get_profile() -> ProfileResponse:
    """Readable without a session: the frontend asks this first to draw the
    title, the navigation, and whether to show a sign-in."""
    org = load_org()
    return ProfileResponse(
        title=org.title,
        org_name=org.org_name,
        nav=ORG_NAV,
        answer_model=org.answer_model,
    )


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


class QuoteOut(BaseModel):
    passage: int
    sentence: int
    text: str


class SentenceOut(BaseModel):
    text: str
    cites: list[int]
    quote: QuoteOut | None = None


class PassageOut(BaseModel):
    n: int
    path: str
    title: str
    kind: str
    chunk_id: int
    ordinal: int
    heading: str | None = None
    page: int | None = None
    work_title: str | None = None
    isbn: str | None = None
    sentences: list[str]
    annotations: list[dict] = Field(default_factory=list)


class SourceOut(BaseModel):
    path: str
    title: str
    kind: str | None = None


class ClosedNamedOut(BaseModel):
    path: str
    title: str
    kind: str | None = None
    state: str = "closed"  # "closed" or "withdrawn"
    reason: str = ""  # plain language: who closed it, or "withdrawn by its writer"


class ClosedByOut(BaseModel):
    """How many of the closed items each kind of actor closed."""

    writer: int = 0
    default: int = 0
    staff: int = 0


class NoDocumentOut(BaseModel):
    """The question names a title and a kind the archive does not hold."""

    title: str
    kind: str


class SilencesOut(BaseModel):
    """What the archive could not say; `line` is the one-sentence form."""

    closed: int = 0
    missing_correspondents: list[str] = Field(default_factory=list)
    empty_years: list[int] = Field(default_factory=list)
    closed_named: list[ClosedNamedOut] = Field(default_factory=list)
    closed_by: ClosedByOut | None = None
    no_document: NoDocumentOut | None = None
    line: str = ""


class AskResponse(BaseModel):
    question: str
    answer: list[SentenceOut]
    not_answered: bool
    would_answer: str | None = None
    passages: list[PassageOut]
    staff_only_sources: list[SourceOut]
    withheld_from_ai: int
    receipt_id: int | None = None
    answer_id: int | None = None
    silences: SilencesOut = Field(default_factory=SilencesOut)
    model: str
    timing: dict[str, float]


@router.post(
    "/ask",
    response_model=AskResponse,
    dependencies=[Depends(staff_up)],
)
async def post_ask(body: AskRequest) -> AskResponse:
    from services.archive.ask import ask

    try:
        out = await asyncio.to_thread(ask, body.question.strip())
    except OSError as exc:  # Ollama down or unreachable
        raise HTTPException(
            status_code=503, detail="The local model is not running."
        ) from exc
    return AskResponse(**{k: out[k] for k in AskResponse.model_fields})


class WithdrawRequest(BaseModel):
    path: str = Field(min_length=1)
    by: str = Field(default="admin", min_length=1)


@router.post("/withdraw")
def post_withdraw(body: WithdrawRequest, request: Request) -> dict:
    """A writer takes an item back: tombstone, forget, mark earlier answers."""
    from services.archive.withdraw import withdraw
    from services.db import get_db

    _require_account(request)
    conn = get_db()
    try:
        _may_control(request, conn, body.path)
        return withdraw(conn, body.path, by=_actor(request, body.by))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Not found") from exc
    finally:
        conn.close()


@router.get("/answers/{answer_id}", dependencies=[Depends(staff_up)])
def get_answer(answer_id: int) -> dict:
    """An earlier answer, with `withdrawn_sources` naming any cited item
    that has since been withdrawn."""
    from services.archive.answers import answer_view
    from services.db import get_db

    conn = get_db()
    try:
        out = answer_view(conn, answer_id)
    finally:
        conn.close()
    if out is None:
        raise HTTPException(status_code=404, detail="Not found")
    return out


@router.get("/ledger/verify", dependencies=[Depends(staff_up)])
def get_ledger_verify() -> dict:
    """Walk the hash chain; `ok` is false and `first_bad_seq` named if any
    line was edited or removed."""
    from services.archive.ledger import verify
    from services.db import get_db

    conn = get_db()
    try:
        return verify(conn)
    finally:
        conn.close()


@router.get("/ledger/{seq}", dependencies=[Depends(staff_up)])
def get_ledger_entry(seq: int, request: Request) -> dict:
    """One ledger line: an answer's receipt is the `model_call` line.

    Admins read any line. Staff read only a `model_call` whose items they may
    see; every other line (withdraw, owner, intake, consent) names item paths
    and hashes, and anything else answers 404 like a missing line."""
    from services.archive.access import staff_may_see
    from services.archive.ledger import entry
    from services.db import get_db

    conn = get_db()
    try:
        out = entry(conn, seq)
    finally:
        conn.close()
    a = _acct(request)
    if out is not None and a is not None and a["role"] != "admin":
        items = out["data"].get("items") if isinstance(out["data"], dict) else None
        ok = (
            out["kind"] == "model_call"
            and isinstance(items, list)
            and all(
                isinstance(i, dict) and staff_may_see(i.get("path", "")) for i in items
            )
        )
        if not ok:
            out = None
    if out is None:
        raise HTTPException(status_code=404, detail="Not found")
    return out


@router.get("/items/reads")
def get_item_reads(request: Request) -> list[dict]:
    """Each item staff may see, with how many times the AI read it."""
    from services.archive.access import staff_may_see_many
    from services.archive.labels import aipref_string
    from services.archive.ledger import reads_by_sha
    from services.db import get_db

    conn = get_db()
    try:
        reads = reads_by_sha(conn)
        rows = conn.execute(
            "SELECT path, sha256, kind, consent, labels FROM item ORDER BY path"
        ).fetchall()
    finally:
        conn.close()
    acct = _acct(request)
    if acct and acct["role"] == "writer":
        from services.archive.accounts import owned_paths

        conn = get_db()
        try:
            ok = owned_paths(conn, acct["id"])
        finally:
            conn.close()
    else:
        ok = staff_may_see_many(r[0] for r in rows)
    out = []
    for p, sha, k, c, lab in rows:
        if p not in ok:
            continue
        labels = json.loads(lab or "[]")
        out.append(
            {
                "path": p,
                "kind": k,
                "consent": c,
                "read_by_ai": reads.get(sha, 0),
                "labels": labels,
                "aipref": aipref_string(labels),
            }
        )
    return out


class LabelNotice(BaseModel):
    id: str
    name: str
    meaning: str
    aipref: str


class ReadEntry(BaseModel):
    at: str
    purpose: str
    receipt: int


class MyWorkItem(BaseModel):
    path: str
    title: str
    kind: str | None = None
    consent: str
    labels: list[LabelNotice]
    withdrawn_at: str | None = None
    reads: list[ReadEntry]


class MyWorkResponse(BaseModel):
    items: list[MyWorkItem]
    label_options: list[LabelNotice]


@router.get("/my-work", response_model=MyWorkResponse)
def get_my_work(request: Request) -> MyWorkResponse:
    """The writer's own items, their terms and the dated record of every time
    the AI read them. Writers only: staff and admins have no terms view of
    another writer's work. The question text is never returned."""
    from services.archive.mywork import label_catalogue, my_work
    from services.db import get_db

    acct = _acct(request)
    if acct is None or acct["role"] != "writer":
        raise HTTPException(status_code=403, detail="Not allowed")
    conn = get_db()
    try:
        items = my_work(conn, acct["id"])
    finally:
        conn.close()
    return MyWorkResponse.model_validate(
        {"items": items, "label_options": label_catalogue()}
    )


class LabelsRequest(BaseModel):
    path: str = Field(min_length=1)
    labels: list[str]
    by: str = Field(default="admin", min_length=1)


@router.post("/items/labels")
def post_item_labels(body: LabelsRequest, request: Request) -> dict:
    """Set a writer's terms (label ids from org.yaml) on an item."""
    from services.archive.labels import set_labels
    from services.db import get_db

    _require_account(request)
    conn = get_db()
    try:
        _may_control(request, conn, body.path)
        set_labels(conn, body.path, body.labels, by=_actor(request, body.by))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        conn.close()
    return {"path": body.path, "labels": sorted(set(body.labels))}


class AnnotationRequest(BaseModel):
    path: str = Field(min_length=1)
    body: str = Field(min_length=1, max_length=4000)
    by: str = Field(min_length=1)
    role: str | None = None
    ordinal: int | None = None


@router.post("/annotations")
def post_annotation(body: AnnotationRequest, request: Request) -> dict:
    """Attach a signed, dated note (the right of reply) to an item or to one
    passage (`ordinal`). Items staff may not see cannot be annotated."""
    from services.archive.access import staff_may_see
    from services.archive.annotations import add_annotation
    from services.db import get_db

    if not staff_may_see(body.path):
        raise HTTPException(status_code=404, detail="Not found")
    conn = get_db()
    try:
        _may_control(request, conn, body.path, staff_ok=True)
        acct = _acct(request)
        aid = add_annotation(
            conn,
            body.path,
            body.body,
            by=_actor(request, body.by),
            ordinal=body.ordinal,
            role=acct["role"] if acct else body.role,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        conn.close()
    return {"id": aid}


@router.get("/annotations")
def get_annotations(path: str, request: Request) -> list[dict]:
    """The live annotations on one item. Staff and admins, or the writer who
    owns the item: the same rule as /api/file."""
    from services.archive.annotations import list_annotations
    from services.db import get_db

    conn = get_db()
    try:
        _may_control(request, conn, path, staff_ok=True)
        return list_annotations(conn, path)
    finally:
        conn.close()


class RetractRequest(BaseModel):
    by: str = Field(min_length=1)


@router.post("/annotations/{annotation_id}/retract")
def post_annotation_retract(
    annotation_id: int, body: RetractRequest, request: Request
) -> dict:
    """Withdraw a note. It is hidden, not erased: the ledger keeps the line."""
    from services.archive.annotations import retract_annotation
    from services.db import get_db

    conn = get_db()
    try:
        acct = _acct(request)
        row = conn.execute(
            "SELECT author FROM annotation WHERE id = ?", (annotation_id,)
        ).fetchone()
        if acct and acct["role"] != "admin" and (row is None or row[0] != acct["name"]):
            raise HTTPException(status_code=403, detail="Not allowed")
        retract_annotation(conn, annotation_id, by=_actor(request, body.by))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Not found") from exc
    finally:
        conn.close()
    return {"id": annotation_id, "retracted": True}


@router.get("/gaps", dependencies=[Depends(staff_up)])
def get_gaps() -> dict:
    """What the press might collect next: the silences logged with every
    answer, aggregated (whose letters, which years)."""
    from services.archive.silences import gaps
    from services.db import get_db

    conn = get_db()
    try:
        return gaps(conn)
    finally:
        conn.close()


class ConsentRequest(BaseModel):
    path: str = Field(min_length=1)
    level: str


@router.post("/items/consent")
def post_item_consent(body: ConsentRequest, request: Request) -> dict:
    """Set an item's consent level. A writer sets it on their own items; an
    admin on any. Staff cannot: consent is the writer's to give."""
    from services.archive.items import ItemWithdrawn, set_consent
    from services.db import get_db

    _require_account(request)
    conn = get_db()
    try:
        _may_control(request, conn, body.path)
        set_consent(conn, body.path, body.level, by=_actor(request, None))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Not found") from exc
    except ItemWithdrawn as exc:
        raise HTTPException(
            status_code=409, detail="This item was withdrawn and cannot be reopened"
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        conn.close()
    return {"path": body.path, "consent": body.level}


class AccountRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    role: str
    password: str


@router.post(
    "/accounts",
    dependencies=[Depends(loopback_only), Depends(admin_only)],
)
def post_account(body: AccountRequest, request: Request) -> dict:
    """Create an account. Open until the first one exists, which must be an
    admin; after that only a signed-in admin."""
    from services.archive.accounts import create_account
    from services.db import get_db

    conn = get_db()
    try:
        create_account(
            conn, body.name, body.role, body.password, by=_actor(request, "setup")
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        conn.close()
    return {"name": body.name, "role": body.role}


@router.get(
    "/accounts",
    dependencies=[Depends(loopback_only), Depends(admin_only)],
)
def get_accounts() -> list[dict]:
    """Every account and the items linked to it (never password hashes)."""
    from services.db import get_db

    conn = get_db()
    try:
        out = []
        for aid, name, role in conn.execute(
            "SELECT id, name, role FROM account ORDER BY id"
        ).fetchall():
            paths = [
                r[0]
                for r in conn.execute(
                    "SELECT path FROM item_owner WHERE account_id = ? ORDER BY path",
                    (aid,),
                )
            ]
            out.append({"name": name, "role": role, "items": paths})
        return out
    finally:
        conn.close()


class OwnerRequest(BaseModel):
    paths: list[str]


@router.post(
    "/accounts/{name}/items",
    dependencies=[Depends(loopback_only), Depends(admin_only)],
)
def post_account_items(name: str, body: OwnerRequest, request: Request) -> dict:
    """Link items to an account: what a writer may control."""
    from services.archive.accounts import link_items
    from services.db import get_db

    conn = get_db()
    try:
        link_items(conn, name, body.paths, by=_actor(request, "admin"))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Not found") from exc
    finally:
        conn.close()
    return {"name": name, "items": sorted(body.paths)}


class LoginRequest(BaseModel):
    name: str
    password: str


@router.post("/login")
def post_login(body: LoginRequest, response: Response) -> dict:
    """Sign in. Sets an HttpOnly, SameSite=Strict session cookie.

    Not `loopback_only`: the web container's proxy rewrites `Host` to the api
    service name, so a loopback check on `Host` refused every browser sign-in
    (404 through :5221, 200 on :8071). Writers sign in from their own devices
    (concept-org 8.2); DNS rebinding is covered by TrustedHostMiddleware.
    Account administration stays loopback-only."""
    from services.archive.accounts import COOKIE, login
    from services.db import get_db

    conn = get_db()
    try:
        token = login(conn, body.name, body.password)
        role = None
        if token:
            row = conn.execute(
                "SELECT role FROM account WHERE name = ?", (body.name,)
            ).fetchone()
            role = row[0]
    finally:
        conn.close()
    if token is None:
        raise HTTPException(status_code=401, detail="Wrong name or password")
    response.set_cookie(COOKIE, token, httponly=True, samesite="strict", path="/")
    return {"name": body.name, "role": role}


@router.post("/logout")
def post_logout(request: Request, response: Response) -> dict:
    from services.archive.accounts import COOKIE, logout
    from services.db import get_db

    token = request.cookies.get(COOKIE)
    if token:
        conn = get_db()
        try:
            logout(conn, token)
        finally:
            conn.close()
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@router.get("/me")
def get_me(request: Request) -> dict:
    """The signed-in account (name and role), or `{"name": null}` while the
    archive is still open."""
    a = _acct(request)
    return {"name": a["name"], "role": a["role"]} if a else {"name": None, "role": None}


class OpenKind(BaseModel):
    kind: str
    count: int


class OpenToAi(BaseModel):
    total: int
    by_kind: list[OpenKind]


@router.get(
    "/open-to-ai",
    response_model=OpenToAi,
    dependencies=[Depends(staff_up)],
)
def get_open_to_ai() -> OpenToAi:
    """How many items the AI may read for a question, by kind. Same test as
    `ask`: consent `model` and every label permitting `ask`."""
    from services.archive.items import open_counts
    from services.db import get_db

    conn = get_db()
    try:
        counts = open_counts(conn)
    finally:
        conn.close()
    return OpenToAi(
        total=sum(counts.values()),
        by_kind=[OpenKind(kind=k, count=n) for k, n in counts.items()],
    )


class HighlightBox(BaseModel):
    x: float
    y: float
    w: float
    h: float


class PassageBoxes(BaseModel):
    page: int
    match: str
    boxes: list[HighlightBox]


@router.get(
    "/passage-boxes",
    response_model=PassageBoxes,
    dependencies=[Depends(staff_up)],
)
def get_passage_boxes(
    path: str, page: int, text: str = Query(max_length=3000)
) -> PassageBoxes:
    """Boxes (fractions of the page) for cited text on a PDF page. `match` is
    `exact`, `nearest` (best-matching lines) or `none`."""
    from config import settings
    from services.archive.highlight import locate

    try:
        resolved = settings.resolve(path)
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if resolved.suffix.lower() != ".pdf" or not resolved.is_file():
        raise HTTPException(status_code=404, detail="Not found")
    return PassageBoxes(**locate(resolved, page, text))
