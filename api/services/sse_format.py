"""The SSE wire format, in one place.

`data: {json}\\n\\n` was hand-written at 30 call sites across 15 modules, in
routes and services alike, plus three separate private formatter helpers. Every
one of them had to independently remember the `data: ` prefix and — more easily
missed — that the frame terminates on a BLANK line, i.e. two newlines. A single
missing `\\n` produces a stream the browser accepts and then silently never
dispatches an event from.

This lives under services/ rather than routes/ so `services.sse_bridge` can use
it without a service importing from the route layer.
"""

from __future__ import annotations

import json
from typing import Any


def sse_frame(payload: dict[str, Any]) -> str:
    """Encode one already-built payload dict as an SSE `data:` frame."""
    return f"data: {json.dumps(payload)}\n\n"


def sse(event: str, **payload: Any) -> str:
    """Encode an SSE frame for `event`, with the rest of the payload inlined.

    `event` is emitted first, matching what every hand-rolled call site did.
    json.dumps preserves insertion order, so the bytes are unchanged.
    """
    return sse_frame({"event": event, **payload})


# The terminator the frontend's parseSSEStream watches for to close a stream.
# Not a `data:` frame — a bare sentinel — so it does not go through sse_frame().
SSE_DONE = "data: [DONE]\n\n"
