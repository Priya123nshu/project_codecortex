from __future__ import annotations

import argparse
import json
import uuid

from avatar_service.config import validate_environment
from avatar_service.pipeline.preprocess import preprocess_avatar
from avatar_service.pipeline.render import render_job
from avatar_service.schemas import SmokeTestResult, model_to_dict


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a local preprocess + render smoke test.")
    parser.add_argument("--video-path", required=True, help="Path to the avatar video")
    parser.add_argument("--audio-path", required=True, help="Path to the source audio")
    parser.add_argument("--avatar-id", default="smoke-avatar", help="Avatar identifier")
    parser.add_argument("--job-id", default=None, help="Optional stable job identifier")
    parser.add_argument("--model-version", default=None, choices=["v1", "v15"])
    parser.add_argument("--fps", default=None, type=int)
    parser.add_argument("--batch-size", default=None, type=int)
    parser.add_argument("--chunk-duration", default=3, type=int)
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    environment = validate_environment()
    if environment.overall_status == "error":
        print(json.dumps(model_to_dict(environment), indent=2))
        raise SystemExit(1)

    preprocess_result = preprocess_avatar(
        video_path=args.video_path,
        avatar_id=args.avatar_id,
        model_version=args.model_version,
    )
    render_result = render_job(
        avatar_id=args.avatar_id,
        audio_path=args.audio_path,
        job_id=args.job_id or f"smoke-{uuid.uuid4().hex[:8]}",
        fps=args.fps,
        batch_size=args.batch_size,
        model_version=args.model_version,
        chunk_duration=args.chunk_duration,
    )

    result = SmokeTestResult(
        environment=environment,
        preprocess=preprocess_result,
        render=render_result,
    )
    print(json.dumps(model_to_dict(result), indent=2))


if __name__ == "__main__":
    main()
