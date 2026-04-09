# Video Translator

AI-powered video dubbing pipeline. Upload a video, get a dubbed version in another language with voice cloning.

Built as a POC for lecture and media translation. Currently supports any source language to any target language, with voice cloning that preserves the original speaker's voice characteristics.

## What it does

1. **Upload** a video (lecture, anime clip, news segment)
2. **Transcribe** with speaker diarization (OpenAI gpt-4o-transcribe-diarize)
3. **Translate** the transcript (OpenAI GPT-4o)
4. **Clone voices** and generate dubbed audio per speaker (Fish Audio S2-Pro)
5. **Mix** the dubbed audio with the original background sounds
6. **Export** a final MP4 with the new audio track

The browser UI lets you review and edit transcripts/translations, regenerate individual segments, and compare the original with the dubbed version side-by-side.

## Architecture

```
Frontend (React + Vite + Tailwind + shadcn/ui)
    |
    | /api/* (proxied in dev)
    v
FastAPI Backend (Python)
    |
    |-- SQLite (lectures, segments, translations, jobs)
    |-- Local filesystem (media files)
    |-- asyncio background tasks (pipeline orchestration)
    |
    |-- OpenAI API (transcription + translation)
    |-- Fish Audio API (voice-cloned TTS)
    |-- ffmpeg (all media processing)
```

### Pipeline steps

```
Upload video
  -> Extract audio (ffmpeg)
  -> Normalize to MP3 for transcription (ffmpeg, loudnorm)
  -> Diarized transcription (OpenAI gpt-4o-transcribe-diarize)
       Returns segments with real timestamps + speaker labels
  -> Merge segments into utterance groups
       Consecutive segments from same speaker with <2s gaps
       become one group for natural-flowing TTS
  -> Translate each group (OpenAI GPT-4o with context)
  -> Extract per-speaker voice references from original audio
  -> TTS per group with voice cloning (Fish Audio S2-Pro)
       Fit-to-window: speeds up 1.0x -> 1.35x if too long
       Hallucination detection: retries or truncates bad output
  -> Loudness-matched mixdown (ffmpeg)
       Measures original LUFS, normalizes TTS to match
       Mutes original speech region, keeps intro/outro audio
  -> Mux export (ffmpeg, video copy + new AAC audio)
```

### Key design decisions

- **Utterance group merging**: Diarization returns short fragments. We merge consecutive same-speaker segments into full sentences before translation and TTS. This produces natural cadence instead of choppy per-fragment synthesis.
- **Per-speaker voice cloning**: Each detected speaker gets their own voice reference extracted from the original audio. Fish Audio's inline zero-shot cloning generates target-language speech matching each speaker's voice.
- **Fit-to-window speed adjustment**: Spanish (and other languages) often runs longer than English. The pipeline tries progressively faster speeds (1.0x, 1.1x, 1.2x, 1.35x) and flags segments that still overflow.
- **Loudness matching**: Measures original audio loudness (LUFS) with ffmpeg's ebur128 filter and normalizes the final mix to match, so the dubbed video sounds consistent with the original.
- **Provider adapters**: Transcription, translation, and TTS each have a protocol interface. Swap providers by changing config (OpenAI, Fish Audio, ElevenLabs, Voxtral, mock).

### Data model (SQLite, 6 tables)

```
lectures          -- source video metadata + status
segments          -- diarized transcript segments with timestamps
translations      -- per-segment translations with QA flags
tts_generations   -- per-segment TTS output with duration/speed info
media_objects     -- all files (video, audio, TTS clips, exports)
jobs              -- pipeline job tracking with progress
```

## Running locally

### Prerequisites

- Python 3.12+
- Node.js 18+ and pnpm
- ffmpeg
- API keys: OpenAI, Fish Audio (optional: Mistral, ElevenLabs)

### Setup

```bash
# Clone
git clone https://github.com/dbirks/video-translator.git
cd video-translator

# Backend
cp .env.example .env
# Edit .env with your API keys
uv sync

# Frontend
cd frontend
pnpm install
cd ..
```

### Run

```bash
# Terminal 1: Backend
uv run uvicorn backend.main:app --reload --port 8000 --host 0.0.0.0

# Terminal 2: Frontend
cd frontend && pnpm dev -- --host 0.0.0.0
```

Open http://localhost:5173

### Docker Compose

```bash
docker compose up --build
```

Runs the API on port 8000 behind Caddy on port 80.

## Project structure

```
backend/
  main.py              FastAPI app factory
  config.py            pydantic-settings (reads .env)
  models.py            SQLModel tables (6 core tables)
  database.py          SQLite engine + session
  api/
    lectures.py        CRUD, upload, process, export, media serving
    segments.py        Edit transcript/translation, regenerate TTS
    jobs.py            Job status + SSE events
  services/
    pipeline.py        Main pipeline orchestrator (asyncio)
    media.py           ffmpeg operations (extract, normalize, mix, mux, loudness)
    storage.py         Local file storage
  adapters/
    transcription.py   OpenAI diarized transcription
    translation.py     OpenAI GPT-4o translation
    tts.py             Fish Audio, OpenAI TTS, ElevenLabs, Voxtral (stubs)

frontend/
  src/
    main.tsx           React app entry + routing
    lib/api.ts         API client + types
    pages/
      LectureList.tsx  Lecture list with create/status
      LectureDetail.tsx Video players + progress + editor
    components/
      SegmentEditor.tsx Side-by-side EN/ES editor with regeneration

compose.yaml           Docker Compose (app + Caddy)
Dockerfile             Python 3.12 + ffmpeg + uv
Caddyfile              Reverse proxy config
```

## API keys

| Provider | Used for | Required? |
|----------|----------|-----------|
| OpenAI | Transcription (gpt-4o-transcribe-diarize) + Translation (GPT-4o) | Yes |
| Fish Audio | Voice-cloned TTS (S2-Pro) | No (falls back to OpenAI TTS without cloning) |
| Mistral | Voxtral TTS (stub) | No |
| ElevenLabs | TTS (stub) | No |

## Tested with

- **English lecture** (Chef Mike's Three Cheese Pizza) -> Spanish dub
- **Japanese anime** (Frieren S02E10) -> English dub with 2-speaker voice cloning

## Open issues

- [#1 Improve speaker diarization](https://github.com/dbirks/video-translator/issues/1) -- detect 3+ speakers (pyannote two-pass approach)
- [#2 Demucs vocal separation](https://github.com/dbirks/video-translator/issues/2) -- strip original vocals, keep background sounds for cleaner mix
