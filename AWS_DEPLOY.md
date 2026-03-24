# AWS Deploy Guide

This is the fastest demo setup for this repo on AWS:

- Vercel hosts the frontend.
- One AWS EC2 machine runs all three backend services:
  - `avatar_service` on `8000`
  - `tts_service` on `8200`
  - `platform_service` on `8100`

This single-machine path is the easiest because:

- `platform_service` can call `tts_service` on `127.0.0.1:8200`
- `platform_service` can call `avatar_service` on `127.0.0.1:8000`
- you only expose `8100` publicly for the web app
- you avoid cross-instance networking during the demo

## 1. Create the EC2 machine

Use a GPU instance if you want the lowest-risk demo path, because `avatar_service` depends on the MuseTalk render pipeline.

Recommended simple setup:

- Ubuntu 22.04
- NVIDIA GPU instance
- security group:
  - allow `22` from your IP
  - allow `8100` from `0.0.0.0/0` or your frontend IP range
  - keep `8000` and `8200` private if all services run on the same machine

## 2. SSH in and install base packages

```bash
sudo apt update
sudo apt install -y git ffmpeg python3 python3-venv python3-pip nginx
```

If your GPU AMI does not already have CUDA/NVIDIA drivers ready, install them first before trying to run `avatar_service`.

## 3. Clone the repo

```bash
git clone <your-repo-url>
cd project_codecortex
```

## 4. Frontend on Vercel

Vercel should use the repo root.

Set these Vercel environment variables:

```env
NEXT_PUBLIC_PLATFORM_API_BASE_URL=http://<AWS_PUBLIC_IP>:8100
NEXTAUTH_URL=https://<your-vercel-domain>
NEXTAUTH_SECRET=<strong-random-secret>
PLATFORM_API_JWT_SECRET=<same-strong-random-secret>
PLATFORM_ADMIN_EMAILS=<your-email>
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
MICROSOFT_CLIENT_ID=
MICROSOFT_CLIENT_SECRET=
MICROSOFT_TENANT_ID=
```

Important:

- `NEXTAUTH_SECRET` and `PLATFORM_API_JWT_SECRET` should be the same value.
- After you push the repo, Vercel will rebuild automatically.

## 5. Create the Python environments

### Platform service

```bash
python3 -m venv .venv-platform
source .venv-platform/bin/activate
pip install --upgrade pip
pip install -r platform_service/requirements.txt
```

### TTS service

```bash
deactivate || true
python3 -m venv .venv-tts
source .venv-tts/bin/activate
pip install --upgrade pip
pip install -r tts_service/requirements.txt
```

### Avatar service

Use the environment you already use for MuseTalk on AWS. If you already had a working GPU runtime before, reuse that exact environment because it is the most sensitive part of the stack.

## 6. Configure platform service

Create `platform_service/.env`:

```env
PLATFORM_PUBLIC_BASE_URL=http://<AWS_PUBLIC_IP>:8100
PLATFORM_CORS_ALLOW_ORIGINS=http://localhost:3000,https://<your-vercel-domain>
PLATFORM_AUTH_REQUIRED=true
PLATFORM_JWT_SECRET=<same-value-as-PLATFORM_API_JWT_SECRET>
PLATFORM_DEFAULT_ORG_ID=pilot-org
PLATFORM_DEFAULT_ORG_NAME=Pilot Organization
PLATFORM_ADMIN_EMAILS=<your-email>
AVATAR_RENDER_SERVICE_BASE_URL=http://127.0.0.1:8000
AVATAR_RENDER_PUBLIC_BASE_URL=http://<AWS_PUBLIC_IP>:8000
TTS_SERVICE_BASE_URL=http://127.0.0.1:8200
PLATFORM_AVATAR_CHUNK_DURATION_SECONDS=2
PLATFORM_TTS_REQUEST_TIMEOUT_SECONDS=180
AZURE_OPENAI_ENDPOINT=https://secureme-openai.openai.azure.com/
AZURE_OPENAI_API_KEY=<your-key>
AZURE_OPENAI_DEPLOYMENT_NAME=gpt-4o-mini
AZURE_OPENAI_API_VERSION=2025-01-01-preview
```

Notes:

- The code now accepts `AZURE_OPENAI_DEPLOYMENT_NAME` directly.
- `AZURE_OPENAI_EMBEDDINGS_DEPLOYMENT` is optional. If you do not set it, the platform uses the built-in local embedding fallback.
- If you later want better retrieval quality from Azure embeddings, deploy an embeddings model separately and set `AZURE_OPENAI_EMBEDDINGS_DEPLOYMENT=text-embedding-3-small` or your chosen deployment name.

## 7. Configure TTS service

Create `tts_service/.env`:

```env
TTS_PUBLIC_BASE_URL=http://<AWS_PUBLIC_IP>:8200
TTS_GENERATED_ROOT=/home/ubuntu/project_codecortex/tts_service/storage/generated
TTS_MODELS_ROOT=/home/ubuntu/project_codecortex/tts_service/models
TTS_RUNTIME_ROOT=/home/ubuntu/project_codecortex/tts_service/runtime
TTS_MODEL_DOWNLOADS_DIR=/home/ubuntu/Downloads
TTS_PYTHON_BIN=/home/ubuntu/py38tts/bin/python
TTS_REFERENCE_AUDIO=/home/ubuntu/reference.wav
TTS_GENDER=female
TTS_EDGE_EN_VOICE=en-US-JennyNeural
TTS_EDGE_HI_VOICE=hi-IN-SwaraNeural
TTS_FFMPEG_BIN=ffmpeg
```

Notes:

- `TTS_PYTHON_BIN` should point to the Python environment that can run the friend TTS runtime.
- Put the downloaded friend model zip files in `TTS_MODEL_DOWNLOADS_DIR`.
- Edge TTS needs outbound internet access.

## 8. Put the model files in place

For the Punjabi/Tamil friend runtime, make sure these assets are available on the AWS machine:

- the downloaded model zip files from the friend project
- the `tts-inference.tar` bundle included in those model folders
- a usable Python runtime for that TTS code
- an optional reference WAV if you want custom voice adaptation

For `avatar_service`, make sure your MuseTalk model assets are present exactly the way your existing GPU setup expects them.

## 9. Start services manually the first time

### Start avatar service

Use the environment that already works for MuseTalk. Example:

```bash
cd /home/ubuntu/project_codecortex
<your-avatar-python> -m uvicorn avatar_service.api:app --host 0.0.0.0 --port 8000
```

### Start TTS service

```bash
cd /home/ubuntu/project_codecortex
source .venv-tts/bin/activate
uvicorn tts_service.api:app --host 0.0.0.0 --port 8200
```

### Start platform service

Open a new shell:

```bash
cd /home/ubuntu/project_codecortex
source .venv-platform/bin/activate
uvicorn platform_service.api:app --host 0.0.0.0 --port 8100
```

## 10. Verify the services

From the AWS machine:

```bash
curl http://127.0.0.1:8200/health
curl http://127.0.0.1:8100/health
curl http://127.0.0.1:8000/
```

From your laptop:

```bash
curl http://<AWS_PUBLIC_IP>:8100/health
```

## 11. Point Vercel to AWS

Once `8100` is reachable, make sure this is set in Vercel:

```env
NEXT_PUBLIC_PLATFORM_API_BASE_URL=http://<AWS_PUBLIC_IP>:8100
```

Redeploy Vercel if needed.

## 12. Demo test order

Test in this order:

1. Open the Vercel frontend.
2. Sign in.
3. Upload or confirm at least one ready avatar.
4. Upload at least one grounding document.
5. Choose an avatar.
6. Choose input language and output language.
7. Record a short turn.
8. Confirm the transcript if needed.
9. Watch the SSE events, reply text, and chunked MP4 playback.

## 13. Productionizing after the demo

After the demo, you can split this into:

- GPU EC2 for `avatar_service`
- CPU EC2 for `platform_service` + `tts_service`
- Nginx reverse proxy in front of `platform_service`
- systemd services for automatic restart

But for the hackathon demo, one machine is the easiest and safest path.
