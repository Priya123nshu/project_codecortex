from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

try:
    from pydantic import ConfigDict
except ImportError:  # pragma: no cover
    ConfigDict = None


AvatarStatus = Literal["uploading", "uploaded", "preprocessing", "ready", "failed"]
DocumentStatus = Literal["uploaded", "indexing", "ready", "failed"]
SessionStatus = Literal["active", "completed", "failed"]
TurnStatus = Literal["received", "transcribing", "thinking", "synthesizing", "rendering", "completed", "failed"]
RoleValue = Literal["admin", "user"]
InputLanguageValue = Literal["en", "hi"]
OutputLanguageValue = Literal["en", "hi", "pa", "ta"]
AvatarLanguageValue = Literal["en", "hi", "pa", "ta", "multilingual"]
TtsProviderValue = Literal["edge-tts", "friend-local"]


class NamespaceSafeModel(BaseModel):
    if ConfigDict is not None:
        model_config = ConfigDict(protected_namespaces=())


class HealthResponse(BaseModel):
    status: Literal["ok"]
    service: str
    auth_required: bool
    storage_backend: str


class AuthUser(BaseModel):
    user_id: str
    org_id: str
    email: Optional[str] = None
    name: Optional[str] = None
    role: RoleValue


class AdminAvatarCreateRequest(NamespaceSafeModel):
    avatar_id: str = Field(min_length=2, max_length=64)
    display_name: str = Field(min_length=2, max_length=120)
    persona_prompt: str = Field(default="", max_length=8000)
    default_voice: str = Field(default="en-US-JennyNeural", max_length=120)
    language: AvatarLanguageValue = "multilingual"
    approved: bool = True


class UploadTarget(BaseModel):
    upload_method: Literal["PUT", "S3_PRESIGNED_POST"]
    upload_url: str
    object_key: str


class AvatarRecord(BaseModel):
    avatar_id: str
    display_name: str
    status: AvatarStatus
    approved: bool
    language: AvatarLanguageValue = "multilingual"
    source_object_key: Optional[str] = None
    prepared_bundle_location: Optional[str] = None
    persona_prompt: str = ""
    default_voice: str = "en-US-JennyNeural"
    source_upload: Optional[UploadTarget] = None
    num_frames: Optional[int] = None
    last_error: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class AvatarListResponse(BaseModel):
    avatars: List[AvatarRecord] = Field(default_factory=list)


class AvatarPreprocessResponse(BaseModel):
    avatar_id: str
    status: AvatarStatus
    prepared_bundle_location: Optional[str] = None
    last_error: Optional[str] = None


class DocumentRecord(BaseModel):
    document_id: str
    title: str
    status: DocumentStatus
    mime_type: str
    source_object_key: str
    chunk_count: int = 0
    created_at: datetime
    updated_at: datetime
    last_error: Optional[str] = None


class DocumentListResponse(BaseModel):
    documents: List[DocumentRecord] = Field(default_factory=list)


class SessionCreateRequest(NamespaceSafeModel):
    avatar_id: str
    input_language: InputLanguageValue = "en"
    output_language: OutputLanguageValue = "en"
    audience: Optional[str] = None
    context_notes: Optional[str] = None


class SessionRecord(BaseModel):
    session_id: str
    avatar_id: str
    input_language: InputLanguageValue
    output_language: OutputLanguageValue
    status: SessionStatus
    audience: Optional[str] = None
    context_notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class TurnRecord(BaseModel):
    turn_id: str
    session_id: str
    user_transcript: Optional[str] = None
    retrieval_query_text: Optional[str] = None
    assistant_text: Optional[str] = None
    status: TurnStatus
    render_job_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    error: Optional[str] = None


class TurnHistoryResponse(BaseModel):
    session: SessionRecord
    turns: List[TurnRecord] = Field(default_factory=list)


class TranscriptReadyEvent(BaseModel):
    session_id: str
    turn_id: str
    transcript: str
    input_language: InputLanguageValue


class RetrievalChunk(BaseModel):
    document_id: str
    title: str
    chunk_index: int
    score: float
    content: str


class RetrievalReadyEvent(BaseModel):
    session_id: str
    turn_id: str
    query_text: str
    chunks: List[RetrievalChunk] = Field(default_factory=list)


class AssistantTextReadyEvent(BaseModel):
    session_id: str
    turn_id: str
    language: OutputLanguageValue
    text: str


class TtsReadyEvent(BaseModel):
    session_id: str
    turn_id: str
    provider: TtsProviderValue
    language: OutputLanguageValue
    audio_object_key: str
    cache_hit: bool = False


class AvatarChunkReadyEvent(BaseModel):
    session_id: str
    turn_id: str
    avatar_id: str
    chunk_index: int
    video_url: str
    done_marker: bool = False
    text_segment: Optional[str] = None


class TurnCompletedEvent(BaseModel):
    session_id: str
    turn_id: str
    render_job_id: Optional[str] = None
    chunk_count: int = 0


class TurnFailedEvent(BaseModel):
    session_id: str
    turn_id: str
    error: str
    recoverable: bool = True


class PlatformTokenResponse(BaseModel):
    access_token: str
    platform_api_base_url: str
    role: RoleValue


class ProviderDescriptor(BaseModel):
    id: str
    label: str
    enabled: bool


class AuthStatusResponse(BaseModel):
    authenticated: bool
    is_admin: bool
    providers: List[ProviderDescriptor] = Field(default_factory=list)
    user_name: Optional[str] = None
    user_email: Optional[str] = None


def model_to_dict(model: BaseModel) -> Dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return model.dict()
