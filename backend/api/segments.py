import asyncio
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from backend.database import get_session
from backend.models import Segment, Translation, TTSGeneration

router = APIRouter()

SessionDep = Annotated[Session, Depends(get_session)]


class SegmentWithTranslation(BaseModel):
    segment: Segment
    translation: Translation | None = None
    tts: TTSGeneration | None = None

    model_config = {"arbitrary_types_allowed": True}


class SegmentPatch(BaseModel):
    source_text_en: str | None = None
    speaker: str | None = None
    start_sec: float | None = None
    end_sec: float | None = None


class TranslationPatch(BaseModel):
    translated_text: str | None = None


@router.get("/lectures/{lecture_id}/segments", response_model=list[SegmentWithTranslation])
def list_segments(lecture_id: str, session: SessionDep) -> list[SegmentWithTranslation]:
    segments = list(
        session.exec(
            select(Segment).where(Segment.lecture_id == lecture_id).order_by(Segment.ordering)  # type: ignore[arg-type]
        ).all()
    )

    result = []
    for seg in segments:
        # Get the most recent current translation
        translation = session.exec(
            select(Translation)
            .where(Translation.segment_id == seg.id, Translation.status == "current")
            .order_by(Translation.created_at.desc())  # type: ignore[arg-type]
        ).first()

        # Get the most recent current TTS
        tts = session.exec(
            select(TTSGeneration)
            .where(TTSGeneration.segment_id == seg.id, TTSGeneration.status == "current")
            .order_by(TTSGeneration.created_at.desc())  # type: ignore[arg-type]
        ).first()

        result.append(SegmentWithTranslation(segment=seg, translation=translation, tts=tts))

    return result


@router.patch("/segments/{segment_id}", response_model=Segment)
def patch_segment(segment_id: str, data: SegmentPatch, session: SessionDep) -> Segment:
    segment = session.get(Segment, segment_id)
    if not segment:
        raise HTTPException(status_code=404, detail="Segment not found")

    if data.source_text_en is not None:
        segment.source_text_en = data.source_text_en
        # Mark translations and TTS as stale
        translations = session.exec(
            select(Translation).where(Translation.segment_id == segment_id, Translation.status == "current")
        ).all()
        for t in translations:
            t.status = "stale"
            t.updated_at = datetime.utcnow().isoformat()
            session.add(t)

        tts_gens = session.exec(
            select(TTSGeneration).where(TTSGeneration.segment_id == segment_id, TTSGeneration.status == "current")
        ).all()
        for tts in tts_gens:
            tts.status = "stale"
            session.add(tts)

    if data.speaker is not None:
        segment.speaker = data.speaker
    if data.start_sec is not None:
        segment.start_sec = data.start_sec
    if data.end_sec is not None:
        segment.end_sec = data.end_sec

    segment.updated_at = datetime.utcnow().isoformat()
    session.add(segment)
    session.commit()
    session.refresh(segment)
    return segment


@router.patch("/translations/{translation_id}", response_model=Translation)
def patch_translation(translation_id: str, data: TranslationPatch, session: SessionDep) -> Translation:
    translation = session.get(Translation, translation_id)
    if not translation:
        raise HTTPException(status_code=404, detail="Translation not found")

    if data.translated_text is not None:
        translation.translated_text = data.translated_text
        # Mark TTS as stale
        tts_gens = session.exec(
            select(TTSGeneration)
            .where(TTSGeneration.segment_id == translation.segment_id, TTSGeneration.status == "current")
        ).all()
        for tts in tts_gens:
            tts.status = "stale"
            session.add(tts)

    translation.updated_at = datetime.utcnow().isoformat()
    session.add(translation)
    session.commit()
    session.refresh(translation)
    return translation


@router.post("/segments/{segment_id}/translate", response_model=Translation)
async def regenerate_translation(segment_id: str, session: SessionDep) -> Translation:
    segment = session.get(Segment, segment_id)
    if not segment:
        raise HTTPException(status_code=404, detail="Segment not found")

    asyncio.create_task(_regen_translation(segment_id))

    # Return a pending placeholder or the latest stale translation
    translation = session.exec(
        select(Translation).where(Translation.segment_id == segment_id).order_by(Translation.created_at.desc())  # type: ignore[arg-type]
    ).first()

    if not translation:
        translation = Translation(
            segment_id=segment_id,
            translated_text="",
            status="stale",
        )
        session.add(translation)
        session.commit()
        session.refresh(translation)

    return translation


@router.post("/segments/{segment_id}/tts", response_model=TTSGeneration)
async def regenerate_tts(segment_id: str, session: SessionDep) -> TTSGeneration:
    segment = session.get(Segment, segment_id)
    if not segment:
        raise HTTPException(status_code=404, detail="Segment not found")

    asyncio.create_task(_regen_tts(segment_id))

    tts = session.exec(
        select(TTSGeneration).where(TTSGeneration.segment_id == segment_id).order_by(TTSGeneration.created_at.desc())  # type: ignore[arg-type]
    ).first()

    if not tts:
        tts = TTSGeneration(
            segment_id=segment_id,
            provider="pending",
            input_text="",
            status="stale",
        )
        session.add(tts)
        session.commit()
        session.refresh(tts)

    return tts


async def _regen_translation(segment_id: str) -> None:
    from sqlmodel import Session

    from backend.adapters.translation import MockTranslationAdapter, OpenAITranslationAdapter
    from backend.config import get_settings
    from backend.database import engine

    settings = get_settings()

    with Session(engine) as session:
        segment = session.get(Segment, segment_id)
        if not segment:
            return

        # Mark existing translations stale
        existing = session.exec(
            select(Translation).where(Translation.segment_id == segment_id, Translation.status == "current")
        ).all()
        for t in existing:
            t.status = "stale"
            session.add(t)

        if settings.openai_api_key:
            adapter = OpenAITranslationAdapter(api_key=settings.openai_api_key)
            provider_model = "gpt-4o"
        else:
            adapter = MockTranslationAdapter()
            provider_model = "mock"

        translated = await adapter.translate(segment.source_text_en, source_lang="en", target_lang="es")

        new_translation = Translation(
            segment_id=segment_id,
            translated_text=translated,
            provider_model=provider_model,
            status="current",
        )
        session.add(new_translation)
        session.commit()


async def _regen_tts(segment_id: str) -> None:
    import os

    from sqlmodel import Session

    from backend.adapters.tts import MockTTSAdapter, OpenAITTSAdapter
    from backend.config import get_settings
    from backend.database import engine

    settings = get_settings()

    with Session(engine) as session:
        segment = session.get(Segment, segment_id)
        if not segment:
            return

        translation = session.exec(
            select(Translation).where(Translation.segment_id == segment_id, Translation.status == "current")
        ).first()

        if not translation:
            return

        # Mark existing TTS stale
        existing = session.exec(
            select(TTSGeneration).where(TTSGeneration.segment_id == segment_id, TTSGeneration.status == "current")
        ).all()
        for t in existing:
            t.status = "stale"
            session.add(t)

        if settings.openai_api_key:
            adapter = OpenAITTSAdapter(api_key=settings.openai_api_key)
            tts_provider = "openai-tts-1"
        else:
            adapter = MockTTSAdapter()
            tts_provider = "mock"

        audio_bytes, audio_fmt = await adapter.synthesize(translation.translated_text)

        tts_dir = os.path.join(settings.media_dir, segment.lecture_id, "tts")
        os.makedirs(tts_dir, exist_ok=True)
        tts_path = os.path.join(segment.lecture_id, "tts", f"{segment_id}.{audio_fmt}")
        abs_path = os.path.join(settings.media_dir, tts_path)

        with open(abs_path, "wb") as f:
            f.write(audio_bytes)

        from backend.models import MediaObject

        mime_type = "audio/mpeg" if audio_fmt == "mp3" else "audio/wav"
        mo = MediaObject(
            lecture_id=segment.lecture_id,
            kind="segment_tts",
            file_path=tts_path,
            size_bytes=len(audio_bytes),
            mime_type=mime_type,
        )
        session.add(mo)
        session.flush()

        tts_gen = TTSGeneration(
            segment_id=segment_id,
            media_object_id=mo.id,
            provider=tts_provider,
            input_text=translation.translated_text,
            status="current",
        )
        session.add(tts_gen)
        session.commit()
