"""File watcher for the notes/inbox/ drop zone.

Moved verbatim from `worker/tasks/inbox_watcher.py` when the worker container
folded into the API lifespan (2026-08-18). It had no worker-specific code —
unlike its six sibling job wrappers it never needed the `sys.path` hack.

Accepts all file types and fires on file creation only (not modification).
Watches flat — recursive=False — since inbox/ is a single-level drop zone.
(The sibling `VaultWatcher`, which only watched .md files, was deleted in the
same change: it had been imported by nothing since the Maintenance Redesign.)
"""

import logging
from pathlib import Path
from typing import Callable

from watchdog.events import DirCreatedEvent, FileCreatedEvent, FileSystemEventHandler
from watchdog.observers import Observer
from watchdog.observers.api import BaseObserver

log = logging.getLogger(__name__)


class _InboxHandler(FileSystemEventHandler):
    def __init__(self, callback: Callable[[str], None]) -> None:
        self._callback = callback

    def on_created(self, event: DirCreatedEvent | FileCreatedEvent) -> None:
        # Signature must match the supertype — watchdog dispatches directory
        # events through the same hook, and `is_directory` is the filter.
        if not event.is_directory:
            # watchdog types src_path as `bytes | str` (it decodes per-platform);
            # everything downstream takes a path string.
            src = event.src_path
            path = src.decode("utf-8", "replace") if isinstance(src, bytes) else src
            log.info("Inbox: new file detected: %s", path)
            try:
                self._callback(path)
            except Exception as e:
                log.error("Inbox callback failed for %s: %s", path, e, exc_info=True)


class InboxWatcher:
    """Watches notes/inbox/ and fires a callback on every new file."""

    def __init__(
        self,
        watch_path: str,
        callback: Callable[[str], None],
    ) -> None:
        self._watch_path = watch_path
        self._callback = callback
        # `Observer` is a factory alias, not a class, so it cannot annotate a
        # variable — `BaseObserver` is what it actually returns.
        self._observer: BaseObserver | None = None

    def start(self) -> None:
        Path(self._watch_path).mkdir(parents=True, exist_ok=True)
        handler = _InboxHandler(self._callback)
        self._observer = Observer()
        self._observer.schedule(handler, self._watch_path, recursive=False)
        self._observer.start()
        log.info("InboxWatcher started on %s", self._watch_path)

    def stop(self) -> None:
        if self._observer:
            self._observer.stop()
            self._observer.join()
            self._observer = None
            log.info("InboxWatcher stopped")
