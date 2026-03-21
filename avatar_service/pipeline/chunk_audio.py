from __future__ import annotations

import math
import subprocess
from pathlib import Path
from typing import List, Optional

from avatar_service.config import Settings, get_settings


def split_audio(
    audio_path: str | Path,
    chunk_seconds: int,
    output_dir: str | Path,
    settings: Optional[Settings] = None,
) -> List[Path]:
    active_settings = settings or get_settings()
    source_path = Path(audio_path).expanduser().resolve()
    target_dir = Path(output_dir).expanduser().resolve()

    if not source_path.exists():
        raise FileNotFoundError(f"Audio file not found: {source_path}")
    if chunk_seconds <= 0:
        raise ValueError("chunk_seconds must be greater than 0")

    target_dir.mkdir(parents=True, exist_ok=True)
    ffprobe_bin = active_settings.resolve_ffprobe_bin()
    ffmpeg_bin = active_settings.resolve_ffmpeg_bin()

    probe_cmd = [
        ffprobe_bin,
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=nw=1:nk=1",
        str(source_path),
    ]
    probe = subprocess.run(probe_cmd, capture_output=True, text=True, check=False)
    if probe.returncode != 0:
        raise RuntimeError(f"ffprobe failed for {source_path}: {probe.stderr.strip()}")

    try:
        total_duration = float(probe.stdout.strip())
    except ValueError as exc:
        raise RuntimeError(
            f"Could not parse audio duration for {source_path}: {probe.stdout!r}"
        ) from exc

    if total_duration <= 0:
        raise RuntimeError(f"Audio duration must be greater than zero: {source_path}")

    chunk_paths: List[Path] = []
    num_chunks = math.ceil(total_duration / chunk_seconds)

    for index in range(num_chunks):
        chunk_path = target_dir / f"chunk_{index:04d}.wav"
        start_seconds = index * chunk_seconds
        cmd = [
            ffmpeg_bin,
            "-y",
            "-v",
            "error",
            "-i",
            str(source_path),
            "-ss",
            str(start_seconds),
            "-t",
            str(chunk_seconds),
            "-ar",
            "16000",
            "-ac",
            "1",
            str(chunk_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise RuntimeError(
                f"ffmpeg failed while splitting {source_path} at chunk {index}: "
                f"{result.stderr.strip()}"
            )
        chunk_paths.append(chunk_path)

    return chunk_paths
