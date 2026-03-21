# Avatar Service

This package extracts the MuseTalk notebook flow into a standalone local service.

## What It Does
- Preprocesses one avatar video into cached MuseTalk artifacts.
- Splits one input audio file into 16kHz mono WAV chunks.
- Renders chunked MP4 outputs with `.done` markers and `stream_info.json`.
- Exposes both CLI entrypoints and a minimal FastAPI app.
- Includes environment validation and a one-command smoke test.

## Recommended Environment
- WSL2 Ubuntu for local development
- AWS EC2 GPU instance for the first cloud run
- Python 3.10
- NVIDIA GPU drivers available inside Linux
- `ffmpeg` and `ffprobe` installed
- MuseTalk cloned outside this repo
- MuseTalk model weights downloaded into the MuseTalk `models/` directory

## Setup
1. Create a Python 3.10 virtual environment.
2. Install `avatar_service/requirements.txt`.
3. Install the remaining MuseTalk dependencies:
   - `mim install mmengine`
   - `mim install "mmcv==2.0.1"`
   - `mim install "mmdet==3.1.0"`
   - `pip install --no-deps "mmpose==1.1.0"`
4. Copy `.env.example` to `.env` and update the paths.
5. Validate the runtime before rendering:

```bash
python -m avatar_service.validate_env
```

## CLI Usage
Validate the environment:

```bash
python -m avatar_service.validate_env
```

Preprocess one avatar:

```bash
python -m avatar_service.pipeline.preprocess \
  --video-path /path/to/avatar.mp4 \
  --avatar-id teacher-avatar
```

Render one audio file:

```bash
python -m avatar_service.pipeline.render \
  --avatar-id teacher-avatar \
  --audio-path /path/to/audio.mp3 \
  --job-id demo-job
```

Run a full local smoke test:

```bash
python -m avatar_service.smoke_test \
  --video-path /path/to/avatar.mp4 \
  --audio-path /path/to/audio.mp3 \
  --avatar-id teacher-avatar
```

## API Usage
Run the API locally:

```bash
uvicorn avatar_service.api:app --host 0.0.0.0 --port 8000
```

Endpoints:
- `POST /avatars/preprocess`
- `POST /jobs/render`
- `GET /jobs/{job_id}`
- `GET /health`
- `GET /environment/validate`

## AWS Quick Start
For the first cloud run, use EC2 rather than SageMaker.

Files added for AWS:
- `avatar_service/AWS_EC2_RUNBOOK.md`
- `avatar_service/bootstrap_aws_ec2.sh`
- `avatar_service/download_musetalk_models.sh`
- `avatar_service/run_aws_job.sh`
- `avatar_service/.env.aws.example`

Fast path on EC2:

```bash
bash avatar_service/bootstrap_aws_ec2.sh
bash avatar_service/download_musetalk_models.sh
bash avatar_service/run_aws_job.sh \
  --video s3://your-bucket/input/avatar.mp4 \
  --audio s3://your-bucket/input/audio.mp3 \
  --avatar-id demo-avatar \
  --job-id first-run \
  --s3-output-prefix s3://your-bucket/output
```

## Storage Layout
- `storage/avatars/<avatar_id>/avatar_data.pkl`
- `storage/avatars/<avatar_id>/avatar_info.json`
- `storage/jobs/<job_id>/audio_chunks/chunk_0000.wav`
- `storage/jobs/<job_id>/job_status.json`
- `storage/outputs/<job_id>/chunk_0000.mp4`
- `storage/outputs/<job_id>/chunk_0000.done`
- `storage/outputs/<job_id>/stream_info.json`
