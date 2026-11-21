"""Backup and restore of the governance state, as one SQLite file.

Consent (`item`), tombstones, accounts, the owners of items, withdrawn-answer
marks and the hash-chained `ledger` live in the same database as the rebuildable
search index. The index can be rebuilt from the documents; these tables cannot:
without the tombstones a re-intake registers withdrawn files again, and without
the ledger the record of who allowed what is gone. This module copies exactly
those tables.

`write_backup` uses SQLite's online backup API (a consistent snapshot while the
archive runs), drops everything that is not governance state, records where the
ledger stood in `backup_meta`, and verifies the chain of the copy before it
returns. `restore_backup` verifies the file first, refuses to replace a database
whose ledger is longer than (or has diverged from) the backup's unless forced,
replaces the tables in one transaction, and rolls back if the chain does not
hold afterwards. Sessions are not backed up; people sign in again.
"""

from __future__ import annotations

import contextlib
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from services.archive import ledger

GOVERNANCE_TABLES = (
    "item",
    "tombstone",
    "ledger",
    "account",
    "item_owner",
    "answer",
    "answer_citation",
    "annotation",
    "correspondent",
)


class BackupError(Exception):
    """A backup or restore that must not go ahead; the message says why."""


def _tables(conn: sqlite3.Connection, schema: str = "main") -> set[str]:
    return {
        r[0]
        for r in conn.execute(
            f"SELECT name FROM {schema}.sqlite_master WHERE type='table'"
        )
    }


def _columns(conn: sqlite3.Connection, table: str, schema: str = "main") -> list[str]:
    return [r[1] for r in conn.execute(f'PRAGMA {schema}.table_info("{table}")')]


def state(conn: sqlite3.Connection) -> dict:
    """What would be lost with the database: counts and where the ledger stands."""
    have = _tables(conn)

    def count(t: str) -> int:
        if t not in have:
            return 0
        return conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]

    last = None
    if "ledger" in have:
        last = conn.execute(
            "SELECT seq, hash FROM ledger ORDER BY seq DESC LIMIT 1"
        ).fetchone()
    return {
        "ledger_seq": last[0] if last else 0,
        "ledger_hash": last[1] if last else ledger.GENESIS,
        "items": count("item"),
        "tombstones": count("tombstone"),
        "accounts": count("account"),
    }


def write_backup(conn: sqlite3.Connection, dest: Path) -> dict:
    """Write the governance tables of `conn` to `dest`; verify the copy."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".partial")
    tmp.unlink(missing_ok=True)
    out = sqlite3.connect(str(tmp))
    try:
        conn.backup(out)  # consistent snapshot, even while the archive writes
        keep = set(GOVERNANCE_TABLES)
        for t in sorted(_tables(out) - keep):
            if t.startswith("sqlite_"):
                continue
            with contextlib.suppress(sqlite3.DatabaseError):
                # a shadow table of a virtual table that is already gone fails here
                out.execute(f'DROP TABLE IF EXISTS "{t}"')
        present = sorted(keep & _tables(out))
        if "ledger" not in present:
            raise BackupError("this database has no ledger; nothing to back up")
        s = state(out)
        out.execute("DROP TABLE IF EXISTS backup_meta")
        out.execute(
            "CREATE TABLE backup_meta (made_at TEXT, ledger_seq INTEGER, "
            "ledger_hash TEXT, tables TEXT)"
        )
        out.execute(
            "INSERT INTO backup_meta VALUES (?,?,?,?)",
            (
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
                s["ledger_seq"],
                s["ledger_hash"],
                ",".join(present),
            ),
        )
        out.commit()
        out.execute("VACUUM")
        chain = ledger.verify(out)
        if not chain["ok"]:
            raise BackupError(
                f"the ledger does not verify (first bad line {chain['first_bad_seq']}); "
                "backup not kept"
            )
        s["tables"] = present
        s["chain"] = chain
    except BaseException:
        out.close()
        tmp.unlink(missing_ok=True)
        raise
    out.close()
    tmp.replace(dest)
    return s


def _open_ro(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def check_backup(path: Path) -> dict:
    """Open a backup file read-only and verify its ledger chain."""
    path = Path(path)
    if not path.is_file() or path.stat().st_size == 0:
        raise BackupError(f"{path} is missing or empty")
    conn = _open_ro(path)
    try:
        try:
            meta = conn.execute(
                "SELECT made_at, ledger_seq, ledger_hash, tables FROM backup_meta"
            ).fetchone()
        except sqlite3.DatabaseError as e:
            raise BackupError(
                f"{path} is not a Pillar-43 governance backup ({e})"
            ) from e
        if meta is None:
            raise BackupError(f"{path} is not a Pillar-43 governance backup")
        chain = ledger.verify(conn)
        if not chain["ok"]:
            raise BackupError(
                f"the ledger in {path} does not verify "
                f"(first bad line {chain['first_bad_seq']})"
            )
        if chain["entries"] != meta[1]:
            raise BackupError(
                f"{path} records {meta[1]} ledger lines but holds {chain['entries']}"
            )
        s = state(conn)
        s.update(made_at=meta[0], tables=meta[3].split(","), chain=chain)
        return s
    finally:
        conn.close()


def _same_history(live: sqlite3.Connection, path: Path, seq: int) -> bool:
    mine = live.execute("SELECT hash FROM ledger WHERE seq=?", (seq,)).fetchone()
    theirs = _open_ro(path)
    try:
        other = theirs.execute("SELECT hash FROM ledger WHERE seq=?", (seq,)).fetchone()
    finally:
        theirs.close()
    return mine is not None and other is not None and mine[0] == other[0]


def restore_backup(conn: sqlite3.Connection, path: Path, force: bool = False) -> dict:
    """Replace the governance tables in `conn` with those in the backup."""
    path = Path(path)
    info = check_backup(path)
    live = state(conn)
    if not force and live["ledger_seq"] > 0:
        if live["ledger_seq"] > info["ledger_seq"]:
            raise BackupError(
                f"the archive's ledger has {live['ledger_seq']} lines; the backup has "
                f"{info['ledger_seq']}. Restoring would lose "
                f"{live['ledger_seq'] - info['ledger_seq']} ledger line(s) and the "
                "consent changes they record. Make a fresh backup, or restore with "
                "--force if you mean to discard them."
            )
        if not _same_history(conn, path, live["ledger_seq"]):
            raise BackupError(
                "the archive's ledger and the backup's are not the same history "
                f"(they differ at line {live['ledger_seq']}). Restore with --force "
                "only if you mean to replace it."
            )
    conn.commit()
    conn.execute("ATTACH DATABASE ? AS bk", (str(path),))
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            for t in info["tables"]:
                if t not in _tables(conn):
                    raise BackupError(
                        f"this archive has no table {t}; update Pillar-43 to the "
                        "version that made the backup, then restore"
                    )
                theirs = _columns(conn, t, "bk")
                cols = [c for c in _columns(conn, t) if c in theirs]
                if not cols:
                    raise BackupError(
                        f"table {t} has no columns in common with the backup"
                    )
                names = ", ".join(f'"{c}"' for c in cols)
                conn.execute(f'DELETE FROM main."{t}"')
                conn.execute(
                    f'INSERT INTO main."{t}" ({names}) SELECT {names} FROM bk."{t}"'
                )
            if "session" in _tables(conn):
                conn.execute("DELETE FROM main.session")  # account ids may differ
            chain = ledger.verify(conn)
            if not chain["ok"] or chain["entries"] != info["ledger_seq"]:
                raise BackupError(
                    "after the restore the ledger does not verify (first bad line "
                    f"{chain['first_bad_seq']}); nothing was changed"
                )
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.execute("DETACH DATABASE bk")
    return {"restored": info["tables"], "chain": chain, "state": state(conn)}
