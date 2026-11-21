"""Transcribe handwritten notes (image/PDF) → markdown + optional SVG diagrams.

POST /api/handwriting/transcribe — SSE stream of progress, ends with paths
to the saved transcript and any diagram SVGs.

Distinct from /api/transcribe because:
  - accepts PDFs (the audio/image transcriber doesn't)
  - produces 1 .md plus 0..N .svg artifacts (different response shape)
  - uses a structured tool-use prompt that decides text vs diagram per region
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from services import handwriting

from ._sse_worker import stream_background_work

router = APIRouter(prefix="/api")

log = logging.getLogger(__name__)


class HandwritingRequest(BaseModel):
    path: str
    # When true, regenerate even if the transcript already matches the source hash.
    force: bool = False


class HandwritingDone(BaseModel):
    transcript_path: str
    diagram_paths: list[str]
    diagrams_found: int
    pages_processed: int


@router.post("/handwriting/transcribe")
async def transcribe_handwriting_endpoint(body: HandwritingRequest, request: Request):
    """Stream SSE progress events while transcribing a handwritten page.

    Events:
      data: {"event": "progress", "stage": "...", "fraction": 0.42}
      data: {"event": "done", "result": {... HandwritingDone ...}}
      data: {"event": "error", "message": "..."}

    Worker keeps running on client disconnect so the transcript still gets
    written; the SSE stream just stops yielding. Mirrors transcription.py.
    """
    if not handwriting.is_handwriting_transcribable(body.path):
        raise HTTPException(
            status_code=400,
            detail=f"Not a handwriting-transcribable file type: {body.path}",
        )

    return StreamingResponse(
        stream_background_work(
            request,
            work=lambda progress: handwriting.transcribe(
                body.path, progress=progress, force=body.force
            ),
            done_payload=lambda result: {"result": result},
            label=f"handwriting transcription for {body.path}",
        ),
        media_type="text/event-stream",
    )
