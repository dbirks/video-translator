"""Main pipeline orchestrator for video translation."""

import os
from datetime import datetime

from sqlmodel import Session, select

from backend.config import get_settings
from backend.models import Job, Lecture, MediaObject, Segment, Translation, TTSGeneration


def _publish(lecture_id: str, event: dict) -> None:
    """Publish an SSE event without importing at module level to avoid circular imports."""
    try:
        from backend.api.jobs import publish_event

        publish_event(lecture_id, event)
    except Exception:
        pass


def _update_job(session: Session, job: Job, **kwargs) -> None:
    for k, v in kwargs.items():
        setattr(job, k, v)
    session.add(job)
    session.commit()


async def run_pipeline(lecture_id: str, session: Session) -> None:
    """
    Full pipeline: extract_audio -> normalize -> transcribe -> translate -> tts -> mixdown -> mux
    Creates/updates a Job record and publishes SSE progress events.
    """
    settings = get_settings()

    # Create a job record
    job = Job(
        lecture_id=lecture_id,
        job_type="full_pipeline",
        status="running",
        started_at=datetime.utcnow().isoformat(),
    )
    session.add(job)
    session.commit()
    session.refresh(job)

    lecture = session.get(Lecture, lecture_id)
    if not lecture:
        _update_job(session, job, status="failed", error_message="Lecture not found",
                    completed_at=datetime.utcnow().isoformat())
        return

    def step(name: str, progress: float) -> None:
        _update_job(session, job, current_step=name, progress=progress)
        lecture.status = name
        lecture.updated_at = datetime.utcnow().isoformat()
        session.add(lecture)
        session.commit()
        _publish(lecture_id, {"type": "progress", "job_id": job.id, "step": name, "progress": progress})

    try:
        # --- Step 1: Find source video ---
        step("extracting", 0.05)
        source_media = session.exec(
            select(MediaObject).where(
                MediaObject.lecture_id == lecture_id,
                MediaObject.kind == "source_video",
            )
        ).first()

        if not source_media:
            raise RuntimeError("No source video found for lecture")

        video_abs = os.path.join(settings.media_dir, source_media.file_path)
        lecture_dir = os.path.join(settings.media_dir, lecture_id)
        os.makedirs(lecture_dir, exist_ok=True)

        # --- Step 2: Extract audio ---
        step("extracting", 0.10)
        wav_rel = os.path.join(lecture_id, "extracted_audio.wav")
        wav_abs = os.path.join(settings.media_dir, wav_rel)

        from backend.services.media import extract_audio, get_duration

        await extract_audio(video_abs, wav_abs)

        wav_media = MediaObject(
            lecture_id=lecture_id,
            kind="extracted_audio",
            file_path=wav_rel,
            size_bytes=os.path.getsize(wav_abs),
            mime_type="audio/wav",
        )
        session.add(wav_media)
        session.commit()

        # Get duration
        duration = await get_duration(video_abs)
        lecture.duration_seconds = duration
        lecture.updated_at = datetime.utcnow().isoformat()
        session.add(lecture)
        session.commit()

        # --- Step 3: Normalize audio ---
        step("extracting", 0.20)
        norm_rel = os.path.join(lecture_id, "normalized_audio.mp3")
        norm_abs = os.path.join(settings.media_dir, norm_rel)

        from backend.services.media import normalize_audio

        await normalize_audio(wav_abs, norm_abs)

        norm_media = MediaObject(
            lecture_id=lecture_id,
            kind="normalized_audio",
            file_path=norm_rel,
            size_bytes=os.path.getsize(norm_abs),
            mime_type="audio/mpeg",
        )
        session.add(norm_media)
        session.commit()

        # --- Step 4: Transcribe ---
        step("transcribing", 0.35)

        from backend.adapters.transcription import OpenAITranscriptionAdapter
        from backend.config import get_settings as _get_settings

        s = _get_settings()
        transcriber = OpenAITranscriptionAdapter(api_key=s.openai_api_key or None)
        transcript_segments = await transcriber.transcribe(norm_abs, language=lecture.source_language)

        # Remove any existing segments for this lecture
        existing_segments = session.exec(select(Segment).where(Segment.lecture_id == lecture_id)).all()
        for seg in existing_segments:
            session.delete(seg)
        session.commit()

        # Persist segments
        db_segments = []
        for i, ts in enumerate(transcript_segments):
            seg = Segment(
                lecture_id=lecture_id,
                start_sec=ts.start,
                end_sec=ts.end,
                source_text_en=ts.text,
                speaker=ts.speaker,
                ordering=i,
            )
            session.add(seg)
            db_segments.append(seg)
        session.commit()
        for seg in db_segments:
            session.refresh(seg)

        # --- Step 5: Translate all segments ---
        step("translating", 0.55)

        from backend.adapters.translation import LLMTranslationAdapter

        translator = LLMTranslationAdapter(api_key=s.mistral_api_key or None)

        for seg in db_segments:
            translated_text = await translator.translate(
                seg.source_text_en,
                source_lang=lecture.source_language,
                target_lang=lecture.target_language,
            )
            translation = Translation(
                segment_id=seg.id,
                translated_text=translated_text,
                provider_model="mock",
                status="current",
            )
            session.add(translation)
        session.commit()

        # --- Step 6: TTS for all segments ---
        step("dubbing", 0.70)

        from backend.adapters.tts import VoxtralTTSAdapter

        tts_adapter = VoxtralTTSAdapter(api_key=s.mistral_api_key or None)
        tts_dir = os.path.join(settings.media_dir, lecture_id, "tts")
        os.makedirs(tts_dir, exist_ok=True)

        for seg in db_segments:
            translation = session.exec(
                select(Translation).where(
                    Translation.segment_id == seg.id,
                    Translation.status == "current",
                )
            ).first()

            if not translation:
                continue

            audio_bytes = await tts_adapter.synthesize(translation.translated_text)
            tts_rel = os.path.join(lecture_id, "tts", f"{seg.id}.wav")
            tts_abs = os.path.join(settings.media_dir, tts_rel)
            with open(tts_abs, "wb") as f:
                f.write(audio_bytes)

            tts_mo = MediaObject(
                lecture_id=lecture_id,
                kind="segment_tts",
                file_path=tts_rel,
                size_bytes=len(audio_bytes),
                mime_type="audio/wav",
            )
            session.add(tts_mo)
            session.flush()

            tts_gen = TTSGeneration(
                segment_id=seg.id,
                media_object_id=tts_mo.id,
                provider="voxtral",
                input_text=translation.translated_text,
                status="current",
            )
            session.add(tts_gen)

        session.commit()

        # --- Step 7: Mixdown ---
        step("dubbing", 0.85)

        segment_tts_paths = []
        timestamps = []

        for seg in db_segments:
            tts_gen = session.exec(
                select(TTSGeneration).where(
                    TTSGeneration.segment_id == seg.id,
                    TTSGeneration.status == "current",
                )
            ).first()

            if tts_gen and tts_gen.media_object_id:
                tts_mo = session.get(MediaObject, tts_gen.media_object_id)
                if tts_mo:
                    segment_tts_paths.append(os.path.join(settings.media_dir, tts_mo.file_path))
                    timestamps.append((seg.start_sec, seg.end_sec))

        mix_rel = os.path.join(lecture_id, "spanish_mix.mp3")
        mix_abs = os.path.join(settings.media_dir, mix_rel)

        from backend.services.media import mixdown_segments

        await mixdown_segments(segment_tts_paths, timestamps, duration or 60.0, mix_abs)

        mix_mo = MediaObject(
            lecture_id=lecture_id,
            kind="spanish_mix",
            file_path=mix_rel,
            size_bytes=os.path.getsize(mix_abs),
            mime_type="audio/mpeg",
        )
        session.add(mix_mo)
        session.commit()

        # --- Step 8: Mux export ---
        step("dubbing", 0.95)

        export_rel = os.path.join(lecture_id, "export.mp4")
        export_abs = os.path.join(settings.media_dir, export_rel)

        from backend.services.media import mux_export

        await mux_export(video_abs, mix_abs, export_abs)

        export_mo = MediaObject(
            lecture_id=lecture_id,
            kind="export_mp4",
            file_path=export_rel,
            size_bytes=os.path.getsize(export_abs),
            mime_type="video/mp4",
        )
        session.add(export_mo)
        session.commit()

        # --- Done ---
        lecture.status = "draft"
        lecture.updated_at = datetime.utcnow().isoformat()
        session.add(lecture)

        _update_job(
            session, job,
            status="completed",
            current_step="done",
            progress=1.0,
            completed_at=datetime.utcnow().isoformat(),
        )

        _publish(lecture_id, {
            "type": "completed",
            "job_id": job.id,
            "lecture_id": lecture_id,
        })

    except Exception as exc:
        _update_job(
            session, job,
            status="failed",
            error_message=str(exc),
            completed_at=datetime.utcnow().isoformat(),
        )
        lecture.status = "uploaded"
        lecture.updated_at = datetime.utcnow().isoformat()
        session.add(lecture)
        session.commit()

        _publish(lecture_id, {
            "type": "failed",
            "job_id": job.id,
            "error": str(exc),
        })
        raise


async def run_export(lecture_id: str, job_id: str, session: Session) -> None:
    """Re-run just the mixdown + mux steps for an already-processed lecture."""
    settings = get_settings()

    job = session.get(Job, job_id)
    if not job:
        return

    lecture = session.get(Lecture, lecture_id)
    if not lecture:
        _update_job(session, job, status="failed", error_message="Lecture not found",
                    completed_at=datetime.utcnow().isoformat())
        return

    try:
        _update_job(session, job, status="running", started_at=datetime.utcnow().isoformat(),
                    current_step="exporting", progress=0.1)
        _publish(lecture_id, {"type": "progress", "job_id": job_id, "step": "exporting", "progress": 0.1})

        source_media = session.exec(
            select(MediaObject).where(
                MediaObject.lecture_id == lecture_id,
                MediaObject.kind == "source_video",
            )
        ).first()

        if not source_media:
            raise RuntimeError("No source video found")

        video_abs = os.path.join(settings.media_dir, source_media.file_path)

        mix_media = session.exec(
            select(MediaObject).where(
                MediaObject.lecture_id == lecture_id,
                MediaObject.kind == "spanish_mix",
            ).order_by(MediaObject.created_at.desc())  # type: ignore[arg-type]
        ).first()

        if not mix_media:
            raise RuntimeError("No mixdown audio found — run full pipeline first")

        mix_abs = os.path.join(settings.media_dir, mix_media.file_path)
        export_rel = os.path.join(lecture_id, "export.mp4")
        export_abs = os.path.join(settings.media_dir, export_rel)

        from backend.services.media import mux_export

        await mux_export(video_abs, mix_abs, export_abs)

        # Remove old export media object if exists
        old_exports = session.exec(
            select(MediaObject).where(
                MediaObject.lecture_id == lecture_id,
                MediaObject.kind == "export_mp4",
            )
        ).all()
        for old in old_exports:
            session.delete(old)

        export_mo = MediaObject(
            lecture_id=lecture_id,
            kind="export_mp4",
            file_path=export_rel,
            size_bytes=os.path.getsize(export_abs),
            mime_type="video/mp4",
        )
        session.add(export_mo)

        lecture.status = "exported"
        lecture.updated_at = datetime.utcnow().isoformat()
        session.add(lecture)

        _update_job(
            session, job,
            status="completed",
            current_step="done",
            progress=1.0,
            completed_at=datetime.utcnow().isoformat(),
        )

        _publish(lecture_id, {"type": "completed", "job_id": job_id})

    except Exception as exc:
        _update_job(
            session, job,
            status="failed",
            error_message=str(exc),
            completed_at=datetime.utcnow().isoformat(),
        )
        _publish(lecture_id, {"type": "failed", "job_id": job_id, "error": str(exc)})
        raise
