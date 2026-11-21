"""Local Archive command line (organization edition). Runs in the api container.

python scripts/archive_cli.py intake
    Register every file under the library mount as an item: hash, kind and
    default consent from org.yaml. Original folders are kept as they are.
    Existing items keep their consent. Tombstoned files are refused.
python scripts/archive_cli.py index
    Extract, chunk and embed every file under library/ with the local
    embedder, so Ask can retrieve. No AI summaries.
python scripts/archive_cli.py consent <path|kind:NAME|glob:PATTERN|person:ADDRESS> <private|staff|model> [--by NAME]
python scripts/archive_cli.py withdraw <path|person:ADDRESS> [--by NAME]
    Tombstone the item's bytes, forget it from search, mark earlier answers.
python scripts/archive_cli.py labels <path> [label ...] [--by NAME]
    Set a writer's terms (label ids from org.yaml); no labels clears them.
python scripts/archive_cli.py account <name> <admin|staff|writer> <password>
    Create a local account (the first must be an admin).
python scripts/archive_cli.py owner <name> <path> [path ...]
    Link items to a writer: what they may control.
python scripts/archive_cli.py ask "<question>" [--unconstrained]
python scripts/archive_cli.py job <editorial-history|teaching-packet|rights-answer> "<title or ISBN>" [--cover-note]
    Assemble a folder under generated/archive/jobs/ from consent- and
    label-filtered items, with manifest.json (labels, ledger receipts). Without
    --cover-note no model reads anything and staff-level items enter; the
    cover note is the only model call, and with it only model-level items do.
python scripts/archive_cli.py stats      # generated/archive/stats.json (code only)
python scripts/archive_cli.py colophon   # generated/archive/COLOPHON.md (code only)
python scripts/archive_cli.py counts
python scripts/archive_cli.py backup <file|->      # governance state -> one file (- = stdout)
python scripts/archive_cli.py backup-check <file|->  # verify a backup's ledger chain
python scripts/archive_cli.py restore <file|-> [--force]
python scripts/archive_cli.py ledger-state        # key=value lines, for the shell guards
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import settings
from services.archive.items import (
    ItemWithdrawn,
    TombstonedError,
    register_item,
    set_consent,
)
from services.archive.mail import MAIL_EXTENSIONS, register_mail
from services.db import get_db

SKIP_NAMES = {".DS_Store", "Thumbs.db"}


def intake() -> dict:
    root = Path(settings.library_root)
    conn = get_db()
    stats: Counter = Counter()
    refused: list[str] = []
    mail = {"messages": 0, "attachments": 0, "refused": 0}
    threads: set[str] = set()
    try:
        for f in sorted(root.rglob("*")):
            if not f.is_file() or f.name in SKIP_NAMES or f.name.startswith("._"):
                continue
            rel = "library/" + f.relative_to(root).as_posix()
            try:
                r = register_item(conn, rel, f)
            except TombstonedError:
                refused.append(rel)
                continue
            stats[f"{r['kind']}:{r['consent']}"] += 1
            stats["new" if r["new"] else "existing"] += 1
            if f.suffix.lower() == ".docx":
                from services.archive.docx_changes import register_changes

                register_changes(conn, rel, f)
            if f.suffix.lower() in MAIL_EXTENSIONS:
                m = register_mail(conn, rel, f)
                mail["messages"] += m.messages
                mail["attachments"] += m.attachments
                mail["refused"] += m.refused
                threads |= {f"{rel}#{t}" for t in m.threads}
    finally:
        conn.close()
    out: dict = {
        "counts": dict(sorted(stats.items())),
        "refused_tombstoned": len(refused),
    }
    if mail["messages"] or mail["refused"]:
        out["mail"] = {**mail, "threads": len(threads)}
    return out


def consent(target: str, level: str, by: str) -> int:
    conn = get_db()
    try:
        if target.startswith("person:"):
            from services.archive.correspondents import record_consent

            return len(record_consent(conn, target[7:], level, by=by))
        if target.startswith("kind:"):
            paths = [
                r[0]
                for r in conn.execute(
                    "SELECT path FROM item WHERE kind = ?", (target[5:],)
                )
            ]
        elif target.startswith("glob:"):
            from fnmatch import fnmatch

            pat = target[5:].lower()
            paths = [
                r[0]
                for r in conn.execute("SELECT path FROM item ORDER BY path")
                if fnmatch(r[0].lower(), pat)
            ]
        else:
            paths = [target]
        changed = 0
        for p in paths:
            try:
                set_consent(conn, p, level, by=by)
            except ItemWithdrawn:
                if target.startswith(("kind:", "glob:")):
                    continue  # a bulk rule skips what was withdrawn
                raise
            changed += 1
        return changed
    finally:
        conn.close()


def withdraw(path: str, by: str) -> dict:
    if path.startswith("person:"):
        from services.archive.correspondents import withdraw_person

        conn = get_db()
        try:
            return withdraw_person(conn, path[7:], by=by)
        finally:
            conn.close()
    from services.archive.withdraw import withdraw as _withdraw

    conn = get_db()
    try:
        return _withdraw(conn, path, by=by)
    finally:
        conn.close()


def counts() -> dict:
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT kind, consent, COUNT(*) FROM item GROUP BY kind, consent"
        ).fetchall()
        return {f"{k}:{c}": n for k, c, n in rows}
    finally:
        conn.close()


def governance_command(args) -> int:
    """backup / backup-check / restore / ledger-state. Returns the exit code.

    `-` means stdin or stdout, so the host keeps the file outside the Docker
    volume without a bind mount; messages go to stderr.
    """
    import shutil
    import tempfile

    from services.archive import backup as bk

    def say(msg: str) -> None:
        print(msg, file=sys.stderr)

    conn = get_db()
    tmpdir = tempfile.mkdtemp(prefix="p43-backup-")
    try:
        if args.cmd == "ledger-state":
            for k, v in bk.state(conn).items():
                print(f"{k}={v}")
            return 0
        if args.cmd == "backup":
            target = Path(tmpdir) / "governance.sqlite"
            if args.dest != "-":
                target = Path(args.dest)
            s = bk.write_backup(conn, target)
            say(
                f"backed up {s['ledger_seq']} ledger line(s), {s['items']} item(s), "
                f"{s['tombstones']} tombstone(s), {s['accounts']} account(s); "
                "ledger chain verified"
            )
            if args.dest == "-":
                with open(target, "rb") as f:
                    shutil.copyfileobj(f, sys.stdout.buffer)
                sys.stdout.buffer.flush()
            return 0
        src = Path(args.src)
        if args.src == "-":
            src = Path(tmpdir) / "in.sqlite"
            with open(src, "wb") as fout:
                shutil.copyfileobj(sys.stdin.buffer, fout)
        if args.cmd == "backup-check":
            s = bk.check_backup(src)
            say(
                f"backup ok: made {s['made_at']}, {s['ledger_seq']} ledger line(s), "
                "chain verified"
            )
            print(f"ledger_seq={s['ledger_seq']}")
            return 0
        r = bk.restore_backup(conn, src, force=args.force)
        say(
            f"restored {len(r['restored'])} table(s); ledger now "
            f"{r['chain']['entries']} line(s), chain verified. Sign in again."
        )
        return 0
    except bk.BackupError as e:
        say(f"refused: {e}")
        return 1
    finally:
        conn.close()
        shutil.rmtree(tmpdir, ignore_errors=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("intake")
    sub.add_parser("index")
    c = sub.add_parser("consent")
    c.add_argument("target")
    c.add_argument("level", choices=["private", "staff", "model"])
    c.add_argument("--by", default="admin")
    w = sub.add_parser("withdraw")
    w.add_argument("path")
    w.add_argument("--by", default="admin")
    lb = sub.add_parser("labels")
    lb.add_argument("path")
    lb.add_argument("labels", nargs="*")
    lb.add_argument("--by", default="admin")
    ac = sub.add_parser("account")
    ac.add_argument("name")
    ac.add_argument("role", choices=["admin", "staff", "writer"])
    ac.add_argument("password")
    ow = sub.add_parser("owner")
    ow.add_argument("name")
    ow.add_argument("paths", nargs="+")
    a = sub.add_parser("ask")
    a.add_argument("question")
    a.add_argument("--unconstrained", action="store_true")
    j = sub.add_parser("job")
    j.add_argument(
        "job", choices=["editorial-history", "teaching-packet", "rights-answer"]
    )
    j.add_argument("title")
    j.add_argument("--cover-note", action="store_true")
    sub.add_parser("stats")
    sub.add_parser("colophon")
    sub.add_parser("counts")
    sub.add_parser("ledger-state")
    bk = sub.add_parser("backup")
    bk.add_argument("dest")
    bc = sub.add_parser("backup-check")
    bc.add_argument("src")
    rs = sub.add_parser("restore")
    rs.add_argument("src")
    rs.add_argument("--force", action="store_true")
    args = ap.parse_args()

    if args.cmd == "intake":
        print(json.dumps(intake(), indent=2))
    elif args.cmd == "index":
        from services.archive.index import index_library

        print(json.dumps(index_library(), indent=2))
    elif args.cmd == "consent":
        print(
            f"{consent(args.target, args.level, args.by)} item(s) set to {args.level}"
        )
    elif args.cmd == "withdraw":
        print(json.dumps(withdraw(args.path, args.by), indent=2))
    elif args.cmd == "labels":
        from services.archive.labels import set_labels

        conn = get_db()
        try:
            set_labels(conn, args.path, args.labels, by=args.by)
        finally:
            conn.close()
        print(f"{args.path}: {sorted(set(args.labels))}")
    elif args.cmd in ("account", "owner"):
        from services.archive import accounts

        conn = get_db()
        try:
            if args.cmd == "account":
                accounts.create_account(
                    conn, args.name, args.role, args.password, by="cli"
                )
                print(f"account {args.name} ({args.role}) created")
            else:
                accounts.link_items(conn, args.name, args.paths, by="cli")
                print(f"{args.name}: {len(args.paths)} item(s) linked")
        finally:
            conn.close()
    elif args.cmd in ("job", "stats", "colophon"):
        from services.archive import jobs

        conn = get_db()
        try:
            if args.cmd == "job":
                fn = getattr(jobs, args.job.replace("-", "_"))
                print(fn(conn, args.title, cover_note=args.cover_note))
            elif args.cmd == "stats":
                print(jobs.write_stats(conn))
            else:
                print(jobs.write_colophon(conn))
        finally:
            conn.close()
    elif args.cmd in ("backup", "backup-check", "restore", "ledger-state"):
        sys.exit(governance_command(args))
    elif args.cmd == "counts":
        print(json.dumps(counts(), indent=2))
    elif args.cmd == "ask":
        from services.archive.ask import ask

        out = ask(args.question, constrained=not args.unconstrained)
        out.pop("raw", None)
        print(json.dumps(out, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
