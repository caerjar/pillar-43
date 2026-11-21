#!/usr/bin/env bash
# Trim the bundled interpreter. Called by scripts/build-desktop.sh.
#
# Every deletion here is a judgement call that fails at RUNTIME rather than at
# build time, so each one carries its reason and `smoke-desktop-python.py` runs
# immediately afterwards to turn a bad prune into a failed build instead of a
# tester's crash. Add nothing here without adding a matching assertion there.
#
# Measured 2026-08-19: 460MB → 308MB. The PyInstaller bundle it replaces was
# 286MB, which it got by tree-shaking to only the modules it could prove were
# imported — an option a real interpreter does not have.
set -euo pipefail

P="${1:?usage: prune-desktop-python.sh <python-dir>}"
SP="$P/lib/python3.12/site-packages"
[ -d "$SP" ] || { echo "  ERROR: no site-packages at $SP" >&2; exit 1; }

before=$(du -sm "$P" | cut -f1)

# ── 1. Google API discovery documents ─────────────────────────────────────
# 532 static JSON descriptions, one per Google API, ~79MB. Pillar-43 builds
# exactly one service: `build("drive", "v3", ...)` in services/sources/
# google_drive.py:281.
#
# Keep drive.v3.json. Do NOT delete the directory wholesale: that call passes
# `cache_discovery=False`, which disables the HTTP-response *cache* and is
# unrelated — `static_discovery` still defaults to True when discoveryServiceUrl
# is unset, so this file is what Drive sync is built from. Deleting it breaks
# Drive at runtime with no build-time signal.
DOCS="$SP/googleapiclient/discovery_cache/documents"
if [ -d "$DOCS" ]; then
  find "$DOCS" -type f ! -name 'drive.v3.json' -delete
fi

# ── 2. Type stubs ─────────────────────────────────────────────────────────
# .pyi files are consumed by type checkers, never by the interpreter.
find "$P" -name '*.pyi' -delete 2>/dev/null || true

# ── 3. Packages' own test suites ──────────────────────────────────────────
find "$SP" -maxdepth 2 -type d \( -name tests -o -name test \) -exec rm -rf {} + 2>/dev/null || true

# ── 4. Ship bytecode, not source ──────────────────────────────────────────
# Two reasons, and the second is the one that matters:
#   - it removes the .py/.pyc duplication (~78MB of __pycache__)
#   - a signed .app is effectively read-only, and any __pycache__ written into
#     the bundle after signing INVALIDATES THE CODE SIGNATURE. Shipping .pyc
#     means the interpreter never needs to write one. main.rs also sets
#     PYTHONDONTWRITEBYTECODE=1; belt and braces.
# `-b` writes foo.pyc beside foo.py (legacy layout) instead of into a
# __pycache__ subdirectory, so deleting the .py leaves an importable module.
# Cost: tracebacks from bundled code lose their source lines.
"$P/bin/python3.12" -m compileall -q -b -f "$P/lib/python3.12" >/dev/null 2>&1 || true
find "$P/lib/python3.12" -name '*.py' -delete 2>/dev/null || true
find "$P" -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true

# ── 5. Redundant interpreter aliases ──────────────────────────────────────
# `bin/python` and `bin/python3` ship as symlinks to `python3.12`, which costs
# 9 bytes each in the tarball — but TAURI DEREFERENCES SYMLINKS when it copies
# resources into the .app, turning them into two more full 18.5MB copies of the
# interpreter. Measured: 307MB staged became 343MB bundled, all of it this.
#
# Safe to drop because main.rs spawns `python3.12` by its exact name. If you
# ever change that, change this.
rm -f "$P/bin/python" "$P/bin/python3"

# ── NOT pruned, deliberately ──────────────────────────────────────────────
# *.dist-info (~6MB): ~15 shipped packages read their own metadata through
# importlib.metadata at import time — alembic, fastembed, fastmcp,
# jsonschema, numpy, onnxruntime among them. Six megabytes is not worth an
# ImportError that only appears on a tester's machine.

after=$(du -sm "$P" | cut -f1)
echo "  pruned interpreter ${before}MB → ${after}MB"
