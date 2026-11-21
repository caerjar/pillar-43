"""Run blocking work on a thread and stream its progress as SSE.

`routes/handwriting.py` and `routes/transcription.py` had the same ~50 lines:
a queue.Queue bridging a daemon thread to an async generator, a disconnect
poll, and three event kinds. The only real differences were the key in the
done payload and two log strings.

Two behaviours here are load-bearing and easy to lose in a rewrite:

1. **The worker keeps running after the client disconnects.** The generator
   returns, but the thread is not cancelled — the transcript still gets
   written for a user who closed the tab mid-run. It is a daemon thread so it
   cannot hold up interpreter shutdown.

2. **Exceptions go through `_human_error` before reaching the wire.** Provider
   SDKs put the full request payload in the exception body, and on some
   providers that includes the API key. Anything that puts `str(exc)` on this
   stream is an API-key leak, which is why the error path here takes no
   caller-supplied formatting.

Also note the queue is polled with `get_nowait()` plus an explicit
`asyncio.sleep`, not a blocking `get()`. A blocking get would park the event
loop thread and stall every other request in the process.
"""

from __future__ import annotations

import asyncio
import logging
import queue
import threading
from typing import Any, AsyncIterator, Callable

from fastapi import Request

from services.ai_errors import _human_error
from services.sse_format import SSE_DONE, sse

log = logging.getLogger(__name__)

# Poll interval while the worker is running. Short enough that progress feels
# immediate, long enough not to spin the event loop at full CPU.
_POLL_SECONDS = 0.05

ProgressFn = Callable[[str, float], None]


async def stream_background_work(
    request: Request,
    *,
    work: Callable[[ProgressFn], Any],
    done_payload: Callable[[Any], dict[str, Any]],
    label: str,
) -> AsyncIterator[str]:
    """Stream `work` as SSE progress/done/error events.

    `work` is called on a daemon thread with a `progress(stage, fraction)`
    callback. Its return value is passed to `done_payload` to build the fields
    of the terminal `done` event.

    `label` identifies the operation in logs only — it never reaches the wire.
    """
    q: queue.Queue[tuple] = queue.Queue()

    def _progress(stage: str, fraction: float) -> None:
        q.put(("progress", stage, fraction))

    def _worker() -> None:
        try:
            q.put(("done", work(_progress)))
        except Exception as e:
            log.exception("%s failed", label)
            # Scrubbed, never str(e) — see the module docstring.
            q.put(("error", _human_error(e)))

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()

    while True:
        if await request.is_disconnected():
            # Deliberately does NOT stop the worker: the artifact should still
            # be written for a user who closed the tab.
            log.info("client disconnected, stopping SSE stream for %s", label)
            return
        try:
            item = q.get_nowait()
        except queue.Empty:
            if not thread.is_alive():
                # Finished without queuing anything — nothing left to send.
                return
            await asyncio.sleep(_POLL_SECONDS)
            continue

        kind = item[0]
        if kind == "progress":
            _, stage, fraction = item
            yield sse("progress", stage=stage, fraction=fraction)
        elif kind == "done":
            _, result = item
            yield sse("done", **done_payload(result))
            yield SSE_DONE
            return
        elif kind == "error":
            _, message = item
            yield sse("error", message=message)
            yield SSE_DONE
            return
