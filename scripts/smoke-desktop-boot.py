#!/usr/bin/env python3
"""Boot the bundled backend the way the Tauri shell does, and probe it.

Run from scripts/build-desktop.sh after the resources are staged.

## What this catches that nothing else does

`smoke-desktop-python.py` proves the dependencies import and construct.
`test-desktop-bundle` runs the unit suite against the bundle's dependency set.
Neither one *starts the application*. Between them they would pass on a build
whose Alembic chain fails against a fresh database, whose `validate_startup`
rejects its own mounts, whose static-file mount points nowhere, or that has a
router importing a name that no longer exists — a build that imports perfectly
and does not work.

That last one is not hypothetical: `routes/catalog/passes/threads.py` was
deleted in 2026-08-07 because `POST /threads/regenerate` imported a function
that had never existed.

## What it deliberately does not touch

A temporary vault and data directory, never `~/Pillar-43` or the real
Application Support directory. This runs in a build, unattended, and a smoke
test that writes into a user's archive is worse than no smoke test.

Exits non-zero on any failure, which fails the build.
"""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
RES = REPO / "desktop" / "src-tauri" / "resources"

# Generous, and for the same reason main.rs is: a first launch runs the whole
# migration chain. HEALTH_TIMEOUT there is 90s.
BOOT_TIMEOUT = 90.0


def free_port() -> int:
    """Mirrors `free_port()` in main.rs, including its race.

    There is a gap between releasing and the child binding. It is the same race
    every dev server on the machine runs, and a fixed port would collide with
    the Docker stack a developer may also have up.
    """
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def get(port: int, path: str, timeout: float = 10.0) -> tuple[int, str]:
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def main() -> int:
    python = RES / "python" / "bin" / "python3.12"
    entry = RES / "backend" / "app" / "backend_main.py"
    for p in (python, entry):
        if not p.exists():
            print(f"  FAIL  missing {p} — run build-desktop.sh first")
            return 1

    port = free_port()
    failures: list[str] = []

    with tempfile.TemporaryDirectory(prefix="pillar43-boot-") as tmp:
        root = Path(tmp)
        vault, data = root / "vault", root / "data"
        for d in (vault / "notes", vault / "generated", vault / "library", data):
            d.mkdir(parents=True)

        # The same environment main.rs:168-180 passes. Keep in step with it —
        # a divergence here means this proves a configuration the app never
        # actually runs in.
        env = {
            **os.environ,
            "PILLAR43_DESKTOP": "1",
            "PILLAR43_PORT": str(port),
            "NOTES_PATH": str(vault / "notes"),
            "GENERATED_PATH": str(vault / "generated"),
            "LIBRARY_ROOT": str(vault / "library"),
            "DATA_PATH": str(data),
            "LIBRARIES_CONFIG_PATH": str(data / "libraries.conf"),
            "PILLAR43_LOCATIONS_PATH": str(data / "locations.json"),
            "WEB_DIST_PATH": str(RES / "web"),
            "FASTEMBED_CACHE_PATH": str(RES / "models"),
            "PILLAR43_HELP_SEED": str(RES / "seed" / "help" / "manual.md"),
            "PYTHONPATH": str(RES / "backend" / "api"),
        }
        env.pop("PYTHONHOME", None)

        print("boot smoke test — bundled backend")
        print(f"  port {port}, vault {vault}")

        child = subprocess.Popen(
            [str(python), str(entry)],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        try:
            started = time.time()
            healthy = False
            while time.time() - started < BOOT_TIMEOUT:
                if child.poll() is not None:
                    out = child.stdout.read() if child.stdout else ""
                    print(f"  FAIL  backend exited early (code {child.returncode})")
                    print("  ---- output ----")
                    print("\n".join(out.splitlines()[-40:]))
                    return 1
                try:
                    code, _ = get(port, "/health", timeout=2.0)
                    if code == 200:
                        healthy = True
                        break
                except OSError:
                    pass
                time.sleep(0.4)

            if not healthy:
                print(f"  FAIL  /health never answered within {BOOT_TIMEOUT:.0f}s")
                return 1
            print(f"  ok    /health in {time.time() - started:.1f}s")

            # Real routes, not just liveness. `/api/settings` exercises the
            # config layer and every effective_* getter; local-models exercises
            # the provider path that the openai/httpx break lived on.
            for path, want in (("/api/settings", 200), ("/api/ai/local-models", 200)):
                code, body = get(port, path)
                if code != want:
                    failures.append(path)
                    print(f"  FAIL  {path} → {code}: {body[:200]}")
                else:
                    print(f"  ok    {path} → {code}")

            # The settings payload should carry the desktop signal, since that
            # is what the whole run is pretending to be.
            code, body = get(port, "/api/settings")
            if code == 200:
                try:
                    if json.loads(body).get("desktop_mode") is not True:
                        failures.append("desktop_mode")
                        print("  FAIL  desktop_mode not true in a desktop boot")
                    else:
                        print("  ok    desktop_mode reported true")
                except json.JSONDecodeError:
                    failures.append("settings json")
                    print("  FAIL  /api/settings did not return JSON")

            # The migration chain ran against a genuinely fresh database. If
            # Alembic had failed, main.py logs and carries on — so the file's
            # absence is the only evidence.
            if not (data / "pillar43.db").exists():
                failures.append("database")
                print("  FAIL  no pillar43.db — the migration chain did not run")
            else:
                print("  ok    database created and migrated")

        finally:
            # Every exit path. A leaked backend holds the port, the SQLite file
            # and a live scheduler, and the next launch starts a second one
            # against the same database — see backend_main.py's own docstring.
            if child.poll() is not None:
                # Already dead — it crashed, and the caller has printed why.
                # Claiming "exited on SIGTERM" here reads as a passing check
                # directly under a failure.
                pass
            else:
                child.send_signal(signal.SIGTERM)
                try:
                    child.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=5)
                    failures.append("shutdown")
                    print("  FAIL  did not exit on SIGTERM (killed)")
                else:
                    print("  ok    exited on SIGTERM")

    print()
    if failures:
        print(f"*** BOOT SMOKE FAILED — {len(failures)}: {', '.join(failures)}")
        return 1
    print("boot smoke test passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
