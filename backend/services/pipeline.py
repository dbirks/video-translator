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


async def run_pipeline(lecture_id: str, session: Session, job_id: str | None = None) -> None:
    """
    Full pipeline: extract_audio -> normalize -> transcribe -> translate -> tts -> mixdown -> mux
    Uses an existing Job record if job_id is provided, otherwise creates one.
    """
    settings = get_settings()

    if job_id:
        job = session.get(Job, job_id)
        if job:
            job.status = "running"
            job.started_at = datetime.utcnow().isoformat()
            session.add(job)
            session.commit()
        else:
            job = None

    if not job_id or not job:
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

        from backend.adapters.transcription import MockTranscriptionAdapter, OpenAITranscriptionAdapter
        from backend.config import get_settings as _get_settings

        s = _get_settings()
        if s.openai_api_key:
            transcriber = OpenAITranscriptionAdapter(api_key=s.openai_api_key)
        else:
            transcriber = MockTranscriptionAdapter()
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

        # --- Step 5: Merge segments into utterance groups ---
        # Combine consecutive segments with small gaps into natural sentence groups.
        # This produces much more natural TTS (one call per sentence/paragraph
        # instead of one per fragment).
        step("translating", 0.50)

        MAX_GAP = 2.0  # seconds — merge if gap is less than this
        groups: list[list] = []  # each group is a list of consecutive Segment objects
        current_group: list = []

        for seg in db_segments:
            if not current_group:
                current_group = [seg]
            else:
                gap = seg.start_sec - current_group[-1].end_sec
                same_speaker = (seg.speaker or "") == (current_group[-1].speaker or "")
                if gap < MAX_GAP and same_speaker:
                    current_group.append(seg)
                else:
                    groups.append(current_group)
                    current_group = [seg]
        if current_group:
            groups.append(current_group)

        _publish(lecture_id, {"step": "translating", "progress": 0.52,
                              "detail": f"Merged {len(db_segments)} segments into {len(groups)} utterance groups"})

        # --- Step 5b: Translate each group as a whole ---
        from backend.adapters.translation import MockTranslationAdapter, OpenAITranslationAdapter

        if s.openai_api_key:
            translator = OpenAITranslationAdapter(api_key=s.openai_api_key)
            provider_model = "gpt-4o"
        else:
            translator = MockTranslationAdapter()
            provider_model = "mock"

        group_translations: list[str] = []
        for gi, group in enumerate(groups):
            group_text = " ".join(seg.source_text_en for seg in group)
            context_before = " ".join(s.source_text_en for s in groups[gi - 1]) if gi > 0 else ""
            context_after = " ".join(s.source_text_en for s in groups[gi + 1]) if gi < len(groups) - 1 else ""

            translated_text = await translator.translate(
                group_text,
                source_lang=lecture.source_language,
                target_lang=lecture.target_language,
                context_before=context_before,
                context_after=context_after,
            )
            group_translations.append(translated_text)

            # Store translation on the first segment of the group (the others get a reference)
            for si, seg in enumerate(group):
                if si == 0:
                    translation = Translation(
                        segment_id=seg.id,
                        translated_text=translated_text,
                        provider_model=provider_model,
                        status="current",
                    )
                else:
                    # Mark non-primary segments as part of the group
                    translation = Translation(
                        segment_id=seg.id,
                        translated_text=f"[part of group with {group[0].id[:8]}]",
                        provider_model=provider_model,
                        status="current",
                    )
                session.add(translation)
        session.commit()

        # --- Step 6: TTS per utterance group (with fit-to-window) ---
        step("dubbing", 0.70)

        from backend.adapters.tts import FishAudioTTSAdapter, MockTTSAdapter, OpenAITTSAdapter
        from backend.services.media import get_duration

        # Extract a voice reference clip from the original audio
        voice_ref_path = None
        if db_segments:
            best_seg = max(db_segments, key=lambda seg: min(seg.end_sec - seg.start_sec, 15.0))
            ref_start = best_seg.start_sec
            ref_end = min(best_seg.end_sec, ref_start + 15.0)
            voice_ref_rel = os.path.join(lecture_id, "voice_reference.wav")
            voice_ref_path = os.path.join(settings.media_dir, voice_ref_rel)
            from backend.services.media import extract_clip
            await extract_clip(wav_abs, voice_ref_path, ref_start, ref_end)

            ref_mo = MediaObject(
                lecture_id=lecture_id, kind="voice_reference",
                file_path=voice_ref_rel, size_bytes=os.path.getsize(voice_ref_path),
                mime_type="audio/wav",
            )
            session.add(ref_mo)
            session.commit()

        if s.fish_api_key:
            tts_adapter = FishAudioTTSAdapter(api_key=s.fish_api_key)
            tts_provider = "fish-s2-pro"
        elif s.openai_api_key:
            tts_adapter = OpenAITTSAdapter(api_key=s.openai_api_key)
            tts_provider = "openai-tts-1"
        else:
            tts_adapter = MockTTSAdapter()
            tts_provider = "mock"

        tts_dir = os.path.join(settings.media_dir, lecture_id, "tts")
        os.makedirs(tts_dir, exist_ok=True)

        # TTS one audio file per group, placed at the group's start time
        group_tts_paths: list[str] = []
        group_timestamps: list[tuple[float, float]] = []

        for gi, (group, translated_text) in enumerate(zip(groups, group_translations)):
            group_start = group[0].start_sec
            group_end = group[-1].end_sec
            window = group_end - group_start

            speed = 1.0
            audio_bytes = None
            audio_fmt = "mp3"
            tts_duration = 0.0
            qa_flags = []

            for attempt_speed in [1.0, 1.1, 1.2, 1.35]:
                audio_bytes, audio_fmt = await tts_adapter.synthesize(
                    translated_text,
                    voice_ref_path=voice_ref_path,
                    language=lecture.target_language,
                    speed=attempt_speed,
                )
                tmp_path = os.path.join(tts_dir, f"group_{gi}_tmp.{audio_fmt}")
                with open(tmp_path, "wb") as f:
                    f.write(audio_bytes)
                try:
                    tts_duration = await get_duration(tmp_path)
                except Exception:
                    tts_duration = 0.0
                os.remove(tmp_path)

                speed = attempt_speed
                overflow = (tts_duration - window) / window if window > 0 else 0
                if overflow <= 0.15:
                    break

            if tts_duration > window * 1.15:
                qa_flags.append(f"TOO_LONG: {tts_duration:.1f}s vs {window:.1f}s window (speed={speed})")

            group_file = f"group_{gi}.{audio_fmt}"
            tts_rel = os.path.join(lecture_id, "tts", group_file)
            tts_abs = os.path.join(settings.media_dir, tts_rel)
            with open(tts_abs, "wb") as f:
                f.write(audio_bytes)

            group_tts_paths.append(tts_abs)
            group_timestamps.append((group_start, group_end))

            mime_type = "audio/mpeg" if audio_fmt == "mp3" else "audio/wav"
            tts_mo = MediaObject(
                lecture_id=lecture_id, kind="segment_tts",
                file_path=tts_rel, size_bytes=len(audio_bytes), mime_type=mime_type,
            )
            session.add(tts_mo)
            session.flush()

            # Store TTS generation on the first segment of the group
            import json as _json
            first_seg = group[0]
            if qa_flags:
                first_trans = session.exec(
                    select(Translation).where(Translation.segment_id == first_seg.id, Translation.status == "current")
                ).first()
                if first_trans:
                    first_trans.qa_flags = _json.dumps(qa_flags)
                    session.add(first_trans)

            tts_gen = TTSGeneration(
                segment_id=first_seg.id,
                media_object_id=tts_mo.id,
                provider=tts_provider,
                input_text=translated_text,
                duration_seconds=tts_duration,
                settings_json=_json.dumps({"speed": speed, "window": window, "group_size": len(group)}),
                status="current",
            )
            session.add(tts_gen)

        session.commit()

        # --- Step 7: Mixdown ---
        step("dubbing", 0.85)

        mix_rel = os.path.join(lecture_id, "spanish_mix.mp3")
        mix_abs = os.path.join(settings.media_dir, mix_rel)

        from backend.services.media import mixdown_segments

        # Find the original extracted audio to mix underneath (preserves background sounds)
        orig_audio_mo = session.exec(
            select(MediaObject).where(
                MediaObject.lecture_id == lecture_id,
                MediaObject.kind == "extracted_audio",
            )
        ).first()
        orig_audio_path = os.path.join(settings.media_dir, orig_audio_mo.file_path) if orig_audio_mo else None

        await mixdown_segments(
            group_tts_paths, group_timestamps, duration or 60.0, mix_abs,
            original_audio_path=orig_audio_path,
        )

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
