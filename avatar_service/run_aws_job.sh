#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
SERVICE_DIR="$SCRIPT_DIR"
VENV_DIR="${VENV_DIR:-$PROJECT_ROOT/.venv-avatar}"
INPUT_DIR="$SERVICE_DIR/storage/inputs"
mkdir -p "$INPUT_DIR"

usage() {
  cat <<EOF
Usage:
  bash avatar_service/run_aws_job.sh --video <local-path-or-s3-uri> --audio <local-path-or-s3-uri> --avatar-id <avatar-id> [--job-id <job-id>] [--s3-output-prefix s3://bucket/path]
EOF
}

VIDEO_INPUT=""
AUDIO_INPUT=""
AVATAR_ID=""
JOB_ID=""
S3_OUTPUT_PREFIX=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --video)
      VIDEO_INPUT="$2"
      shift 2
      ;;
    --audio)
      AUDIO_INPUT="$2"
      shift 2
      ;;
    --avatar-id)
      AVATAR_ID="$2"
      shift 2
      ;;
    --job-id)
      JOB_ID="$2"
      shift 2
      ;;
    --s3-output-prefix)
      S3_OUTPUT_PREFIX="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 1
      ;;
  esac
done

if [[ -z "$VIDEO_INPUT" || -z "$AUDIO_INPUT" || -z "$AVATAR_ID" ]]; then
  usage
  exit 1
fi

if [[ -z "$JOB_ID" ]]; then
  JOB_ID="job-$(date +%Y%m%d-%H%M%S)"
fi

if [ ! -d "$VENV_DIR" ]; then
  echo "Virtual environment not found at $VENV_DIR. Run bootstrap_aws_ec2.sh first." >&2
  exit 1
fi

resolve_input() {
  local source_path="$1"
  local target_name="$2"
  local target_path="$INPUT_DIR/$target_name"

  if [[ "$source_path" == s3://* ]]; then
    if ! command -v aws >/dev/null 2>&1; then
      echo "aws CLI is required for s3:// inputs." >&2
      exit 1
    fi
    aws s3 cp "$source_path" "$target_path"
    echo "$target_path"
  else
    echo "$source_path"
  fi
}

LOCAL_VIDEO="$(resolve_input "$VIDEO_INPUT" "$(basename "$VIDEO_INPUT")")"
LOCAL_AUDIO="$(resolve_input "$AUDIO_INPUT" "$(basename "$AUDIO_INPUT")")"

# shellcheck disable=SC1090
source "$VENV_DIR/bin/activate"
export PYTHONPATH="$PROJECT_ROOT:${PYTHONPATH:-}"

python -m avatar_service.validate_env
python -m avatar_service.pipeline.preprocess --video-path "$LOCAL_VIDEO" --avatar-id "$AVATAR_ID"
python -m avatar_service.pipeline.render --avatar-id "$AVATAR_ID" --audio-path "$LOCAL_AUDIO" --job-id "$JOB_ID"

OUTPUT_DIR="$SERVICE_DIR/storage/outputs/$JOB_ID"
STATUS_FILE="$SERVICE_DIR/storage/jobs/$JOB_ID/job_status.json"
STREAM_INFO_FILE="$OUTPUT_DIR/stream_info.json"

if [[ -n "$S3_OUTPUT_PREFIX" ]]; then
  if ! command -v aws >/dev/null 2>&1; then
    echo "aws CLI is required for S3 output upload." >&2
    exit 1
  fi
  aws s3 sync "$OUTPUT_DIR" "$S3_OUTPUT_PREFIX/$JOB_ID/"
  echo "Uploaded outputs to $S3_OUTPUT_PREFIX/$JOB_ID/"
fi

cat <<EOF
Run complete.

Avatar cache:
  $SERVICE_DIR/storage/avatars/$AVATAR_ID

Job status:
  $STATUS_FILE

Stream info:
  $STREAM_INFO_FILE

Chunk outputs:
  $OUTPUT_DIR
EOF
