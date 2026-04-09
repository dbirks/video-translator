"""FFmpeg-based media operations using asyncio subprocesses."""

import asyncio
import json
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
        "-vn",
        "-acodec", "pcm_s16le",
        "-ar", "44100",
        "-ac", "2",
        output_path,
    )
    if returncode != 0:
        raise RuntimeError(f"ffmpeg extract_audio failed (rc={returncode}): {stderr}")


async def normalize_audio(wav_path: str, output_path: str, target_bitrate: str = "64k") -> None:
    """Normalize audio: convert to mono MP3 at target bitrate for transcription."""
    returncode, _, stderr = await _run_ffmpeg(
        "-i", wav_path,
        "-ac", "1",
        "-acodec", "libmp3lame",
        "-b:a", target_bitrate,
        "-af", "loudnorm",
        output_path,
    )
    if returncode != 0:
        raise RuntimeError(f"ffmpeg normalize_audio failed (rc={returncode}): {stderr}")


async def mixdown_segments(
    segment_audio_paths: list[str],
    timestamps: list[tuple[float, float]],
    total_duration: float,
    output_path: str,
    original_audio_path: str | None = None,
) -> None:
    """
    Compose a full audio track from segment TTS files placed at their timestamps,
    mixed with the original audio (ducked during speech).

    If original_audio_path is provided, the original audio plays underneath at
    reduced volume during speech segments and normal volume otherwise.
    """
    if not segment_audio_paths:
        if original_audio_path:
            # Just copy the original audio
            returncode, _, stderr = await _run_ffmpeg(
                "-i", original_audio_path,
                "-acodec", "libmp3lame",
                "-b:a", "128k",
                output_path,
            )
        else:
            returncode, _, stderr = await _run_ffmpeg(
                "-f", "lavfi",
                "-i", f"anullsrc=r=44100:cl=mono:d={total_duration}",
                "-acodec", "libmp3lame",
                "-b:a", "128k",
                output_path,
            )
        if returncode != 0:
            raise RuntimeError(f"ffmpeg mixdown failed: {stderr}")
        return

    # Strategy:
    # 1. Build a TTS-only track: place each TTS segment at its timestamp, boost volume
    # 2. If we have original audio, duck it during speech and mix with TTS track
    # 3. If no original audio, just output the TTS track

    inputs = []
    filter_parts = []

    # Input 0: silence base (for TTS overlay timing)
    inputs += ["-f", "lavfi", "-i", f"anullsrc=r=44100:cl=stereo:d={total_duration}"]

    # Inputs 1..N: TTS segment audio files
    for audio_path in segment_audio_paths:
        inputs += ["-i", audio_path]

    # Delay each TTS segment to its start time and boost volume
    for i, (start_sec, _end_sec) in enumerate(timestamps):
        delay_ms = int(start_sec * 1000)
        # Boost TTS volume by 6dB and convert to stereo if needed
        filter_parts.append(
            f"[{i + 1}]aresample=44100,aformat=channel_layouts=stereo,"
            f"volume=6dB,adelay={delay_ms}|{delay_ms}[tts{i}]"
        )

    # Mix all TTS segments onto the silence base
    # Use weights to prevent amix from averaging down the volume
    tts_labels = "".join(f"[tts{i}]" for i in range(len(segment_audio_paths)))
    n_tts = len(segment_audio_paths) + 1  # +1 for silence base
    weights = " ".join(["0"] + ["1"] * len(segment_audio_paths))
    filter_parts.append(
        f"[0]{tts_labels}amix=inputs={n_tts}:duration=first:weights={weights},"
        f"volume={n_tts}dB[tts_mix]"
    )

    if original_audio_path:
        # Add original audio as another input
        orig_idx = len(segment_audio_paths) + 1
        inputs += ["-i", original_audio_path]

        # Build a volume automation for the original audio:
        # Lower volume during speech segments, keep it during gaps
        # Use sidechaincompress or volume with enable expressions
        duck_volume = 0.15  # 15% volume during speech
        normal_volume = 0.7  # 70% volume during non-speech (background level)

        # Build enable expressions for ducking
        # We use the volume filter with 'enable' to duck during each segment
        duck_filters = f"[{orig_idx}]aresample=44100,aformat=channel_layouts=stereo"
        # Apply a base volume reduction
        duck_filters += f",volume={normal_volume}"

        # For each speech segment, reduce volume further
        for start_sec, end_sec in timestamps:
            # Pad the duck window slightly for smoother transitions
            duck_start = max(0, start_sec - 0.1)
            duck_end = end_sec + 0.1
            ratio = duck_volume / normal_volume
            duck_filters += (
                f",volume='{ratio}':enable='between(t,{duck_start:.2f},{duck_end:.2f})'"
            )

        duck_filters += "[orig_ducked]"
        filter_parts.append(duck_filters)

        # Final mix: ducked original + TTS
        filter_parts.append(
            "[orig_ducked][tts_mix]amix=inputs=2:duration=first:weights=1 1[out]"
        )
    else:
        filter_parts.append("[tts_mix]acopy[out]")

    filter_complex = ";".join(filter_parts)

    returncode, _, stderr = await _run_ffmpeg(
        *inputs,
        "-filter_complex", filter_complex,
        "-map", "[out]",
        "-acodec", "libmp3lame",
        "-b:a", "128k",
        output_path,
    )
    if returncode != 0:
        raise RuntimeError(f"ffmpeg mixdown failed (rc={returncode}): {stderr}")


async def mux_export(video_path: str, audio_path: str, output_path: str) -> None:
    """Replace the audio track of a video with the mixed audio, producing an MP4."""
    returncode, _, stderr = await _run_ffmpeg(
        "-i", video_path,
        "-i", audio_path,
        "-c:v", "copy",
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-c:a", "aac",
        "-b:a", "192k",
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
    info = json.loads(stdout.decode())
    return float(info.get("format", {}).get("duration", 0.0))
