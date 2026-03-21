#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
SERVICE_DIR="$SCRIPT_DIR"
VENV_DIR="${VENV_DIR:-$PROJECT_ROOT/.venv-avatar}"
MUSE_TALK_REPO_DIR="${MUSE_TALK_REPO_DIR:-$HOME/MuseTalk}"
MODEL_ROOT="${MODEL_ROOT:-$MUSE_TALK_REPO_DIR/models}"
WORK_ROOT="${WORK_ROOT:-$SERVICE_DIR}"
AVATAR_ROOT="${AVATAR_ROOT:-$WORK_ROOT/storage/avatars}"
JOBS_ROOT="${JOBS_ROOT:-$WORK_ROOT/storage/jobs}"
OUTPUT_ROOT="${OUTPUT_ROOT:-$WORK_ROOT/storage/outputs}"
PYTHON_BIN="${PYTHON_BIN:-python3.10}"

export DEBIAN_FRONTEND=noninteractive

sudo apt-get update
sudo apt-get install -y \
  awscli \
  build-essential \
  curl \
  ffmpeg \
  git \
  git-lfs \
  libgl1 \
  libglib2.0-0 \
  python3-pip \
  python3.10 \
  python3.10-dev \
  python3.10-venv \
  unzip

git lfs install || true

if [ ! -d "$MUSE_TALK_REPO_DIR/.git" ]; then
  git clone https://github.com/TMElyralab/MuseTalk.git "$MUSE_TALK_REPO_DIR"
fi

mkdir -p "$AVATAR_ROOT" "$JOBS_ROOT" "$OUTPUT_ROOT"

if [ ! -d "$VENV_DIR" ]; then
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

# shellcheck disable=SC1090
source "$VENV_DIR/bin/activate"
python -m pip install --upgrade pip setuptools wheel
python -m pip install --extra-index-url https://download.pytorch.org/whl/cu118 -r "$SERVICE_DIR/requirements.txt"
python -m pip install --upgrade "huggingface_hub[hf_xet]>=0.30.2"
python -m pip install cython xtcocotools munkres
python -m pip install --no-deps "mmpose==1.1.0"
python -m pip install openmim
mim install mmengine "mmcv==2.0.1" "mmdet==3.1.0"

if [ ! -f "$SERVICE_DIR/.env" ]; then
  cp "$SERVICE_DIR/.env.aws.example" "$SERVICE_DIR/.env"
fi

python - <<EOF
from pathlib import Path
env_path = Path(r"$SERVICE_DIR/.env")
text = env_path.read_text(encoding="utf-8")
replacements = {
    "/home/ubuntu/MuseTalk": r"$MUSE_TALK_REPO_DIR",
    "/home/ubuntu/MuseTalk/models": r"$MODEL_ROOT",
    "/home/ubuntu/spillr-avatar/avatar_service": r"$WORK_ROOT",
    "/home/ubuntu/spillr-avatar/avatar_service/storage/avatars": r"$AVATAR_ROOT",
    "/home/ubuntu/spillr-avatar/avatar_service/storage/jobs": r"$JOBS_ROOT",
    "/home/ubuntu/spillr-avatar/avatar_service/storage/outputs": r"$OUTPUT_ROOT",
}
for src, dst in replacements.items():
    text = text.replace(src, dst)
env_path.write_text(text, encoding="utf-8")
print(f"Wrote AWS env file to {env_path}")
EOF

cat <<EOF
Bootstrap complete.

Next commands:
  source "$VENV_DIR/bin/activate"
  bash "$SERVICE_DIR/download_musetalk_models.sh"
  bash "$SERVICE_DIR/run_aws_job.sh" --video /path/to/avatar.mp4 --audio /path/to/audio.mp3 --avatar-id demo-avatar --job-id demo-job
EOF
