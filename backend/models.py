from datetime import datetime
from typing import Optional
from uuid import uuid4

from sqlmodel import Field, SQLModel


class Lecture(SQLModel, table=True):
    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    title: str
    status: str = "uploaded"  # uploaded|extracting|transcribing|translating|dubbing|draft|exported
    duration_seconds: Optional[float] = None
    source_language: str = "en"
    target_language: str = "es"
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


class MediaObject(SQLModel, table=True):
    __tablename__ = "media_objects"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    lecture_id: str = Field(foreign_key="lecture.id")
    kind: str  # source_video|extracted_audio|normalized_audio|voice_reference|segment_tts|spanish_mix|export_mp4
    file_path: str  # local path relative to MEDIA_DIR
    size_bytes: Optional[int] = None
    mime_type: Optional[str] = None
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


class Job(SQLModel, table=True):
    __tablename__ = "jobs"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    lecture_id: str = Field(foreign_key="lecture.id")
    job_type: str  # full_pipeline|regenerate_translation|regenerate_tts|export
    status: str = "pending"  # pending|running|completed|failed
    current_step: Optional[str] = None
    progress: float = 0.0
    error_message: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


class Segment(SQLModel, table=True):
    __tablename__ = "segments"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    lecture_id: str = Field(foreign_key="lecture.id")
    parent_id: Optional[str] = Field(default=None, foreign_key="segments.id")
    speaker: Optional[str] = None
    start_sec: float
    end_sec: float
    source_text_en: str
    ordering: int
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


class Translation(SQLModel, table=True):
    __tablename__ = "translations"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    segment_id: str = Field(foreign_key="segments.id")
    translated_text: str
    provider_model: Optional[str] = None
    qa_flags: Optional[str] = None  # JSON array as string
    status: str = "current"  # current|stale
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


class TTSGeneration(SQLModel, table=True):
    __tablename__ = "tts_generations"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    segment_id: str = Field(foreign_key="segments.id")
    media_object_id: Optional[str] = Field(default=None, foreign_key="media_objects.id")
    provider: str  # voxtral|elevenlabs
    model_id: Optional[str] = None
    input_text: str
    voice_ref_id: Optional[str] = Field(default=None, foreign_key="media_objects.id")
    settings_json: Optional[str] = None
    duration_seconds: Optional[float] = None
    status: str = "current"  # current|stale
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
