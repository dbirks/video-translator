"""Transcription adapters: Protocol + OpenAI diarized implementation."""

import logging
from typing import Protocol, runtime_checkable

from openai import AsyncOpenAI

log = logging.getLogger(__name__)


class TranscriptSegment:
    """Represents a single transcribed segment."""

    def __init__(self, start: float, end: float, text: str, speaker: str | None = None):
        self.start = start
        self.end = end
        self.text = text
        self.speaker = speaker

    def __repr__(self) -> str:
        return f"TranscriptSegment(start={self.start}, end={self.end}, text={self.text!r})"


@runtime_checkable
class TranscriptionAdapter(Protocol):
    async def transcribe(self, audio_path: str, language: str = "en") -> list[TranscriptSegment]:
        """Transcribe audio file and return a list of timed segments."""
        ...


class OpenAITranscriptionAdapter:
    """Transcription adapter using OpenAI gpt-4o-transcribe-diarize."""

    def __init__(self, api_key: str, model: str = "gpt-4o-transcribe"):
        self.client = AsyncOpenAI(api_key=api_key)
        self.model = model

    async def transcribe(self, audio_path: str, language: str = "en") -> list[TranscriptSegment]:
        """Transcribe audio and return timed segments.

        Uses gpt-4o-transcribe with verbose_json for timestamps.
        Falls back to gpt-4o-transcribe-diarize if available.
        """
        import os

        file_size = os.path.getsize(audio_path)
        log.info(f"Transcribing {audio_path} ({file_size / 1024 / 1024:.1f} MB) with {self.model}")

        if file_size > 25 * 1024 * 1024:
            log.warning("File exceeds 25MB OpenAI limit — should have been normalized/chunked first")

        with open(audio_path, "rb") as f:
            response = await self.client.audio.transcriptions.create(
                model=self.model,
                file=f,
                response_format="verbose_json",
                timestamp_granularities=["segment"],
                language=language,
            )

        segments = []
        if hasattr(response, "segments") and response.segments:
            for seg in response.segments:
                segments.append(
                    TranscriptSegment(
                        start=seg.get("start", 0.0) if isinstance(seg, dict) else getattr(seg, "start", 0.0),
                        end=seg.get("end", 0.0) if isinstance(seg, dict) else getattr(seg, "end", 0.0),
                        text=(seg.get("text", "") if isinstance(seg, dict) else getattr(seg, "text", "")).strip(),
                        speaker=None,
                    )
                )
        elif hasattr(response, "text") and response.text:
            # Fallback: no segments returned, treat whole text as one segment
            from backend.services.media import get_duration

            duration = await get_duration(audio_path)
            segments.append(TranscriptSegment(start=0.0, end=duration, text=response.text.strip(), speaker=None))

        log.info(f"Transcription complete: {len(segments)} segments")
        return segments


class MockTranscriptionAdapter:
    """Mock adapter for testing without API keys."""

    async def transcribe(self, audio_path: str, language: str = "en") -> list[TranscriptSegment]:
        from backend.services.media import get_duration

        try:
            duration = await get_duration(audio_path)
        except Exception:
            duration = 60.0

        segments = []
        mock_sentences = [
            "Welcome to this lecture on machine learning fundamentals.",
            "Today we will cover the basics of neural networks and deep learning.",
            "A neural network consists of layers of interconnected nodes.",
            "Each node applies an activation function to its inputs.",
            "Training involves adjusting weights to minimize a loss function.",
            "Backpropagation is the algorithm used to compute gradients.",
            "Gradient descent updates the weights in the direction of steepest descent.",
        ]

        t = 0.0
        i = 0
        while t < duration:
            end = min(t + 8.0, duration)
            text = mock_sentences[i % len(mock_sentences)]
            segments.append(TranscriptSegment(start=t, end=end, text=text, speaker="Speaker 1"))
            t = end + 0.5
            i += 1

        return segments
