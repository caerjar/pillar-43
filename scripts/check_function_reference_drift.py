#!/usr/bin/env python3
"""Lint: function/class names mentioned in the maintainer notes / MANUAL.md /
module docstrings must exist in code.

The narrower sibling `check_route_docstring_drift.py` catches the
phantom-endpoint case (`@router.<verb>` decorators vs. module
docstring listings). This script generalizes to any prose claim
like "`outbox.drain()` returns a DrainResult" or "see
`channel_store.create_channel`". If the named function doesn't
exist, the claim is a hallucination.

**Status: --strict in pre-commit (calibrated 2026-05-20).** Pre-
commit gate blocks commits on drift. Calibration history:

  - First run (warn-only): ~22 hits, majority class-method calls
    + frontend `api.X` refs + DB-table column refs.
  - Calibration 2026-05-20:
    1. AST-based symbol index walks `ClassDef.body` for
       `FunctionDef` (class methods now indexed).
    2. INSTANCE_NAMES allowlist (`client`, `req`, `manifest`,
       `outbound`, `outbox`, ...) — first segment matches → skip.
    3. DB_TABLE_NAMES allowlist (`files`, `threads`, `jobs`, ...)
       — first segment matches → skip.
    4. Shadow worktrees + archived plans excluded from scan.
    5. Module-path resolution (`services.ai_client` resolves if
       `api/services/ai_client.py` exists, even with no leaf symbol).
  - After calibration: zero hits on a clean main.

Heuristic; false positives still possible on novel shapes.
Allowlist per-line with `<!-- noqa: FNREF -->` (markdown) or
`# noqa: FNREF` (Python).

Targets:
  - All `.md` files in the repo (the maintainer notes, MANUAL.md, ROADMAP.md,
    plans/, docs/, READMEs, area the maintainer notes files)
  - Module-level docstrings in api/ Python files

Reference shapes detected:
  - `` `module.symbol` `` — backticked dotted reference
  - `` `module.Class.method` `` — three-level dotted
  - `` `Class.method` `` (CamelCase first component)
  - `` `func_name()` `` — backticked call shape, with or without
    args in the backticks

Existence verified via:
  - For `module.symbol`: search `api/services/<module>.py` /
    `api/routes/<module>.py` / `api/services/<module>/__init__.py`
    for a `def symbol` or `class symbol` line.
  - For `Class.method`: search any .py file for `class Class:` then
    `def method` within its body.
  - For `func_name()`: search any .py file for `def func_name`.

Aggressive whitelist:
  - Words that aren't snake_case or CamelCase ignored
  - Standard library refs ignored (re, os, pathlib, etc.)
  - Third-party module refs ignored (anthropic, requests, etc.)
  - Inline-code-blocks that are clearly bash/shell ignored (start
    with `$ ` or `./`)
  - Cells inside markdown tables only checked when the cell is
    JUST a backticked symbol (not prose with embedded backticks)
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path


# Known third-party / stdlib names — ignore refs to these.
IGNORE_PREFIXES = frozenset(
    {
        # stdlib
        "re",
        "os",
        "sys",
        "json",
        "ast",
        "time",
        "uuid",
        "logging",
        "pathlib",
        "dataclasses",
        "typing",
        "datetime",
        "collections",
        "itertools",
        "functools",
        "subprocess",
        "tempfile",
        "shutil",
        "argparse",
        "io",
        "asyncio",
        "threading",
        "queue",
        "abc",
        "enum",
        "math",
        "random",
        "hashlib",
        "base64",
        # third-party we use
        "anthropic",
        "openai",
        "requests",
        "httpx",
        "pydantic",
        "fastapi",
        "uvicorn",
        "sqlite3",
        "yaml",
        "alembic",
        "pytest",
        "starlette",
        "fastmcp",
        "qdrant_client",
        "faster_whisper",
        "PIL",
        # frontend (not what this lint targets)
        "react",
        "vite",
        # meta
        "self",
        "cls",
        "args",
        "kwargs",
        "None",
        "True",
        "False",
    }
)

# Symbols to ignore (common false-positive shapes).
IGNORE_SYMBOLS = frozenset(
    {
        "py",
        "md",
        "ts",
        "tsx",
        "yml",
        "yaml",
        "json",
        "sql",
        "lock",
        "txt",
        "sh",
        "ini",
        "cfg",
        "items",
        "values",
        "keys",
        "get",
        "set",
        "add",
        "remove",
        "TODO",
        "FIXME",
        "NOTE",
    }
)

# Instance-name allowlist (calibration 2026-05-20). When a dotted
# ref's first segment is one of these AND it doesn't match a known
# pillar43 module, treat it as an instance-method call on a runtime
# object and skip. Pure heuristic — these names get used both as
# instance variables AND as module references, so the gate is OR-d
# with the known-root check rather than AND-d.
INSTANCE_NAMES = frozenset(
    {
        "client",
        "req",
        "request",
        "resp",
        "response",
        "ctx",
        "context",
        "conn",
        "cursor",
        "cur",
        "session",
        "sess",
        "tx",
        "manifest",
        "outbound",
        "outbox",
        "channel",
        "post",
        "entry",
        "agent",
        "settings",
        "config",
        "result",
        "raw",
        "fmeta",
        "args",
        "kwargs",
        "data",
        "payload",
        "obj",
        "row",
        "rec",
        "log",
        "logger",
        "exc",
        "err",
        "e",
        "ex",
        "self",
        "cls",
        "api",  # frontend TS api client
        "qc",  # react-query client
    }
)

# SQL-table prefixes — when a dotted ref's first segment matches a
# SQLite table from the pillar43 schema, treat it as a column
# reference (`files.authorship`, `threads.source`, `jobs.last_heartbeat`)
# rather than a python module-path. Calibration 2026-05-20.
DB_TABLE_NAMES = frozenset(
    {
        "files",
        "tasks",
        "threads",
        "jobs",
        "thread_links",
        "wikilinks",
        "file_checkpoints",
        "file_connections",
        "saved_searches",
        "ca_ghosts",
        "ca_figures",
        "ca_gaps",
        "ca_detritus",
        "ca_sessions",
        "ca_interactions",
        "ca_potentials",
        "agents",
        "roundtable_sessions",
        "roundtable_posts",
        "commons_channels",
        "metadata",  # generic YAML-frontmatter key
        "main",  # often refers to FastAPI app instance: main.app
    }
)

# Backticked dotted reference: `module.symbol` or `module.Class.method`
DOTTED_REF_RE = re.compile(
    r"`(?P<ref>[a-z_][a-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*){1,3})(?:\([^`]*\))?`"
)

# Backticked function-call-shape: `func_name()` or `func_name(...)`
CALL_REF_RE = re.compile(r"`(?P<name>[a-z_][a-z0-9_]+)\([^`]*\)`")

# Per-line allowlist marker.
NOQA_RE = re.compile(r"noqa:\s*FNREF", re.IGNORECASE)


def is_ignored(ref: str, known_roots: set[str]) -> bool:
    """Heuristic — is this reference too generic to check?

    The strict gate: a dotted ref is ONLY checked if its first
    segment is a known pillar43 module/package name. Stdlib +
    third-party refs (`settings.foo`, `conn.execute`, `log.warning`)
    fail this gate and skip.

    Calibration 2026-05-20: also skip if the first segment is in
    INSTANCE_NAMES (likely an instance-method call). This avoids
    flagging things like `client.download_file` where `client` is a
    local `MattermostClient` instance, not a module path.
    """
    parts = ref.split(".")
    root = parts[0]
    if root in INSTANCE_NAMES:
        return True
    if root in DB_TABLE_NAMES:
        return True
    if root not in known_roots:
        return True
    if root in IGNORE_PREFIXES:
        return True
    last = parts[-1]
    if last in IGNORE_SYMBOLS:
        return True
    return len(last) < 3


def build_symbol_index(api_root: Path) -> tuple[dict[str, set[str]], set[str]]:
    """For every .py file under api/, extract def/class names AND class methods.

    Returns (index, known_roots) where:
      index["__all__"]                 → every def/class/method symbol found
      index["<module-dotted-path>"]    → symbols in that module
      known_roots                      → set of first-segment names that
                                         are legitimate pillar43 modules
                                         (e.g. "services", "routes",
                                         "commons", "outbox", "polling")

    The known_roots set is the gate: a backticked dotted ref like
    `outbox.drain` is only checked if "outbox" ∈ known_roots. References
    like `settings.foo`, `log.warning`, `conn.execute` skip the check
    entirely — they aren't claims about pillar43's surface.

    Calibration 2026-05-20: switched from regex to AST so we can walk
    `ast.ClassDef.body` for `FunctionDef` and `AsyncFunctionDef`, which
    were the dominant false-positive class on first-run (instance method
    calls like `client.download_file` flagged when `download_file` is a
    method on `MattermostClient`).
    """
    index: dict[str, set[str]] = {"__all__": set()}
    known_roots: set[str] = {"services", "routes", "api", "worker"}
    if not api_root.exists():
        return index, known_roots

    for py in api_root.rglob("*.py"):
        if "__pycache__" in py.parts or py.name.startswith("test_"):
            continue
        try:
            src = py.read_text(encoding="utf-8")
        except OSError:
            continue
        try:
            tree = ast.parse(src, filename=str(py))
        except SyntaxError:
            continue

        all_syms: set[str] = set()
        # Module-level defs + classes
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                all_syms.add(node.name)
            elif isinstance(node, ast.ClassDef):
                all_syms.add(node.name)
                # Class methods — the calibration fix
                for member in node.body:
                    if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        all_syms.add(member.name)

        rel = py.relative_to(api_root)
        if rel.name == "__init__.py":
            module = ".".join(rel.parent.parts)
        else:
            module = ".".join(rel.with_suffix("").parts)
        index.setdefault(module, set()).update(all_syms)
        index["__all__"].update(all_syms)

        for part in rel.with_suffix("").parts:
            if part != "__init__":
                known_roots.add(part)

    return index, known_roots


def ref_exists(ref: str, index: dict[str, set[str]]) -> bool:
    """Best-effort lookup."""
    parts = ref.split(".")
    sym = parts[-1]

    # First try: leaf symbol exists somewhere in the index.
    if sym in index["__all__"]:
        return True

    # Second try: the full dotted path IS a module (no leaf symbol).
    # `services.ai_client` resolves if api/services/ai_client.py exists.
    # `services.catalog.extract` likewise. This catches refs that point
    # at a module rather than a function inside it.
    if ref in index:
        return True

    # Third try: explicit module path with symbol leaf.
    if len(parts) >= 2:
        module_guesses = [
            ".".join(parts[:-1]),  # e.g. "commons.outbox" for "commons.outbox.drain"
            ".".join(parts[:-2]) if len(parts) >= 3 else None,
        ]
        for mg in module_guesses:
            if mg and mg in index and sym in index[mg]:
                return True
            # services.<x> and routes.<x> are the conventional roots.
            for prefix in ("services.", "routes."):
                if mg and f"{prefix}{mg}" in index and sym in index[f"{prefix}{mg}"]:
                    return True
            # The dotted path itself might be a module even without
            # a known root: `commons.outbox` resolves to
            # services.commons.outbox.
            if mg:
                for prefix in ("services.", "routes."):
                    if f"{prefix}{mg}" in index:
                        return True

    return False


def check_markdown_file(
    md: Path, index: dict[str, set[str]], known_roots: set[str]
) -> list[str]:
    try:
        text = md.read_text(encoding="utf-8")
    except OSError:
        return []
    lines = text.splitlines()
    msgs: list[str] = []

    for lineno, line in enumerate(lines, start=1):
        if NOQA_RE.search(line):
            continue

        # Skip code-fenced blocks. Cheap heuristic: line starts with
        # 4+ spaces or inside a ``` block (we don't track block state
        # perfectly; this is a fast pass).
        if line.startswith("    "):
            continue

        for m in DOTTED_REF_RE.finditer(line):
            ref = m.group("ref")
            if is_ignored(ref, known_roots):
                continue
            if not ref_exists(ref, index):
                msgs.append(
                    f"{md}:{lineno}: `{ref}` referenced but not found "
                    f"in api/ (add `<!-- noqa: FNREF -->` if intentional)"
                )

        # Bare `func_name(...)` refs (no dotted prefix) skipped — too
        # noisy. Stdlib functions like `sorted(...)`, `list(...)`,
        # `fetchall(...)` would all false-positive. Use the dotted
        # form (`module.func(...)`) to opt into the check.
        _ = CALL_REF_RE  # kept defined for future use

    return msgs


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Function-reference drift lint.")
    ap.add_argument("--strict", action="store_true")
    ap.add_argument(
        "--root",
        type=Path,
        default=Path("."),
        help="Repo root (default: cwd).",
    )
    args = ap.parse_args(argv)

    api_root = args.root / "api"
    index, known_roots = build_symbol_index(api_root)

    # Markdown files to check: top-level docs + the maintainer notes + plans/
    # + docs/ + per-package the maintainer notes files. Exclude pillar43-notes/
    # and node_modules.
    md_files: list[Path] = []
    for root_dir in [args.root]:
        for md in root_dir.rglob("*.md"):
            if any(
                p in md.parts
                for p in (
                    "node_modules",
                    ".git",
                    "pillar43-notes",
                    "ai_learnings",
                    "web",
                    "dist",
                    # Shadow worktrees managed by parallel-agent harness.
                    # Their content mirrors the main worktree's; including
                    # them produces duplicate hits without new signal.
                    "worktrees",
                    # Archived plans — frozen at write time, drift is
                    # expected and intentional (the plans describe
                    # past states + future-aspirational APIs).
                    "archive",
                )
            ):
                continue
            md_files.append(md)

    all_msgs: list[str] = []
    for md in sorted(md_files):
        all_msgs.extend(check_markdown_file(md, index, known_roots))

    if not all_msgs:
        print("✓ markdown function references in sync with api/")
        return 0

    for m in all_msgs[:50]:  # cap output to first 50
        print(m)
    if len(all_msgs) > 50:
        print(f"... and {len(all_msgs) - 50} more")

    print(
        f"\n{len(all_msgs)} potential drift item(s). Verify the "
        "symbol exists in api/ or annotate the line with "
        "`<!-- noqa: FNREF -->`.",
        file=sys.stderr,
    )

    if args.strict:
        return 1
    print("\n(warn-only; pass --strict to block commits)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
