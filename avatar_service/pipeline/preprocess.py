from __future__ import annotations

import argparse
import glob
import json
import os
import pickle
import shutil
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

from avatar_service.config import Settings, get_settings
from avatar_service.schemas import AvatarPreprocessResult, model_to_dict


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


def preprocess_avatar(
    video_path: str | Path,
    avatar_id: str,
    model_version: Optional[str] = None,
    settings: Optional[Settings] = None,
) -> AvatarPreprocessResult:
    active_settings = settings or get_settings()
    active_settings.ensure_storage_dirs()
    source_video_path = Path(video_path).expanduser().resolve()

    if not source_video_path.exists():
        raise FileNotFoundError(f"Avatar source video not found: {source_video_path}")

    resolved_model_version = model_version or active_settings.default_model_version
    model_paths = active_settings.resolve_model_paths(resolved_model_version)

    with _musetalk_runtime_context(active_settings):
        import cv2
        import torch
        from tqdm import tqdm

        from musetalk.utils.blending import get_image_prepare_material
        from musetalk.utils.face_parsing import FaceParsing
        from musetalk.utils.preprocessing import get_landmark_and_bbox
        from musetalk.utils.utils import load_all_model

        avatar_dir = active_settings.avatar_root / avatar_id
        full_imgs_dir = avatar_dir / 'full_imgs'

        if avatar_dir.exists():
            shutil.rmtree(avatar_dir)
        full_imgs_dir.mkdir(parents=True, exist_ok=True)

        device = torch.device('cuda:0' if torch.cuda.is_available() else 'cpu')

        vae, _unet, _pe = load_all_model(
            unet_model_path=str(model_paths.unet_model_path),
            vae_type='sd-vae',
            unet_config=str(model_paths.unet_config),
            device=device,
        )
        vae.vae = vae.vae.half().to(device)

        face_parser = (
            FaceParsing(left_cheek_width=90, right_cheek_width=90)
            if resolved_model_version == 'v15'
            else FaceParsing()
        )

        capture = cv2.VideoCapture(str(source_video_path))
        if not capture.isOpened():
            raise RuntimeError(f"Could not open avatar video: {source_video_path}")

        frame_count = 0
        while True:
            success, frame = capture.read()
            if not success:
                break
            cv2.imwrite(str(full_imgs_dir / f'{frame_count:08d}.png'), frame)
            frame_count += 1
        capture.release()

        if frame_count == 0:
            raise RuntimeError(f"No frames were extracted from avatar video: {source_video_path}")

        image_paths = sorted(glob.glob(str(full_imgs_dir / '*.png')))
        coord_list, frame_list = get_landmark_and_bbox(image_paths, upperbondrange=0)
        if not frame_list:
            raise RuntimeError('MuseTalk did not detect any frames for preprocessing')

        input_latent_list = []
        coord_placeholder = (0.0, 0.0, 0.0, 0.0)

        for index, (bbox, frame) in enumerate(zip(coord_list, frame_list)):
            if bbox == coord_placeholder:
                continue
            x1, y1, x2, y2 = bbox
            if resolved_model_version == 'v15':
                y2 = min(y2 + 10, frame.shape[0])
                coord_list[index] = [x1, y1, x2, y2]

            crop = cv2.resize(
                frame[y1:y2, x1:x2],
                (256, 256),
                interpolation=cv2.INTER_LANCZOS4,
            )
            input_latent_list.append(vae.get_latents_for_unet(crop))

        if not input_latent_list:
            raise RuntimeError('MuseTalk preprocessing did not produce any face latents')

        frame_list_cycle = frame_list + frame_list[::-1]
        coord_list_cycle = coord_list + coord_list[::-1]
        latent_list_cycle = input_latent_list + input_latent_list[::-1]

        mask_list_cycle = []
        mask_coords_cycle = []
        blend_mode = 'jaw' if resolved_model_version == 'v15' else 'raw'
        for index, frame in enumerate(tqdm(frame_list_cycle, desc='Building masks')):
            x1, y1, x2, y2 = coord_list_cycle[index]
            mask, crop_box = get_image_prepare_material(
                frame,
                [x1, y1, x2, y2],
                fp=face_parser,
                mode=blend_mode,
            )
            mask_list_cycle.append(mask)
            mask_coords_cycle.append(crop_box)

    avatar_data_path = avatar_dir / 'avatar_data.pkl'
    avatar_info_path = avatar_dir / 'avatar_info.json'
    with avatar_data_path.open('wb') as handle:
        pickle.dump(
            {
                'frame_list_cycle': frame_list_cycle,
                'coord_list_cycle': coord_list_cycle,
                'latent_list_cycle': latent_list_cycle,
                'mask_list_cycle': mask_list_cycle,
                'mask_coords_cycle': mask_coords_cycle,
            },
            handle,
            protocol=pickle.HIGHEST_PROTOCOL,
        )

    avatar_info = {
        'avatar_id': avatar_id,
        'source_video_path': str(source_video_path),
        'num_frames': frame_count,
        'num_cycled_frames': len(frame_list_cycle),
        'model_version': resolved_model_version,
    }
    avatar_info_path.write_text(json.dumps(avatar_info, indent=2), encoding='utf-8')

    return AvatarPreprocessResult(
        avatar_id=avatar_id,
        status='completed',
        avatar_data_path=str(avatar_data_path),
        avatar_info_path=str(avatar_info_path),
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='Preprocess a MuseTalk avatar locally.')
    parser.add_argument('--video-path', required=True, help='Path to the source avatar video')
    parser.add_argument('--avatar-id', required=True, help='Logical avatar identifier')
    parser.add_argument(
        '--model-version',
        default=None,
        choices=['v1', 'v15'],
        help='MuseTalk model version to use',
    )
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    result = preprocess_avatar(
        video_path=args.video_path,
        avatar_id=args.avatar_id,
        model_version=args.model_version,
    )
    print(json.dumps(model_to_dict(result), indent=2))


if __name__ == '__main__':
    main()
