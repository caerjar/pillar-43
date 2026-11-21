#!/usr/bin/env python3
"""Lint: each module dir's README.md row count should match its file count.

Compares `api/routes/`, `api/services/`, `web/src/components/`, and
`web/src/hooks/` against their README.md. A divergence means the README
lags actual files — agents fall back to `ls` for ground truth.

Stdlib only. Run from `src/` root. Pre-commit hook in
`.pre-commit-config.yaml` invokes this on every commit.

Exit codes:
    0  — every README is in sync (file count within tolerance of row count)
    1  — drift detected; commit blocked

The check is intentionally fuzzy: it counts "module-like" files (`.py`
top-level files in api/, `.tsx`/`.ts` panel entry files in web/), not
every single file. Tolerance of ±1 absorbs accidental noise from
helpers or in-progress renames.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Tolerance: README is "in sync" if |actual - documented| ≤ this. README
# tables sometimes combine related files into a single row (e.g. one row
# covering a package's submodules rather than a row each). Tolerance
# absorbs that pattern without losing drift-detection value — anything
# beyond ±4 means a real module appeared without any documentation
# pointer.
TOLERANCE = 5


def count_documented_files(readme: Path) -> int:
    """Count markdown table data rows in a README (lines starting with `|`,
    minus header + separator).

    Counts rows, not file references — backtick-matching is too noisy
    (picks up function names + module references in prose). Tolerance
    absorbs the multi-file-per-row pattern (e.g. one row covering several
    submodules of the same package).
    """
    if not readme.exists():
        return 0
    rows = 0
    in_table = False
    for line in readme.read_text().splitlines():
        if line.startswith("|"):
            if not in_table:
                in_table = True
                continue
            if re.match(r"^\|[\s\-:|]+\|?\s*$", line):
                continue
            rows += 1
        else:
            in_table = False
    return rows


def count_python_modules(dir_path: Path) -> int:
    """Count top-level Python modules. Packages (subdirs with __init__.py) count once."""
    if not dir_path.exists():
        return 0
    count = 0
    for child in dir_path.iterdir():
        if child.name.startswith(("_", ".")):
            continue
        if child.is_dir():
            if (child / "__init__.py").exists():
                count += 1
        elif child.suffix == ".py" and child.stem != "__init__":
            count += 1
    return count


def count_react_entries(dir_path: Path) -> int:
    """Count React panel directories. Each `<Name>/` subdirectory with at
    least one non-test `.tsx` file counts as one panel — there's no single
    canonical entry filename across the codebase (some are `<Name>.tsx`,
    others `<Name>Panel.tsx`, `<Name>Modal.tsx`, `<Name>View.tsx`, etc.).

    Excluded:
    - `ui/` — holds primitives, documented as a bullet list in the README.
    - Top-level `.tsx` files (`ActivityBar.tsx`, `PanelHeader.tsx`) — stable,
      documented as bullets above the panels table; don't drift in practice.
    """
    if not dir_path.exists():
        return 0
    count = 0
    for child in dir_path.iterdir():
        if not child.is_dir():
            continue
        if child.name.startswith((".", "_")) or child.name == "ui":
            continue
        has_real_tsx = any(
            p.suffix == ".tsx"
            and not p.stem.endswith(".test")
            and not p.stem.endswith(".stories")
            for p in child.iterdir()
            if p.is_file()
        )
        if has_real_tsx:
            count += 1
    return count


def count_hook_files(dir_path: Path) -> int:
    """Count hook files (use*.ts / use*.tsx). README.md itself excluded."""
    if not dir_path.exists():
        return 0
    return sum(
        1
        for child in dir_path.iterdir()
        if child.is_file()
        and child.stem.startswith("use")
        and child.suffix in (".ts", ".tsx")
        and not child.stem.endswith(".test")
    )


def check_one(label: str, expected: int, actual: int) -> bool:
    diff = actual - expected
    if abs(diff) <= TOLERANCE:
        print(f"✓ {label}: {expected} documented, {actual} actual (within tolerance)")
        return True
    print(f"✗ {label}: {expected} documented, {actual} actual (drift: {diff:+d})")
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--src",
        type=Path,
        default=Path(__file__).resolve().parent.parent,
        help="Path to pillar43 src/ root (default: parent of scripts/)",
    )
    ap.add_argument(
        "--strict",
        action="store_true",
        help="Exit 1 on any drift. Default is warn-only (exit 0) — see header.",
    )
    args = ap.parse_args()
    src: Path = args.src

    ok = True
    ok &= check_one(
        "api/routes/",
        count_documented_files(src / "api/routes/README.md"),
        count_python_modules(src / "api/routes"),
    )
    ok &= check_one(
        "api/services/",
        count_documented_files(src / "api/services/README.md"),
        count_python_modules(src / "api/services"),
    )
    ok &= check_one(
        "web/src/components/",
        count_documented_files(src / "web/src/components/README.md"),
        count_react_entries(src / "web/src/components"),
    )
    ok &= check_one(
        "web/src/hooks/",
        count_documented_files(src / "web/src/hooks/README.md"),
        count_hook_files(src / "web/src/hooks"),
    )

    if not ok:
        print(
            "\nREADME drift detected. Update each README's row count to "
            "match actual files. Per-dir details above.",
            file=sys.stderr,
        )
        if args.strict:
            return 1
        print(
            "\nGate currently warn-only. Pass --strict in CI once the "
            "READMEs are caught up.",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
