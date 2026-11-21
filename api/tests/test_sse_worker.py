"""Tests for the shared SSE background-work scaffold.

The handwriting and transcription route suites cover this end-to-end, but only
through their own happy paths. These pin the scaffold's contract directly —
particularly the two behaviours that are invisible from a passing happy path
and expensive to get wrong:

  - a worker exception is scrubbed through `_human_error` before it reaches
    the wire (provider SDKs put the request payload, and on some providers the
    API key, in the exception body);
  - a client disconnect ends the STREAM but not the WORK, so the artifact is
    still written for someone who closed the tab.
"""

from __future__ import annotations

import json
import threading

import pytest

from routes._sse_worker import stream_background_work


class FakeRequest:
    """Minimal stand-in for starlette's Request.is_disconnected()."""

    def __init__(self, disconnect_after: int | None = None):
        self.disconnected = False
        self._calls = 0
        self._disconnect_after = disconnect_after

    async def is_disconnected(self) -> bool:
        self._calls += 1
        if self._disconnect_after is not None and self._calls > self._disconnect_after:
            return True
        return self.disconnected


def parse(frame: str) -> dict:
    """SSE frame -> payload. Also asserts the framing itself."""
    assert frame.startswith("data: ")
    assert frame.endswith("\n\n"), "a frame terminates on a BLANK line"
    return json.loads(frame.removeprefix("data: ").strip())


async def collect(gen) -> list[str]:
    return [chunk async for chunk in gen]


@pytest.mark.asyncio
async def test_progress_events_forwarded_in_order_then_done():
    def work(progress):
        progress("reading", 0.25)
        progress("thinking", 0.5)
        return "out.md"

    frames = await collect(
        stream_background_work(
            FakeRequest(),
            work=work,
            done_payload=lambda r: {"transcript_path": r},
            label="test",
        )
    )

    payloads = [parse(f) for f in frames if f != "data: [DONE]\n\n"]
    assert [p["event"] for p in payloads] == ["progress", "progress", "done"]
    assert payloads[0] == {"event": "progress", "stage": "reading", "fraction": 0.25}
    assert payloads[1] == {"event": "progress", "stage": "thinking", "fraction": 0.5}
    assert payloads[2] == {"event": "done", "transcript_path": "out.md"}


@pytest.mark.asyncio
async def test_done_is_followed_by_exactly_one_terminator():
    frames = await collect(
        stream_background_work(
            FakeRequest(),
            work=lambda progress: {"ok": True},
            done_payload=lambda r: {"result": r},
            label="test",
        )
    )
    assert frames[-1] == "data: [DONE]\n\n"
    assert frames.count("data: [DONE]\n\n") == 1


@pytest.mark.asyncio
async def test_done_payload_shapes_the_terminal_event():
    """The one thing that differs between the two callers."""
    frames = await collect(
        stream_background_work(
            FakeRequest(),
            work=lambda progress: "value",
            done_payload=lambda r: {"result": r, "extra": 1},
            label="test",
        )
    )
    done = parse(frames[-2])
    assert done == {"event": "done", "result": "value", "extra": 1}


@pytest.mark.asyncio
async def test_provider_exception_is_scrubbed_to_its_class_name():
    """The API-key-leak guard, exercised against the real threat.

    The guard is scoped to PROVIDER exceptions on purpose (SECURITY.md says
    "provider-namespaced"): an SDK may put the whole request payload, API key
    included, in the exception body. `_human_error` classifies by isinstance
    against the httpx base class, so a version bump adding an unrecognised
    subclass still degrades to the class name rather than leaking.

    Errors raised by Pillar-43's own code are deliberately passed through — our
    messages are written to be read by the user. Asserting otherwise would be
    testing a behaviour the code does not have and should not.
    """
    import httpx

    secret = "sk-ant-DO-NOT-LEAK-THIS"

    class UnrecognisedProviderError(httpx.HTTPError):
        """Stands in for an SDK exception class we do not classify yet."""

    def work(progress):
        raise UnrecognisedProviderError(f"request failed: api_key={secret}")

    frames = await collect(
        stream_background_work(
            FakeRequest(),
            work=work,
            done_payload=lambda r: {"result": r},
            label="test",
        )
    )

    err = parse(frames[0])
    assert err["event"] == "error"
    assert secret not in json.dumps(frames), "the API key must never reach the wire"
    assert "api_key" not in err["message"]
    assert err["message"] == "AI provider error (UnrecognisedProviderError)"
    assert frames[-1] == "data: [DONE]\n\n"


@pytest.mark.asyncio
async def test_pillar43_own_errors_are_passed_through():
    """Counterpart to the above: our own messages are meant to be read."""

    def work(progress):
        raise RuntimeError("Not a transcribable file type: notes/x.md")

    frames = await collect(
        stream_background_work(
            FakeRequest(),
            work=work,
            done_payload=lambda r: {"result": r},
            label="test",
        )
    )
    assert parse(frames[0])["message"] == "Not a transcribable file type: notes/x.md"


@pytest.mark.asyncio
async def test_disconnect_ends_the_stream_but_not_the_work():
    started = threading.Event()
    finished = threading.Event()

    def work(progress):
        started.set()
        # Long enough that the generator gives up on us first.
        finished.wait(timeout=5)
        return "written-anyway.md"

    # Disconnect on the very first poll.
    frames = await collect(
        stream_background_work(
            FakeRequest(disconnect_after=0),
            work=work,
            done_payload=lambda r: {"result": r},
            label="test",
        )
    )

    assert frames == [], "no events after a disconnect"
    assert started.wait(timeout=2), "the worker must have been started"
    # Still running: the transcript keeps being written for a user who left.
    assert not finished.is_set()
    finished.set()


@pytest.mark.asyncio
async def test_work_returning_nothing_still_terminates():
    """A worker that queues nothing must not hang the generator."""
    frames = await collect(
        stream_background_work(
            FakeRequest(),
            work=lambda progress: None,
            done_payload=lambda r: {"result": r},
            label="test",
        )
    )
    assert parse(frames[0])["event"] == "done"
