"""FFmpeg-based media operations using asyncio subprocesses."""

import asyncio
import json
import logging
import os

log = logging.getLogger(__name__)


async def _run_ffmpeg(*args: str) -> tuple[int, str, str]:
    """Run ffmpeg with the given arguments. Returns (returncode, stdout, stderr)."""
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-y",
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    return proc.returncode or 0, stdout.decode(), stderr.decode()


async def extract_audio(video_path: str, output_path: str) -> None:
    """Extract audio from video as WAV (PCM 16-bit, 44100Hz stereo)."""
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


async def measure_loudness(audio_path: str) -> float:
    """Measure integrated loudness (LUFS) of an audio file using ebur128."""
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-i", audio_path,
        "-af", "ebur128=framelog=verbose",
        "-f", "null", "-",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr_bytes = await proc.communicate()
    stderr_text = stderr_bytes.decode()

    # Parse "I: -XX.X LUFS" from the summary
    for line in stderr_text.split("\n"):
        line = line.strip()
        if line.startswith("I:") and "LUFS" in line:
            try:
                return float(line.split(":")[1].strip().split()[0])
            except (ValueError, IndexError):
                pass

    log.warning(f"Could not measure loudness for {audio_path}, defaulting to -23 LUFS")
    return -23.0  # EBU R128 target


async def mixdown_segments(
    segment_audio_paths: list[str],
    timestamps: list[tuple[float, float]],
    total_duration: float,
    output_path: str,
    original_audio_path: str | None = None,
) -> None:
    """
    Compose a full dubbed audio track:
    1. Measure original audio loudness
    2. Build TTS track with segments at correct timestamps, normalized to match
    3. Mute original during speech, keep background audio in gaps
    4. Mix together and apply final loudnorm
    """
    if not segment_audio_paths:
        src = original_audio_path or None
        if src:
            returncode, _, stderr = await _run_ffmpeg(
                "-i", src, "-acodec", "libmp3lame", "-b:a", "128k", output_path)
        else:
            returncode, _, stderr = await _run_ffmpeg(
                "-f", "lavfi", "-i", f"anullsrc=r=44100:cl=stereo:d={total_duration}",
                "-acodec", "libmp3lame", "-b:a", "128k", output_path)
        if returncode != 0:
            raise RuntimeError(f"ffmpeg mixdown failed: {stderr}")
        return

    # --- Step 1: Measure loudness ---
    orig_lufs = -23.0
    if original_audio_path:
        orig_lufs = await measure_loudness(original_audio_path)
        log.info(f"Original audio loudness: {orig_lufs:.1f} LUFS")

    # Measure average TTS loudness from a few segments
    tts_lufs_samples = []
    for path in segment_audio_paths[:3]:
        lufs = await measure_loudness(path)
        if lufs > -70:  # ignore silence/errors
            tts_lufs_samples.append(lufs)
    tts_lufs = sum(tts_lufs_samples) / len(tts_lufs_samples) if tts_lufs_samples else -23.0
    log.info(f"TTS average loudness: {tts_lufs:.1f} LUFS")

    # Calculate how much to boost/cut TTS to match original speech level
    # Aim for TTS to be slightly louder than original (it's the primary audio now)
    target_tts_lufs = orig_lufs + 1.0  # 1 LUFS louder than original
    tts_adjust_db = target_tts_lufs - tts_lufs
    log.info(f"TTS volume adjustment: {tts_adjust_db:+.1f} dB (target {target_tts_lufs:.1f} LUFS)")

    # --- Step 2: Build filter graph ---
    inputs = []
    filter_parts = []

    # Input 0: silence base
    inputs += ["-f", "lavfi", "-i", f"anullsrc=r=44100:cl=stereo:d={total_duration}"]

    # Inputs 1..N: TTS segments
    for audio_path in segment_audio_paths:
        inputs += ["-i", audio_path]

    # Process each TTS segment: resample, match channels, adjust volume, delay
    for i, (start_sec, _end_sec) in enumerate(timestamps):
        delay_ms = int(start_sec * 1000)
        filter_parts.append(
            f"[{i + 1}]aresample=44100,aformat=channel_layouts=stereo,"
            f"volume={tts_adjust_db:.1f}dB,"
            f"adelay={delay_ms}|{delay_ms}[tts{i}]"
        )

    # Overlay all TTS onto silence base using amix with proper weights
    tts_labels = "".join(f"[tts{i}]" for i in range(len(segment_audio_paths)))
    n_inputs = len(segment_audio_paths) + 1
    weights = " ".join(["0"] + ["1"] * len(segment_audio_paths))
    # Compensate for amix averaging: boost by number of inputs
    filter_parts.append(
        f"[0]{tts_labels}amix=inputs={n_inputs}:duration=first"
        f":weights={weights},volume={n_inputs}dB[tts_mix]"
    )

    if original_audio_path:
        orig_idx = len(segment_audio_paths) + 1
        inputs += ["-i", original_audio_path]

        # Build the original audio chain:
        # - Base volume at 100% (for gaps — music, transitions)
        # - Mute completely during speech windows (with small fade padding)
        orig_filter = f"[{orig_idx}]aresample=44100,aformat=channel_layouts=stereo"

        for start_sec, end_sec in timestamps:
            fade_in = 0.15  # seconds to fade back in after speech
            fade_out = 0.08  # seconds to fade out before speech
            mute_start = max(0, start_sec - fade_out)
            mute_end = end_sec + fade_in
            orig_filter += (
                f",volume=0:enable='between(t,{mute_start:.3f},{mute_end:.3f})'"
            )

        orig_filter += "[orig_processed]"
        filter_parts.append(orig_filter)

        # Mix: original (background) + TTS (speech)
        # amix with 2 inputs halves volume, so compensate with 2dB boost
        filter_parts.append(
            "[orig_processed][tts_mix]amix=inputs=2:duration=first:weights=1 1,"
            "volume=2dB[premix]"
        )

        # Final loudnorm pass to match broadcast standard and ensure consistent output
        filter_parts.append(
            f"[premix]loudnorm=I={orig_lufs:.1f}:TP=-1.0:LRA=11[out]"
        )
    else:
        # No original audio — just normalize the TTS track
        filter_parts.append(f"[tts_mix]loudnorm=I=-16:TP=-1.0:LRA=11[out]")

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

    # Verify output loudness
    out_lufs = await measure_loudness(output_path)
    log.info(f"Final mix loudness: {out_lufs:.1f} LUFS (target: {orig_lufs:.1f})")


async def extract_clip(audio_path: str, output_path: str, start_sec: float, end_sec: float) -> None:
    """Extract a clip from an audio file between start and end timestamps."""
    duration = end_sec - start_sec
    returncode, _, stderr = await _run_ffmpeg(
        "-i", audio_path,
        "-ss", str(start_sec),
        "-t", str(duration),
        "-acodec", "pcm_s16le",
        "-ar", "44100",
        "-ac", "1",
        output_path,
    )
    if returncode != 0:
        raise RuntimeError(f"ffmpeg extract_clip failed (rc={returncode}): {stderr}")


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
