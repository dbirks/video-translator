"""FFmpeg-based media operations using asyncio subprocesses."""

import asyncio
import os


async def _run_ffmpeg(*args: str) -> tuple[int, str, str]:
    """Run ffmpeg with the given arguments. Returns (returncode, stdout, stderr)."""
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-y",  # overwrite output
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    return proc.returncode or 0, stdout.decode(), stderr.decode()


async def extract_audio(video_path: str, output_path: str) -> None:
    """Extract audio from video as WAV (PCM 16-bit, original sample rate)."""
    returncode, _, stderr = await _run_ffmpeg(
        "-i", video_path,
        "-vn",           # no video
        "-acodec", "pcm_s16le",
        "-ar", "44100",
        "-ac", "2",
        output_path,
    )
    if returncode != 0:
        raise RuntimeError(f"ffmpeg extract_audio failed (rc={returncode}): {stderr}")


async def normalize_audio(wav_path: str, output_path: str, target_bitrate: str = "64k") -> None:
    """Normalize audio: convert to mono MP3 at target bitrate."""
    returncode, _, stderr = await _run_ffmpeg(
        "-i", wav_path,
        "-ac", "1",               # mono
        "-acodec", "libmp3lame",
        "-b:a", target_bitrate,
        "-af", "loudnorm",        # EBU R128 loudness normalization
        output_path,
    )
    if returncode != 0:
        raise RuntimeError(f"ffmpeg normalize_audio failed (rc={returncode}): {stderr}")


async def mixdown_segments(
    segment_audio_paths: list[str],
    timestamps: list[tuple[float, float]],
    total_duration: float,
    output_path: str,
) -> None:
    """
    Compose a full audio track from segment TTS files placed at their timestamps.
    Silence pads gaps between segments.

    segment_audio_paths: list of absolute paths to WAV/MP3 files
    timestamps: list of (start_sec, end_sec) tuples matching segment_audio_paths
    total_duration: total video duration in seconds
    output_path: path for the output MP3
    """
    if not segment_audio_paths:
        # Create a silent track if no segments
        returncode, _, stderr = await _run_ffmpeg(
            "-f", "lavfi",
            "-i", f"anullsrc=r=44100:cl=mono:d={total_duration}",
            "-acodec", "libmp3lame",
            "-b:a", "64k",
            output_path,
        )
        if returncode != 0:
            raise RuntimeError(f"ffmpeg silent track failed (rc={returncode}): {stderr}")
        return

    # Build a complex filter graph that:
    # 1. Creates a silent base track of total_duration
    # 2. Overlays each segment at its start time using amix/adelay
    filter_parts = []
    inputs = ["-f", "lavfi", "-i", f"anullsrc=r=44100:cl=mono:d={total_duration}"]

    for i, (audio_path, (start_sec, _)) in enumerate(zip(segment_audio_paths, timestamps)):
        inputs += ["-i", audio_path]
        delay_ms = int(start_sec * 1000)
        filter_parts.append(f"[{i + 1}]adelay={delay_ms}|{delay_ms}[delayed{i}]")

    # Mix everything together
    delayed_labels = "".join(f"[delayed{i}]" for i in range(len(segment_audio_paths)))
    n_inputs = len(segment_audio_paths) + 1
    filter_parts.append(f"[0]{delayed_labels}amix=inputs={n_inputs}:duration=first[out]")

    filter_complex = ";".join(filter_parts)

    returncode, _, stderr = await _run_ffmpeg(
        *inputs,
        "-filter_complex", filter_complex,
        "-map", "[out]",
        "-acodec", "libmp3lame",
        "-b:a", "64k",
        output_path,
    )
    if returncode != 0:
        raise RuntimeError(f"ffmpeg mixdown failed (rc={returncode}): {stderr}")


async def mux_export(video_path: str, audio_path: str, output_path: str) -> None:
    """Replace the audio track of a video with new audio, producing an MP4."""
    returncode, _, stderr = await _run_ffmpeg(
        "-i", video_path,
        "-i", audio_path,
        "-c:v", "copy",       # copy video stream unchanged
        "-map", "0:v:0",      # video from first input
        "-map", "1:a:0",      # audio from second input
        "-c:a", "aac",
        "-b:a", "128k",
        "-shortest",
        output_path,
    )
    if returncode != 0:
        raise RuntimeError(f"ffmpeg mux_export failed (rc={returncode}): {stderr}")


async def get_duration(media_path: str) -> float:
    """Return the duration of a media file in seconds using ffprobe."""
    proc = await asyncio.create_subprocess_exec(
        "ffprobe",
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        media_path,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    import json

    info = json.loads(stdout.decode())
    return float(info.get("format", {}).get("duration", 0.0))
