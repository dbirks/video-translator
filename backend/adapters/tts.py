"""TTS adapters: Protocol + Voxtral and ElevenLabs stubs."""

import struct
import wave
from io import BytesIO
from typing import Protocol, runtime_checkable


def _generate_silence_wav(duration_seconds: float = 1.0, sample_rate: int = 22050) -> bytes:
    """Generate a silent WAV file as bytes."""
    n_samples = int(sample_rate * duration_seconds)
    buf = BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # 16-bit
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
    ) -> bytes:
        """Synthesize speech from text. Returns WAV audio bytes."""
        ...


class VoxtralTTSAdapter:
    """
    TTS adapter for Voxtral (Mistral's TTS model).

    For the POC, this returns a silent WAV placeholder so the pipeline can
    run end-to-end. Replace synthesize() with real Voxtral API calls when ready.
    """

    def __init__(self, api_key: str | None = None, model_id: str = "voxtral-mini"):
        self.api_key = api_key
        self.model_id = model_id

    async def synthesize(
        self,
        text: str,
        voice_ref_path: str | None = None,
        language: str = "es",
    ) -> bytes:
        """Return silent WAV as placeholder. ~0.5s of silence per 10 chars."""
        word_count = len(text.split())
        # Rough estimate: 150 words/min => 0.4s per word
        duration = max(0.5, word_count * 0.4)
        return _generate_silence_wav(duration_seconds=duration)


class ElevenLabsTTSAdapter:
    """
    TTS adapter for ElevenLabs.

    For the POC, returns silent WAV placeholder.
    Replace synthesize() with real ElevenLabs API calls when ready.
    """

    def __init__(
        self,
        api_key: str | None = None,
        voice_id: str = "21m00Tcm4TlvDq8ikWAM",  # Rachel voice
        model_id: str = "eleven_multilingual_v2",
    ):
        self.api_key = api_key
        self.voice_id = voice_id
        self.model_id = model_id

    async def synthesize(
        self,
        text: str,
        voice_ref_path: str | None = None,
        language: str = "es",
    ) -> bytes:
        """Return silent WAV as placeholder."""
        word_count = len(text.split())
        duration = max(0.5, word_count * 0.4)
        return _generate_silence_wav(duration_seconds=duration)
