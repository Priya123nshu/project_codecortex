#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
SERVICE_DIR="$SCRIPT_DIR"
VENV_DIR="${VENV_DIR:-$PROJECT_ROOT/.venv-avatar}"
MUSE_TALK_REPO_DIR="${MUSE_TALK_REPO_DIR:-$HOME/MuseTalk}"
MODEL_ROOT="${MODEL_ROOT:-$MUSE_TALK_REPO_DIR/models}"
HF_CACHE_DIR="${HF_CACHE_DIR:-$SERVICE_DIR/.hf-cache}"
HF_ENDPOINT="${HF_ENDPOINT:-https://huggingface.co}"
HF_TOKEN="${HF_TOKEN:-}"

if [ ! -d "$VENV_DIR" ]; then
  echo "Virtual environment not found at $VENV_DIR. Run bootstrap_aws_ec2.sh first." >&2
  exit 1
fi

# shellcheck disable=SC1090
source "$VENV_DIR/bin/activate"

mkdir -p "$MODEL_ROOT" "$HF_CACHE_DIR/hub" "$HF_CACHE_DIR/transformers"
export HF_HOME="$HF_CACHE_DIR"
export HUGGINGFACE_HUB_CACHE="$HF_CACHE_DIR/hub"
export TRANSFORMERS_CACHE="$HF_CACHE_DIR/transformers"
export HF_ENDPOINT="$HF_ENDPOINT"

HF_ARGS=()
if [ -n "$HF_TOKEN" ]; then
  HF_ARGS+=(--token "$HF_TOKEN")
fi

download_repo() {
  local repo_id="$1"
  local local_dir="$2"
  shift 2
  mkdir -p "$local_dir"
  echo "Downloading $repo_id -> $local_dir"
  huggingface-cli download "$repo_id" --local-dir "$local_dir" --max-workers 2 "${HF_ARGS[@]}" "$@"
}

download_repo TMElyralab/MuseTalk "$MODEL_ROOT" --include musetalkV15/unet.pth musetalkV15/musetalk.json
download_repo stabilityai/sd-vae-ft-mse "$MODEL_ROOT/sd-vae" --include config.json diffusion_pytorch_model.bin
download_repo openai/whisper-tiny "$MODEL_ROOT/whisper" --include config.json pytorch_model.bin preprocessor_config.json
download_repo yzd-v/DWPose "$MODEL_ROOT/dwpose" --include dw-ll_ucoco_384.pth
download_repo ManyOtherFunctions/face-parse-bisent "$MODEL_ROOT/face-parse-bisent" --include 79999_iter.pth resnet18-5c106cde.pth

for required_path in \
  "$MODEL_ROOT/musetalkV15/unet.pth" \
  "$MODEL_ROOT/musetalkV15/musetalk.json" \
  "$MODEL_ROOT/sd-vae/config.json" \
  "$MODEL_ROOT/sd-vae/diffusion_pytorch_model.bin" \
  "$MODEL_ROOT/whisper/config.json" \
  "$MODEL_ROOT/whisper/pytorch_model.bin" \
  "$MODEL_ROOT/dwpose/dw-ll_ucoco_384.pth" \
  "$MODEL_ROOT/face-parse-bisent/79999_iter.pth" \
  "$MODEL_ROOT/face-parse-bisent/resnet18-5c106cde.pth"; do
  if [ ! -f "$required_path" ]; then
    echo "Missing required file: $required_path" >&2
    exit 1
  fi
done

echo "MuseTalk v15 model download complete."
