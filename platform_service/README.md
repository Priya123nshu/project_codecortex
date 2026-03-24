# Platform Service

`platform_service` is the CPU-side orchestration API for the multilingual real-time avatar demo.

## What it does

It sits in front of the existing GPU-backed `avatar_service` and handles:

- authenticated avatar listing for end users
- admin avatar creation plus preprocess kickoff
- admin document upload and retrieval indexing
- session creation with explicit input and output languages
- push-to-talk turn orchestration with transcript confirmation
- Hindi-to-English retrieval query normalization through Azure OpenAI
- final answer generation directly in the selected output language
- audio synthesis handoff to the internal `tts_service`
- streamed turn events over Server-Sent Events
- handoff to the existing MuseTalk render service for chunked avatar output

## Default local architecture

- Web app: Next.js in the repo root
- Platform API: `uvicorn platform_service.api:app --port 8100`
- TTS service: `uvicorn tts_service.api:app --port 8200`
- Avatar render service: `uvicorn avatar_service.api:app --port 8000`
- Storage: local filesystem under `platform_service/storage`
- Metadata store: SQLite under `platform_service/storage/platform.sqlite3`

## Main endpoints

### User-facing

- `GET /health`
- `GET /avatars`
- `POST /sessions`
- `GET /sessions/{session_id}`
- `GET /sessions/{session_id}/history`
- `POST /sessions/{session_id}/turns`

### Admin

- `GET /admin/avatars`
- `POST /admin/avatars`
- `PUT /admin/avatars/{avatar_id}/source`
- `POST /admin/avatars/{avatar_id}/preprocess`
- `GET /admin/documents`
- `POST /admin/documents`

## Session and turn model

- `POST /sessions` now accepts `avatar_id`, `input_language`, and `output_language`.
- `POST /sessions/{session_id}/turns` still accepts uploaded audio, but `transcript_hint` is required in the v1 multilingual flow.
- Turn records persist `user_transcript`, `retrieval_query_text`, and the final target-language assistant reply.

## Environment

Copy `.env.example` to `.env` and update at minimum:

- `PLATFORM_PUBLIC_BASE_URL`
- `PLATFORM_CORS_ALLOW_ORIGINS`
- `PLATFORM_JWT_SECRET`
- `PLATFORM_ADMIN_EMAILS`
- `AVATAR_RENDER_SERVICE_BASE_URL`
- `AVATAR_RENDER_PUBLIC_BASE_URL`
- `TTS_SERVICE_BASE_URL`

For multilingual cognition and retrieval, also configure:

- `AZURE_OPENAI_ENDPOINT`
- `AZURE_OPENAI_API_KEY`
- `AZURE_OPENAI_DEPLOYMENT_NAME` or `AZURE_OPENAI_CHAT_DEPLOYMENT`
- `AZURE_OPENAI_EMBEDDINGS_DEPLOYMENT` (optional; if omitted, the service uses the built-in local embedding fallback)

Useful optional settings:

- `PLATFORM_AVATAR_CHUNK_DURATION_SECONDS=2`
- `PLATFORM_TTS_REQUEST_TIMEOUT_SECONDS=180`

## Local run sequence

1. Start the GPU avatar render service.
2. Start the TTS service.
3. Start the platform service.
4. Start the Next.js app.
5. Sign in and use the admin console to upload avatars and documents.
6. Open the conversation tab and use push-to-talk.

```bash
uvicorn avatar_service.api:app --host 0.0.0.0 --port 8000
uvicorn tts_service.api:app --host 0.0.0.0 --port 8200
uvicorn platform_service.api:app --host 0.0.0.0 --port 8100
npm run dev
```

## Current pilot scope

- input languages: English and Hindi
- output languages: English, Hindi, Punjabi, and Tamil
- single organization
- admin-curated avatar library
- login-only usage
- push-to-talk turns, not continuous duplex streaming
- chunked MP4 response playback over the existing MuseTalk render pipeline

