from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Tuple

from avatar_service.schemas import EnvironmentCheck, EnvironmentValidationResult


class ConfigurationError(RuntimeError):
    """Raised when the avatar service environment is misconfigured."""


@dataclass(frozen=True)
class ModelPaths:
    model_root: Path
    model_version: str
    model_dir: Path
    unet_model_path: Path
    unet_config: Path
    whisper_dir: Path


@dataclass(frozen=True)
class Settings:
    muse_talk_repo_dir: Path
    model_root: Path
    work_root: Path
    avatar_root: Path
    jobs_root: Path
    output_root: Path
    default_model_version: str
    default_fps: int
    default_batch_size: int
    ffmpeg_bin: str
    api_host: str
    api_port: int
    cors_allow_origins: Tuple[str, ...]

    def ensure_storage_dirs(self) -> None:
        for path in (self.work_root, self.avatar_root, self.jobs_root, self.output_root):
            path.mkdir(parents=True, exist_ok=True)

    def require_musetalk_repo(self) -> Path:
        repo_dir = self.muse_talk_repo_dir.expanduser().resolve()
        if not repo_dir.exists():
            raise ConfigurationError(f"MuseTalk repo not found: {repo_dir}")
        return repo_dir

    def resolve_model_paths(self, model_version: str | None = None) -> ModelPaths:
        resolved_version = (model_version or self.default_model_version).strip().lower()
        model_root = self.model_root.expanduser().resolve()

        model_dir_candidates = []
        if resolved_version == "v15":
            model_dir_candidates = [model_root / "musetalkV15"]
        else:
            model_dir_candidates = [
                model_root / "musetalkV1",
                model_root / "musetalk",
                model_root / "musetalkv1",
            ]

        model_dir = _first_existing_path(model_dir_candidates) or model_dir_candidates[0]
        unet_model_path = model_dir / "unet.pth"
        unet_config = _first_existing_path(
            [model_dir / "musetalk.json", model_dir / "config.json"]
        ) or (model_dir / "musetalk.json")
        whisper_dir = model_root / "whisper"

        return ModelPaths(
            model_root=model_root,
            model_version=resolved_version,
            model_dir=model_dir,
            unet_model_path=unet_model_path,
            unet_config=unet_config,
            whisper_dir=whisper_dir,
        )

    def resolve_ffmpeg_bin(self) -> str:
        return _resolve_binary(self.ffmpeg_bin, "ffmpeg")

    def resolve_ffprobe_bin(self) -> str:
        return _resolve_binary("ffprobe", "ffprobe")


def _service_root() -> Path:
    return Path(__file__).resolve().parent


def _project_root() -> Path:
    return _service_root().parent


def _strip_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _resolve_binary(value: str, label: str) -> str:
    located = shutil.which(value)
    if located:
        return located

    explicit_path = Path(value).expanduser()
    if explicit_path.exists():
        return str(explicit_path)

    raise ConfigurationError(
        f"{label} binary not found. Set it to a valid executable path. Current value: {value}"
    )


def _load_env_file() -> dict[str, str]:
    env: dict[str, str] = {}
    candidate_paths = [
        _service_root() / ".env",
        Path.cwd() / ".env",
        _project_root() / ".env",
    ]

    env_path = _first_existing_path(candidate_paths)
    if not env_path:
        return env

    for raw_line in env_path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key.strip()] = _strip_quotes(value)
    return env


def _env_value(key: str, env_map: dict[str, str], default: str | None = None) -> str:
    value = os.getenv(key)
    if value is not None and value != "":
        return value
    if key in env_map and env_map[key] != "":
        return env_map[key]
    if default is None:
        raise ConfigurationError(f"Missing required configuration value: {key}")
    return default


def _csv_from_env(key: str, env_map: dict[str, str], default: str = "") -> Tuple[str, ...]:
    raw_value = _env_value(key, env_map, default=default)
    values = [item.strip() for item in raw_value.split(",") if item.strip()]
    return tuple(values)


def _first_existing_path(paths: Iterable[Path]) -> Path | None:
    for path in paths:
        if path.exists():
            return path
    return None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    env_map = _load_env_file()
    service_root = _service_root()
    project_root = _project_root()

    default_repo_dir = project_root / "MuseTalk"
    muse_talk_repo_dir = Path(
        _env_value("MUSE_TALK_REPO_DIR", env_map, default=str(default_repo_dir))
    ).expanduser()
    model_root = Path(
        _env_value("MODEL_ROOT", env_map, default=str(muse_talk_repo_dir / "models"))
    ).expanduser()
    work_root = Path(
        _env_value("WORK_ROOT", env_map, default=str(service_root))
    ).expanduser()
    avatar_root = Path(
        _env_value("AVATAR_ROOT", env_map, default=str(work_root / "storage" / "avatars"))
    ).expanduser()
    jobs_root = Path(
        _env_value("JOBS_ROOT", env_map, default=str(work_root / "storage" / "jobs"))
    ).expanduser()
    output_root = Path(
        _env_value("OUTPUT_ROOT", env_map, default=str(work_root / "storage" / "outputs"))
    ).expanduser()

    settings = Settings(
        muse_talk_repo_dir=muse_talk_repo_dir,
        model_root=model_root,
        work_root=work_root,
        avatar_root=avatar_root,
        jobs_root=jobs_root,
        output_root=output_root,
        default_model_version=_env_value("DEFAULT_MODEL_VERSION", env_map, default="v15"),
        default_fps=int(_env_value("DEFAULT_FPS", env_map, default="25")),
        default_batch_size=int(_env_value("DEFAULT_BATCH_SIZE", env_map, default="8")),
        ffmpeg_bin=_env_value("FFMPEG_BIN", env_map, default="ffmpeg"),
        api_host=_env_value("API_HOST", env_map, default="0.0.0.0"),
        api_port=int(_env_value("API_PORT", env_map, default="8000")),
        cors_allow_origins=_csv_from_env("CORS_ALLOW_ORIGINS", env_map, default="*"),
    )
    settings.ensure_storage_dirs()
    return settings


def _build_check(name: str, status: str, detail: str) -> EnvironmentCheck:
    return EnvironmentCheck(name=name, status=status, detail=detail)


def validate_environment() -> EnvironmentValidationResult:
    checks: list[EnvironmentCheck] = []
    settings = get_settings()

    python_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    python_status = "ok" if sys.version_info[:2] == (3, 10) else "warning"
    checks.append(
        _build_check(
            "python_version",
            python_status,
            f"Python {python_version} detected.",
        )
    )

    for binary_name in ("ffmpeg", "ffprobe"):
        located = shutil.which(binary_name)
        if located:
            checks.append(_build_check(binary_name, "ok", f"{binary_name} found at {located}"))
        else:
            checks.append(_build_check(binary_name, "error", f"{binary_name} not found in PATH"))

    try:
        repo_dir = settings.require_musetalk_repo()
        checks.append(_build_check("musetalk_repo", "ok", f"MuseTalk repo found at {repo_dir}"))
    except ConfigurationError as exc:
        checks.append(_build_check("musetalk_repo", "error", str(exc)))

    model_root = settings.model_root.expanduser().resolve()
    if model_root.exists():
        checks.append(_build_check("model_root", "ok", f"Model root verified at {model_root}"))
    else:
        checks.append(_build_check("model_root", "error", f"Model root not found: {model_root}"))

    model_paths = settings.resolve_model_paths(settings.default_model_version)
    if model_paths.unet_model_path.exists():
        checks.append(
            _build_check(
                "unet_model",
                "ok",
                f"UNet weights found at {model_paths.unet_model_path}",
            )
        )
    else:
        checks.append(
            _build_check(
                "unet_model",
                "error",
                f"UNet weights missing at {model_paths.unet_model_path}",
            )
        )

    if model_paths.whisper_dir.exists():
        checks.append(
            _build_check(
                "whisper_model",
                "ok",
                f"Whisper model directory found at {model_paths.whisper_dir}",
            )
        )
    else:
        checks.append(
            _build_check(
                "whisper_model",
                "error",
                f"Whisper model directory missing at {model_paths.whisper_dir}",
            )
        )

    for name, path in (
        ("avatar_root", settings.avatar_root),
        ("jobs_root", settings.jobs_root),
        ("output_root", settings.output_root),
    ):
        path.mkdir(parents=True, exist_ok=True)
        checks.append(_build_check(name, "ok", f"Storage directory ready at {path.resolve()}"))

    overall_status = "ok"
    if any(check.status == "error" for check in checks):
        overall_status = "error"
    elif any(check.status == "warning" for check in checks):
        overall_status = "warning"

    return EnvironmentValidationResult(overall_status=overall_status, checks=checks)
