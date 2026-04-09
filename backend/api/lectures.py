import asyncio
import os
from datetime import datetime
from typing import Annotated

import aiofiles
from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlmodel import Session, select

from backend.config import get_settings
from backend.database import get_session
from backend.models import Job, Lecture, MediaObject

router = APIRouter()

SessionDep = Annotated[Session, Depends(get_session)]


class LectureCreate(BaseModel):
    title: str
    source_language: str = "en"
    target_language: str = "es"


class LectureUpdate(BaseModel):
    title: str | None = None
    source_language: str | None = None
    target_language: str | None = None


@router.post("/lectures", response_model=Lecture)
def create_lecture(data: LectureCreate, session: SessionDep) -> Lecture:
    lecture = Lecture(
        title=data.title,
        source_language=data.source_language,
        target_language=data.target_language,
    )
    session.add(lecture)
    session.commit()
    session.refresh(lecture)
    return lecture


@router.get("/lectures", response_model=list[Lecture])
def list_lectures(session: SessionDep) -> list[Lecture]:
    return list(session.exec(select(Lecture).order_by(Lecture.created_at.desc())).all())  # type: ignore[arg-type]


@router.get("/lectures/{lecture_id}", response_model=Lecture)
def get_lecture(lecture_id: str, session: SessionDep) -> Lecture:
    lecture = session.get(Lecture, lecture_id)
    if not lecture:
        raise HTTPException(status_code=404, detail="Lecture not found")
    return lecture


@router.get("/media/{media_object_id}")
def serve_media(media_object_id: str, session: SessionDep):
    mo = session.get(MediaObject, media_object_id)
    if not mo:
        raise HTTPException(status_code=404, detail="Media not found")
    settings = get_settings()
    abs_path = os.path.join(settings.media_dir, mo.file_path)
    if not os.path.exists(abs_path):
        raise HTTPException(status_code=404, detail="File not found on disk")
    return FileResponse(abs_path, media_type=mo.mime_type or "application/octet-stream")


@router.get("/lectures/{lecture_id}/media/{kind}")
def serve_lecture_media(lecture_id: str, kind: str, session: SessionDep):
    """Serve a media file by lecture ID and kind (e.g., export_mp4, source_video)."""
    mo = session.exec(
        select(MediaObject)
        .where(MediaObject.lecture_id == lecture_id, MediaObject.kind == kind)
        .order_by(MediaObject.created_at.desc())  # type: ignore[arg-type]
    ).first()
    if not mo:
        raise HTTPException(status_code=404, detail=f"No {kind} media found")
    settings = get_settings()
    abs_path = os.path.join(settings.media_dir, mo.file_path)
    if not os.path.exists(abs_path):
        raise HTTPException(status_code=404, detail="File not found on disk")
    return FileResponse(abs_path, media_type=mo.mime_type or "application/octet-stream")


@router.post("/lectures/{lecture_id}/upload", response_model=MediaObject)
async def upload_video(lecture_id: str, file: UploadFile, session: SessionDep) -> MediaObject:
    lecture = session.get(Lecture, lecture_id)
    if not lecture:
        raise HTTPException(status_code=404, detail="Lecture not found")

    settings = get_settings()
    lecture_dir = os.path.join(settings.media_dir, lecture_id)
    os.makedirs(lecture_dir, exist_ok=True)

    filename = file.filename or "source_video"
    relative_path = os.path.join(lecture_id, filename)
    absolute_path = os.path.join(settings.media_dir, relative_path)

    async with aiofiles.open(absolute_path, "wb") as f:
        content = await file.read()
        await f.write(content)

    size_bytes = os.path.getsize(absolute_path)

    media_obj = MediaObject(
        lecture_id=lecture_id,
        kind="source_video",
        file_path=relative_path,
        size_bytes=size_bytes,
        mime_type=file.content_type,
    )
    session.add(media_obj)

    lecture.status = "uploaded"
    lecture.updated_at = datetime.utcnow().isoformat()
    session.add(lecture)
    session.commit()
    session.refresh(media_obj)

    # Kick off pipeline in background
    asyncio.create_task(_start_pipeline(lecture_id))

    return media_obj


@router.post("/lectures/{lecture_id}/process", response_model=Job)
async def process_lecture(lecture_id: str, session: SessionDep) -> Job:
    lecture = session.get(Lecture, lecture_id)
    if not lecture:
        raise HTTPException(status_code=404, detail="Lecture not found")

    job = Job(
        lecture_id=lecture_id,
        job_type="full_pipeline",
        status="pending",
    )
    session.add(job)
    session.commit()
    session.refresh(job)

    asyncio.create_task(_start_pipeline(lecture_id))
    return job


@router.post("/lectures/{lecture_id}/export", response_model=Job)
async def export_lecture(lecture_id: str, session: SessionDep) -> Job:
    lecture = session.get(Lecture, lecture_id)
    if not lecture:
        raise HTTPException(status_code=404, detail="Lecture not found")

    job = Job(
        lecture_id=lecture_id,
        job_type="export",
        status="pending",
    )
    session.add(job)
    session.commit()
    session.refresh(job)

    asyncio.create_task(_run_export(lecture_id, job.id))
    return job


async def _start_pipeline(lecture_id: str) -> None:
    from sqlmodel import Session

    from backend.database import engine
    from backend.services.pipeline import run_pipeline

    with Session(engine) as session:
        await run_pipeline(lecture_id, session)


async def _run_export(lecture_id: str, job_id: str) -> None:
    from sqlmodel import Session

    from backend.database import engine
    from backend.services.pipeline import run_export

    with Session(engine) as session:
        await run_export(lecture_id, job_id, session)
