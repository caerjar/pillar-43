"""The old names (the first product name and the second) must not come back.

The project was renamed to pillar43 / Pillar-43 on 2026-11-20 (clean break; see
docs/rename-map.md). This test fails when either old word appears, in any case,
in a tracked file, except for the short allowlist below. Every entry has a reason.

It reads `git ls-files`, so untracked and ignored files (a local .env) are not
its business. The test container mounts the repo read-only at /repo
(docker-compose.test.yml); outside Docker it uses the checkout it lives in.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve()
REPO = Path("/repo") if Path("/repo/docker-compose.yml").exists() else _HERE.parents[2]

OLD_NAMES = re.compile(r"meridian|colophon", re.IGNORECASE)

# Whole files that keep the old names, and why.
ALLOWED_PATHS = {
    "CHANGELOG.md": "dated release entries; history is not rewritten",
    "NEXT.md": "live plan; names the out-of-repo paths below and the rename itself",
    "docs/rename-map.md": "the old -> new table is the record of the rename",
    "docs/sequence.md": "dated record of the prune run",
    "docs/prune-inventory.md": "dated record of the prune inventory",
    "api/tests/test_removed_routes_absent.py": "asserts /api/ai/meridian* stays gone",
    "api/tests/test_name_guard.py": "this file",
}
ALLOWED_PREFIXES = {
    "docs/audits/": "dated audit reports written under the old names",
    "docs/eval/": "dated eval records written under the old names",
}

# Exact strings removed from a file's text before it is checked.
# The person and the person's site: not renamed.
PERSON = ["Eon Meridian", "eonmeridian.github.io"]
# "colophon" is the ordinary book term for the generated document of models,
# consent and withholding (2026-11-20). Only these exact uses stay.
BOOK_TERM = [
    "COLOPHON.md",
    "write_colophon",
    "test_colophon_names_models_consent_withholding_and_ledger_head",
    "# Colophon:",
    "archive_cli.py colophon",
    'add_parser("colophon")',
    '("job", "stats", "colophon")',
    "CLI colophon",
    "`stats`, `colophon`",
    "`stats` and `colophon`",
    "stats,colophon,counts",
]
STRIPPED = PERSON + BOOK_TERM


def _tracked_files() -> list[str]:
    out = subprocess.run(
        ["git", "-c", "safe.directory=*", "-C", str(REPO), "ls-files", "-z"],
        capture_output=True,
        check=False,
    )
    if out.returncode != 0:
        pytest.fail(
            f"git ls-files failed in {REPO}: {out.stderr.decode()[:300]}\n"
            "A test container started before the /repo mount was added needs "
            "recreating: ./scripts/test-api --down, then run again."
        )
    return [p for p in out.stdout.decode().split("\0") if p]


def _allowed(path: str) -> bool:
    return path in ALLOWED_PATHS or any(path.startswith(p) for p in ALLOWED_PREFIXES)


def _hits(path: str) -> list[tuple[int, str]]:
    try:
        text = (REPO / path).read_text(encoding="utf-8")
    except (UnicodeDecodeError, FileNotFoundError, IsADirectoryError):
        return []  # binary, deleted in the working tree, or a submodule
    for s in STRIPPED:
        text = text.replace(s, "")
    return [
        (n, line.strip()[:160])
        for n, line in enumerate(text.splitlines(), 1)
        if OLD_NAMES.search(line)
    ]


def test_no_old_names_in_tracked_files():
    found = []
    for path in _tracked_files():
        if OLD_NAMES.search(path):
            found.append(f"{path}: the file name itself")
        if _allowed(path):
            continue
        found += [f"{path}:{n}: {line}" for n, line in _hits(path)]
    assert not found, (
        "the old names meridian/colophon appeared outside the allowlist "
        "(see api/tests/test_name_guard.py):\n" + "\n".join(found)
    )


def test_allowlisted_paths_exist():
    tracked = set(_tracked_files())
    stale = [p for p in ALLOWED_PATHS if p not in tracked]
    assert not stale, f"allowlist entries that are not tracked files: {stale}"
