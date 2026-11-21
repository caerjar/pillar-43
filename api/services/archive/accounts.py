"""Local accounts and roles for the organization edition. Minimal on purpose:
no OAuth, no email, nothing leaves the machine.

Roles
  admin   everything: accounts, links, consent on any item, intake.
  staff   asks, reads what consent opens to staff, annotates.
  writer  sees and controls only the items linked to them (consent, labels,
          withdraw, annotate). Never asks, never sees the ledger or gaps.

Decision (agent, needs maintainer review): a writer is tied to items by an explicit
`item_owner` link an admin sets (CLI `owner`, `POST /accounts/{name}/items`),
not by matching names in `item.people`: names are free text and a wrong match
would give someone control of a stranger's work. Matching `people` is a later
suggestion an admin can accept.

Until the first account exists the archive is open (a fresh install must be
able to make its admin); the first account has to be an admin. From then on
every archive route needs a session. Sessions are random tokens in an
HttpOnly, SameSite=Strict cookie; only their SHA-256 is stored. Passwords are
scrypt-hashed with a per-account salt. Login and account routes refuse a Host
header that is not loopback (the container is published on 127.0.0.1 only).
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import sqlite3
from datetime import datetime, timezone

from services.archive import ledger

ROLES = ("admin", "staff", "writer")
COOKIE = "pillar43_session"
MIN_PASSWORD = 8
_SCRYPT = {"n": 2**14, "r": 8, "p": 1}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def is_loopback_host(host: str) -> bool:
    h = (host or "").strip().lower()
    # "[::1]:8000" or "localhost:8000"
    h = h[1 : h.find("]")] if h.startswith("[") else h.split(":")[0]
    return h in ("localhost", "127.0.0.1", "::1")


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or os.urandom(16)
    dk = hashlib.scrypt(password.encode("utf-8"), salt=salt, dklen=32, **_SCRYPT)
    return f"scrypt${salt.hex()}${dk.hex()}"


def check_password(password: str, stored: str) -> bool:
    try:
        _, salt, dk = stored.split("$")
        got = hashlib.scrypt(
            password.encode("utf-8"), salt=bytes.fromhex(salt), dklen=32, **_SCRYPT
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(got.hex(), dk)


def accounts_exist(conn: sqlite3.Connection) -> bool:
    return conn.execute("SELECT 1 FROM account LIMIT 1").fetchone() is not None


def create_account(
    conn: sqlite3.Connection, name: str, role: str, password: str, *, by: str
) -> None:
    if role not in ROLES:
        raise ValueError(f"unknown role {role!r}")
    if len(password) < MIN_PASSWORD:
        raise ValueError(f"password must be at least {MIN_PASSWORD} characters")
    if not accounts_exist(conn) and role != "admin":
        raise ValueError("the first account must be an admin")
    try:
        with conn:
            conn.execute(
                "INSERT INTO account (name, role, password_hash, created_at) VALUES (?,?,?,?)",
                (name, role, hash_password(password), _now()),
            )
    except sqlite3.IntegrityError as exc:
        raise ValueError(f"account {name!r} exists") from exc
    ledger.append(conn, "account", by, name, {"role": role})


def login(conn: sqlite3.Connection, name: str, password: str) -> str | None:
    """A session token, or None. A wrong name costs the same as a wrong
    password (a hash is always computed)."""
    row = conn.execute(
        "SELECT id, password_hash FROM account WHERE name = ? AND disabled_at IS NULL",
        (name,),
    ).fetchone()
    stored = row[1] if row else hash_password("x" * MIN_PASSWORD)
    ok = check_password(password, stored)
    if not (row and ok):
        return None
    token = secrets.token_urlsafe(32)
    with conn:
        conn.execute(
            "INSERT INTO session (token_sha256, account_id, created_at) VALUES (?,?,?)",
            (hashlib.sha256(token.encode()).hexdigest(), row[0], _now()),
        )
    return token


def logout(conn: sqlite3.Connection, token: str) -> None:
    with conn:
        conn.execute(
            "DELETE FROM session WHERE token_sha256 = ?",
            (hashlib.sha256(token.encode()).hexdigest(),),
        )


def account_for_token(conn: sqlite3.Connection, token: str | None) -> dict | None:
    if not token:
        return None
    r = conn.execute(
        "SELECT a.id, a.name, a.role FROM session s JOIN account a ON a.id = s.account_id "
        "WHERE s.token_sha256 = ? AND a.disabled_at IS NULL",
        (hashlib.sha256(token.encode()).hexdigest(),),
    ).fetchone()
    return {"id": r[0], "name": r[1], "role": r[2]} if r else None


def link_items(
    conn: sqlite3.Connection, name: str, paths: list[str], *, by: str
) -> None:
    acct = conn.execute("SELECT id FROM account WHERE name = ?", (name,)).fetchone()
    if acct is None:
        raise KeyError(name)
    for p in paths:
        if conn.execute("SELECT 1 FROM item WHERE path = ?", (p,)).fetchone() is None:
            raise KeyError(p)
    with conn:
        for p in paths:
            conn.execute(
                "INSERT OR IGNORE INTO item_owner (path, account_id) VALUES (?,?)",
                (p, acct[0]),
            )
    ledger.append(conn, "owner", by, name, {"paths": sorted(paths)})


def owns(conn: sqlite3.Connection, account_id: int, path: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM item_owner WHERE path = ? AND account_id = ?",
            (path, account_id),
        ).fetchone()
        is not None
    )


def owned_paths(conn: sqlite3.Connection, account_id: int) -> set[str]:
    return {
        r[0]
        for r in conn.execute(
            "SELECT path FROM item_owner WHERE account_id = ?", (account_id,)
        )
    }
