from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from avatar_service.config import Settings, get_settings
from avatar_service.schemas import JobStatusResponse, model_to_dict


@dataclass(frozen=True)
class JobPaths:
    job_id: str
    job_dir: Path
    audio_chunks_dir: Path
    output_dir: Path
    status_path: Path
    stream_info_path: Path


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def build_job_paths(job_id: str, settings: Optional[Settings] = None) -> JobPaths:
    active_settings = settings or get_settings()
    job_dir = active_settings.jobs_root / job_id
    output_dir = active_settings.output_root / job_id
    return JobPaths(
        job_id=job_id,
        job_dir=job_dir,
        audio_chunks_dir=job_dir / "audio_chunks",
        output_dir=output_dir,
        status_path=job_dir / "job_status.json",
        stream_info_path=output_dir / "stream_info.json",
    )


def initialize_job(
    job_id: str,
    *,
    avatar_id: str,
    audio_path: Path,
    settings: Optional[Settings] = None,
) -> JobPaths:
    paths = build_job_paths(job_id, settings=settings)
    paths.job_dir.mkdir(parents=True, exist_ok=True)
    paths.audio_chunks_dir.mkdir(parents=True, exist_ok=True)
    paths.output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = _utc_now()
    payload = JobStatusResponse(
        job_id=job_id,
        status="queued",
        output_dir=str(paths.output_dir),
        stream_info_path=str(paths.stream_info_path),
        chunks_total=0,
        chunks_completed=0,
        chunk_video_paths=[],
        avatar_id=avatar_id,
        audio_path=str(audio_path),
        job_status_path=str(paths.status_path),
        created_at=timestamp,
        updated_at=timestamp,
    )
    _write_json(paths.status_path, model_to_dict(payload))
    return paths


def load_job_status(job_id: str, settings: Optional[Settings] = None) -> JobStatusResponse:
    paths = build_job_paths(job_id, settings=settings)
    if not paths.status_path.exists():
        raise FileNotFoundError(f"Job status file not found for job_id={job_id}")

    payload = json.loads(paths.status_path.read_text(encoding="utf-8"))
    return JobStatusResponse(**payload)


def update_job_status(
    job_id: str,
    *,
    settings: Optional[Settings] = None,
    status: Optional[str] = None,
    chunks_total: Optional[int] = None,
    chunks_completed: Optional[int] = None,
    chunk_video_paths: Optional[list[str]] = None,
    error: Optional[str] = None,
    avatar_id: Optional[str] = None,
    audio_path: Optional[str] = None,
) -> JobStatusResponse:
    current = load_job_status(job_id, settings=settings)
    payload = model_to_dict(current)

    if status is not None:
        payload["status"] = status
    if chunks_total is not None:
        payload["chunks_total"] = chunks_total
    if chunks_completed is not None:
        payload["chunks_completed"] = chunks_completed
    if chunk_video_paths is not None:
        payload["chunk_video_paths"] = chunk_video_paths
    if error is not None:
        payload["error"] = error
    if avatar_id is not None:
        payload["avatar_id"] = avatar_id
    if audio_path is not None:
        payload["audio_path"] = audio_path

    payload["updated_at"] = _utc_now()
    updated = JobStatusResponse(**payload)

    status_path = Path(updated.job_status_path) if updated.job_status_path else None
    if not status_path:
        raise RuntimeError(f"job_status_path is missing for job_id={job_id}")
    _write_json(status_path, model_to_dict(updated))
    return updated


def write_stream_info(path: Path, *, num_chunks: int, status: str, error: Optional[str] = None) -> None:
    payload = {
        "num_chunks": num_chunks,
        "status": status,
    }
    if error:
        payload["error"] = error
    _write_json(path, payload)
