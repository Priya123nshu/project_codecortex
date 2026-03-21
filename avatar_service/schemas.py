from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

try:
    from pydantic import ConfigDict
except ImportError:  # pragma: no cover
    ConfigDict = None


JobStatusValue = Literal["queued", "running", "failed", "completed"]
CheckStatusValue = Literal["ok", "warning", "error"]


class _ModelNamespaceSafeBase(BaseModel):
    if ConfigDict is not None:
        model_config = ConfigDict(protected_namespaces=())


class PreprocessAvatarRequest(_ModelNamespaceSafeBase):
    video_path: str
    avatar_id: str
    model_version: Optional[str] = "v15"


class PreprocessAvatarResponse(BaseModel):
    avatar_id: str
    status: JobStatusValue
    avatar_data_path: str
    avatar_info_path: str


class AvatarSummary(BaseModel):
    avatar_id: str
    status: Literal["ready", "missing"]
    avatar_data_path: Optional[str] = None
    avatar_info_path: Optional[str] = None
    source_video_path: Optional[str] = None
    model_version: Optional[str] = None
    num_frames: Optional[int] = None


class AvatarListResponse(BaseModel):
    avatars: List[AvatarSummary] = Field(default_factory=list)


class RenderAudioRequest(_ModelNamespaceSafeBase):
    avatar_id: str
    audio_path: str
    job_id: Optional[str] = None
    fps: Optional[int] = Field(default=None, ge=1)
    batch_size: Optional[int] = Field(default=None, ge=1)
    model_version: Optional[str] = "v15"
    chunk_duration: int = Field(default=3, ge=1, le=30)


class RenderAudioResponse(BaseModel):
    job_id: str
    status: JobStatusValue
    output_dir: str
    stream_info_path: str
    chunks_total: int = 0
    chunks_completed: int = 0
    chunk_video_paths: List[str] = Field(default_factory=list)
    chunk_video_urls: List[str] = Field(default_factory=list)
    stream_info_url: Optional[str] = None
    output_url_prefix: Optional[str] = None
    error: Optional[str] = None


class JobStatusResponse(BaseModel):
    job_id: str
    status: JobStatusValue
    output_dir: str
    stream_info_path: str
    chunks_total: int = 0
    chunks_completed: int = 0
    chunk_video_paths: List[str] = Field(default_factory=list)
    chunk_video_urls: List[str] = Field(default_factory=list)
    stream_info_url: Optional[str] = None
    output_url_prefix: Optional[str] = None
    error: Optional[str] = None
    avatar_id: Optional[str] = None
    audio_path: Optional[str] = None
    job_status_path: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class AvatarPreprocessResult(BaseModel):
    avatar_id: str
    status: JobStatusValue
    avatar_data_path: str
    avatar_info_path: str


class RenderJobResult(BaseModel):
    job_id: str
    status: JobStatusValue
    output_dir: str
    stream_info_path: str
    chunks_total: int = 0
    chunks_completed: int = 0
    chunk_video_paths: List[str] = Field(default_factory=list)
    error: Optional[str] = None


class EnvironmentCheck(BaseModel):
    name: str
    status: CheckStatusValue
    detail: str


class EnvironmentValidationResult(BaseModel):
    overall_status: Literal["ok", "warning", "error"]
    checks: List[EnvironmentCheck] = Field(default_factory=list)


class SmokeTestResult(BaseModel):
    environment: EnvironmentValidationResult
    preprocess: AvatarPreprocessResult
    render: RenderJobResult


def model_to_dict(model: BaseModel) -> Dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()
