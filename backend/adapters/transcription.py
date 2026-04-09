"""Transcription adapters: Protocol + OpenAI implementation (stubbed for POC)."""

from typing import Protocol, runtime_checkable


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
    """
    Transcription adapter backed by OpenAI Whisper API.

    For the POC, this returns mock data so the pipeline can run end-to-end
    without a real API key. Replace the body of transcribe() with real
    OpenAI API calls when ready.
    """

    def __init__(self, api_key: str | None = None, model: str = "whisper-1"):
        self.api_key = api_key
        self.model = model

    async def transcribe(self, audio_path: str, language: str = "en") -> list[TranscriptSegment]:
        """Return mock transcript segments based on audio duration."""
        from backend.services.media import get_duration

        try:
            duration = await get_duration(audio_path)
        except Exception:
            duration = 60.0  # fallback

        # Generate mock segments spaced every ~10 seconds
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
