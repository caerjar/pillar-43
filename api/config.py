import json
import logging
import os
import shutil
import time
from pathlib import Path

_log = logging.getLogger(__name__)

# Module-level TTL cache for _load_overrides().
# Avoids reading and parsing pillar43.config.json on every settings access.
# Keys: "data" (parsed dict or None), "ts" (timestamp), "path" (config file path as str).
# Cache is invalidated when:
#   - The config path changes (e.g. monkeypatching generated_path in tests)
#   - The TTL of 5 seconds expires
#   - save_overrides() is called
# In TESTING=1 mode the TTL is 0 so every call re-reads from disk, keeping
# test assertions that write then immediately read the config file correct.
_OV_CACHE: dict = {"data": None, "ts": 0.0, "path": ""}
_OV_TTL = 0.0 if os.getenv("TESTING", "0") == "1" else 5.0

# Browser-facing base URL for the api, and therefore the HOST port — 8002,
# not the container's 8000. Keep in step with `API_PORT` in
# docker-compose.yml, which defaults to the same value; a mismatch sends
# every OAuth redirect to a port nothing is listening on. Imported by the
# source connectors rather than re-spelled, so the two cannot drift.
DEFAULT_API_BASE_URL = "http://127.0.0.1:8002"


def _desktop_mode() -> bool:
    """Is this the native macOS app rather than the Docker stack?

    Set by the Tauri shell when it spawns the backend. It is a deliberate
    explicit signal rather than something inferred (no "am I in a container?"
    heuristic), because the two runtimes differ in ways that must not be
    guessed at: under Docker a library reaches the app through a bind mount and
    changing one needs a compose regeneration and a restart, while natively the
    path in the config file *is* the path on disk and takes effect at once.
    """
    return os.getenv("PILLAR43_DESKTOP", "").strip().lower() in ("1", "true", "yes")


def _default_data_path() -> str:
    """Where the SQLite DB and model cache live when DATA_PATH is unset.

    The Tauri shell passes DATA_PATH explicitly, so this is the fallback for a
    frozen binary launched by hand — but it needs to be somewhere writable and
    conventional rather than `/generated`, which does not exist on a Mac.
    """
    explicit = os.getenv("DATA_PATH")
    if explicit:
        return explicit
    if _desktop_mode():
        return str(Path.home() / "Library" / "Application Support" / "Pillar-43")
    return os.getenv("GENERATED_PATH") or "/generated"


class Settings:
    # True in the native app, False under Docker. Read once at import — the
    # shell sets it before spawning, and it cannot change within a process.
    desktop_mode: bool = _desktop_mode()

    library_root: Path = Path(os.getenv("LIBRARY_ROOT", "/library"))
    notes_path: Path = Path(os.getenv("NOTES_PATH", "/notes"))
    generated_path: Path = Path(os.getenv("GENERATED_PATH", "/generated"))
    # Internal application state (SQLite DB). Backed by a named Docker volume,
    # not a bind mount — see services/db.py and docker-compose.yml for why.
    # When DATA_PATH is unset (tests, dev outside Docker), fall back to
    # generated_path so tests that monkeypatch only `generated_path` keep working.
    data_path: Path = Path(_default_data_path())
    extra_libraries_dir: Path = Path(os.getenv("EXTRA_LIBRARIES_DIR", "/libraries"))
    # Host-side paths — the actual filesystem paths on the user's machine.
    # Empty string means unknown (e.g. in test environments).
    host_library_root: str = os.getenv("HOST_LIBRARY_ROOT", "")
    host_notes_path: str = os.getenv("HOST_NOTES_PATH", "")
    host_generated_path: str = os.getenv("HOST_GENERATED_PATH", "")
    testing: bool = os.getenv("TESTING", "0") == "1"
    # When True (default), library/ is read-only — moves and folder creation are blocked.
    # Set LIBRARY_READONLY=false to allow reorganising vault files.
    library_readonly: bool = os.getenv("LIBRARY_READONLY", "true").lower() != "false"

    # When True, the catalog pass prunes auto-generated threads that don't
    # carry an open question or open task — keeps the Threads panel focused
    # on threads with actual signal. Off by default to preserve existing
    # behaviour; user opts in via Settings. See services/catalog/threads_pass.py:
    # _prune_threads_without_signal for the SQL rules.
    threads_require_signal: bool = (
        os.getenv("THREADS_REQUIRE_SIGNAL", "false").lower() == "true"
    )
    # "confirm" (default) requires the user to approve the link-change diff before
    # a move is committed.  "silent" moves immediately and rewrites links in one shot.
    move_confirm: str = os.getenv("MOVE_CONFIRM", "confirm")

    # Base URL the browser hits the api on. Used to construct OAuth
    # redirect URIs for source connectors (Google Drive, future
    # connectors). Users on non-default ports or behind a reverse proxy
    # override via API_BASE_URL. Trailing slashes are stripped at the
    # property to keep concatenation predictable.
    api_base_url: str = os.getenv("API_BASE_URL", DEFAULT_API_BASE_URL)

    @property
    def extra_library_mounts(self) -> "dict[str, Path]":
        """Extra read-only libraries, as mount name → path.

        Two runtimes, two sources of truth, and the difference is the whole
        reason `desktop_mode` exists:

        **Docker** — discovered by listing subdirectories of
        `EXTRA_LIBRARIES_DIR` (`/libraries`). The name→path mapping in
        `libraries.conf` is not read at runtime at all; it is compiled into
        bind mounts by `docker-compose.override.yml`, and a container only sees
        a library once it has been restarted with that mount in place.

        **Desktop** — read straight from `libraries.conf`, because the app is
        already on the host and the configured path *is* the path. There is no
        mount to arrange, so adding a library takes effect on the next call
        rather than the next restart. Non-existent paths are dropped rather
        than surfaced, matching what Docker does when a mount is missing.

        Evaluated per call in both modes, with no caching — several callers
        depend on a newly added library appearing without a process restart.
        """
        if self.desktop_mode:
            from services import libraries_config

            try:
                entries = libraries_config.read_entries()
            except OSError:
                _log.warning("could not read libraries.conf", exc_info=True)
                return {}
            return {
                name: Path(host_path)
                for name, host_path in sorted(entries.items())
                if Path(host_path).is_dir()
            }

        if not self.extra_libraries_dir.exists():
            return {}
        return {
            d.name: d
            for d in sorted(self.extra_libraries_dir.iterdir())
            if d.is_dir() and not d.name.startswith(".")
        }

    @property
    def all_mounts(self) -> "dict[str, Path]":
        """All known mount name → path mappings.

        Used everywhere a mount→path lookup is needed so new extra vaults
        automatically propagate to the tree, search, catalog, and AI routes
        without touching those files.
        """
        return {
            "notes": self.notes_path,
            "generated": self.generated_path,
            "library": self.library_root,
            **self.extra_library_mounts,
        }

    # ── Runtime config file ───────────────────────────────────────────────────
    # pillar43.config.json overrides env vars without requiring a restart.

    @property
    def _config_path(self) -> Path:
        """Where the runtime override file lives.

        **Docker: inside the vault** (`generated/`). Correct there — the mounts
        are bind mounts, so relocating one already means editing `.env` and
        recreating the container, and nothing can move out from under a
        running process.

        **Native app: `data_path`** (`~/Library/Application Support/Pillar-43`),
        which the shell computes *before* it knows where the vault is and which
        never moves. This file holds every API key, OAuth refresh token, SMTP
        password and bot token, plus `pending_path_changes` — the record of
        where the mounts are moving *to*. Inside `generated/` it was the one
        file that could not survive relocating `generated/`: the move would
        orphan the entire credential store, and the record of a pending move
        would live inside the mount it describes.

        See `_legacy_config_path` / `migrate_config_file` for installs that
        predate the move.
        """
        if self.desktop_mode:
            return self.data_path / "pillar43.config.json"
        return self.generated_path / "pillar43.config.json"

    @property
    def _legacy_config_path(self) -> Path:
        """Where the override file lived before it moved out of the vault."""
        return self.generated_path / "pillar43.config.json"

    def migrate_config_file(self) -> bool:
        """Copy a pre-move config file into `data_path`. Desktop only; idempotent.

        Returns True only when a copy actually happened, so callers can log or
        re-read. Never raises: a failure here must degrade to "no overrides
        yet", not stop the app from booting.

        **Copy, not move.** A user who rolls back to an older build must still
        find their keys where that build looks for them. The duplicate is
        stale from the moment the new build writes anything, which is the
        lesser evil against a rollback that silently loses every credential.
        """
        if not self.desktop_mode:
            return False
        dest, src = self._config_path, self._legacy_config_path
        if dest == src or dest.exists() or not src.is_file():
            return False
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
        except OSError as e:
            _log.error("could not migrate runtime config %s -> %s: %s", src, dest, e)
            return False
        _log.info("migrated runtime config out of the vault: %s -> %s", src, dest)
        return True

    def _load_overrides(self) -> dict:
        global _OV_CACHE
        now = time.time()
        current_path = str(self._config_path)
        # Cache hit: same path and within TTL (TTL=0 in test mode disables caching)
        if (
            _OV_TTL > 0
            and _OV_CACHE["data"] is not None
            and _OV_CACHE["path"] == current_path
            and now - _OV_CACHE["ts"] < _OV_TTL
        ):
            return _OV_CACHE["data"]
        try:
            data = json.loads(self._config_path.read_text())
        except FileNotFoundError:
            # The migration hangs off the read path rather than a startup hook
            # on purpose: routers touch config during module import, before any
            # lifespan hook could run, so there is no startup moment early
            # enough to beat them. Hooking the miss costs nothing in the normal
            # case (the file exists, so we never get here) and is ordering-proof.
            data = {}
            if self.migrate_config_file():
                try:
                    data = json.loads(self._config_path.read_text())
                except (OSError, json.JSONDecodeError):
                    data = {}
        except json.JSONDecodeError:
            data = {}
        _OV_CACHE["data"] = data
        _OV_CACHE["ts"] = now
        _OV_CACHE["path"] = current_path
        return data

    def effective_library_readonly(self) -> bool:
        ov = self._load_overrides()
        return bool(ov.get("library_readonly", self.library_readonly))

    def effective_move_confirm(self) -> str:
        ov = self._load_overrides()
        return str(ov.get("move_confirm", self.move_confirm))

    def effective_voice_language(self) -> str:
        ov = self._load_overrides()
        return str(ov.get("voice_language", os.getenv("VOICE_LANGUAGE", "")))

    def effective_embedding_model(self) -> str:
        ov = self._load_overrides()
        return str(
            ov.get(
                "embedding_model",
                os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5"),
            )
        )

    def effective_ollama_base_url(self) -> str:
        """Ollama's address (the `/v1` base). Ollama is the only model provider.

        Reads `OLLAMA_URL` (the host's Ollama, reached from the container via
        host.docker.internal). No stored setting or other env var can point
        the archive at another address.
        """
        return os.getenv("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/") + "/v1"

    def effective_ollama_model(self) -> str:
        ov = self._load_overrides()
        return str(ov.get("ollama_model", os.getenv("OLLAMA_MODEL", "llama3")))

    def effective_vision_model(self) -> str:
        """The local Ollama vision model used for handwriting and captions.

        One setting for every image-reading call. Default is a model that
        ships a vision encoder; the model must already be pulled in Ollama.
        """
        ov = self._load_overrides()
        return str(ov.get("vision_model", os.getenv("VISION_MODEL", "qwen2.5vl:7b")))

    # ── Notification settings ─────────────────────────────────────────────────

    _DEFAULT_EXCLUDED_EXTENSIONS: "frozenset[str]" = frozenset(
        {
            ".sh",
            ".dmg",
            ".zip",
            ".tar",
            ".gz",
            ".webp",
            ".ogg",
            ".canvas",
            ".base",
            ".db",
            ".json",
        }
    )

    def effective_excluded_extensions(self) -> "set[str]":
        ov = self._load_overrides()
        val = ov.get("excluded_extensions")
        if val is None:
            return set(self._DEFAULT_EXCLUDED_EXTENSIONS)
        if isinstance(val, list):
            return {str(e) for e in val}
        return set(self._DEFAULT_EXCLUDED_EXTENSIONS)

    def effective_tree_dim_extensions(self) -> "set[str]":
        """Extensions to grey out in the file tree. Defaults to empty when unset."""
        ov = self._load_overrides()
        val = ov.get("tree_dim_extensions")
        if val is None:
            return set()
        if isinstance(val, list):
            return {str(e) for e in val}
        return self.effective_excluded_extensions()

    def effective_setup_complete(self) -> bool | None:
        """Whether first-run setup finished, as a *recorded decision*.

        Three-state on purpose:

        - ``True``  — the wizard was completed (``POST /api/setup/complete``).
        - ``False`` — a reset asked for it to run again.
        - ``None``  — nobody has recorded anything. Every install predating this
          key is here, so callers must fall back to the ``git_ready`` heuristic
          rather than treating the absence as "not set up" and showing the
          wizard to someone with a full vault.

        The flag exists because ``git_ready`` cannot express "start over": a soft
        reset keeps ``notes/`` including ``.git``, so that heuristic stays true
        forever and the wizard could never reappear. It is also the better shape
        on its own — re-running setup should be a decision someone made, not an
        inference from a missing directory.
        """
        ov = self._load_overrides()
        if "setup_complete" not in ov:
            return None
        return bool(ov["setup_complete"])

    # ── Multimedia transcription ──────────────────────────────────────────────

    _LOCAL_WHISPER_MODELS: "frozenset[str]" = frozenset(
        {
            "tiny.en",
            "tiny",
            "small.en",
            "small",
            "distil-small.en",
            "medium.en",
            "medium",
            "large-v3",
        }
    )

    def effective_local_whisper_model(self) -> str:
        ov = self._load_overrides()
        val = str(
            ov.get(
                "local_whisper_model",
                os.getenv("LOCAL_WHISPER_MODEL", "distil-small.en"),
            )
        )
        return val if val in self._LOCAL_WHISPER_MODELS else "distil-small.en"

    def effective_auto_transcribe_on_catalog_run(self) -> bool:
        ov = self._load_overrides()
        return bool(ov.get("auto_transcribe_on_catalog_run", False))

    def effective_video_frame_sampling(self) -> bool:
        ov = self._load_overrides()
        return bool(ov.get("video_frame_sampling", True))

    def effective_transcription_max_frames_per_video(self) -> int:
        ov = self._load_overrides()
        val = ov.get("transcription_max_frames_per_video")
        if val is None:
            return 20
        try:
            n = int(val)
        except (TypeError, ValueError):
            return 20
        return max(1, min(50, n))

    def save_overrides(self, updates: dict) -> None:
        """Merge updates into the config file and write it, then bust the cache."""
        global _OV_CACHE
        current = self._load_overrides()
        current.update(updates)
        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        self._config_path.write_text(json.dumps(current, indent=2))
        # Bust cache so next read sees the new values immediately
        _OV_CACHE["data"] = None
        _OV_CACHE["ts"] = 0.0
        _OV_CACHE["path"] = ""

    def effective_allowed_hosts(self) -> "list[str]":
        """Host-header allowlist for TrustedHostMiddleware (anti-DNS-rebinding).

        Loopback + the ``api`` docker service name are always allowed. The
        latter is required because the Vite dev proxy forwards ``/api`` with
        ``changeOrigin: true``, which rewrites the Host to the target
        (``api:8000``) — without it every proxied request 400s and the app
        won't load. ``api`` is an internal docker name a browser can't rebind
        to (a rebinding attack carries the attacker's hostname, never ``api``),
        so allowing it does not weaken the guard.

        Extend via the ``ALLOWED_HOSTS`` env var (comma-separated bare
        hostnames, no port — Starlette strips the port before matching) for
        reverse-proxy / custom-hostname / packaged-app installs. In TESTING
        mode the in-process ASGI test hosts are appended. Never contains ``*``.
        """
        hosts = ["127.0.0.1", "localhost", "api"]
        raw = os.getenv("ALLOWED_HOSTS", "").strip()
        if raw:
            hosts += [
                h.strip() for h in raw.split(",") if h.strip() and h.strip() != "*"
            ]
        if self.testing:
            hosts += ["test", "testserver"]
        return list(dict.fromkeys(hosts))  # dedupe, preserve order

    # ── Pending path changes ──────────────────────────────────────────────────

    # ── Where the vault lives (native app only) ───────────────────────────────
    #
    # The shell must know which folders to pass to the backend *before* it can
    # spawn the backend, so it cannot ask over HTTP. `locations.json` is the
    # handoff: the backend writes it, the shell reads it at launch. It is
    # deliberately NOT `pillar43.config.json` — that file is a bag of overrides
    # a Rust process should not have to parse, and it did not always live
    # outside the vault.
    #
    # Schema, versioned so a future shape change is detectable rather than
    # silently misread:
    #
    #   {"version": 1, "vault": "/Users/me/Pillar-43",
    #    "notes": null, "generated": null, "library": null}
    #
    # A null (or absent) mount means "<vault>/<mount>". A non-null value is an
    # absolute path anywhere on disk. That is what makes "one folder by
    # default, each mount relocatable" one concept instead of two.
    #
    # Extra libraries do NOT belong here — they live in libraries.conf, which
    # the running backend re-reads per call. This file is only the three mounts
    # the shell needs before boot. See `extra_library_mounts`.

    LOCATION_MOUNTS = ("notes", "generated", "library")
    LOCATIONS_VERSION = 1

    @property
    def locations_path(self) -> Path:
        """The vault-location handoff file. Passed by the shell so the two
        processes cannot disagree about the filename."""
        explicit = os.getenv("PILLAR43_LOCATIONS_PATH")
        if explicit:
            return Path(explicit)
        return self.data_path / "locations.json"

    def read_locations(self) -> dict:
        """Parse locations.json, or return an empty dict.

        Never raises. A malformed file must degrade to "no recorded choice"
        (i.e. today's defaults) rather than make the app unlaunchable — the
        Rust side has the same rule, and the two must agree.
        """
        try:
            data = json.loads(self.locations_path.read_text())
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(data, dict):
            _log.warning("locations.json is not an object: %s", self.locations_path)
            return {}
        return data

    def write_locations(
        self, *, vault: str | None = None, mounts: "dict[str, str | None] | None" = None
    ) -> dict:
        """Merge into locations.json and write it atomically.

        `vault` sets the base folder; `mounts` sets per-mount overrides, where
        an explicit ``None`` means "back to inside the vault". Returns the
        record as written.

        Atomic here in the ordinary way (`.tmp` + `os.replace`), unlike
        `services.libraries_config._write_file` — this file sits in a normal
        directory, not a per-file bind mount, so the rename actually works.
        """
        record = self.read_locations()
        record["version"] = self.LOCATIONS_VERSION
        if vault is not None:
            record["vault"] = str(vault)
        for mount, value in (mounts or {}).items():
            if mount not in self.LOCATION_MOUNTS:
                raise ValueError(f"not a relocatable mount: {mount!r}")
            record[mount] = str(value) if value is not None else None

        path = self.locations_path
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(record, indent=2))
        os.replace(tmp, path)
        return record

    def vault_root_display(self) -> str:
        """The folder the three mounts sit under, for the UI to show.

        Empty under Docker — the mounts arrive there as independent bind
        mounts and there is no enclosing folder to name, so reporting one
        would be a fiction the paths panel then invites the user to edit.

        Natively: the recorded vault if there is one, else the common parent
        the shell derived the mounts from. Empty again once the user has
        relocated a mount out of the vault and no single parent is true.
        """
        if not self.desktop_mode:
            return ""
        recorded = self.read_locations().get("vault")
        if recorded:
            return str(recorded)
        parents = {
            p.parent for p in (self.notes_path, self.generated_path, self.library_root)
        }
        return str(parents.pop()) if len(parents) == 1 else ""

    def pending_path_changes(self) -> dict[str, str]:
        """Return staged path changes awaiting container restart.

        Returns dict mapping mount name ("library", "notes", "generated")
        to new host filesystem path.
        """
        ov = self._load_overrides()
        return ov.get("pending_path_changes", {})

    def stage_path_change(self, mount: str, new_host_path: str) -> None:
        """Stage a path change. User must restart container with new env var.

        Args:
            mount: Mount name ("library", "notes", "generated")
            new_host_path: New host filesystem path (e.g. "/srv/pillar43/new-library")
        """
        current = self._load_overrides()
        if "pending_path_changes" not in current:
            current["pending_path_changes"] = {}
        current["pending_path_changes"][mount] = new_host_path
        self.save_overrides(current)

    def clear_pending_path_changes(self) -> None:
        """Clear all staged path changes (user has applied them via restart)."""
        current = self._load_overrides()
        if "pending_path_changes" in current:
            current.pop("pending_path_changes")
        if "pending_library_removals" in current:
            current.pop("pending_library_removals")
        self.save_overrides(current)

    def reconcile_pending_path_changes(self) -> "list[str]":
        """Drop staged path changes the running mounts already satisfy.

        A staged change is a note-to-self meaning "this needs a restart before
        it takes effect". Once the app HAS restarted into the new path the note
        is stale — but `services/vault/tree.py` answers **503** for any mount
        carrying one, so the note outlived the restart that satisfied it and
        the only way out was a button inside the panel whose tree was broken.
        That is US-122, and this is what closes it.

        Runs at startup, before any request can hit the tree. Returns the
        mounts it cleared, so the caller can log something honest.
        """
        pending = self.pending_path_changes()
        if not pending:
            return []
        mounts = self.all_mounts
        cleared = []
        for mount, target in list(pending.items()):
            live = mounts.get(mount)
            if live is None:
                continue
            try:
                satisfied = Path(target).resolve() == Path(live).resolve()
            except OSError:
                continue
            if satisfied:
                cleared.append(mount)
        if not cleared:
            return []
        current = self._load_overrides()
        remaining = {
            k: v
            for k, v in current.get("pending_path_changes", {}).items()
            if k not in cleared
        }
        if remaining:
            current["pending_path_changes"] = remaining
        else:
            current.pop("pending_path_changes", None)
        self.save_overrides(current)
        return cleared

    def pending_library_removals(self) -> list[str]:
        """Return list of library mounts staged for removal."""
        ov = self._load_overrides()
        return ov.get("pending_library_removals", [])

    def stage_library_removal(self, mount: str) -> None:
        """Stage a library for removal. User must restart without its env var."""
        current = self._load_overrides()
        if "pending_library_removals" not in current:
            current["pending_library_removals"] = []
        if mount not in current["pending_library_removals"]:
            current["pending_library_removals"].append(mount)
        self.save_overrides(current)

    def is_path_pending_change(self, mount: str) -> bool:
        """Is this mount still waiting on a restart to reach its staged path?

        **False once the running mount already IS the staged path.** A staged
        change is a note saying "restart to apply"; after the restart that
        applied it the note is stale, and `services/vault/tree.py` turns any
        surviving note into a 503. Asking the question this way — rather than
        `mount in pending` — means a change staged and satisfied inside one
        process (the first-run apply) never becomes a trap either.

        `reconcile_pending_path_changes()` clears the stale entries at startup;
        this is the same question asked per call, so the two cannot disagree.
        """
        target = self.pending_path_changes().get(mount)
        if target is None:
            return False
        live = self.all_mounts.get(mount)
        if live is None:
            return True
        try:
            return Path(target).resolve() != Path(live).resolve()
        except OSError:
            return True

    def is_library_pending_removal(self, mount: str) -> bool:
        """Check if a library is staged for removal."""
        return mount in self.pending_library_removals()

    def resolve(self, rel: str) -> Path:
        """Resolve a client-supplied relative path against known roots.

        Security: rejects any path that escapes its root via traversal.
        """
        # Paths are prefixed with their mount name so we know which root to use.
        # e.g. "notes/balmology/INDEX.md", "generated/project-status.md",
        #      "library/2024/someNote.md"
        parts = Path(rel).parts
        if not parts:
            raise ValueError("Empty path")

        mount = parts[0]
        rest = Path(*parts[1:]) if len(parts) > 1 else Path(".")

        root_map = self.all_mounts
        if mount not in root_map:
            raise ValueError(f"Unknown mount: {mount!r}")

        root = root_map[mount]
        candidate = (root / rest).resolve()

        # Prevent path traversal outside the root
        try:
            candidate.relative_to(root.resolve())
        except ValueError:
            # `from None`: relative_to's message embeds both resolved absolute
            # paths. This message reaches the client as a 400 detail, so the
            # cause is suppressed deliberately rather than leaking the vault
            # layout to whoever probed for it.
            raise ValueError("Path traversal detected") from None

        return candidate

    @property
    def db_path(self) -> Path:
        """Absolute path to the SQLite catalog database.

        Lives in `data_path` (a Docker named volume), NOT `generated_path` (a
        bind mount). Bind mounts on macOS go through VirtioFS/gRPC FUSE, which
        doesn't reliably support SQLite's WAL mmap or journal fcntl semantics
        — concurrent connections produced `disk I/O error`, `database is
        locked`, and `database disk image is malformed` errors that were
        ultimately untraceable to anything other than the filesystem bridge.
        Named volumes use Docker's native storage. See services/db.py.

        The `generated_path` fallback below is for callers that set neither
        DATA_PATH nor a data_path — it keeps db_path off the unwritable
        `/data` default. NOTE: it is effectively dead in the test suite. The
        autouse `_isolate_db_per_test` fixture (`api/tests/conftest.py:22`)
        sets DATA_PATH on every test to give each xdist worker its own DB, so
        the first branch always wins there. A test that monkeypatches only
        `settings.generated_path` expecting db_path to follow is patching
        something with no effect.
        """
        if os.getenv("DATA_PATH"):
            return self.data_path / "pillar43.db"
        return self.generated_path / "pillar43.db"

    def validate_startup(self, *, strict: bool = False) -> "list[str]":
        """Fail-fast diagnostics run once at boot.

        Checks the load-bearing config so a misconfiguration surfaces as a
        clear, actionable log line at startup instead of an opaque error at
        first use. Returns the list of HARD problems (empty == healthy).

        Hard problems (block a usable app): the read-write mounts (notes,
        generated) missing / not a directory / not writable. When ``strict``
        is set (production boot), any hard problem raises ``RuntimeError`` so
        the process refuses to start rather than serve a broken app.

        Soft problems (log a warning, keep going): none today; the list is kept so one can be added without changing the shape.
        """
        hard: list[str] = []
        soft: list[str] = []

        for name, path in (
            ("notes", self.notes_path),
            ("generated", self.generated_path),
        ):
            if not path.exists():
                hard.append(f"{name} mount does not exist: {path}")
            elif not path.is_dir():
                hard.append(f"{name} mount is not a directory: {path}")
            elif not os.access(path, os.W_OK):
                hard.append(f"{name} mount is not writable: {path}")

        for problem in soft:
            _log.warning("startup config check: %s", problem)
        for problem in hard:
            _log.error("startup config check: %s", problem)

        if hard and strict:
            raise RuntimeError(
                "Pillar-43 cannot start — fix these and restart:\n  - "
                + "\n  - ".join(hard)
            )
        return hard


settings = Settings()
