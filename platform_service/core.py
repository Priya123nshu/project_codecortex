from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Optional, Sequence

import jwt
import requests
from fastapi import Header, HTTPException, UploadFile

from platform_service.schemas import (
    AdminAvatarCreateRequest,
    AssistantTextReadyEvent,
    AuthUser,
    AvatarChunkReadyEvent,
    AvatarListResponse,
    AvatarRecord,
    DocumentListResponse,
    DocumentRecord,
    HealthResponse,
    InputLanguageValue,
    RetrievalChunk,
    RetrievalReadyEvent,
    SessionCreateRequest,
    SessionRecord,
    TranscriptReadyEvent,
    TtsReadyEvent,
    TurnCompletedEvent,
    TurnFailedEvent,
    TurnHistoryResponse,
    TurnRecord,
    model_to_dict,
)


EMBEDDING_DIMENSIONS = 64
INPUT_LANGUAGE_LABELS: dict[str, str] = {
    "en": "English",
    "hi": "Hindi",
}
OUTPUT_LANGUAGE_LABELS: dict[str, str] = {
    "en": "English",
    "hi": "Hindi",
    "pa": "Punjabi",
    "ta": "Tamil",
}
LANGUAGE_PROVIDER_MAP: dict[str, str] = {
    "en": "indic-parler",
    "hi": "indic-parler",
    "pa": "friend-local",
    "ta": "indic-parler",
}
INDIC_PARLER_CACHE_VERSION = "indic-parler-v1"


class ConfigurationError(RuntimeError):
    """Raised when the platform service environment is misconfigured."""


@dataclass(frozen=True)
class Settings:
    service_root: Path
    database_path: Path
    uploads_root: Path
    objects_root: Path
    tts_cache_root: Path
    avatar_render_service_base_url: str
    avatar_render_public_base_url: str
    tts_service_base_url: str
    public_base_url: str
    cors_allow_origins: tuple[str, ...]
    auth_required: bool
    platform_jwt_secret: str
    default_org_id: str
    default_org_name: str
    admin_emails: tuple[str, ...]
    azure_openai_endpoint: str | None
    azure_openai_api_key: str | None
    azure_openai_chat_deployment: str | None
    azure_openai_embeddings_deployment: str | None
    azure_openai_api_version: str
    default_voice: str
    avatar_chunk_duration_seconds: int
    tts_request_timeout_seconds: int

    def ensure_dirs(self) -> None:
        for path in (
            self.service_root,
            self.uploads_root,
            self.objects_root,
            self.tts_cache_root,
            self.database_path.parent,
        ):
            path.mkdir(parents=True, exist_ok=True)

    def object_url(self, object_key: str) -> str:
        normalized_key = object_key.replace("\\", "/").lstrip("/")
        return f"{self.public_base_url.rstrip('/')}/objects/{normalized_key}"


def _service_root() -> Path:
    return Path(__file__).resolve().parent


def _strip_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _load_env_file() -> dict[str, str]:
    env: dict[str, str] = {}
    candidates = [
        _service_root() / ".env",
        _service_root().parent / ".env",
        Path.cwd() / ".env",
    ]
    env_path = next((path for path in candidates if path.exists()), None)
    if not env_path:
        return env

    for raw_line in env_path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key.strip()] = _strip_quotes(value)
    return env


def _env(key: str, env_map: dict[str, str], default: str | None = None) -> str:
    value = os.getenv(key)
    if value:
        return value
    if key in env_map and env_map[key]:
        return env_map[key]
    if default is None:
        raise ConfigurationError(f"Missing required configuration value: {key}")
    return default


def _bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _csv(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())


def _int(value: str, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


_SETTINGS: Settings | None = None


def get_settings() -> Settings:
    global _SETTINGS
    if _SETTINGS is not None:
        return _SETTINGS

    env_map = _load_env_file()
    service_root = _service_root()
    objects_root = Path(_env("PLATFORM_OBJECTS_ROOT", env_map, default=str(service_root / "storage" / "objects")))
    settings = Settings(
        service_root=service_root,
        database_path=Path(_env("PLATFORM_DATABASE_PATH", env_map, default=str(service_root / "storage" / "platform.sqlite3"))),
        uploads_root=Path(_env("PLATFORM_UPLOADS_ROOT", env_map, default=str(service_root / "storage" / "uploads"))),
        objects_root=objects_root,
        tts_cache_root=objects_root / "tts-cache",
        avatar_render_service_base_url=_env("AVATAR_RENDER_SERVICE_BASE_URL", env_map, default="http://127.0.0.1:8000").rstrip("/"),
        avatar_render_public_base_url=_env(
            "AVATAR_RENDER_PUBLIC_BASE_URL",
            env_map,
            default=_env("AVATAR_RENDER_SERVICE_BASE_URL", env_map, default="http://127.0.0.1:8000"),
        ).rstrip("/"),
        tts_service_base_url=_env("TTS_SERVICE_BASE_URL", env_map, default="http://127.0.0.1:8200").rstrip("/"),
        public_base_url=_env("PLATFORM_PUBLIC_BASE_URL", env_map, default="http://127.0.0.1:8100").rstrip("/"),
        cors_allow_origins=_csv(_env("PLATFORM_CORS_ALLOW_ORIGINS", env_map, default="*")),
        auth_required=_bool(_env("PLATFORM_AUTH_REQUIRED", env_map, default="true")),
        platform_jwt_secret=_env("PLATFORM_JWT_SECRET", env_map, default="change-me-for-production"),
        default_org_id=_env("PLATFORM_DEFAULT_ORG_ID", env_map, default="pilot-org"),
        default_org_name=_env("PLATFORM_DEFAULT_ORG_NAME", env_map, default="Pilot Organization"),
        admin_emails=_csv(_env("PLATFORM_ADMIN_EMAILS", env_map, default="")),
        azure_openai_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT") or env_map.get("AZURE_OPENAI_ENDPOINT"),
        azure_openai_api_key=os.getenv("AZURE_OPENAI_API_KEY") or env_map.get("AZURE_OPENAI_API_KEY"),
        azure_openai_chat_deployment=(os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT") or env_map.get("AZURE_OPENAI_CHAT_DEPLOYMENT") or os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME") or env_map.get("AZURE_OPENAI_DEPLOYMENT_NAME")),
        azure_openai_embeddings_deployment=os.getenv("AZURE_OPENAI_EMBEDDINGS_DEPLOYMENT") or env_map.get("AZURE_OPENAI_EMBEDDINGS_DEPLOYMENT"),
        azure_openai_api_version=_env("AZURE_OPENAI_API_VERSION", env_map, default="2024-10-21"),
        default_voice=_env("PLATFORM_DEFAULT_VOICE", env_map, default="en-US-JennyNeural"),
        avatar_chunk_duration_seconds=_int(_env("PLATFORM_AVATAR_CHUNK_DURATION_SECONDS", env_map, default="2"), 2),
        tts_request_timeout_seconds=_int(_env("PLATFORM_TTS_REQUEST_TIMEOUT_SECONDS", env_map, default="180"), 180),
    )
    settings.ensure_dirs()
    _SETTINGS = settings
    return settings


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect(db_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(str(db_path), check_same_thread=False)
    connection.row_factory = sqlite3.Row
    return connection


@contextmanager
def db_cursor(settings: Settings | None = None) -> Iterator[sqlite3.Cursor]:
    active_settings = settings or get_settings()
    connection = _connect(active_settings.database_path)
    try:
        cursor = connection.cursor()
        yield cursor
        connection.commit()
    finally:
        connection.close()


def _column_exists(cursor: sqlite3.Cursor, table_name: str, column_name: str) -> bool:
    rows = cursor.execute(f"PRAGMA table_info({table_name})").fetchall()
    return any(row[1] == column_name for row in rows)


def _ensure_column(cursor: sqlite3.Cursor, table_name: str, column_name: str, definition: str) -> None:
    if not _column_exists(cursor, table_name, column_name):
        cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")


def init_db(settings: Settings | None = None) -> None:
    active_settings = settings or get_settings()
    active_settings.ensure_dirs()
    with db_cursor(active_settings) as cursor:
        cursor.executescript(
            """
            CREATE TABLE IF NOT EXISTS orgs (
                org_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                org_id TEXT NOT NULL,
                external_subject TEXT UNIQUE,
                email TEXT,
                name TEXT,
                role TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS avatars (
                avatar_id TEXT PRIMARY KEY,
                org_id TEXT NOT NULL,
                display_name TEXT NOT NULL,
                status TEXT NOT NULL,
                approved INTEGER NOT NULL DEFAULT 1,
                language TEXT NOT NULL DEFAULT 'multilingual',
                source_object_key TEXT,
                prepared_bundle_location TEXT,
                persona_prompt TEXT NOT NULL DEFAULT '',
                default_voice TEXT NOT NULL DEFAULT 'en-US-JennyNeural',
                num_frames INTEGER,
                last_error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS documents (
                document_id TEXT PRIMARY KEY,
                org_id TEXT NOT NULL,
                title TEXT NOT NULL,
                status TEXT NOT NULL,
                mime_type TEXT NOT NULL,
                source_object_key TEXT NOT NULL,
                chunk_count INTEGER NOT NULL DEFAULT 0,
                last_error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS document_chunks (
                chunk_id TEXT PRIMARY KEY,
                document_id TEXT NOT NULL,
                org_id TEXT NOT NULL,
                chunk_index INTEGER NOT NULL,
                content TEXT NOT NULL,
                embedding_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                org_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                avatar_id TEXT NOT NULL,
                language TEXT NOT NULL DEFAULT 'en',
                input_language TEXT NOT NULL DEFAULT 'en',
                output_language TEXT NOT NULL DEFAULT 'en',
                audience TEXT,
                context_notes TEXT,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS turns (
                turn_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                org_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                user_audio_object_key TEXT,
                user_transcript TEXT,
                retrieval_query_text TEXT,
                assistant_text TEXT,
                assistant_audio_object_key TEXT,
                render_job_id TEXT,
                status TEXT NOT NULL,
                error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS turn_events (
                event_id TEXT PRIMARY KEY,
                turn_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_turns_session_created_at ON turns (session_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_document_chunks_document_index ON document_chunks (document_id, chunk_index);
            """
        )
        _ensure_column(cursor, "sessions", "input_language", "TEXT NOT NULL DEFAULT 'en'")
        _ensure_column(cursor, "sessions", "output_language", "TEXT NOT NULL DEFAULT 'en'")
        _ensure_column(cursor, "turns", "retrieval_query_text", "TEXT")
        cursor.execute(
            """
            UPDATE sessions
            SET input_language = COALESCE(NULLIF(input_language, ''), COALESCE(language, 'en')),
                output_language = COALESCE(NULLIF(output_language, ''), COALESCE(language, 'en'))
            """
        )


def ensure_bootstrap(settings: Settings | None = None) -> None:
    active_settings = settings or get_settings()
    init_db(active_settings)
    timestamp = utc_now()
    with db_cursor(active_settings) as cursor:
        cursor.execute(
            """
            INSERT INTO orgs (org_id, name, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(org_id) DO UPDATE SET name=excluded.name, updated_at=excluded.updated_at
            """,
            (active_settings.default_org_id, active_settings.default_org_name, timestamp, timestamp),
        )


def _row_get(row: sqlite3.Row, key: str, default: Any = None) -> Any:
    return row[key] if key in row.keys() else default


def _row_to_avatar(row: sqlite3.Row) -> AvatarRecord:
    return AvatarRecord(
        avatar_id=row["avatar_id"],
        display_name=row["display_name"],
        status=row["status"],
        approved=bool(row["approved"]),
        language=_row_get(row, "language", "multilingual") or "multilingual",
        source_object_key=row["source_object_key"],
        prepared_bundle_location=row["prepared_bundle_location"],
        persona_prompt=row["persona_prompt"] or "",
        default_voice=row["default_voice"] or "en-US-JennyNeural",
        num_frames=row["num_frames"],
        last_error=row["last_error"],
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


def _row_to_document(row: sqlite3.Row) -> DocumentRecord:
    return DocumentRecord(
        document_id=row["document_id"],
        title=row["title"],
        status=row["status"],
        mime_type=row["mime_type"],
        source_object_key=row["source_object_key"],
        chunk_count=row["chunk_count"],
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
        last_error=row["last_error"],
    )


def _row_to_session(row: sqlite3.Row) -> SessionRecord:
    fallback_language = _row_get(row, "language", "en") or "en"
    return SessionRecord(
        session_id=row["session_id"],
        avatar_id=row["avatar_id"],
        input_language=_row_get(row, "input_language", fallback_language) or fallback_language,
        output_language=_row_get(row, "output_language", fallback_language) or fallback_language,
        status=row["status"],
        audience=row["audience"],
        context_notes=row["context_notes"],
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


def _row_to_turn(row: sqlite3.Row) -> TurnRecord:
    return TurnRecord(
        turn_id=row["turn_id"],
        session_id=row["session_id"],
        user_transcript=row["user_transcript"],
        retrieval_query_text=_row_get(row, "retrieval_query_text"),
        assistant_text=row["assistant_text"],
        assistant_audio_object_key=_row_get(row, "assistant_audio_object_key"),
        status=row["status"],
        render_job_id=row["render_job_id"],
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
        error=row["error"],
    )


def upsert_user(*, subject: str, email: str | None, name: str | None, role: str, settings: Settings | None = None) -> AuthUser:
    active_settings = settings or get_settings()
    ensure_bootstrap(active_settings)
    timestamp = utc_now()
    with db_cursor(active_settings) as cursor:
        existing = cursor.execute("SELECT user_id FROM users WHERE external_subject = ?", (subject,)).fetchone()
        user_id = existing["user_id"] if existing else f"user_{uuid.uuid4().hex}"
        cursor.execute(
            """
            INSERT INTO users (user_id, org_id, external_subject, email, name, role, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET email=excluded.email, name=excluded.name, role=excluded.role, updated_at=excluded.updated_at
            """,
            (user_id, active_settings.default_org_id, subject, email, name, role, timestamp, timestamp),
        )
    return AuthUser(
        user_id=user_id,
        org_id=active_settings.default_org_id,
        email=email,
        name=name,
        role="admin" if role == "admin" else "user",
    )


def create_avatar_record(payload: AdminAvatarCreateRequest, settings: Settings | None = None) -> AvatarRecord:
    active_settings = settings or get_settings()
    ensure_bootstrap(active_settings)
    timestamp = utc_now()
    with db_cursor(active_settings) as cursor:
        cursor.execute(
            """
            INSERT INTO avatars (avatar_id, org_id, display_name, status, approved, language, source_object_key, prepared_bundle_location, persona_prompt, default_voice, num_frames, last_error, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload.avatar_id.strip(),
                active_settings.default_org_id,
                payload.display_name.strip(),
                "uploading",
                1 if payload.approved else 0,
                payload.language,
                None,
                None,
                payload.persona_prompt.strip(),
                payload.default_voice.strip() or active_settings.default_voice,
                None,
                None,
                timestamp,
                timestamp,
            ),
        )
    return get_avatar(payload.avatar_id.strip(), settings=active_settings)


def get_avatar(avatar_id: str, settings: Settings | None = None) -> AvatarRecord:
    active_settings = settings or get_settings()
    ensure_bootstrap(active_settings)
    with db_cursor(active_settings) as cursor:
        row = cursor.execute("SELECT * FROM avatars WHERE avatar_id = ?", (avatar_id,)).fetchone()
    if not row:
        raise FileNotFoundError(f"Avatar not found: {avatar_id}")
    return _row_to_avatar(row)


def update_avatar(
    avatar_id: str,
    *,
    status: str | None = None,
    source_object_key: str | None = None,
    prepared_bundle_location: str | None = None,
    num_frames: int | None = None,
    last_error: str | None = None,
    approved: bool | None = None,
    settings: Settings | None = None,
) -> AvatarRecord:
    active_settings = settings or get_settings()
    current = get_avatar(avatar_id, settings=active_settings)
    timestamp = utc_now()
    with db_cursor(active_settings) as cursor:
        cursor.execute(
            """
            UPDATE avatars
            SET status = ?, source_object_key = ?, prepared_bundle_location = ?, num_frames = ?, last_error = ?, approved = ?, updated_at = ?
            WHERE avatar_id = ?
            """,
            (
                status or current.status,
                source_object_key if source_object_key is not None else current.source_object_key,
                prepared_bundle_location if prepared_bundle_location is not None else current.prepared_bundle_location,
                num_frames if num_frames is not None else current.num_frames,
                last_error,
                1 if (approved if approved is not None else current.approved) else 0,
                timestamp,
                avatar_id,
            ),
        )
    return get_avatar(avatar_id, settings=active_settings)


def list_admin_avatars(settings: Settings | None = None) -> AvatarListResponse:
    active_settings = settings or get_settings()
    with db_cursor(active_settings) as cursor:
        rows = cursor.execute("SELECT * FROM avatars ORDER BY updated_at DESC, avatar_id ASC").fetchall()
    return AvatarListResponse(avatars=[_row_to_avatar(row) for row in rows])


def list_public_avatars(settings: Settings | None = None) -> AvatarListResponse:
    active_settings = settings or get_settings()
    with db_cursor(active_settings) as cursor:
        rows = cursor.execute("SELECT * FROM avatars WHERE approved = 1 AND status = 'ready' ORDER BY display_name ASC, avatar_id ASC").fetchall()
    return AvatarListResponse(avatars=[_row_to_avatar(row) for row in rows])


def create_document_record(*, title: str, mime_type: str, source_object_key: str, settings: Settings | None = None) -> DocumentRecord:
    active_settings = settings or get_settings()
    ensure_bootstrap(active_settings)
    document_id = f"doc_{uuid.uuid4().hex}"
    timestamp = utc_now()
    with db_cursor(active_settings) as cursor:
        cursor.execute(
            """
            INSERT INTO documents (document_id, org_id, title, status, mime_type, source_object_key, chunk_count, last_error, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (document_id, active_settings.default_org_id, title, "uploaded", mime_type, source_object_key, 0, None, timestamp, timestamp),
        )
    return get_document(document_id, settings=active_settings)


def get_document(document_id: str, settings: Settings | None = None) -> DocumentRecord:
    active_settings = settings or get_settings()
    with db_cursor(active_settings) as cursor:
        row = cursor.execute("SELECT * FROM documents WHERE document_id = ?", (document_id,)).fetchone()
    if not row:
        raise FileNotFoundError(f"Document not found: {document_id}")
    return _row_to_document(row)


def set_document_chunks(
    document_id: str,
    *,
    chunks: Sequence[tuple[int, str, list[float]]],
    status: str,
    last_error: str | None = None,
    settings: Settings | None = None,
) -> DocumentRecord:
    active_settings = settings or get_settings()
    timestamp = utc_now()
    with db_cursor(active_settings) as cursor:
        cursor.execute("DELETE FROM document_chunks WHERE document_id = ?", (document_id,))
        for chunk_index, content, embedding in chunks:
            cursor.execute(
                """
                INSERT INTO document_chunks (chunk_id, document_id, org_id, chunk_index, content, embedding_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (f"chunk_{uuid.uuid4().hex}", document_id, active_settings.default_org_id, chunk_index, content, json.dumps(embedding), timestamp),
            )
        cursor.execute(
            "UPDATE documents SET status = ?, chunk_count = ?, last_error = ?, updated_at = ? WHERE document_id = ?",
            (status, len(chunks), last_error, timestamp, document_id),
        )
    return get_document(document_id, settings=active_settings)


def list_documents(settings: Settings | None = None) -> DocumentListResponse:
    active_settings = settings or get_settings()
    with db_cursor(active_settings) as cursor:
        rows = cursor.execute("SELECT * FROM documents ORDER BY updated_at DESC, title ASC").fetchall()
    return DocumentListResponse(documents=[_row_to_document(row) for row in rows])


def create_session_record(*, user: AuthUser, payload: SessionCreateRequest, settings: Settings | None = None) -> SessionRecord:
    active_settings = settings or get_settings()
    session_id = f"session_{uuid.uuid4().hex}"
    timestamp = utc_now()
    with db_cursor(active_settings) as cursor:
        cursor.execute(
            """
            INSERT INTO sessions (session_id, org_id, user_id, avatar_id, language, input_language, output_language, audience, context_notes, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                user.org_id,
                user.user_id,
                payload.avatar_id,
                payload.output_language,
                payload.input_language,
                payload.output_language,
                payload.audience,
                payload.context_notes,
                "active",
                timestamp,
                timestamp,
            ),
        )
    return get_session_record(session_id, settings=active_settings)


def get_session_record(session_id: str, settings: Settings | None = None) -> SessionRecord:
    active_settings = settings or get_settings()
    with db_cursor(active_settings) as cursor:
        row = cursor.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
    if not row:
        raise FileNotFoundError(f"Session not found: {session_id}")
    return _row_to_session(row)


def create_turn_record(*, session_id: str, user: AuthUser, user_audio_object_key: str, settings: Settings | None = None) -> TurnRecord:
    active_settings = settings or get_settings()
    turn_id = f"turn_{uuid.uuid4().hex}"
    timestamp = utc_now()
    with db_cursor(active_settings) as cursor:
        cursor.execute(
            """
            INSERT INTO turns (turn_id, session_id, org_id, user_id, user_audio_object_key, user_transcript, retrieval_query_text, assistant_text, assistant_audio_object_key, render_job_id, status, error, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (turn_id, session_id, user.org_id, user.user_id, user_audio_object_key, None, None, None, None, None, "received", None, timestamp, timestamp),
        )
    return get_turn_record(turn_id, settings=active_settings)


def get_turn_record(turn_id: str, settings: Settings | None = None) -> TurnRecord:
    active_settings = settings or get_settings()
    with db_cursor(active_settings) as cursor:
        row = cursor.execute("SELECT * FROM turns WHERE turn_id = ?", (turn_id,)).fetchone()
    if not row:
        raise FileNotFoundError(f"Turn not found: {turn_id}")
    return _row_to_turn(row)


def update_turn_record(
    turn_id: str,
    *,
    user_transcript: str | None = None,
    retrieval_query_text: str | None = None,
    assistant_text: str | None = None,
    assistant_audio_object_key: str | None = None,
    render_job_id: str | None = None,
    status: str | None = None,
    error: str | None = None,
    settings: Settings | None = None,
) -> TurnRecord:
    active_settings = settings or get_settings()
    current = get_turn_record(turn_id, settings=active_settings)
    timestamp = utc_now()
    with db_cursor(active_settings) as cursor:
        cursor.execute(
            """
            UPDATE turns
            SET user_transcript = ?, retrieval_query_text = ?, assistant_text = ?, assistant_audio_object_key = ?, render_job_id = ?, status = ?, error = ?, updated_at = ?
            WHERE turn_id = ?
            """,
            (
                user_transcript if user_transcript is not None else current.user_transcript,
                retrieval_query_text if retrieval_query_text is not None else current.retrieval_query_text,
                assistant_text if assistant_text is not None else current.assistant_text,
                assistant_audio_object_key if assistant_audio_object_key is not None else current.assistant_audio_object_key,
                render_job_id if render_job_id is not None else current.render_job_id,
                status or current.status,
                error,
                timestamp,
                turn_id,
            ),
        )
    return get_turn_record(turn_id, settings=active_settings)


def list_turns_for_session(session_id: str, settings: Settings | None = None) -> list[TurnRecord]:
    active_settings = settings or get_settings()
    with db_cursor(active_settings) as cursor:
        rows = cursor.execute("SELECT * FROM turns WHERE session_id = ? ORDER BY created_at ASC", (session_id,)).fetchall()
    return [_row_to_turn(row) for row in rows]


def append_turn_event(turn_id: str, event_type: str, payload: dict[str, Any], settings: Settings | None = None) -> None:
    active_settings = settings or get_settings()
    with db_cursor(active_settings) as cursor:
        cursor.execute(
            "INSERT INTO turn_events (event_id, turn_id, event_type, payload_json, created_at) VALUES (?, ?, ?, ?, ?)",
            (f"event_{uuid.uuid4().hex}", turn_id, event_type, json.dumps(payload, ensure_ascii=False), utc_now()),
        )


def get_session_history(session_id: str, settings: Settings | None = None) -> TurnHistoryResponse:
    active_settings = settings or get_settings()
    return TurnHistoryResponse(
        session=get_session_record(session_id, settings=active_settings),
        turns=list_turns_for_session(session_id, settings=active_settings),
    )


def recent_conversation_context(session_id: str, settings: Settings | None = None, limit: int = 6) -> list[dict[str, str]]:
    turns = list_turns_for_session(session_id, settings=settings)[-limit:]
    messages: list[dict[str, str]] = []
    for turn in turns:
        if turn.user_transcript:
            messages.append({"role": "user", "content": turn.user_transcript})
        if turn.assistant_text:
            messages.append({"role": "assistant", "content": turn.assistant_text})
    return messages


def collapse_whitespace(text: str) -> str:
    return " ".join((text or "").split())


def _tokenize(text: str) -> list[str]:
    normalized = "".join(ch.lower() if ch.isalnum() else " " for ch in text)
    return [token for token in normalized.split() if token]


def build_local_embedding(text: str) -> list[float]:
    vector = [0.0] * EMBEDDING_DIMENSIONS
    tokens = _tokenize(text)
    if not tokens:
        return vector
    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        slot = digest[0] % EMBEDDING_DIMENSIONS
        sign = 1.0 if digest[1] % 2 == 0 else -1.0
        vector[slot] += sign
    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [value / norm for value in vector]


def split_document_text(text: str, max_chunk_chars: int = 800) -> list[str]:
    cleaned = "\n".join(line.strip() for line in text.splitlines())
    paragraphs = [block.strip() for block in cleaned.split("\n\n") if block.strip()]
    if not paragraphs:
        return []
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        candidate = f"{current}\n\n{paragraph}".strip() if current else paragraph
        if len(candidate) <= max_chunk_chars:
            current = candidate
            continue
        if current:
            chunks.append(current)
        if len(paragraph) <= max_chunk_chars:
            current = paragraph
            continue
        start = 0
        while start < len(paragraph):
            end = start + max_chunk_chars
            chunks.append(paragraph[start:end].strip())
            start = end
        current = ""
    if current:
        chunks.append(current)
    return chunks


def extract_document_text(file_name: str, content: bytes, mime_type: str) -> str:
    lower_name = file_name.lower()
    if mime_type.startswith("text/") or lower_name.endswith((".txt", ".md", ".markdown")):
        return content.decode("utf-8", errors="ignore")
    if lower_name.endswith(".pdf"):
        try:
            from pypdf import PdfReader
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("PDF upload requires pypdf to be installed.") from exc
        import io

        reader = PdfReader(io.BytesIO(content))
        pages = [page.extract_text() or "" for page in reader.pages]
        return "\n".join(page.strip() for page in pages if page.strip())
    raise ValueError(f"Unsupported document type: {mime_type or file_name}")


def list_retrieval_candidates(settings: Settings | None = None) -> list[dict[str, Any]]:
    active_settings = settings or get_settings()
    with db_cursor(active_settings) as cursor:
        rows = cursor.execute(
            """
            SELECT dc.document_id, dc.chunk_index, dc.content, dc.embedding_json, d.title
            FROM document_chunks dc
            JOIN documents d ON d.document_id = dc.document_id
            WHERE d.status = 'ready'
            """
        ).fetchall()
    return [
        {
            "document_id": row["document_id"],
            "title": row["title"],
            "chunk_index": row["chunk_index"],
            "content": row["content"],
            "embedding": json.loads(row["embedding_json"]),
        }
        for row in rows
    ]


def retrieve_chunks_for_query(query_embedding: list[float], settings: Settings | None = None, limit: int = 4) -> list[RetrievalChunk]:
    def cosine(left: list[float], right: list[float]) -> float:
        numerator = sum(a * b for a, b in zip(left, right))
        left_norm = math.sqrt(sum(value * value for value in left)) or 1.0
        right_norm = math.sqrt(sum(value * value for value in right)) or 1.0
        return numerator / (left_norm * right_norm)

    candidates: list[tuple[float, dict[str, Any]]] = []
    for item in list_retrieval_candidates(settings=settings):
        candidates.append((cosine(query_embedding, item["embedding"]), item))
    candidates.sort(key=lambda entry: entry[0], reverse=True)
    return [
        RetrievalChunk(
            document_id=item["document_id"],
            title=item["title"],
            chunk_index=item["chunk_index"],
            score=round(score, 4),
            content=item["content"],
        )
        for score, item in candidates[:limit]
        if score > 0
    ]


def summarize_chunks(chunks: Sequence[RetrievalChunk]) -> str:
    if not chunks:
        return "No indexed organization documents were relevant to this question."
    return "\n".join(
        f"[{chunk.title} #{chunk.chunk_index}] {chunk.content[:220].strip().replace(chr(10), ' ')}"
        for chunk in chunks
    )


def role_for_email(email: str | None, settings: Settings | None = None) -> str:
    active_settings = settings or get_settings()
    if email and email.lower() in {item.lower() for item in active_settings.admin_emails}:
        return "admin"
    return "user"


def decode_platform_token(token: str, settings: Settings | None = None) -> AuthUser:
    active_settings = settings or get_settings()
    payload = jwt.decode(token, active_settings.platform_jwt_secret, algorithms=["HS256"])
    subject = str(payload.get("sub") or "").strip()
    if not subject:
        raise HTTPException(status_code=401, detail="Platform access token is missing a subject.")
    return upsert_user(
        subject=subject,
        email=payload.get("email"),
        name=payload.get("name"),
        role="admin" if payload.get("role") == "admin" else "user",
        settings=active_settings,
    )


def require_user(authorization: Optional[str] = Header(default=None)) -> AuthUser:
    settings = get_settings()
    if not settings.auth_required:
        return AuthUser(user_id="demo-user", org_id=settings.default_org_id, email="demo@example.com", name="Demo User", role="admin")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token.")
    token = authorization.removeprefix("Bearer ").strip()
    try:
        return decode_platform_token(token, settings=settings)
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail=f"Invalid platform access token: {exc}") from exc


def require_admin(authorization: Optional[str] = Header(default=None)) -> AuthUser:
    user = require_user(authorization)
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access is required.")
    return user


class LocalObjectStore:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.settings.ensure_dirs()

    def path_for_key(self, object_key: str) -> Path:
        normalized = object_key.replace("\\", "/").lstrip("/")
        return self.settings.objects_root / Path(normalized)

    def save_bytes(self, object_key: str, content: bytes) -> Path:
        destination = self.path_for_key(object_key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
        return destination

    def save_upload(self, object_key: str, upload: UploadFile) -> Path:
        return self.save_bytes(object_key, upload.file.read())

    def copy_from_path(self, object_key: str, source_path: Path) -> Path:
        return self.save_bytes(object_key, source_path.read_bytes())


class AvatarRenderClient:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def preprocess_avatar(self, *, avatar_id: str, video_path: Path, model_version: str = "v15") -> dict[str, Any]:
        with video_path.open("rb") as handle:
            response = requests.post(
                f"{self.settings.avatar_render_service_base_url}/avatars/preprocess-upload",
                data={"avatar_id": avatar_id, "model_version": model_version},
                files={"video_file": (video_path.name, handle, "video/mp4")},
                timeout=60 * 30,
            )
        response.raise_for_status()
        return response.json()

    def start_render_job(
        self,
        *,
        avatar_id: str,
        audio_path: Path,
        job_id: str,
        batch_size: int = 8,
        chunk_duration: int | None = None,
        model_version: str = "v15",
    ) -> dict[str, Any]:
        with audio_path.open("rb") as handle:
            response = requests.post(
                f"{self.settings.avatar_render_service_base_url}/jobs/render-async",
                data={
                    "avatar_id": avatar_id,
                    "job_id": job_id,
                    "batch_size": str(batch_size),
                    "chunk_duration": str(chunk_duration or self.settings.avatar_chunk_duration_seconds),
                    "model_version": model_version,
                },
                files={"audio_file": (audio_path.name, handle, "audio/wav")},
                timeout=120,
            )
        response.raise_for_status()
        return response.json()

    def get_render_job(self, job_id: str) -> dict[str, Any]:
        response = requests.get(f"{self.settings.avatar_render_service_base_url}/jobs/{job_id}", timeout=30)
        response.raise_for_status()
        return response.json()

    def public_output_url(self, relative_or_absolute: str) -> str:
        if relative_or_absolute.startswith("http://") or relative_or_absolute.startswith("https://"):
            return relative_or_absolute
        normalized = relative_or_absolute if relative_or_absolute.startswith("/") else f"/{relative_or_absolute}"
        return f"{self.settings.avatar_render_public_base_url}{normalized}"


class TtsServiceClient:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def provider_for_language(self, language: str) -> str:
        provider = LANGUAGE_PROVIDER_MAP.get(language)
        if not provider:
            raise RuntimeError(f"Unsupported TTS output language: {language}")
        return provider

    def synthesize(self, *, text: str, language: str, request_id: str) -> dict[str, Any]:
        response = requests.post(
            f"{self.settings.tts_service_base_url}/synthesize",
            json={"text": text, "language": language, "request_id": request_id},
            timeout=self.settings.tts_request_timeout_seconds,
        )
        if not response.ok:
            detail = ""
            try:
                error_payload = response.json()
                if isinstance(error_payload, dict):
                    detail = str(error_payload.get("detail") or error_payload.get("message") or "").strip()
            except ValueError:
                detail = response.text.strip()
            raise RuntimeError(detail or f"TTS service returned {response.status_code}.")
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError("TTS service returned an unexpected response payload.")
        return payload

    def resolve_audio_bytes(self, payload: dict[str, Any]) -> tuple[bytes, str]:
        audio_path = str(payload.get("audio_path") or "").strip()
        audio_url = str(payload.get("audio_url") or "").strip()
        mime_type = str(payload.get("mime_type") or "audio/wav")
        if audio_path:
            source_path = Path(audio_path)
            if source_path.exists():
                return source_path.read_bytes(), mime_type
        if not audio_url:
            raise RuntimeError("TTS service did not return an audio file path or URL.")
        response = requests.get(audio_url, timeout=self.settings.tts_request_timeout_seconds)
        response.raise_for_status()
        return response.content, response.headers.get("content-type", mime_type)


class CognitiveProvider:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def transcribe_audio(
        self,
        audio_path: Path,
        transcript_hint: str | None = None,
        input_language: InputLanguageValue = "en",
    ) -> str:
        del audio_path, input_language
        transcript = collapse_whitespace(transcript_hint or "")
        if transcript:
            return transcript
        raise RuntimeError("Transcript hint is required for the multilingual demo path.")

    def _azure_client(self):
        if not (
            self.settings.azure_openai_endpoint
            and self.settings.azure_openai_api_key
            and self.settings.azure_openai_chat_deployment
        ):
            return None
        try:
            from openai import AzureOpenAI
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("Azure OpenAI chat requires the openai package.") from exc
        return AzureOpenAI(
            api_key=self.settings.azure_openai_api_key,
            azure_endpoint=self.settings.azure_openai_endpoint,
            api_version=self.settings.azure_openai_api_version,
        )

    def embed_text(self, text: str) -> list[float]:
        if self.settings.azure_openai_endpoint and self.settings.azure_openai_api_key and self.settings.azure_openai_embeddings_deployment:
            try:
                from openai import AzureOpenAI
            except ImportError as exc:  # pragma: no cover
                raise RuntimeError("Azure OpenAI embeddings require the openai package.") from exc
            client = AzureOpenAI(
                api_key=self.settings.azure_openai_api_key,
                azure_endpoint=self.settings.azure_openai_endpoint,
                api_version=self.settings.azure_openai_api_version,
            )
            response = client.embeddings.create(model=self.settings.azure_openai_embeddings_deployment, input=text)
            return list(response.data[0].embedding)
        return build_local_embedding(text)

    def normalize_query_for_retrieval(self, *, transcript: str, input_language: InputLanguageValue) -> str:
        if input_language == "en":
            return collapse_whitespace(transcript)

        client = self._azure_client()
        if client is None:
            return collapse_whitespace(transcript)

        response = client.chat.completions.create(
            model=self.settings.azure_openai_chat_deployment,
            temperature=0.1,
            messages=[
                {
                    "role": "system",
                    "content": "Translate the user's Hindi utterance into concise natural English for internal retrieval. Preserve names and numbers. Return only the English translation.",
                },
                {"role": "user", "content": transcript},
            ],
        )
        normalized = collapse_whitespace(response.choices[0].message.content or "")
        return normalized or collapse_whitespace(transcript)

    def generate_answer(
        self,
        *,
        transcript: str,
        retrieval_query_text: str,
        input_language: InputLanguageValue,
        output_language: str,
        persona_prompt: str,
        retrieved_chunks: Sequence[RetrievalChunk],
        history: Sequence[dict[str, str]],
        audience: str | None,
        context_notes: str | None,
    ) -> str:
        target_language_label = OUTPUT_LANGUAGE_LABELS.get(output_language, output_language)
        input_language_label = INPUT_LANGUAGE_LABELS.get(input_language, input_language)
        retrieved_context = summarize_chunks(retrieved_chunks)
        history_lines = "\n".join(f"{item['role']}: {item['content']}" for item in history[-6:])
        system_prompt = (
            "You are a helpful multilingual digital avatar for a live demo. "
            f"Answer clearly, warmly, and concisely in {target_language_label}. "
            "Use the natural script for that language and avoid Latin transliteration unless the user explicitly writes that way. "
            "Stay grounded in the provided organization context when available."
        )
        if persona_prompt.strip():
            system_prompt = f"{system_prompt}\n\nAvatar persona:\n{persona_prompt.strip()}"

        client = self._azure_client()
        if client is not None:
            response = client.chat.completions.create(
                model=self.settings.azure_openai_chat_deployment,
                temperature=0.4,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": (
                            f"Input language: {input_language_label}\n"
                            f"Target output language: {target_language_label}\n"
                            f"Audience: {audience or 'General public'}\n"
                            f"Session notes: {context_notes or 'None'}\n"
                            f"Recent conversation:\n{history_lines or 'No previous turns'}\n\n"
                            f"Retrieval query in English:\n{retrieval_query_text}\n\n"
                            f"Organization context:\n{retrieved_context}\n\n"
                            f"User said:\n{transcript}"
                        ),
                    },
                ],
            )
            return collapse_whitespace((response.choices[0].message.content or "").strip())

        prefix = persona_prompt.strip().splitlines()[0].strip() if persona_prompt.strip() else "Selected avatar response"
        return f"{prefix}: {transcript}"


def health_payload(settings: Settings | None = None) -> HealthResponse:
    active_settings = settings or get_settings()
    return HealthResponse(
        status="ok",
        service="platform-service",
        auth_required=active_settings.auth_required,
        storage_backend="local",
    )


def sse_message(event_name: str, payload: dict[str, Any]) -> str:
    return f"event: {event_name}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def run_avatar_preprocess_job(avatar_id: str, settings: Settings | None = None) -> None:
    active_settings = settings or get_settings()
    store = LocalObjectStore(active_settings)
    client = AvatarRenderClient(active_settings)
    avatar = get_avatar(avatar_id, settings=active_settings)
    if not avatar.source_object_key:
        update_avatar(avatar_id, status="failed", last_error="No source avatar video uploaded.", settings=active_settings)
        return
    try:
        source_path = store.path_for_key(avatar.source_object_key)
        response = client.preprocess_avatar(avatar_id=avatar.avatar_id, video_path=source_path)
        prepared_location = response.get("avatar_data_path") or response.get("avatar_info_path")
        num_frames = None
        avatar_info_path = response.get("avatar_info_path")
        if avatar_info_path and Path(avatar_info_path).exists():
            payload = json.loads(Path(avatar_info_path).read_text(encoding="utf-8"))
            if isinstance(payload.get("num_frames"), int):
                num_frames = payload["num_frames"]
        update_avatar(
            avatar_id,
            status="ready",
            prepared_bundle_location=str(prepared_location) if prepared_location else None,
            num_frames=num_frames,
            last_error=None,
            settings=active_settings,
        )
    except Exception as exc:
        update_avatar(avatar_id, status="failed", last_error=str(exc), settings=active_settings)


def _tts_cache_key_version(provider: str) -> str | None:
    if provider == "indic-parler":
        return INDIC_PARLER_CACHE_VERSION
    return None


def _tts_cache_object_key(provider: str, language: str, text: str, cache_key_version: str | None = None) -> str:
    normalized_text = collapse_whitespace(text)
    digest = hashlib.sha256(
        json.dumps(
            {
                "provider": provider,
                "language": language,
                "text": normalized_text,
                "cache_key_version": cache_key_version,
            },
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()
    return f"tts-cache/{provider}/{language}/{digest}.wav"


def start_turn_stream(
    *,
    session_id: str,
    user: AuthUser,
    audio_bytes: bytes,
    audio_filename: str,
    transcript_hint: str | None,
    settings: Settings | None = None,
) -> Iterator[str]:
    active_settings = settings or get_settings()
    store = LocalObjectStore(active_settings)
    cognition = CognitiveProvider(active_settings)
    render_client = AvatarRenderClient(active_settings)
    tts_client = TtsServiceClient(active_settings)
    session = get_session_record(session_id, settings=active_settings)
    avatar = get_avatar(session.avatar_id, settings=active_settings)
    if avatar.status != "ready":
        raise RuntimeError(f"Avatar {avatar.avatar_id} is not ready.")

    audio_extension = Path(audio_filename or "turn-audio.webm").suffix or ".webm"
    audio_object_key = f"turn-audio/{session_id}/{uuid.uuid4().hex}/turn{audio_extension}"
    local_audio_path = store.save_bytes(audio_object_key, audio_bytes)
    turn = create_turn_record(session_id=session_id, user=user, user_audio_object_key=audio_object_key, settings=active_settings)

    try:
        transcript = cognition.transcribe_audio(
            local_audio_path,
            transcript_hint=transcript_hint,
            input_language=session.input_language,
        )
        update_turn_record(turn.turn_id, user_transcript=transcript, status="thinking", settings=active_settings)
        transcript_event = TranscriptReadyEvent(
            session_id=session_id,
            turn_id=turn.turn_id,
            transcript=transcript,
            input_language=session.input_language,
        )
        append_turn_event(turn.turn_id, "transcript_ready", model_to_dict(transcript_event), settings=active_settings)
        yield sse_message("transcript_ready", model_to_dict(transcript_event))

        retrieval_query_text = cognition.normalize_query_for_retrieval(
            transcript=transcript,
            input_language=session.input_language,
        )
        update_turn_record(turn.turn_id, retrieval_query_text=retrieval_query_text, status="thinking", settings=active_settings)
        query_embedding = cognition.embed_text(retrieval_query_text)
        retrieved_chunks = retrieve_chunks_for_query(query_embedding, settings=active_settings, limit=4)
        retrieval_event = RetrievalReadyEvent(
            session_id=session_id,
            turn_id=turn.turn_id,
            query_text=retrieval_query_text,
            chunks=retrieved_chunks,
        )
        append_turn_event(turn.turn_id, "retrieval_ready", model_to_dict(retrieval_event), settings=active_settings)
        yield sse_message("retrieval_ready", model_to_dict(retrieval_event))

        assistant_text = cognition.generate_answer(
            transcript=transcript,
            retrieval_query_text=retrieval_query_text,
            input_language=session.input_language,
            output_language=session.output_language,
            persona_prompt=avatar.persona_prompt,
            retrieved_chunks=retrieved_chunks,
            history=recent_conversation_context(session_id, settings=active_settings),
            audience=session.audience,
            context_notes=session.context_notes,
        )
        update_turn_record(turn.turn_id, assistant_text=assistant_text, status="synthesizing", settings=active_settings)
        text_event = AssistantTextReadyEvent(
            session_id=session_id,
            turn_id=turn.turn_id,
            language=session.output_language,
            text=assistant_text,
        )
        append_turn_event(turn.turn_id, "assistant_text_ready", model_to_dict(text_event), settings=active_settings)
        yield sse_message("assistant_text_ready", model_to_dict(text_event))

        provider = tts_client.provider_for_language(session.output_language)
        cache_key_version = _tts_cache_key_version(provider)
        assistant_audio_object_key = _tts_cache_object_key(
            provider,
            session.output_language,
            assistant_text,
            cache_key_version=cache_key_version,
        )
        assistant_audio_path = store.path_for_key(assistant_audio_object_key)
        cache_hit = assistant_audio_path.exists()

        if not cache_hit:
            synth_payload = tts_client.synthesize(
                text=assistant_text,
                language=session.output_language,
                request_id=turn.turn_id,
            )
            provider = str(synth_payload.get("provider") or provider)
            cache_key_version = str(synth_payload.get("cache_key_version") or _tts_cache_key_version(provider) or "").strip() or None
            assistant_audio_object_key = _tts_cache_object_key(
                provider,
                session.output_language,
                assistant_text,
                cache_key_version=cache_key_version,
            )
            assistant_audio_path = store.path_for_key(assistant_audio_object_key)
            if not assistant_audio_path.exists():
                audio_bytes_from_tts, _mime_type = tts_client.resolve_audio_bytes(synth_payload)
                assistant_audio_path = store.save_bytes(assistant_audio_object_key, audio_bytes_from_tts)
            cache_hit = bool(synth_payload.get("cache_hit")) or assistant_audio_path.exists()

        update_turn_record(
            turn.turn_id,
            assistant_audio_object_key=assistant_audio_object_key,
            status="rendering",
            settings=active_settings,
        )
        tts_event = TtsReadyEvent(
            session_id=session_id,
            turn_id=turn.turn_id,
            provider=provider,
            language=session.output_language,
            audio_object_key=assistant_audio_object_key,
            cache_hit=cache_hit,
        )
        append_turn_event(turn.turn_id, "tts_ready", model_to_dict(tts_event), settings=active_settings)
        yield sse_message("tts_ready", model_to_dict(tts_event))

        render_job_id = f"render_{uuid.uuid4().hex}"
        render_client.start_render_job(
            avatar_id=avatar.avatar_id,
            audio_path=assistant_audio_path,
            job_id=render_job_id,
            chunk_duration=active_settings.avatar_chunk_duration_seconds,
        )
        update_turn_record(turn.turn_id, render_job_id=render_job_id, status="rendering", settings=active_settings)

        seen_urls: set[str] = set()
        chunk_count = 0
        while True:
            status_payload = render_client.get_render_job(render_job_id)
            job_status = str(status_payload.get("status") or "running")
            for index, url in enumerate(list(status_payload.get("chunk_video_urls") or [])):
                public_url = render_client.public_output_url(url)
                if public_url in seen_urls:
                    continue
                seen_urls.add(public_url)
                chunk_count += 1
                chunk_event = AvatarChunkReadyEvent(
                    session_id=session_id,
                    turn_id=turn.turn_id,
                    avatar_id=avatar.avatar_id,
                    chunk_index=index,
                    video_url=public_url,
                    done_marker=False,
                    text_segment=assistant_text if index == 0 else None,
                )
                append_turn_event(turn.turn_id, "avatar_chunk_ready", model_to_dict(chunk_event), settings=active_settings)
                yield sse_message("avatar_chunk_ready", model_to_dict(chunk_event))
            if job_status == "completed":
                update_turn_record(turn.turn_id, status="completed", settings=active_settings)
                complete_event = TurnCompletedEvent(
                    session_id=session_id,
                    turn_id=turn.turn_id,
                    render_job_id=render_job_id,
                    chunk_count=chunk_count,
                )
                append_turn_event(turn.turn_id, "turn_completed", model_to_dict(complete_event), settings=active_settings)
                yield sse_message("turn_completed", model_to_dict(complete_event))
                return
            if job_status == "failed":
                error_message = str(status_payload.get("error") or "Avatar rendering failed.")
                update_turn_record(turn.turn_id, status="failed", error=error_message, settings=active_settings)
                failure_event = TurnFailedEvent(
                    session_id=session_id,
                    turn_id=turn.turn_id,
                    error=error_message,
                    recoverable=True,
                )
                append_turn_event(turn.turn_id, "turn_failed", model_to_dict(failure_event), settings=active_settings)
                yield sse_message("turn_failed", model_to_dict(failure_event))
                return
            time.sleep(1.0)
    except Exception as exc:
        update_turn_record(turn.turn_id, status="failed", error=str(exc), settings=active_settings)
        failure_event = TurnFailedEvent(
            session_id=session_id,
            turn_id=turn.turn_id,
            error=str(exc),
            recoverable=True,
        )
        append_turn_event(turn.turn_id, "turn_failed", model_to_dict(failure_event), settings=active_settings)
        yield sse_message("turn_failed", model_to_dict(failure_event))





