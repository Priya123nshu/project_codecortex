from __future__ import annotations

import json
import re
import shutil
import threading
import time
import uuid
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from avatar_service.config import ConfigurationError, get_settings, validate_environment
from avatar_service.pipeline.jobs import initialize_job, load_job_status
from avatar_service.pipeline.preprocess import preprocess_avatar
from avatar_service.pipeline.render import render_job
from avatar_service.schemas import (
    AvatarListResponse,
    AvatarSummary,
    EnvironmentValidationResult,
    JobStatusResponse,
    PreprocessAvatarRequest,
    PreprocessAvatarResponse,
    RenderAudioRequest,
    RenderAudioResponse,
    model_to_dict,
)


settings = get_settings()
settings.ensure_storage_dirs()
AVATAR_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")

app = FastAPI(
    title="Avatar Service",
    description="Standalone local MuseTalk service for avatar preprocessing and rendering.",
    version="0.3.0",
)

cors_allow_origins = list(settings.cors_allow_origins)
if cors_allow_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_allow_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.mount("/outputs", StaticFiles(directory=str(settings.output_root)), name="outputs")


def _raise_http_error(exc: Exception) -> None:
    if isinstance(exc, FileNotFoundError):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, (ConfigurationError, RuntimeError)):
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if isinstance(exc, ValueError):
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    raise HTTPException(status_code=500, detail=str(exc)) from exc


def _validate_avatar_id(avatar_id: str) -> str:
    normalized = avatar_id.strip()
    if not normalized:
        raise ValueError("avatar_id is required")
    if not AVATAR_ID_PATTERN.fullmatch(normalized):
        raise ValueError("avatar_id may only contain letters, numbers, underscores, and hyphens")
    return normalized


def _list_available_avatars() -> AvatarListResponse:
    avatars: list[AvatarSummary] = []
    settings.avatar_root.mkdir(parents=True, exist_ok=True)

    for avatar_dir in sorted(settings.avatar_root.iterdir()):
        if not avatar_dir.is_dir():
            continue

        avatar_id = avatar_dir.name
        avatar_data_path = avatar_dir / "avatar_data.pkl"
        avatar_info_path = avatar_dir / "avatar_info.json"
        payload: dict[str, object] = {}

        if avatar_info_path.exists():
            try:
                payload = json.loads(avatar_info_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                payload = {}

        avatars.append(
            AvatarSummary(
                avatar_id=avatar_id,
                status="ready" if avatar_data_path.exists() else "missing",
                avatar_data_path=str(avatar_data_path) if avatar_data_path.exists() else None,
                avatar_info_path=str(avatar_info_path) if avatar_info_path.exists() else None,
                source_video_path=payload.get("source_video_path") if isinstance(payload.get("source_video_path"), str) else None,
                model_version=payload.get("model_version") if isinstance(payload.get("model_version"), str) else None,
                num_frames=int(payload["num_frames"]) if isinstance(payload.get("num_frames"), int) else None,
            )
        )

    return AvatarListResponse(avatars=avatars)


def _output_path_to_url(path_value: str | None) -> Optional[str]:
    if not path_value:
        return None

    try:
        relative_path = Path(path_value).resolve().relative_to(settings.output_root.resolve())
    except Exception:
        return None

    return "/outputs/" + "/".join(relative_path.parts)


def _output_dir_to_url_prefix(output_dir: str | None) -> Optional[str]:
    if not output_dir:
        return None

    try:
        relative_path = Path(output_dir).resolve().relative_to(settings.output_root.resolve())
    except Exception:
        return None

    return "/outputs/" + "/".join(relative_path.parts)


def _build_render_response(result) -> RenderAudioResponse:
    return RenderAudioResponse(
        job_id=result.job_id,
        status=result.status,
        output_dir=result.output_dir,
        stream_info_path=result.stream_info_path,
        chunks_total=result.chunks_total,
        chunks_completed=result.chunks_completed,
        chunk_video_paths=list(result.chunk_video_paths),
        chunk_video_urls=[
            url for url in (_output_path_to_url(path) for path in result.chunk_video_paths) if url
        ],
        stream_info_url=_output_path_to_url(result.stream_info_path),
        output_url_prefix=_output_dir_to_url_prefix(result.output_dir),
        error=result.error,
    )


def _build_render_response_from_status(status: JobStatusResponse) -> RenderAudioResponse:
    return RenderAudioResponse(
        job_id=status.job_id,
        status=status.status,
        output_dir=status.output_dir,
        stream_info_path=status.stream_info_path,
        chunks_total=status.chunks_total,
        chunks_completed=status.chunks_completed,
        chunk_video_paths=list(status.chunk_video_paths),
        chunk_video_urls=[
            url for url in (_output_path_to_url(path) for path in status.chunk_video_paths) if url
        ],
        stream_info_url=_output_path_to_url(status.stream_info_path),
        output_url_prefix=_output_dir_to_url_prefix(status.output_dir),
        error=status.error,
    )


def _build_job_status_response(status: JobStatusResponse) -> JobStatusResponse:
    payload = model_to_dict(status)
    payload["chunk_video_urls"] = [
        url for url in (_output_path_to_url(path) for path in status.chunk_video_paths) if url
    ]
    payload["stream_info_url"] = _output_path_to_url(status.stream_info_path)
    payload["output_url_prefix"] = _output_dir_to_url_prefix(status.output_dir)
    return JobStatusResponse(**payload)


def _run_render_job_async(**kwargs) -> None:
    try:
        render_job(**kwargs)
    except Exception:
        return


@app.get("/")
def index() -> dict[str, object]:
    return {
        "service": "avatar-service",
        "status": "ok",
        "docs": "/docs",
        "health": "/health",
        "avatars": "/avatars",
        "avatar_preprocess_upload": "/avatars/preprocess-upload",
        "render_upload": "/jobs/render-upload",
        "outputs": "/outputs/{job_id}/chunk_0000.mp4",
    }


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/environment/validate", response_model=EnvironmentValidationResult)
def environment_validate() -> EnvironmentValidationResult:
    return validate_environment()


@app.get("/avatars", response_model=AvatarListResponse)
def list_avatars_endpoint() -> AvatarListResponse:
    return _list_available_avatars()


@app.post("/avatars/preprocess", response_model=PreprocessAvatarResponse)
def preprocess_avatar_endpoint(
    payload: PreprocessAvatarRequest,
) -> PreprocessAvatarResponse:
    try:
        result = preprocess_avatar(
            video_path=payload.video_path,
            avatar_id=_validate_avatar_id(payload.avatar_id),
            model_version=payload.model_version,
        )
        return PreprocessAvatarResponse(**model_to_dict(result))
    except Exception as exc:
        _raise_http_error(exc)


@app.post("/avatars/preprocess-upload", response_model=PreprocessAvatarResponse)
def preprocess_avatar_upload_endpoint(
    avatar_id: str = Form(...),
    video_file: UploadFile = File(...),
    model_version: Optional[str] = Form(default="v15"),
) -> PreprocessAvatarResponse:
    normalized_avatar_id = _validate_avatar_id(avatar_id)
    upload_root = settings.jobs_root / "_avatar_uploads" / normalized_avatar_id / uuid.uuid4().hex
    upload_root.mkdir(parents=True, exist_ok=True)

    filename = Path(video_file.filename or "avatar-upload.bin").name
    upload_path = upload_root / filename

    try:
        with upload_path.open("wb") as handle:
            shutil.copyfileobj(video_file.file, handle)

        result = preprocess_avatar(
            video_path=upload_path,
            avatar_id=normalized_avatar_id,
            model_version=model_version,
        )
        return PreprocessAvatarResponse(**model_to_dict(result))
    except Exception as exc:
        _raise_http_error(exc)
    finally:
        video_file.file.close()


@app.post("/jobs/render", response_model=RenderAudioResponse)
def render_audio_endpoint(payload: RenderAudioRequest) -> RenderAudioResponse:
    try:
        result = render_job(
            avatar_id=_validate_avatar_id(payload.avatar_id),
            audio_path=payload.audio_path,
            job_id=payload.job_id,
            fps=payload.fps,
            batch_size=payload.batch_size,
            model_version=payload.model_version,
            chunk_duration=payload.chunk_duration,
        )
        return _build_render_response(result)
    except Exception as exc:
        _raise_http_error(exc)


@app.post("/jobs/render-upload", response_model=RenderAudioResponse)
def render_audio_upload_endpoint(
    avatar_id: str = Form(...),
    audio_file: UploadFile = File(...),
    job_id: Optional[str] = Form(default=None),
    fps: Optional[int] = Form(default=None),
    batch_size: Optional[int] = Form(default=None),
    model_version: Optional[str] = Form(default="v15"),
    chunk_duration: int = Form(default=3),
) -> RenderAudioResponse:
    resolved_job_id = job_id or uuid.uuid4().hex
    normalized_avatar_id = _validate_avatar_id(avatar_id)
    upload_dir = settings.jobs_root / resolved_job_id / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)

    filename = Path(audio_file.filename or "audio-upload.bin").name
    upload_path = upload_dir / filename

    try:
        with upload_path.open("wb") as handle:
            shutil.copyfileobj(audio_file.file, handle)

        result = render_job(
            avatar_id=normalized_avatar_id,
            audio_path=upload_path,
            job_id=resolved_job_id,
            fps=fps,
            batch_size=batch_size,
            model_version=model_version,
            chunk_duration=chunk_duration,
        )
        return _build_render_response(result)
    except Exception as exc:
        _raise_http_error(exc)
    finally:
        audio_file.file.close()


@app.post("/jobs/render-async", response_model=RenderAudioResponse)
def render_audio_async_endpoint(
    avatar_id: str = Form(...),
    audio_file: UploadFile = File(...),
    job_id: Optional[str] = Form(default=None),
    fps: Optional[int] = Form(default=None),
    batch_size: Optional[int] = Form(default=None),
    model_version: Optional[str] = Form(default="v15"),
    chunk_duration: int = Form(default=3),
) -> RenderAudioResponse:
    resolved_job_id = job_id or uuid.uuid4().hex
    normalized_avatar_id = _validate_avatar_id(avatar_id)
    upload_dir = settings.jobs_root / resolved_job_id / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)

    filename = Path(audio_file.filename or "audio-upload.bin").name
    upload_path = upload_dir / filename

    try:
        with upload_path.open("wb") as handle:
            shutil.copyfileobj(audio_file.file, handle)

        initialize_job(
            resolved_job_id,
            avatar_id=normalized_avatar_id,
            audio_path=upload_path,
            settings=settings,
        )

        worker = threading.Thread(
            target=_run_render_job_async,
            kwargs={
                "avatar_id": normalized_avatar_id,
                "audio_path": upload_path,
                "job_id": resolved_job_id,
                "fps": fps,
                "batch_size": batch_size,
                "model_version": model_version,
                "chunk_duration": chunk_duration,
                "settings": settings,
            },
            daemon=True,
        )
        worker.start()

        status = None
        for _ in range(20):
            try:
                status = load_job_status(resolved_job_id, settings=settings)
                break
            except FileNotFoundError:
                time.sleep(0.1)
        if status is None:
            raise RuntimeError(f"Unable to initialize async render job {resolved_job_id}")

        return _build_render_response_from_status(status)
    except Exception as exc:
        _raise_http_error(exc)
    finally:
        audio_file.file.close()


@app.get("/jobs/{job_id}", response_model=JobStatusResponse)
def get_job_status(job_id: str) -> JobStatusResponse:
    try:
        return _build_job_status_response(load_job_status(job_id))
    except Exception as exc:
        _raise_http_error(exc)



