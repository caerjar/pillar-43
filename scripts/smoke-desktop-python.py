#!/usr/bin/env python3
"""Prove the pruned interpreter can still do its job. Run BY the bundled
interpreter, from scripts/build-desktop.sh, immediately after pruning.

This exists because `prune-desktop-python.sh` deletes files, and a deletion
fails at *runtime* — on a tester's machine, in a code path nobody exercised —
rather than at build time. Every prune there should have an assertion here, so
the failure lands in the build instead.

It deliberately does more than `import x`: the Drive check builds a real
service object, because the failure mode being guarded against is a discovery
document that was deleted while `import googleapiclient` still succeeds.

**That principle earned its keep, and was under-applied.** The macOS app
once shipped with an `openai` release against `httpx==0.28.1`, which removed
the `proxies` kwarg that release passes. `import openai` succeeded; building
the client raised `TypeError`, so every model provider was dead on arrival
while the whole backend suite stayed green. The hosted SDKs are gone, but
every model call still rides httpx, so the check below constructs its client.

So the rule for anything added below: **do the first real thing the app does
with it**, not `import x`.

Exits non-zero on any failure, which fails the build.
"""

from __future__ import annotations

import sys

failures: list[str] = []


def check(label: str, fn, *, must_fail: bool = False) -> None:
    """`must_fail` inverts the assertion — for things that must NOT be shipped."""
    try:
        result = fn()
    except Exception as exc:
        if must_fail:
            print(f"  ok    {label} — correctly absent ({type(exc).__name__})")
        else:
            failures.append(label)
            print(f"  FAIL  {label} — {type(exc).__name__}: {exc}")
        return
    if must_fail:
        failures.append(label)
        print(f"  FAIL  {label} — present, but must not be bundled")
    else:
        detail = f" — {result}" if result else ""
        print(f"  ok    {label}{detail}")


def drive_service() -> str:
    """The guard for the discovery-document prune.

    `build()` reads discovery_cache/documents/drive.v3.json when
    static_discovery is on. A wholesale delete of that directory leaves every
    import working and breaks only this, only when a user syncs Drive.
    """
    from googleapiclient.discovery import build

    build("drive", "v3", developerKey="smoke-test", static_discovery=True)
    return "built from the static discovery document"


def embeddings_stack() -> str:
    """ONNX is the reason the hardened runtime needs allow-jit; if the runtime
    is broken the process still starts and dies later, on the catalog pass."""
    import numpy
    import onnxruntime

    total = int(numpy.array([2, 3]).sum())
    assert total == 5, f"numpy arithmetic wrong: {total}"
    return f"onnxruntime {onnxruntime.__version__}, providers={len(onnxruntime.get_available_providers())}"


def httpx_client() -> str:
    """Construct the client, do not merely import the module.

    Every model call (Ollama chat, vision) goes through httpx. Building a
    Client is where an incompatible dependency pair raises, before any request,
    so no network is involved.
    """
    import httpx

    httpx.Client().close()
    return f"httpx {httpx.__version__} constructs"


print("smoke test — bundled interpreter")
print(f"  python {sys.version.split()[0]} at {sys.executable}")

check("embeddings stack (numpy + onnxruntime)", embeddings_stack)
check("fastembed", lambda: __import__("fastembed").__name__)
check("alembic", lambda: __import__("alembic").__version__)
check(
    "fastapi + uvicorn",
    lambda: (__import__("fastapi"), __import__("uvicorn")) and "both import",
)
check("lxml.etree", lambda: __import__("lxml.etree", fromlist=["etree"]).__name__)
check("PIL.Image", lambda: __import__("PIL.Image", fromlist=["Image"]).__name__)
check("pillow_heif", lambda: __import__("pillow_heif").__name__)
check("cryptography", lambda: __import__("cryptography").__version__)
check("pypdf", lambda: __import__("pypdf").__name__)
check("certifi", lambda: __import__("certifi").where().rsplit("/", 1)[-1])
check("google drive v3", drive_service)
check("httpx client constructs", httpx_client)

# Not a dependency check — a size check. faster-whisper is omitted from
# requirements-desktop.txt because it drags ctranslate2 + av for ~51MB and needs
# an ffmpeg the bundle does not ship. If it reappears, that omission regressed.
check("anthropic NOT bundled", lambda: __import__("anthropic"), must_fail=True)
check("openai NOT bundled", lambda: __import__("openai"), must_fail=True)
check(
    "faster_whisper NOT bundled", lambda: __import__("faster_whisper"), must_fail=True
)

print()
if failures:
    print(f"*** SMOKE TEST FAILED — {len(failures)} check(s): {', '.join(failures)}")
    sys.exit(1)
print("smoke test passed")
