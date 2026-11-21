#!/usr/bin/env python3
"""Lint: filesystem ops that join a path with attacker-controlled input
must sanitize the input first.

Catches the audit-2026-05-20-Critical-#1 class (`polling.py:173` joined
Mattermost-supplied `name` into `media/` and let `../../escape.bin` land
in the user's vault).

Heuristic — false positives are possible. Allowlist with the per-line
comment `# noqa: TRAVERSAL`.

Targets:
  - `Path(...) / name` where `name` is sourced externally without a
    sanitization guard within N lines above.
  - `os.path.join(..., name)` same pattern.

External-input heuristic:
  - Subscript on common request/event objects: `raw["..."]`,
    `fmeta.get(...)`, `req.json()[...]`, etc.
  - Function parameters whose name matches `*_name`, `filename`,
    `path`, `slug` and the function has no type annotation OR
    annotation `str`.

Sanitization heuristic (any of these within 10 lines above the
join):
  - `if <var> in (".", "..")` or similar literal check
  - `"/" in <var>` or `"\\" in <var>` check
  - `<var>.startswith(".")` check
  - Reassignment `<var> = Path(<orig>).name`
  - Reassignment `<var> = ... pathlib.Path(...).name`
  - Explicit `.relative_to(...)` call on the joined result
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path


# External-input heuristics: names + access patterns that imply
# attacker-controlled values.
SUSPICIOUS_NAME_RE = re.compile(
    r"^(?:.*_)?(name|filename|file_name|path|rel_path|slug|fname)$"
)
SUSPICIOUS_SOURCES = {"raw", "fmeta", "req", "request", "body", "post", "metadata"}

# Sanitization markers (substring search on the function body source).
SANITIZER_PATTERNS = [
    re.compile(r'in\s*\(\s*"\.\.?"\s*[,)]'),  # in (".", "..")
    re.compile(r'"/"\s*in\s+\w+'),  # "/" in x
    re.compile(r'"\\\\"\s*in\s+\w+'),  # "\\" in x
    re.compile(r"\.startswith\(\s*['\"]\."),  # x.startswith(".")
    re.compile(r"=\s*Path\([^)]+\)\.name"),  # x = Path(...).name
    re.compile(r"=\s*pathlib\.Path\([^)]+\)\.name"),
    re.compile(r"\.relative_to\("),  # resolved.relative_to(...)
    re.compile(r"noqa:\s*TRAVERSAL"),  # explicit allowlist
]


def is_suspicious_name(name: str) -> bool:
    return bool(SUSPICIOUS_NAME_RE.match(name)) or name in SUSPICIOUS_SOURCES


def is_path_div(node: ast.AST) -> ast.AST | None:
    """If `node` is a BinOp(op=Div) whose left side is a `Path(...)`
    call OR `Path() / x / y` chain that involves Path somewhere on
    the left, return the right-hand operand. Else None.
    """
    if not isinstance(node, ast.BinOp) or not isinstance(node.op, ast.Div):
        return None
    # Walk down the left chain looking for a Path() call.
    left = node.left
    has_path = False
    while isinstance(left, ast.BinOp) and isinstance(left.op, ast.Div):
        if _is_path_call(left.right) or _is_path_call(left.left):
            has_path = True
            break
        left = left.left
    if _is_path_call(left):
        has_path = True
    # Check the right-hand operand of the outermost expression: is it
    # a Name or Subscript that looks attacker-controlled?
    if not has_path:
        return None
    return node.right


def _is_path_call(node: ast.AST) -> bool:
    """True if node looks like Path(...) or pathlib.Path(...)."""
    if isinstance(node, ast.Call):
        f = node.func
        if isinstance(f, ast.Name) and f.id == "Path":
            return True
        if isinstance(f, ast.Attribute) and f.attr == "Path":
            return True
    return False


def is_path_join_call(node: ast.AST) -> ast.AST | None:
    """If `node` is `os.path.join(*args)`, return the last arg."""
    if not isinstance(node, ast.Call):
        return None
    f = node.func
    if isinstance(f, ast.Attribute) and f.attr == "join":
        if isinstance(f.value, ast.Attribute) and f.value.attr == "path":
            if isinstance(f.value.value, ast.Name) and f.value.value.id == "os":
                if node.args:
                    return node.args[-1]
    return None


def rhs_looks_external(node: ast.AST) -> bool:
    """Heuristic: does the RHS expression look like attacker-controlled
    input?
    """
    if isinstance(node, ast.Name):
        return is_suspicious_name(node.id)
    if isinstance(node, ast.Subscript):
        # x["key"] or x[var]
        if isinstance(node.value, ast.Name) and node.value.id in SUSPICIOUS_SOURCES:
            return True
        return rhs_looks_external(node.value)
    if isinstance(node, ast.Call):
        # x.get("key") on a suspicious source
        f = node.func
        if isinstance(f, ast.Attribute) and f.attr == "get":
            if isinstance(f.value, ast.Name) and f.value.id in SUSPICIOUS_SOURCES:
                return True
    if isinstance(node, ast.Attribute):
        # x.name where x is a suspicious source
        if isinstance(node.value, ast.Name) and node.value.id in SUSPICIOUS_SOURCES:
            return True
    return False


def find_enclosing_function(
    tree: ast.Module, target_line: int
) -> ast.FunctionDef | None:
    """Find the function whose body contains `target_line`."""
    best = None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.lineno <= target_line <= (node.end_lineno or target_line):
                if best is None or node.lineno > best.lineno:
                    best = node
    return best


def function_has_sanitizer(func: ast.FunctionDef, source: str) -> bool:
    """Return True if the function body contains any sanitization marker."""
    if func.end_lineno is None or func.lineno is None:
        return False
    body_text = "\n".join(source.splitlines()[func.lineno - 1 : func.end_lineno])
    return any(pat.search(body_text) for pat in SANITIZER_PATTERNS)


def line_has_noqa(source_lines: list[str], lineno: int) -> bool:
    if lineno < 1 or lineno > len(source_lines):
        return False
    return "noqa: TRAVERSAL" in source_lines[lineno - 1]


def check_file(py_file: Path) -> list[str]:
    try:
        source = py_file.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(py_file))
    except (SyntaxError, OSError):
        return []

    source_lines = source.splitlines()
    msgs: list[str] = []

    for node in ast.walk(tree):
        rhs = is_path_div(node) or is_path_join_call(node)
        if rhs is None:
            continue
        if not rhs_looks_external(rhs):
            continue

        line = getattr(node, "lineno", 0)
        if line_has_noqa(source_lines, line):
            continue

        func = find_enclosing_function(tree, line)
        if func is not None and function_has_sanitizer(func, source):
            continue

        # Describe the RHS.
        try:
            rhs_str = ast.unparse(rhs)
        except Exception:
            rhs_str = "<?>"

        msgs.append(
            f"{py_file}:{line}: filesystem join with attacker-controllable "
            f"RHS `{rhs_str}` without visible sanitizer "
            f"(add a check, or `# noqa: TRAVERSAL` if intentional)"
        )

    return msgs


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Path-traversal heuristic lint.")
    ap.add_argument("--strict", action="store_true")
    ap.add_argument(
        "--api",
        type=Path,
        default=Path("api"),
        help="Path to api/ dir (default: api).",
    )
    args = ap.parse_args(argv)

    scan_dirs = [args.api / "services", args.api / "routes"]
    py_files: list[Path] = []
    for d in scan_dirs:
        if d.exists():
            py_files.extend(d.rglob("*.py"))
    py_files = [
        f for f in py_files if "__pycache__" not in f.parts and "test_" not in f.name
    ]

    all_msgs: list[str] = []
    for py in sorted(py_files):
        all_msgs.extend(check_file(py))

    if not all_msgs:
        print("✓ no unguarded path joins with external input")
        return 0

    for m in all_msgs:
        print(m)

    print(
        f"\n{len(all_msgs)} potential traversal site(s). Add a "
        "sanitization guard (Path(x).name + reject '..'/'.' and "
        "separators) or annotate with # noqa: TRAVERSAL.",
        file=sys.stderr,
    )

    if args.strict:
        return 1
    print("\n(warn-only; pass --strict to block commits)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
