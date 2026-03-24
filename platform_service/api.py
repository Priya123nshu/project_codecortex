from __future__ import annotations

import threading
import uuid
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from platform_service.core import (
    CognitiveProvider,
    LocalObjectStore,
    create_avatar_record,
    create_document_record,
    create_session_record,
    ensure_bootstrap,
    extract_document_text,
    get_avatar,
    get_session_history,
    get_settings,
    health_payload,
    init_db,
    list_admin_avatars,
    list_documents,
    list_public_avatars,
    require_admin,
    require_user,
    run_avatar_preprocess_job,
    set_document_chunks,
    split_document_text,
    start_turn_stream,
    update_avatar,
)
from platform_service.schemas import (
    AdminAvatarCreateRequest,
    AuthUser,
    AvatarPreprocessResponse,
    AvatarRecord,
    DocumentRecord,
    HealthResponse,
    SessionCreateRequest,
)


settings = get_settings()
settings.ensure_dirs()
init_db(settings)
ensure_bootstrap(settings)

app = FastAPI(
    title="Avatar Platform Service",
    description="CPU-side orchestration API for the multilingual real-time avatar pilot.",
    version="0.2.0",
)

if settings.cors_allow_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_allow_origins),
        allow_credentials="*" not in settings.cors_allow_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.mount("/objects", StaticFiles(directory=str(settings.objects_root)), name="objects")


def _wrap_error(exc: Exception) -> HTTPException:
    if isinstance(exc, HTTPException):
        return exc
    if isinstance(exc, FileNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=500, detail=str(exc))


@app.get("/")
def index() -> dict[str, object]:
    return {
        "service": "platform-service",
        "status": "ok",
        "health": "/health",
        "avatars": "/avatars",
        "admin_avatars": "/admin/avatars",
        "admin_documents": "/admin/documents",
        "sessions": "/sessions",
    }


@app.get("/health", response_model=HealthResponse)
def health() -> dict[str, object]:
    return health_payload(settings=settings).model_dump(mode="json")


@app.get("/avatars")
def list_public_avatar_library(user: AuthUser = Depends(require_user)):
    return list_public_avatars(settings=settings)


@app.get("/admin/avatars")
def list_admin_avatar_library(admin: AuthUser = Depends(require_admin)):
    return list_admin_avatars(settings=settings)


@app.post("/admin/avatars")
def create_avatar(payload: AdminAvatarCreateRequest, admin: AuthUser = Depends(require_admin)):
    try:
        avatar = create_avatar_record(payload, settings=settings)
        upload_url = f"{settings.public_base_url.rstrip('/')}/admin/avatars/{avatar.avatar_id}/source"
        data = avatar.model_dump(mode="json")
        data["source_upload"] = {
            "upload_method": "PUT",
            "upload_url": upload_url,
            "object_key": f"avatar-sources/{avatar.avatar_id}/{uuid.uuid4().hex}/{avatar.avatar_id}.mp4",
        }
        return AvatarRecord(**data)
    except Exception as exc:
        raise _wrap_error(exc) from exc


@app.put("/admin/avatars/{avatar_id}/source")
def upload_avatar_source(
    avatar_id: str,
    video_file: UploadFile = File(...),
    admin: AuthUser = Depends(require_admin),
):
    try:
        normalized_avatar_id = avatar_id.strip()
        store = LocalObjectStore(settings)
        object_key = f"avatar-sources/{normalized_avatar_id}/{uuid.uuid4().hex}/{Path(video_file.filename or 'avatar.mp4').name}"
        store.save_upload(object_key, video_file)
        return update_avatar(normalized_avatar_id, status="uploaded", source_object_key=object_key, last_error=None, settings=settings)
    except Exception as exc:
        raise _wrap_error(exc) from exc


@app.post("/admin/avatars/{avatar_id}/preprocess")
def start_avatar_preprocess(avatar_id: str, admin: AuthUser = Depends(require_admin)):
    try:
        normalized_avatar_id = avatar_id.strip()
        avatar = update_avatar(normalized_avatar_id, status="preprocessing", last_error=None, settings=settings)
        worker = threading.Thread(target=run_avatar_preprocess_job, args=(normalized_avatar_id, settings), daemon=True)
        worker.start()
        return AvatarPreprocessResponse(
            avatar_id=avatar.avatar_id,
            status=avatar.status,
            prepared_bundle_location=avatar.prepared_bundle_location,
            last_error=avatar.last_error,
        )
    except Exception as exc:
        raise _wrap_error(exc) from exc


@app.post("/admin/documents")
def upload_document(
    file: UploadFile = File(...),
    title: str = Form(...),
    admin: AuthUser = Depends(require_admin),
):
    try:
        store = LocalObjectStore(settings)
        raw_bytes = file.file.read()
        filename = Path(file.filename or "document.bin").name
        object_key = f"documents/{uuid.uuid4().hex}/{filename}"
        store.save_bytes(object_key, raw_bytes)
        document = create_document_record(
            title=title.strip() or filename,
            mime_type=file.content_type or "application/octet-stream",
            source_object_key=object_key,
            settings=settings,
        )
        text = extract_document_text(filename, raw_bytes, file.content_type or "application/octet-stream")
        chunks = split_document_text(text)
        cognition = CognitiveProvider(settings)
        updated = set_document_chunks(
            document.document_id,
            chunks=[(index, content, cognition.embed_text(content)) for index, content in enumerate(chunks)],
            status="ready",
            settings=settings,
        )
        return DocumentRecord(**updated.model_dump(mode="json"))
    except Exception as exc:
        raise _wrap_error(exc) from exc


@app.get("/admin/documents")
def list_admin_documents(admin: AuthUser = Depends(require_admin)):
    return list_documents(settings=settings)


@app.post("/sessions")
def create_session(payload: SessionCreateRequest, user: AuthUser = Depends(require_user)):
    try:
        avatar = get_avatar(payload.avatar_id, settings=settings)
        if avatar.status != "ready" or not avatar.approved:
            raise ValueError("Selected avatar is not available for users.")
        return create_session_record(user=user, payload=payload, settings=settings)
    except Exception as exc:
        raise _wrap_error(exc) from exc


@app.get("/sessions/{session_id}")
def get_session(session_id: str, user: AuthUser = Depends(require_user)):
    try:
        return get_session_history(session_id, settings=settings)
    except Exception as exc:
        raise _wrap_error(exc) from exc


@app.get("/sessions/{session_id}/history")
def get_history(session_id: str, user: AuthUser = Depends(require_user)):
    try:
        return get_session_history(session_id, settings=settings)
    except Exception as exc:
        raise _wrap_error(exc) from exc


@app.post("/sessions/{session_id}/turns")
def create_turn(
    session_id: str,
    audio_file: UploadFile = File(...),
    transcript_hint: str = Form(...),
    user: AuthUser = Depends(require_user),
):
    try:
        if not transcript_hint.strip():
            raise ValueError("Transcript hint is required for the multilingual demo path.")
        audio_bytes = audio_file.file.read()
        return StreamingResponse(
            start_turn_stream(
                session_id=session_id,
                user=user,
                audio_bytes=audio_bytes,
                audio_filename=audio_file.filename or "turn-audio.webm",
                transcript_hint=transcript_hint,
                settings=settings,
            ),
            media_type="text/event-stream",
        )
    except Exception as exc:
        raise _wrap_error(exc) from exc
