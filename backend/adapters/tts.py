"""TTS adapters: Protocol + OpenAI TTS implementation."""

import logging
import struct
import wave
from io import BytesIO
from typing import Protocol, runtime_checkable

from openai import AsyncOpenAI

log = logging.getLogger(__name__)


def _generate_silence_wav(duration_seconds: float = 1.0, sample_rate: int = 22050) -> bytes:
    """Generate a silent WAV file as bytes."""
    n_samples = int(sample_rate * duration_seconds)
    buf = BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(struct.pack("<" + "h" * n_samples, *([0] * n_samples)))
    return buf.getvalue()


@runtime_checkable
class TTSAdapter(Protocol):
    async def synthesize(
        self,
        text: str,
        voice_ref_path: str | None = None,
        language: str = "es",
        speed: float = 1.0,
    ) -> tuple[bytes, str]:
        """Synthesize speech from text. Returns (audio_bytes, format)."""
        ...


class OpenAITTSAdapter:
    """TTS adapter using OpenAI tts-1 / tts-1-hd."""

    # Available voices: alloy, ash, ballad, coral, echo, fable, nova, onyx, sage, shimmer
    def __init__(self, api_key: str, model: str = "tts-1", voice: str = "nova"):
        self.client = AsyncOpenAI(api_key=api_key)
        self.model = model
        self.voice = voice

    async def synthesize(
        self,
        text: str,
        voice_ref_path: str | None = None,
        language: str = "es",
        speed: float = 1.0,
    ) -> tuple[bytes, str]:
        """Generate Spanish speech using OpenAI TTS. Returns (mp3_bytes, 'mp3')."""
        log.info(f"TTS ({self.model}/{self.voice}, speed={speed}): {text[:60]}...")

        response = await self.client.audio.speech.create(
            model=self.model,
            voice=self.voice,
            input=text,
            response_format="mp3",
            speed=speed,
        )

        audio_bytes = response.content
        log.info(f"TTS complete: {len(audio_bytes)} bytes")
        return audio_bytes, "mp3"


class VoxtralTTSAdapter:
    """TTS adapter for Voxtral (Mistral). Placeholder — needs API spike."""

    def __init__(self, api_key: str | None = None, model_id: str = "voxtral-mini"):
        self.api_key = api_key
        self.model_id = model_id

    async def synthesize(
        self,
        text: str,
        voice_ref_path: str | None = None,
        language: str = "es",
        speed: float = 1.0,
    ) -> tuple[bytes, str]:
        word_count = len(text.split())
        duration = max(0.5, word_count * 0.4)
        return _generate_silence_wav(duration_seconds=duration), "wav"


class ElevenLabsTTSAdapter:
    """TTS adapter for ElevenLabs. Placeholder — needs API key."""

    def __init__(self, api_key: str | None = None, voice_id: str = "21m00Tcm4TlvDq8ikWAM"):
        self.api_key = api_key
        self.voice_id = voice_id

    async def synthesize(
        self,
        text: str,
        voice_ref_path: str | None = None,
        language: str = "es",
        speed: float = 1.0,
    ) -> tuple[bytes, str]:
        word_count = len(text.split())
        duration = max(0.5, word_count * 0.4)
        return _generate_silence_wav(duration_seconds=duration), "wav"


class MockTTSAdapter:
    """Mock adapter for testing without API keys."""

    async def synthesize(
        self,
        text: str,
        voice_ref_path: str | None = None,
        language: str = "es",
        speed: float = 1.0,
    ) -> tuple[bytes, str]:
        word_count = len(text.split())
        duration = max(0.5, word_count * 0.4)
        return _generate_silence_wav(duration_seconds=duration), "wav"
