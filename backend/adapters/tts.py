"""TTS adapters: Protocol + Fish Audio, OpenAI, and stub implementations."""

import logging
import struct
import wave
from io import BytesIO
from typing import Protocol, runtime_checkable

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


class FishAudioTTSAdapter:
    """TTS adapter using Fish Audio with voice cloning."""

    def __init__(self, api_key: str, model: str = "s2-pro"):
        import httpx
        self.api_key = api_key
        self.model = model
        self.client = httpx.AsyncClient(
            base_url="https://api.fish.audio",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=60.0,
        )
        self._voice_ref_cache: dict[str, bytes] = {}

    async def synthesize(
        self,
        text: str,
        voice_ref_path: str | None = None,
        language: str = "es",
        speed: float = 1.0,
    ) -> tuple[bytes, str]:
        """Generate speech with Fish Audio, optionally cloning from reference audio."""
        log.info(f"Fish TTS (speed={speed}): {text[:60]}...")

        # Build request body
        body: dict = {
            "text": text,
            "format": "mp3",
            "mp3_bitrate": 128,
            "sample_rate": 44100,
            "normalize": True,
        }

        if speed != 1.0:
            body["speed"] = speed

        if voice_ref_path:
            # Use inline voice cloning with reference audio
            ref_audio = await self._load_reference(voice_ref_path)
            # For inline cloning, we use msgpack format with references
            import ormsgpack
            body["references"] = [
                {"audio": ref_audio, "text": ""}  # text left empty — Fish will auto-detect
            ]
            response = await self.client.post(
                "/v1/tts",
                content=ormsgpack.packb(body),
                headers={"Content-Type": "application/msgpack"},
            )
        else:
            # No voice reference — use default voice
            response = await self.client.post(
                "/v1/tts",
                json=body,
            )

        if response.status_code != 200:
            error_text = response.text
            log.error(f"Fish Audio TTS failed ({response.status_code}): {error_text}")
            raise RuntimeError(f"Fish Audio TTS failed: {response.status_code} {error_text}")

        audio_bytes = response.content
        log.info(f"Fish TTS complete: {len(audio_bytes)} bytes")
        return audio_bytes, "mp3"

    async def _load_reference(self, path: str) -> bytes:
        """Load and cache reference audio bytes."""
        if path not in self._voice_ref_cache:
            with open(path, "rb") as f:
                self._voice_ref_cache[path] = f.read()
        return self._voice_ref_cache[path]


class OpenAITTSAdapter:
    """TTS adapter using OpenAI tts-1 / tts-1-hd. No voice cloning."""

    def __init__(self, api_key: str, model: str = "tts-1", voice: str = "nova"):
        from openai import AsyncOpenAI
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
        log.info(f"OpenAI TTS ({self.model}/{self.voice}, speed={speed}): {text[:60]}...")
        response = await self.client.audio.speech.create(
            model=self.model,
            voice=self.voice,
            input=text,
            response_format="mp3",
            speed=speed,
        )
        audio_bytes = response.content
        log.info(f"OpenAI TTS complete: {len(audio_bytes)} bytes")
        return audio_bytes, "mp3"


class VoxtralTTSAdapter:
    """TTS adapter for Voxtral (Mistral). Placeholder."""

    def __init__(self, api_key: str | None = None, model_id: str = "voxtral-mini"):
        self.api_key = api_key
        self.model_id = model_id

    async def synthesize(self, text: str, voice_ref_path: str | None = None,
                         language: str = "es", speed: float = 1.0) -> tuple[bytes, str]:
        word_count = len(text.split())
        duration = max(0.5, word_count * 0.4)
        return _generate_silence_wav(duration_seconds=duration), "wav"


class ElevenLabsTTSAdapter:
    """TTS adapter for ElevenLabs. Placeholder."""

    def __init__(self, api_key: str | None = None, voice_id: str = "21m00Tcm4TlvDq8ikWAM"):
        self.api_key = api_key
        self.voice_id = voice_id

    async def synthesize(self, text: str, voice_ref_path: str | None = None,
                         language: str = "es", speed: float = 1.0) -> tuple[bytes, str]:
        word_count = len(text.split())
        duration = max(0.5, word_count * 0.4)
        return _generate_silence_wav(duration_seconds=duration), "wav"


class MockTTSAdapter:
    """Mock adapter for testing without API keys."""

    async def synthesize(self, text: str, voice_ref_path: str | None = None,
                         language: str = "es", speed: float = 1.0) -> tuple[bytes, str]:
        word_count = len(text.split())
        duration = max(0.5, word_count * 0.4)
        return _generate_silence_wav(duration_seconds=duration), "wav"
