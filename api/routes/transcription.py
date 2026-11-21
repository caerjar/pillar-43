"""Transcribe multimedia files (audio/video → Whisper, images → local vision model).

POST /api/transcribe          — SSE stream of progress, ends with the saved transcript path
POST /api/transcribe/estimate — synchronous estimate for the auto-sweep warning UI
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from services import transcription

from ._sse_worker import stream_background_work

router = APIRouter(prefix="/api")

log = logging.getLogger(__name__)


class TranscribeRequest(BaseModel):
    path: str
    # When true, regenerate even if a transcript with the matching source_hash
    # already exists. Useful after switching providers or changing the local
    # Whisper model.
    force: bool = False


class EstimateRequest(BaseModel):
    paths: list[str]


@router.post("/transcribe")
async def transcribe_endpoint(body: TranscribeRequest, request: Request):
    """Stream SSE progress events while transcribing a single file.

    Events:
      data: {"event": "progress", "stage": "...", "fraction": 0.42}
      data: {"event": "done", "transcript_path": "generated/transcripts/..."}
      data: {"event": "error", "message": "..."}

    On client disconnect we stop streaming and stop polling the worker
    queue. faster-whisper has no in-flight cancel hook, so the worker
    daemon thread keeps running to completion in the background — it'll
    write the transcript on success even if no one is listening.
    """
    if not transcription.is_transcribable(body.path):
        raise HTTPException(
            status_code=400,
            detail=f"Not a transcribable file type: {body.path}",
        )

    return StreamingResponse(
        stream_background_work(
            request,
            work=lambda progress: transcription.transcribe(
                body.path, progress=progress, force=body.force
            ),
            # Key differs from handwriting's "result" — this endpoint's
            # frontend reads transcript_path directly. Kept as-is deliberately.
            done_payload=lambda transcript_rel: {"transcript_path": transcript_rel},
            label=f"transcription for {body.path}",
        ),
        media_type="text/event-stream",
    )


@router.post("/transcribe/estimate")
async def estimate_endpoint(body: EstimateRequest):
    """Estimate total media duration and processing time for an upcoming sweep."""
    total_duration = 0.0
    total_processing = 0.0
    items = []
    for p in body.paths:
        try:
            duration, processing = transcription.estimate_seconds(p)
        except Exception as e:
            log.warning("estimate failed for %s: %s", p, e)
            duration, processing = 0.0, 0.0
        total_duration += duration
        total_processing += processing
        items.append(
            {
                "path": p,
                "duration_seconds": duration,
                "estimated_processing_seconds": processing,
            }
        )
    return {
        "total_duration_seconds": total_duration,
        "estimated_processing_seconds": total_processing,
        "items": items,
    }
