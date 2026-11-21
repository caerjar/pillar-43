"""Read, mutate, and regenerate the extra-library bind-mount configuration.

Source of truth: `libraries.conf` at the repo root. The bash script
`scripts/gen-libraries-override.sh` reads it and writes
`docker-compose.override.yml` next to `docker-compose.yml`. This module is
the Python port the Settings route calls in-process.

**They are equivalent, not identical, and the difference is deliberate.** The
generated override carries a provenance header naming whichever one wrote it,
so the two differ by that line. More importantly the bash script only ever
*reads* `libraries.conf` — it never writes it — while this module owns both
files. Do not "fix" a diff between the two by making the headers match; the
header is how you tell which path produced the file you are looking at.

Why a Python port (instead of `subprocess.run("bash scripts/...")`):
- The api container doesn't ship bash scripts; the project root is
  bind-mounted in but the script may not even be on PATH.
- An in-process write is deterministic and unit-testable without docker.
- The bash script remains the legacy entry point for users editing the
  conf by hand; the Python here is what the UI calls. They must produce
  equivalent YAML for the override file (same mounts, same order), and
  both must EMPTY the override rather than delete it — see
  `regenerate_override`.

Paths are env-overridable so tests can point at tmp dirs:
  - LIBRARIES_CONFIG_PATH  → default /app/libraries.conf
  - DOCKER_OVERRIDE_PATH   → default /app/docker-compose.override.yml

In production these are bind-mounts of the host repo-root files (see
`docker-compose.yml`). Inside the container, the api writes to the
in-container path; docker propagates the write back to the host.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Dict, List, Tuple

import yaml

logger = logging.getLogger(__name__)

_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_ENTRY_RE = re.compile(r"^\s*([A-Za-z0-9_-]+)\s*=\s*(.+?)\s*$")


def _conf_path() -> Path:
    return Path(os.getenv("LIBRARIES_CONFIG_PATH", "/app/libraries.conf"))


def _override_path() -> Path:
    return Path(os.getenv("DOCKER_OVERRIDE_PATH", "/app/docker-compose.override.yml"))


def validate_name(name: str) -> None:
    """Raise ValueError if name contains characters that aren't [A-Za-z0-9_-]."""
    if not name or not _NAME_RE.match(name):
        raise ValueError(f"Library name must be alphanumeric (plus _ and -): {name!r}")


# Characters that change how the path is read once it sits in
# `- <path>:/libraries/<name>:ro` (compose splits on `:`), in YAML (`#`, quotes)
# or in libraries.conf (a newline starts another entry). A real host path may
# contain a space, but not at either end.
_BAD_PATH_CHARS = frozenset(":#\"'`\\")


def validate_host_path(host_path: str) -> None:
    """Raise ValueError unless `host_path` is a plain absolute host path.

    Rejects: not absolute, the bare root, `:` `#` quotes backtick backslash,
    control characters (newline, tab, NUL ...), and leading or trailing space.
    A path that passes cannot change the meaning of the bind-mount string it
    is rendered into, so a library can only ever mount what it names, read-only.
    """
    if not host_path or not host_path.startswith("/"):
        raise ValueError(f"Library path must be absolute (start with /): {host_path!r}")
    if host_path != host_path.strip(" "):
        raise ValueError(
            f"Library path must not start or end with a space: {host_path!r}"
        )
    if host_path == "/":
        raise ValueError("Library path must not be the filesystem root")
    if any(c in _BAD_PATH_CHARS or ord(c) < 32 or ord(c) == 127 for c in host_path):
        raise ValueError(
            f"Library path must not contain : # quotes, backslash or control characters: {host_path!r}"
        )


def read_entries() -> Dict[str, str]:
    """Return name→host_path mapping from `libraries.conf`.

    Returns empty dict if file is missing. Skips comments (`#`) and blank
    lines. Malformed lines are silently skipped to match the bash script's
    behaviour.
    """
    path = _conf_path()
    if not path.exists():
        return {}
    entries: Dict[str, str] = {}
    for raw in path.read_text().splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        m = _ENTRY_RE.match(stripped)
        if not m:
            continue
        name, host_path = m.group(1), m.group(2).rstrip()
        entries[name] = host_path
    return entries


def _write_file(path: Path, text: str) -> None:
    """Write `text` to `path`, atomically where that is possible.

    Prefers the usual write-to-`.tmp`-then-rename, which is what runs in tests
    and whenever the parent directory is writable.

    **In the api container it cannot.** `docker-compose.yml` bind-mounts
    libraries.conf and docker-compose.override.yml as individual FILES so the
    rest of the project root can stay read-only, and a per-file bind mount
    defeats atomic replacement from both ends. Measured, not assumed:

      - creating the sibling `.tmp` fails — the parent is the read-only root
        mount (EROFS)
      - `os.replace` from a writable directory such as /tmp fails with EXDEV,
        because the mounted file is its own device

    In-place writing is what remains. The window is one truncate-then-write of
    a file measured in hundreds of bytes, and both files are recoverable — the
    override regenerates from libraries.conf, and a torn libraries.conf costs
    the user re-adding their library paths through Settings. That is a smaller
    exposure than handing the container write access to .git and .env, which
    is what the read-write project root did.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_text(text)
    except OSError:
        # Read-only parent — the per-file bind-mount case. Write in place.
        path.write_text(text)
        return
    try:
        os.replace(tmp, path)
    except OSError:
        # Cross-device: the target is its own bind mount. Write in place and
        # clean up the tmp we did manage to create.
        path.write_text(text)
        tmp.unlink(missing_ok=True)


def _write_entries(entries: Dict[str, str]) -> None:
    """Write the conf file. Atomic where the filesystem allows — see `_write_file`.

    Preserves the canonical header comment so the file remains
    human-editable. Entries are emitted in insertion order.
    """
    path = _conf_path()
    header = (
        "# Extra read-only library bind mounts. One per line as "
        "`name = /host/path`.\n"
        "# Names may use [A-Za-z0-9_-]. Paths must be absolute.\n"
        "# Edit via Settings → Paths → Add Library, or hand-edit then run\n"
        "# `scripts/gen-libraries-override.sh && docker compose up --build -d`.\n"
    )
    body_lines = [f"{name} = {p}" for name, p in entries.items()]
    body = "\n".join(body_lines)
    text = header + body + ("\n" if body else "")
    _write_file(path, text)


def add_entry(name: str, host_path: str) -> None:
    """Add or replace the entry for `name`. Atomic; idempotent.

    Raises ValueError on invalid name or non-absolute host_path.
    """
    validate_name(name)
    validate_host_path(host_path)
    entries = read_entries()
    entries[name] = host_path
    _write_entries(entries)


def remove_entry(name: str) -> bool:
    """Remove the entry for `name`. Returns True if removed, False if absent."""
    entries = read_entries()
    if name not in entries:
        return False
    del entries[name]
    _write_entries(entries)
    return True


def _render_override_yaml(entries: List[Tuple[str, str]]) -> str:
    """Render the docker-compose.override.yml body. Matches gen-libraries-override.sh.

    Built as data and dumped with `yaml.safe_dump`, never by string formatting:
    the host path is user text, and formatting it into YAML let a crafted path
    add or rewrite mounts. Entries that fail validation (libraries.conf can be
    hand-edited) are left out.
    """
    volumes = []
    for name, host_path in entries:
        try:
            validate_name(name)
            validate_host_path(host_path)
        except ValueError:
            logger.warning("Skipping invalid library entry %r in libraries.conf", name)
            continue
        volumes.append(f"{host_path}:/libraries/{name}:ro")
    header = (
        "# Auto-generated by api/services/libraries_config.py — do not edit directly.\n"
        "# Update libraries.conf and re-run the regen flow, then: docker compose up --build -d\n"
    )
    # The `worker` service was folded into the API (2026-08-18) and no longer
    # exists. Emitting a second block for it is not merely redundant: compose
    # would merge it into a service with volumes and no image, which fails the
    # whole stack rather than being ignored.
    body = yaml.safe_dump(
        {"services": {"api": {"volumes": volumes}}},
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
    )
    return header + body


# What `regenerate_override` writes when there are no libraries configured.
# Comment-only: `docker compose` accepts it (verified against an empty file, a
# comment-only file, and `services: {}` — all three parse), and unlike a
# zero-byte file it cannot be mistaken for a truncated write.
_INERT_OVERRIDE = (
    "# Auto-generated by api/services/libraries_config.py — do not edit directly.\n"
    "# No extra libraries are configured, so this file deliberately declares\n"
    "# nothing. It is left in place rather than deleted because it is a\n"
    "# bind-mounted FILE: a container cannot unlink one (EBUSY), and if it is\n"
    "# missing when the stack comes up Docker silently creates a DIRECTORY at\n"
    "# that path instead. Add a library and this file is rewritten with mounts.\n"
)


def regenerate_override() -> Path:
    """Rewrite `docker-compose.override.yml` from `libraries.conf`.

    Mirrors `scripts/gen-libraries-override.sh`: with 0 entries the override is
    truncated to an inert comment-only file; otherwise it lists every entry as
    a bind mount under both the api and worker services.

    **It is emptied, never unlinked.** The file is bind-mounted from the host,
    and a bind-mounted file cannot be removed from inside a container — the
    unlink fails with EBUSY. That was the blocker that kept the project root
    mounted read-write for everything; emptying instead of deleting is what
    makes the narrow, file-scoped mount possible.

    Returns the override file path.
    """
    entries = list(read_entries().items())
    override = _override_path()
    override.parent.mkdir(parents=True, exist_ok=True)
    if not entries:
        _write_file(override, _INERT_OVERRIDE)
        return override
    _write_file(override, _render_override_yaml(entries))
    return override
