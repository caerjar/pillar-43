"""Jobs: the archive put to work (brief stage 6), plus stats.json and COLOPHON.md.

A job is a folder assembled by code, never by a model:

  generated/archive/jobs/<job>-<title>-<stamp>/
      manifest.json     every item included, in original (path) order, with its
                        labels, their aipref string, and its ledger receipt
      <job>.md          the text of the job
      items/NN-<name>   a copy of each item that is a file
      cover-note.md     only when asked for: <= 3 sentences, cites manifest numbers

Which items may enter is decided in one place: `labels.select_for(conn,
purpose, audience=...)` (consent the audience reaches, not withdrawn, every
label permits the purpose), then `items.allowed_paths(..)` as a second check.
An item that is private, withdrawn, or whose label denies the purpose is not
in the folder and not in the manifest; the manifest does not even count it.

The audience follows the cover note (2026-11-19). Without one no model
reads anything, so the job is staff work and takes staff-level items. With
`cover_note=True` the model reads the excerpts, so the whole job is built from
model-level items only.

Output goes to `generated/`: the app owns it and the AI never reads it back
(the maintainer notes, "Where AI output goes").

Purposes (org.yaml): each job has its own, so a label can allow or refuse it
alone: `editorial-history`, `teaching-packet`, and the rights answer is an
answer (`ask`). `export` stays for the catalog rows titles resolve against.
"""

from __future__ import annotations

import csv
import io
import json
import re
import shutil
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from config import settings
from services.archive import ledger
from services.archive.docx_changes import read_changes, render_changes
from services.archive.items import allowed_paths, item_meta
from services.archive.labels import aipref_string, select_for
from services.archive.org import load_org

COVER_NOTE_SYSTEM = (
    "You write a cover note for a folder of archive items. At most three "
    "sentences, plain statements about what the folder holds, using only the "
    "excerpts given. Cite each sentence with the item numbers it rests on. "
    'Reply as JSON: {"note": string, "cites": [int]}.'
)
_COVER_SCHEMA = {
    "type": "object",
    "properties": {
        "note": {"type": "string"},
        "cites": {"type": "array", "items": {"type": "integer"}},
    },
    "required": ["note", "cites"],
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def _slug(s: str) -> str:
    return _norm(s).replace(" ", "-") or "untitled"


def _disk(rel: str) -> Path:
    return Path(settings.library_root) / rel.removeprefix("library/")


# ── what may enter ──────────────────────────────────────────────────────────


def eligible(
    conn: sqlite3.Connection, purpose: str, audience: str = "model"
) -> list[str]:
    """Paths `audience` may use for `purpose`, in original (path) order."""
    paths = select_for(conn, purpose, audience=audience)
    ok = allowed_paths(conn, paths, audience, purpose)
    return sorted(p for p in paths if p in ok)


def _audience(cover_note: bool) -> str:
    return "model" if cover_note else "staff"


def _text_of(conn: sqlite3.Connection, rel: str) -> str:
    row = conn.execute(
        "SELECT extracted_text FROM files WHERE rel_path = ?", (rel,)
    ).fetchone()
    if row and row[0]:
        return row[0]
    return ""


def _catalog_rows(conn: sqlite3.Connection) -> list[dict]:
    """Catalog CSV rows from catalog items the export purpose allows."""
    out: list[dict] = []
    for p in eligible(conn, "export"):
        meta = item_meta(conn, [p])[p]
        if meta["kind"] != "catalog" or not p.endswith(".csv"):
            continue
        f = _disk(p)
        if f.is_file():
            out.extend(csv.DictReader(io.StringIO(f.read_text(encoding="utf-8"))))
    return out


def resolve_title(conn: sqlite3.Connection, query: str) -> tuple[str, str | None]:
    """(title, isbn13) for a title or ISBN as typed; unknown stays as typed."""
    q = _norm(query)
    qd = re.sub(r"\D", "", query)
    for r in _catalog_rows(conn):
        if q == _norm(r.get("title", "")) or (qd and qd == r.get("isbn13")):
            return r["title"], r.get("isbn13")
    return query.strip(), None


def _matches(title: str, isbn: str | None, rel: str, text: str, title_isbn) -> bool:
    nt = _norm(title)
    if isbn and title_isbn and re.sub(r"\D", "", str(title_isbn)) == isbn:
        return True
    if nt and (f" {nt} " in f" {_norm(text)} " or f" {nt} " in f" {_norm(rel)} "):
        return True
    return bool(isbn and isbn in re.sub(r"[-\s]", "", text))


# ── folder assembly ─────────────────────────────────────────────────────────


def _folder(job: str, title: str) -> Path:
    base = Path(settings.generated_path) / "archive" / "jobs"
    base.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    name = f"{job}-{_slug(title)}-{stamp}"
    for n in range(1, 100):
        d = base / (name if n == 1 else f"{name}-{n}")
        try:
            d.mkdir()
            return d
        except FileExistsError:
            continue
    raise RuntimeError("could not make a job folder")


def _manifest_items(
    conn: sqlite3.Connection, paths: list[str], folder: Path
) -> list[dict]:
    meta = item_meta(conn, paths)
    reads = ledger.reads_by_sha(conn)
    seqs = dict(
        conn.execute(
            f"SELECT path, ledger_seq FROM item WHERE path IN ({','.join('?' * len(paths))})",
            paths,
        )
        if paths
        else []
    )
    out = []
    for n, p in enumerate(paths, 1):
        m = meta[p]
        line = ledger.entry(conn, seqs[p]) if seqs.get(p) else None
        copied = None
        src = _disk(p)
        if "#" not in p and src.is_file():
            (folder / "items").mkdir(exist_ok=True)
            copied = f"items/{n:02d}-{src.name}"
            shutil.copy2(src, folder / copied)
        out.append(
            {
                "n": n,
                "path": p,
                "sha256": m["sha256"],
                "kind": m["kind"],
                "consent": m["consent"],
                "labels": sorted(m["labels"]),
                "aipref": aipref_string(m["labels"]),
                "receipt": {"seq": line["seq"], "hash": line["hash"]} if line else None,
                "read_by_ai": reads.get(m["sha256"], 0),
                "copy": copied,
            }
        )
    return out


def _cover_note(conn, job: str, title: str, entries: list[dict]) -> dict | None:
    from services.archive import ask as ask_mod

    if not entries:
        return None
    parts = []
    for e in entries:
        text = _text_of(conn, e["path"])[:600]
        parts.append(f"[{e['n']}] {e['path']}\n{text}")
    model = load_org().answer_model
    res = ask_mod.call_ollama(
        COVER_NOTE_SYSTEM,
        f"Folder: {job} for {title}\n\n" + "\n\n".join(parts),
        _COVER_SCHEMA,
        model,
    )
    try:
        got = json.loads(res["message"]["content"])
    except (KeyError, TypeError, ValueError):
        return None
    valid = {e["n"] for e in entries}
    cites = [c for c in got.get("cites", []) if c in valid]
    note = str(got.get("note", "")).strip()
    if not note or not cites:
        return None
    seq = ledger.append(
        conn,
        "model_call",
        "jobs",
        "",
        {
            "job": job,
            "model": model,
            "items": [{"path": e["path"], "sha256": e["sha256"]} for e in entries],
        },
    )
    return {"note": note, "cites": sorted(set(cites)), "model_call": seq}


def _finish(
    conn,
    job: str,
    title: str,
    isbn,
    purpose: str,
    audience: str,
    folder: Path,
    entries: list[dict],
    body: str,
    cover_note: bool,
) -> Path:
    (folder / f"{job}.md").write_text(body, encoding="utf-8")
    cover = _cover_note(conn, job, title, entries) if cover_note else None
    if cover:
        marks = " ".join(f"[{c}]" for c in cover["cites"])
        (folder / "cover-note.md").write_text(
            f"{cover['note']} {marks}\n", encoding="utf-8"
        )
    seq = ledger.append(
        conn,
        "job",
        "jobs",
        folder.name,
        {
            "job": job,
            "title": title,
            "purpose": purpose,
            "audience": audience,
            "items": [{"path": e["path"], "sha256": e["sha256"]} for e in entries],
        },
    )
    manifest = {
        "job": job,
        "title": title,
        "isbn": isbn,
        "built_at": _now(),
        "purpose": purpose,
        "audience": audience,
        "ledger_line": seq,
        "cover_note": {"model_call": cover["model_call"]} if cover else None,
        "items": entries,
    }
    (folder / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return folder


def _for_title(
    conn,
    title: str,
    purpose: str,
    audience: str,
    *,
    need_label: str | None = None,
):
    title, isbn = resolve_title(conn, title)
    meta_all = item_meta(conn, eligible(conn, purpose, audience))
    paths = []
    for p, m in meta_all.items():
        if need_label and need_label not in m["labels"]:
            continue
        if _matches(title, isbn, p, _text_of(conn, p), m["title_isbn"]):
            paths.append(p)
    return title, isbn, sorted(paths), meta_all


# ── clauses ─────────────────────────────────────────────────────────────────

_HEADING = re.compile(r"^(\d+)\. ([A-Z][^\n]{1,60})$")
_NOISE = re.compile(r"^(\[Page \d+\]|.* - Agreement .* - page \d+ of \d+)$")


def split_clauses(text: str) -> list[tuple[str, str]]:
    """[(\"7. Reversion\", body)] — body is the clause's lines as extracted."""
    clauses: list[tuple[str, list[str]]] = []
    for line in text.splitlines():
        if _NOISE.match(line.strip()):
            continue
        m = _HEADING.match(line.strip())
        if m:
            clauses.append((f"{m.group(1)}. {m.group(2)}", []))
        elif clauses and line.strip():
            clauses[-1][1].append(line.rstrip())
    return [(h, "\n".join(b)) for h, b in clauses]


# ── the three jobs ──────────────────────────────────────────────────────────


def rights_answer(conn, title: str, *, cover_note: bool = False) -> Path:
    title, isbn, paths, meta = _for_title(conn, title, "ask", _audience(cover_note))
    paths = [p for p in paths if meta[p]["kind"] == "contract"]
    folder = _folder("rights-answer", title)
    entries = _manifest_items(conn, paths, folder)
    body = [f"# Rights answer: {title}\n"]
    if not paths:
        body.append("No contract for this title is open to this job.\n")
    for e in entries:
        body.append(f"## [{e['n']}] {e['path']}\n")
        clauses = split_clauses(_text_of(conn, e["path"]))
        if not clauses:
            body.append(_text_of(conn, e["path"]) + "\n")
        for head, text in clauses:
            body.append(f"### {head}\n\n{text}\n")
    return _finish(
        conn,
        "rights-answer",
        title,
        isbn,
        "ask",
        _audience(cover_note),
        folder,
        entries,
        "\n".join(body),
        cover_note,
    )


def teaching_packet(conn, title: str, *, cover_note: bool = False) -> Path:
    title, isbn, paths, _ = _for_title(
        conn,
        title,
        "teaching-packet",
        _audience(cover_note),
        need_label="teaching_only",
    )
    folder = _folder("teaching-packet", title)
    entries = _manifest_items(conn, paths, folder)
    body = [
        f"# Teaching packet: {title}\n",
        "Items their writers opened for teaching only.\n",
    ]
    for e in entries:
        terms = e["aipref"] or "no aipref terms"
        body.append(f"- [{e['n']}] {e['path']} ({', '.join(e['labels'])}; {terms})")
    return _finish(
        conn,
        "teaching-packet",
        title,
        isbn,
        "teaching-packet",
        _audience(cover_note),
        folder,
        entries,
        "\n".join(body) + "\n",
        cover_note,
    )


def editorial_history(conn, title: str, *, cover_note: bool = False) -> Path:
    title, isbn, paths, meta = _for_title(
        conn, title, "editorial-history", _audience(cover_note)
    )
    paths = [
        p
        for p in paths
        if p.lower().endswith(".docx") or meta[p]["kind"] in ("letter", "email")
    ]
    folder = _folder("editorial-history", title)
    entries = _manifest_items(conn, paths, folder)
    body = [f"# Editorial history: {title}\n"]
    for e in entries:
        body.append(f"## [{e['n']}] {e['path']}\n")
        if e["path"].lower().endswith(".docx"):
            ch = read_changes(_disk(e["path"]))
            body.append((render_changes(ch) if ch else "No tracked changes.") + "\n")
        else:
            body.append(_text_of(conn, e["path"]).strip() + "\n")
    return _finish(
        conn,
        "editorial-history",
        title,
        isbn,
        "editorial-history",
        _audience(cover_note),
        folder,
        entries,
        "\n".join(body),
        cover_note,
    )


# ── stats.json and COLOPHON.md ──────────────────────────────────────────────


def compute_stats(conn: sqlite3.Connection) -> dict:
    cat = _catalog_rows(conn)
    years = Counter((r.get("pub_date") or "")[:4] for r in cat if r.get("pub_date"))
    langs = Counter(
        r["language_original"]
        for r in cat
        if ";" in (r.get("contributors") or "")
        and r.get("language_original", "English") != "English"
    )
    rows = conn.execute("SELECT path, kind, consent, withdrawn_at FROM item").fetchall()
    by_consent = Counter(r[2] for r in rows)
    by_kind = Counter(f"{r[1]}:{r[2]}" for r in rows)
    recs = [r[0] for r in rows if r[1] == "recording"]
    return {
        "titles": len(cat),
        "titles_by_year": dict(sorted(years.items())),
        "translations_by_language": dict(sorted(langs.items())),
        "recordings": len(recs),
        "readings": sum("reading" in Path(p).name.lower() for p in recs),
        "items": len(rows),
        "items_by_consent": dict(sorted(by_consent.items())),
        "items_by_kind_and_consent": dict(sorted(by_kind.items())),
        "withdrawn": sum(1 for r in rows if r[3]),
    }


def _out_dir() -> Path:
    d = Path(settings.generated_path) / "archive"
    d.mkdir(parents=True, exist_ok=True)
    return d


def write_stats(conn: sqlite3.Connection) -> Path:
    out = _out_dir() / "stats.json"
    out.write_text(json.dumps(compute_stats(conn), indent=2, ensure_ascii=False) + "\n")
    return out


def write_colophon(conn: sqlite3.Connection) -> Path:
    import os

    org = load_org()
    s = compute_stats(conn)
    chain = ledger.verify(conn)
    head = conn.execute(
        "SELECT seq, hash FROM ledger ORDER BY seq DESC LIMIT 1"
    ).fetchone()
    labelled = conn.execute(
        "SELECT COUNT(*) FROM item WHERE labels IS NOT NULL AND labels NOT IN ('', '[]')"
    ).fetchone()[0]
    L = [
        f"# Colophon: {org.title}",
        "",
        f"{org.org_name}. Generated {_now()} by code from the ledger and the item table; counts only, never contents.",
        "",
    ]
    L += ["## Models", ""]
    L += [
        f"- {role}: {name} (digest: not recorded here)"
        for role, name in sorted(org.models.items())
    ]
    L += ["", f"Code version: {os.getenv('PILLAR43_VERSION', 'unversioned')}", ""]
    L += ["## Consent", ""]
    L += [f"- {lvl}: {n}" for lvl, n in s["items_by_consent"].items()]
    L += ["", "## Items by kind and consent", ""]
    L += [
        f"- {k.replace(':', ' / ')}: {n}"
        for k, n in s["items_by_kind_and_consent"].items()
    ]
    L += ["", "## Withheld", ""]
    L += [
        f"- withdrawn by their writers: {s['withdrawn']}",
        f"- carrying a writer's label: {labelled} (terms follow {org.aipref_draft or 'no aipref draft'})",
        f"- private (never read by anyone but their writer): {s['items_by_consent'].get('private', 0)}",
    ]
    L += ["", "## Ledger", ""]
    L += [
        f"- entries: {chain['entries']}, chain {'holds' if chain['ok'] else 'BROKEN at ' + str(chain['first_bad_seq'])}",
        f"- head: {head[1] if head else 'none'} (line {head[0] if head else 0})",
        "",
        "Signed by: ______________________  Date: ____________",
        "",
    ]
    out = _out_dir() / "COLOPHON.md"
    out.write_text("\n".join(L), encoding="utf-8")
    return out
