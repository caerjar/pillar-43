#!/usr/bin/env python3
"""Fail when a user-facing endpoint has no caller in the frontend.

This exists because the same mistake happened five times in this codebase: a
mechanism shipped complete and tested, and the thing that made it *reachable*
did not. `is_research` had no setter. `open_topic` had no caller.
`peer_derived` had no producer. The peer-facing prompt did not exist.
`patterns/accept` shipped with no UI at all.

Every one had passing tests, because the tests covered the piece rather than
the join. Vigilance did not catch any of them; this is the cheap structural
check instead.

Deliberately a pre-commit hook rather than a pytest test: the api test
container mounts only `./api`, so `web/src` is not visible from inside it. A
test written there passes by finding nothing — the exact shape of failure it
was meant to catch. (Learned the hard way: the first version of this was a
test, and its own self-check reported it inert.)

It is a string search, not a proof. It cannot tell whether a caller is
rendered, routed to, or dead code — only whether *anything* references the
endpoint. That is enough for the failure it targets.

Entries for the Commons, research-interest and peer-pattern endpoints were
removed with the frontend clients that called them (prune lane W2); those
routes are deleted from the API in the route lane.

Adding an entry below is a deliberate act. If an endpoint is internal, leave
it out and say so in its docstring; if it is user-facing, wiring the UI is
part of shipping it.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB_SRC = ROOT / "web" / "src"

# label → the URL fragment a frontend client would contain.
USER_FACING: dict[str, str] = {
    "apply a vault path change natively": "settings/apply-path",
}


def frontend_source() -> str:
    """All hand-written .ts/.tsx under web/src.

    `_generated.ts` is excluded on purpose: it names every route in the
    OpenAPI schema, so including it would make this pass for endpoints
    nothing calls — asserting the opposite of the point.
    """
    parts: list[str] = []
    for path in sorted(WEB_SRC.rglob("*.ts*")):
        if "_generated" in path.name:
            continue
        try:
            parts.append(path.read_text(encoding="utf-8"))
        except OSError:
            continue
    return "\n".join(parts)


def main() -> int:
    if not WEB_SRC.is_dir():
        print(f"web/src not found at {WEB_SRC} — cannot check reachability")
        return 1

    src = frontend_source()
    # Self-check: an empty read would make every assertion below vacuously
    # pass and silently stop guarding anything.
    if len(src) < 10_000:
        print(f"only {len(src)} chars of frontend source loaded — check is inert")
        return 1

    missing = [
        f"{label}  ({fragment})"
        for label, fragment in USER_FACING.items()
        if fragment not in src
    ]
    if missing:
        print("Endpoints with no caller in web/src — a user cannot reach these:\n")
        for line in missing:
            print(f"  {line}")
        print(
            "\nWire the UI, or if the endpoint is genuinely internal remove it "
            "from USER_FACING in this script and say why in its docstring."
        )
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
