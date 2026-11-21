#!/usr/bin/env python3
"""Lint: route module docstrings must match the actual @router.<verb>
decorators in the same file.

Catches the audit-2026-05-20-Critical-#2 class: `routes/commons.py:11`
documented `POST /api/commons/channels/{slug}/outbox/flush` as an
endpoint in its module docstring but no `@router.post("/channels/{slug}/outbox/flush")`
handler existed. The file-level docs drift check missed it because
the claim lived in a module docstring, not in the maintainer notes.

Stdlib only. Mirrors the shape of `check_module_readmes.py`:
warn-by-default, `--strict` flag for the pre-commit gate.

Exit codes:
    0  — every claimed endpoint has a handler; every handler is mentioned
    1  — drift detected on `--strict`; commit blocked
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path
from typing import NamedTuple


# Match endpoint claims in docstrings like:
#   GET    /api/commons/channels                       list all
#   POST   /api/commons/channels/{slug}/outbox/flush   force now
# Verb is one of GET/POST/PUT/PATCH/DELETE; path starts with /api/.
DOCSTRING_ENDPOINT_RE = re.compile(
    r"^\s*(GET|POST|PUT|PATCH|DELETE)\s+(/\S+)",
    re.MULTILINE,
)


class RouteClaim(NamedTuple):
    verb: str  # 'get', 'post', ...
    path: str  # path arg of @router.<verb>("...")
    source: str  # 'docstring' or 'decorator'
    line: int


def _normalize_path(path: str) -> str:
    """Strip leading prefix mismatches (`/api/commons/...` in docstring
    vs `/channels/...` in `@router.post(...)` when router has
    `prefix="/api/commons"`). For our purposes, compare suffixes.

    Returns a "match key": the path with leading `/api/<feature>/`
    optional and lowercased.
    """
    # Drop the `/api/<scope>` prefix if present so docstring claims
    # (full path) line up with @router decorators (router-prefix-
    # relative).
    p = path.strip().lower()
    # Strip query string + fragment.
    p = p.split("?", 1)[0].split("#", 1)[0]
    # Trailing slash is not a distinction FastAPI makes here, and a docstring
    # writing `/api/dispatch` must match a decorator that resolves to the same
    # endpoint. Keep bare "/" intact.
    if len(p) > 1:
        p = p.rstrip("/")
    return p


def _strip_prefix(path: str, router_prefix: str | None) -> str:
    """If a route has `prefix="/api/commons"` on its APIRouter and the
    decorator says `/channels/...`, the full path is `/api/commons/channels/...`.
    Use the router_prefix (if extractable) to reconstruct."""
    if router_prefix and not path.startswith(router_prefix):
        # `@router.get("")` on a prefixed router IS the prefix itself
        # (FastAPI registers `/api/dispatch`, not `/api/dispatch/`). Joining
        # blindly appended a trailing slash and reported one endpoint twice —
        # once as a phantom docstring claim, once as an undocumented handler.
        if not path.strip("/"):
            return router_prefix.rstrip("/")
        return router_prefix.rstrip("/") + "/" + path.lstrip("/")
    return path


def find_router_prefix(tree: ast.AST) -> str | None:
    """Scan module-level assignments for `router = APIRouter(prefix="/...")`."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id == "router":
                    if isinstance(node.value, ast.Call):
                        for kw in node.value.keywords:
                            if kw.arg == "prefix" and isinstance(
                                kw.value, ast.Constant
                            ):
                                return str(kw.value.value)
    return None


def extract_doc_claims(tree: ast.Module) -> list[RouteClaim]:
    """Pull module-level docstring claims."""
    if not tree.body or not isinstance(tree.body[0], ast.Expr):
        return []
    expr = tree.body[0]
    if not isinstance(expr.value, ast.Constant) or not isinstance(
        expr.value.value, str
    ):
        return []
    docstring = expr.value.value
    base_line = expr.lineno
    out = []
    for m in DOCSTRING_ENDPOINT_RE.finditer(docstring):
        verb = m.group(1).lower()
        path = m.group(2)
        # Approximate the line: base_line + line offset within docstring.
        offset = docstring[: m.start()].count("\n")
        out.append(
            RouteClaim(
                verb=verb, path=path, source="docstring", line=base_line + offset
            )
        )
    return out


def extract_decorator_routes(
    tree: ast.Module, router_prefix: str | None
) -> list[RouteClaim]:
    """Find every `@router.<verb>("<path>", ...)` and `@<x>.<verb>(...)`
    decorator. We assume the variable is `router` per project convention.
    """
    out = []
    for node in ast.walk(tree):
        decs = getattr(node, "decorator_list", None) or []
        for dec in decs:
            if not isinstance(dec, ast.Call):
                continue
            func = dec.func
            if not isinstance(func, ast.Attribute):
                continue
            if not isinstance(func.value, ast.Name) or func.value.id != "router":
                continue
            verb = func.attr.lower()
            if verb not in {"get", "post", "put", "patch", "delete"}:
                continue
            if not dec.args:
                continue
            first = dec.args[0]
            if not isinstance(first, ast.Constant) or not isinstance(first.value, str):
                continue
            path = _strip_prefix(first.value, router_prefix)
            out.append(
                RouteClaim(verb=verb, path=path, source="decorator", line=dec.lineno)
            )
    return out


def check_file(py_file: Path) -> list[str]:
    """Return a list of drift messages (empty if clean)."""
    try:
        text = py_file.read_text(encoding="utf-8")
        tree = ast.parse(text, filename=str(py_file))
    except SyntaxError:
        return [f"{py_file}: SyntaxError — skipping"]

    router_prefix = find_router_prefix(tree)
    doc_claims = extract_doc_claims(tree)
    decorator_routes = extract_decorator_routes(tree, router_prefix)

    if not doc_claims:
        return []  # No endpoint listing in docstring — nothing to check.

    msgs: list[str] = []

    doc_set = {(c.verb, _normalize_path(c.path)) for c in doc_claims}
    dec_set = {(c.verb, _normalize_path(c.path)) for c in decorator_routes}

    # Claimed in docstring but no decorator
    for c in doc_claims:
        key = (c.verb, _normalize_path(c.path))
        if key not in dec_set:
            msgs.append(
                f"{py_file}:{c.line}: docstring claims {c.verb.upper()} {c.path} "
                f"but no @router.{c.verb}() handler found"
            )

    # Decorator present but not mentioned in docstring (only if docstring
    # HAS endpoint listings — empty doc gets a pass). This catches
    # "added a route but forgot to update the docstring."
    for c in decorator_routes:
        key = (c.verb, _normalize_path(c.path))
        if key not in doc_set:
            msgs.append(
                f"{py_file}:{c.line}: @router.{c.verb}({c.path!r}) handler "
                f"exists but docstring doesn't list it"
            )

    return msgs


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Check route-module docstring claims match the actual handlers."
    )
    ap.add_argument(
        "--strict",
        action="store_true",
        help="Exit 1 on any drift. Default is warn-only (exit 0).",
    )
    ap.add_argument(
        "--api",
        type=Path,
        default=Path("api"),
        help="Path to api/ dir (default: api).",
    )
    args = ap.parse_args(argv)

    route_dirs = [args.api / "routes"]
    py_files: list[Path] = []
    for d in route_dirs:
        if d.exists():
            py_files.extend(d.glob("*.py"))
            py_files.extend(d.glob("*/*.py"))
    # Exclude __init__.py + __pycache__ noise.
    py_files = [
        f
        for f in py_files
        if "__pycache__" not in f.parts and not f.name.startswith("_pkg")
    ]

    all_msgs: list[str] = []
    for py in sorted(py_files):
        all_msgs.extend(check_file(py))

    if not all_msgs:
        print("✓ route docstrings in sync with handlers")
        return 0

    for m in all_msgs:
        print(m)

    print(
        f"\n{len(all_msgs)} drift item(s). "
        "Update the module docstring or implement the handler.",
        file=sys.stderr,
    )

    if args.strict:
        return 1
    print("\n(warn-only; pass --strict to block commits)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
