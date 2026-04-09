import asyncio
import json
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlmodel import Session, select

from backend.database import get_session
from backend.models import Job

router = APIRouter()

SessionDep = Annotated[Session, Depends(get_session)]

# In-memory event queues keyed by lecture_id for SSE
_event_queues: dict[str, list[asyncio.Queue]] = {}


def publish_event(lecture_id: str, event: dict) -> None:
    """Publish an SSE event to all listeners for a lecture."""
    queues = _event_queues.get(lecture_id, [])
    for q in queues:
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            pass


@router.get("/jobs/{job_id}", response_model=Job)
def get_job(job_id: str, session: SessionDep) -> Job:
    job = session.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.get("/lectures/{lecture_id}/jobs", response_model=list[Job])
def list_lecture_jobs(lecture_id: str, session: SessionDep) -> list[Job]:
    return list(
        session.exec(
            select(Job).where(Job.lecture_id == lecture_id).order_by(Job.created_at.desc())  # type: ignore[arg-type]
        ).all()
    )


@router.get("/lectures/{lecture_id}/events")
async def lecture_events(lecture_id: str, session: SessionDep) -> StreamingResponse:
    """SSE endpoint for real-time job progress updates."""
    queue: asyncio.Queue = asyncio.Queue(maxsize=100)

    if lecture_id not in _event_queues:
        _event_queues[lecture_id] = []
    _event_queues[lecture_id].append(queue)

    async def event_generator():
        try:
            # Send an initial connection event
            yield f"data: {json.dumps({'type': 'connected', 'lecture_id': lecture_id})}\n\n"

            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield f"data: {json.dumps(event)}\n\n"

                    if event.get("type") in ("completed", "failed"):
                        break
                except TimeoutError:
                    # Send a keepalive comment
                    yield ": keepalive\n\n"
        finally:
            queues = _event_queues.get(lecture_id, [])
            if queue in queues:
                queues.remove(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
