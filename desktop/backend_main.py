"""Entry point for the backend sidecar.

Run by the bundled CPython interpreter that the Tauri shell spawns; also
runnable from a dev checkout, which is what the `sys.frozen` check at the
bottom used to distinguish. That check is now always false — PyInstaller was
dropped 2026-08-19 because Avast-engine antivirus quarantines its bootloader
as spyware. See plans/EMBEDDED_CPYTHON_SIDECAR.md.

Still imports the FastAPI app OBJECT rather than handing uvicorn the
"main:app" string. That began as a workaround for PyInstaller's static
analysis, which the string form defeated; it is kept because importing eagerly
surfaces a broken router at startup instead of on the first request.
"""

import os
import sys
import threading
import time


def _exit_with_parent() -> None:
    """Exit when the shell that spawned us goes away.

    The Tauri side kills the child on window-destroy, but that only covers a
    graceful quit. If the shell crashes or is force-killed, nothing fires and
    this process keeps running — holding the loopback port, the SQLite file and
    a live scheduler. The next launch then starts a *second* backend against the
    same database. Observed exactly that way while testing the bundle.

    macOS has no equivalent of Linux's PR_SET_PDEATHSIG, so the child watches
    instead: when the parent dies the process is reparented (ppid becomes 1, or
    simply changes), which is unambiguous and costs one syscall a second.
    """
    parent = os.getppid()
    if parent <= 1:
        return
    while True:
        time.sleep(1)
        if os.getppid() != parent:
            os._exit(0)


def main() -> None:
    import main as api_main
    import uvicorn

    # Desktop only: under Docker the container lifecycle owns the process and
    # there is no parent shell to outlive.
    if os.environ.get("PILLAR43_DESKTOP", "").strip().lower() in ("1", "true", "yes"):
        threading.Thread(target=_exit_with_parent, daemon=True).start()

    port = int(os.environ.get("PILLAR43_PORT", "8765"))
    uvicorn.run(api_main.app, host="127.0.0.1", port=port, log_level="info")


if __name__ == "__main__":
    if not getattr(sys, "frozen", False):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
    main()
