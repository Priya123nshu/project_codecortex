from __future__ import annotations

import argparse
import copy
import json
import os
import pickle
import shutil
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

from avatar_service.config import Settings, get_settings
from avatar_service.pipeline.chunk_audio import split_audio
from avatar_service.pipeline.jobs import (
    initialize_job,
    update_job_status,
    write_stream_info,
)
from avatar_service.schemas import RenderJobResult, model_to_dict


@contextmanager
def _musetalk_runtime_context(settings: Settings) -> Iterator[Path]:
    repo_dir = settings.require_musetalk_repo()
    repo_dir_str = str(repo_dir)
    if repo_dir_str not in sys.path:
        sys.path.insert(0, repo_dir_str)

    cache_root = settings.work_root / '.hf-cache'
    cache_root.mkdir(parents=True, exist_ok=True)
    os.environ['HF_HOME'] = str(cache_root)
    os.environ['HUGGINGFACE_HUB_CACHE'] = str(cache_root / 'hub')
    os.environ['TRANSFORMERS_CACHE'] = str(cache_root / 'transformers')

    previous_cwd = Path.cwd()
    os.chdir(repo_dir)
    try:
        yield repo_dir
    finally:
        os.chdir(previous_cwd)


def render_job(
    avatar_id: str,
    audio_path: str | Path,
    job_id: Optional[str] = None,
    fps: Optional[int] = None,
    batch_size: Optional[int] = None,
    model_version: Optional[str] = None,
    chunk_duration: int = 3,
    settings: Optional[Settings] = None,
) -> RenderJobResult:
    active_settings = settings or get_settings()
    active_settings.ensure_storage_dirs()

    resolved_model_version = model_version or active_settings.default_model_version
    resolved_fps = fps or active_settings.default_fps
    resolved_batch_size = batch_size or active_settings.default_batch_size
    resolved_job_id = job_id or uuid.uuid4().hex
    source_audio_path = Path(audio_path).expanduser().resolve()

    if not source_audio_path.exists():
        raise FileNotFoundError(f"Audio file not found: {source_audio_path}")

    avatar_dir = active_settings.avatar_root / avatar_id
    avatar_data_path = avatar_dir / 'avatar_data.pkl'
    if not avatar_data_path.exists():
        raise FileNotFoundError(
            f"Avatar cache not found for avatar_id={avatar_id}: {avatar_data_path}"
        )

    model_paths = active_settings.resolve_model_paths(resolved_model_version)

    paths = initialize_job(
        resolved_job_id,
        avatar_id=avatar_id,
        audio_path=source_audio_path,
        settings=active_settings,
    )
    update_job_status(
        resolved_job_id,
        settings=active_settings,
        status='running',
    )

    chunk_video_paths: list[str] = []
    num_chunks = 0

    try:
        chunk_paths = split_audio(
            source_audio_path,
            chunk_duration,
            paths.audio_chunks_dir,
            settings=active_settings,
        )
        num_chunks = len(chunk_paths)
        write_stream_info(paths.stream_info_path, num_chunks=num_chunks, status='running')
        update_job_status(
            resolved_job_id,
            settings=active_settings,
            chunks_total=num_chunks,
            chunks_completed=0,
        )

        with _musetalk_runtime_context(active_settings):
            import cv2
            import numpy as np
            import torch
            from transformers import WhisperModel

            from musetalk.utils.audio_processor import AudioProcessor
            from musetalk.utils.blending import get_image_blending
            from musetalk.utils.utils import datagen, load_all_model

            device = torch.device('cuda:0' if torch.cuda.is_available() else 'cpu')
            vae, unet, pe = load_all_model(
                unet_model_path=str(model_paths.unet_model_path),
                vae_type='sd-vae',
                unet_config=str(model_paths.unet_config),
                device=device,
            )
            timesteps = torch.tensor([0], device=device)
            pe = pe.half().to(device)
            vae.vae = vae.vae.half().to(device)
            unet.model = unet.model.half().to(device)

            audio_processor = AudioProcessor(feature_extractor_path=str(model_paths.whisper_dir))
            weight_dtype = unet.model.dtype
            whisper_model = WhisperModel.from_pretrained(str(model_paths.whisper_dir))
            whisper_model = whisper_model.to(device=device, dtype=weight_dtype).eval()
            whisper_model.requires_grad_(False)

            with avatar_data_path.open('rb') as handle:
                avatar = pickle.load(handle)

            frame_list_cycle = avatar['frame_list_cycle']
            coord_list_cycle = avatar['coord_list_cycle']
            latent_list_cycle = avatar['latent_list_cycle']
            mask_list_cycle = avatar['mask_list_cycle']
            mask_coords_cycle = avatar['mask_coords_cycle']

            global_frame_idx = 0
            ffmpeg_bin = active_settings.resolve_ffmpeg_bin()

            for chunk_index, chunk_path in enumerate(chunk_paths):
                chunk_started_at = time.time()
                whisper_features, lib_len = audio_processor.get_audio_feature(
                    str(chunk_path),
                    weight_dtype=weight_dtype,
                )
                whisper_chunks = audio_processor.get_whisper_chunk(
                    whisper_features,
                    device,
                    weight_dtype,
                    whisper_model,
                    lib_len,
                    fps=resolved_fps,
                    audio_padding_length_left=2,
                    audio_padding_length_right=2,
                )
                n_frames = len(whisper_chunks)
                result_frames = []
                generator = datagen(whisper_chunks, latent_list_cycle, resolved_batch_size)

                with torch.no_grad():
                    for whisper_batch, latent_batch in generator:
                        audio_feat = pe(whisper_batch.to(device))
                        latent_batch = latent_batch.to(device=device, dtype=unet.model.dtype)
                        pred = unet.model(
                            latent_batch,
                            timesteps,
                            encoder_hidden_states=audio_feat,
                        ).sample
                        pred = pred.to(device=device, dtype=vae.vae.dtype)
                        result_frames.extend(vae.decode_latents(pred))

                blended_frames = []
                for frame_offset, result_frame in enumerate(result_frames):
                    cycle_index = (global_frame_idx + frame_offset) % len(frame_list_cycle)
                    bbox = coord_list_cycle[cycle_index]
                    original = copy.deepcopy(frame_list_cycle[cycle_index])
                    x1, y1, x2, y2 = bbox
                    try:
                        resized = cv2.resize(
                            result_frame.astype(np.uint8),
                            (x2 - x1, y2 - y1),
                        )
                    except Exception:
                        continue

                    mask = mask_list_cycle[cycle_index]
                    mask_box = mask_coords_cycle[cycle_index]
                    blended = get_image_blending(original, resized, bbox, mask, mask_box)
                    blended_frames.append(blended)

                global_frame_idx += n_frames
                if not blended_frames:
                    raise RuntimeError(
                        f"No frames were rendered for chunk {chunk_index} from {chunk_path}"
                    )

                tmp_img_dir = paths.output_dir / f'tmp_{chunk_index}'
                tmp_img_dir.mkdir(parents=True, exist_ok=True)
                try:
                    for image_index, frame in enumerate(blended_frames):
                        cv2.imwrite(str(tmp_img_dir / f'{image_index:08d}.png'), frame)

                    chunk_video_path = paths.output_dir / f'chunk_{chunk_index:04d}.mp4'
                    cmd = [
                        ffmpeg_bin,
                        '-y',
                        '-v',
                        'warning',
                        '-r',
                        str(resolved_fps),
                        '-f',
                        'image2',
                        '-i',
                        str(tmp_img_dir / '%08d.png'),
                        '-i',
                        str(chunk_path),
                        '-vcodec',
                        'libx264',
                        '-vf',
                        'format=yuv420p',
                        '-crf',
                        '18',
                        '-shortest',
                        str(chunk_video_path),
                    ]
                    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
                    if result.returncode != 0:
                        raise RuntimeError(
                            f"ffmpeg failed for chunk {chunk_index}: {result.stderr.strip()}"
                        )
                finally:
                    shutil.rmtree(tmp_img_dir, ignore_errors=True)

                elapsed = time.time() - chunk_started_at
                chunk_video_paths.append(str(chunk_video_path))
                marker_path = paths.output_dir / f'chunk_{chunk_index:04d}.done'
                marker_path.write_text(
                    json.dumps(
                        {
                            'chunk_index': chunk_index,
                            'n_frames': n_frames,
                            'elapsed': elapsed,
                            'video_path': str(chunk_video_path),
                        },
                        indent=2,
                    ),
                    encoding='utf-8',
                )

                update_job_status(
                    resolved_job_id,
                    settings=active_settings,
                    status='running',
                    chunks_total=num_chunks,
                    chunks_completed=len(chunk_video_paths),
                    chunk_video_paths=chunk_video_paths,
                )

        write_stream_info(paths.stream_info_path, num_chunks=num_chunks, status='complete')
        final_status = update_job_status(
            resolved_job_id,
            settings=active_settings,
            status='completed',
            chunks_total=num_chunks,
            chunks_completed=len(chunk_video_paths),
            chunk_video_paths=chunk_video_paths,
            error=None,
        )
        return RenderJobResult(
            job_id=final_status.job_id,
            status=final_status.status,
            output_dir=final_status.output_dir,
            stream_info_path=final_status.stream_info_path,
            chunks_total=final_status.chunks_total,
            chunks_completed=final_status.chunks_completed,
            chunk_video_paths=final_status.chunk_video_paths,
            error=final_status.error,
        )
    except Exception as exc:
        write_stream_info(
            paths.stream_info_path,
            num_chunks=num_chunks,
            status='failed',
            error=str(exc),
        )
        failed_status = update_job_status(
            resolved_job_id,
            settings=active_settings,
            status='failed',
            chunks_total=num_chunks,
            chunks_completed=len(chunk_video_paths),
            chunk_video_paths=chunk_video_paths,
            error=str(exc),
        )
        raise RuntimeError(
            f"Render job failed for job_id={resolved_job_id}: {failed_status.error}"
        ) from exc


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='Render a MuseTalk avatar job locally.')
    parser.add_argument('--avatar-id', required=True, help='Preprocessed avatar identifier')
    parser.add_argument('--audio-path', required=True, help='Source audio file path')
    parser.add_argument('--job-id', default=None, help='Optional stable job identifier')
    parser.add_argument('--fps', default=None, type=int, help='Target frames per second')
    parser.add_argument('--batch-size', default=None, type=int, help='UNet batch size')
    parser.add_argument(
        '--model-version',
        default=None,
        choices=['v1', 'v15'],
        help='MuseTalk model version to use',
    )
    parser.add_argument(
        '--chunk-duration',
        default=3,
        type=int,
        help='Chunk duration in seconds for WAV splitting',
    )
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    result = render_job(
        avatar_id=args.avatar_id,
        audio_path=args.audio_path,
        job_id=args.job_id,
        fps=args.fps,
        batch_size=args.batch_size,
        model_version=args.model_version,
        chunk_duration=args.chunk_duration,
    )
    print(json.dumps(model_to_dict(result), indent=2))


if __name__ == '__main__':
    main()
