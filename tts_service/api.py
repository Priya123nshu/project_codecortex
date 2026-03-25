from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from tts_service.indic_parler import (
    DESCRIPTION_TEMPLATE_VERSION,
    DEFAULT_DESCRIPTION_TEMPLATES,
    IndicParlerError,
    IndicParlerRuntime,
    IndicParlerSettings,
)


ProviderValue = Literal["edge-tts", "friend-local", "indic-parler"]
LanguageValue = Literal["en", "hi", "pa", "ta"]
ALL_PROVIDERS: tuple[ProviderValue, ...] = ("edge-tts", "friend-local", "indic-parler")

LANGUAGE_METADATA: dict[LanguageValue, dict[str, str]] = {
    "en": {
        "label": "English",
        "voice_env": "TTS_EDGE_EN_VOICE",
        "voice_default": "en-US-JennyNeural",
    },
    "hi": {
        "label": "Hindi",
        "voice_env": "TTS_EDGE_HI_VOICE",
        "voice_default": "hi-IN-SwaraNeural",
    },
    "pa": {
        "label": "Punjabi",
        "zip_name": "tts_with_spk_adapt_punjabi_Version_1.zip",
        "checkpoint": "punjabi.pt",
        "folder": "Punjabi",
        "lang_arg": "punjabi",
    },
    "ta": {
        "label": "Tamil",
        "zip_name": "tts_with_spk_adapt_tamil_Version_1.zip",
        "checkpoint": "tamil.pt",
        "folder": "Tamil",
        "lang_arg": "tamil",
    },
}

DEFAULT_PROVIDER_CHAINS: dict[LanguageValue, tuple[ProviderValue, ...]] = {
    "en": ("indic-parler", "edge-tts"),
    "hi": ("indic-parler", "edge-tts"),
    "pa": ("friend-local", "indic-parler"),
    "ta": ("indic-parler", "friend-local"),
}


class TtsServiceError(RuntimeError):
    pass


@dataclass(frozen=True)
class Settings:
    service_root: Path
    public_base_url: str
    generated_root: Path
    models_root: Path
    runtime_root: Path
    downloads_root: Path
    tts_python_bin: str | None
    tts_reference_audio: str | None
    tts_gender: str
    ffmpeg_bin: str
    huggingface_hub_token: str | None
    indic_parler_model_id: str
    indic_parler_device: str
    indic_parler_enabled_languages: tuple[str, ...]
    indic_parler_cache_root: Path
    indic_parler_description_templates: dict[str, str]
    provider_chains: dict[LanguageValue, tuple[ProviderValue, ...]]

    def ensure_dirs(self) -> None:
        for path in (self.generated_root, self.models_root, self.runtime_root, self.indic_parler_cache_root):
            path.mkdir(parents=True, exist_ok=True)


class SynthesizeRequest(BaseModel):
    text: str = Field(min_length=1, max_length=1200)
    language: LanguageValue
    request_id: str | None = None


class SynthesizeResponse(BaseModel):
    request_id: str
    language: LanguageValue
    provider: ProviderValue
    audio_url: str
    audio_path: str
    mime_type: str = "audio/wav"
    cache_hit: bool = False
    warnings: list[str] = Field(default_factory=list)
    cache_key_version: str | None = None


class LanguageDescriptor(BaseModel):
    id: LanguageValue
    label: str
    provider: ProviderValue
    provider_chain: list[ProviderValue] = Field(default_factory=list)


class LanguagesResponse(BaseModel):
    languages: list[LanguageDescriptor]


class HealthResponse(BaseModel):
    status: Literal["ok"]
    service: str
    languages: list[str]
    provider_chains: dict[str, list[ProviderValue]] = Field(default_factory=dict)
    fallback_only_languages: list[str] = Field(default_factory=list)
    indic_parler: dict[str, Any] = Field(default_factory=dict)


class WarmupResponse(BaseModel):
    status: Literal["ok"]
    provider: ProviderValue
    ready: bool
    detail: str | None = None
    fallback_only_languages: list[str] = Field(default_factory=list)
    indic_parler: dict[str, Any] = Field(default_factory=dict)


_SETTINGS: Settings | None = None
_INDIC_PARLER_RUNTIME: IndicParlerRuntime | None = None


def _strip_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _load_env_file() -> dict[str, str]:
    env: dict[str, str] = {}
    service_root = Path(__file__).resolve().parent
    candidates = [service_root / ".env", service_root.parent / ".env", Path.cwd() / ".env"]
    env_path = next((path for path in candidates if path.exists()), None)
    if not env_path:
        return env

    for raw_line in env_path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key.strip()] = _strip_quotes(value)
    return env


def _env(key: str, env_map: dict[str, str], default: str | None = None) -> str:
    value = os.getenv(key)
    if value:
        return value
    if key in env_map and env_map[key]:
        return env_map[key]
    if default is None:
        raise TtsServiceError(f"Missing required configuration value: {key}")
    return default


def _csv(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    return tuple(item.strip() for item in value.split(",") if item.strip())


def _json_dict(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        payload = json.loads(value)
    except json.JSONDecodeError as exc:
        raise TtsServiceError(f"Invalid JSON configuration: {exc}") from exc
    if not isinstance(payload, dict):
        raise TtsServiceError("Expected a JSON object for TTS configuration.")
    return payload


def _parse_provider_chains(value: str | None) -> dict[LanguageValue, tuple[ProviderValue, ...]]:
    chains: dict[LanguageValue, tuple[ProviderValue, ...]] = dict(DEFAULT_PROVIDER_CHAINS)
    raw_overrides = _json_dict(value)
    if not raw_overrides:
        return chains

    for language, raw_chain in raw_overrides.items():
        if language not in LANGUAGE_METADATA or not isinstance(raw_chain, list):
            continue
        normalized = [str(item).strip() for item in raw_chain if str(item).strip() in ALL_PROVIDERS]
        if normalized:
            chains[cast(LanguageValue, language)] = tuple(cast(ProviderValue, item) for item in normalized)
    return chains


def _parse_description_templates(value: str | None) -> dict[str, str]:
    templates = dict(DEFAULT_DESCRIPTION_TEMPLATES)
    overrides = _json_dict(value)
    for language, template in overrides.items():
        if language in LANGUAGE_METADATA and isinstance(template, str) and template.strip():
            templates[language] = collapse_whitespace(template)
    return templates


def get_settings() -> Settings:
    global _SETTINGS
    if _SETTINGS is not None:
        return _SETTINGS

    env_map = _load_env_file()
    service_root = Path(__file__).resolve().parent
    models_root = Path(_env("TTS_MODELS_ROOT", env_map, default=str(service_root / "models")))
    settings = Settings(
        service_root=service_root,
        public_base_url=_env("TTS_PUBLIC_BASE_URL", env_map, default="http://127.0.0.1:8200").rstrip("/"),
        generated_root=Path(_env("TTS_GENERATED_ROOT", env_map, default=str(service_root / "storage" / "generated"))),
        models_root=models_root,
        runtime_root=Path(_env("TTS_RUNTIME_ROOT", env_map, default=str(service_root / "runtime"))),
        downloads_root=Path(_env("TTS_MODEL_DOWNLOADS_DIR", env_map, default=str(Path.home() / "Downloads"))),
        tts_python_bin=os.getenv("TTS_PYTHON_BIN") or env_map.get("TTS_PYTHON_BIN"),
        tts_reference_audio=os.getenv("TTS_REFERENCE_AUDIO") or env_map.get("TTS_REFERENCE_AUDIO"),
        tts_gender=_env("TTS_GENDER", env_map, default="female"),
        ffmpeg_bin=_env("TTS_FFMPEG_BIN", env_map, default="ffmpeg"),
        huggingface_hub_token=os.getenv("HUGGINGFACE_HUB_TOKEN") or env_map.get("HUGGINGFACE_HUB_TOKEN"),
        indic_parler_model_id=_env("INDIC_PARLER_MODEL_ID", env_map, default="ai4bharat/indic-parler-tts"),
        indic_parler_device=_env("INDIC_PARLER_DEVICE", env_map, default="cuda"),
        indic_parler_enabled_languages=_csv(
            os.getenv("TTS_INDIC_PARLER_ENABLED_LANGUAGES")
            or env_map.get("TTS_INDIC_PARLER_ENABLED_LANGUAGES")
            or "en,hi,pa,ta"
        ),
        indic_parler_cache_root=Path(
            _env("TTS_INDIC_PARLER_CACHE_ROOT", env_map, default=str(models_root / "huggingface"))
        ),
        indic_parler_description_templates=_parse_description_templates(
            os.getenv("TTS_INDIC_PARLER_DESCRIPTIONS_JSON") or env_map.get("TTS_INDIC_PARLER_DESCRIPTIONS_JSON")
        ),
        provider_chains=_parse_provider_chains(
            os.getenv("TTS_PROVIDER_CHAINS_JSON") or env_map.get("TTS_PROVIDER_CHAINS_JSON")
        ),
    )
    settings.ensure_dirs()
    _SETTINGS = settings
    return settings


def get_indic_parler_runtime() -> IndicParlerRuntime:
    global _INDIC_PARLER_RUNTIME
    if _INDIC_PARLER_RUNTIME is None:
        settings = get_settings()
        _INDIC_PARLER_RUNTIME = IndicParlerRuntime(
            IndicParlerSettings(
                model_id=settings.indic_parler_model_id,
                device=settings.indic_parler_device,
                token=settings.huggingface_hub_token,
                enabled_languages=settings.indic_parler_enabled_languages,
                cache_dir=settings.indic_parler_cache_root,
                description_templates=settings.indic_parler_description_templates,
            )
        )
    return _INDIC_PARLER_RUNTIME


def collapse_whitespace(text: str) -> str:
    return " ".join((text or "").split())


def provider_chain_for(language: LanguageValue) -> tuple[ProviderValue, ...]:
    chain = get_settings().provider_chains.get(language)
    if not chain:
        raise TtsServiceError(f"Unsupported language: {language}")
    return chain


def get_primary_provider(language: LanguageValue) -> ProviderValue:
    return cast(ProviderValue, provider_chain_for(language)[0])


def provider_chains_payload() -> dict[str, list[ProviderValue]]:
    return {language: list(chain) for language, chain in get_settings().provider_chains.items()}


def fallback_only_languages() -> list[str]:
    return [language for language, chain in get_settings().provider_chains.items() if "indic-parler" in chain and chain[0] != "indic-parler"]


def cache_key_version_for(provider: ProviderValue) -> str | None:
    if provider == "indic-parler":
        return DESCRIPTION_TEMPLATE_VERSION
    return None


def internal_cache_salt_for(provider: ProviderValue, language: LanguageValue) -> str | None:
    if provider == "indic-parler":
        return get_indic_parler_runtime().cache_signature(language)
    return None


def cache_dir_for(provider: ProviderValue, language: LanguageValue, text: str, *, cache_salt: str | None = None) -> Path:
    normalized = collapse_whitespace(text)
    digest = hashlib.sha256(f"{provider}|{language}|{cache_salt or ''}|{normalized}".encode("utf-8")).hexdigest()
    settings = get_settings()
    return settings.generated_root / provider / language / digest


def output_url_for(file_path: Path) -> str:
    settings = get_settings()
    relative = file_path.resolve().relative_to(settings.generated_root.resolve())
    return f"{settings.public_base_url}/generated/{'/'.join(relative.parts)}"


def run_command(command: list[str], *, cwd: str | None = None, env: dict[str, str] | None = None) -> None:
    result = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise TtsServiceError(result.stderr.strip() or result.stdout.strip() or "Command execution failed.")


def ensure_friend_language_assets(language: LanguageValue) -> dict[str, str]:
    settings = get_settings()
    payload = LANGUAGE_METADATA[language]
    extracted_dir = settings.models_root / language
    source_folder = extracted_dir / payload["folder"]
    zip_path = settings.downloads_root / payload["zip_name"]
    if not source_folder.exists():
        if not zip_path.exists():
            raise TtsServiceError(f"Local model zip not found for {language}: {zip_path}")
        extracted_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path, "r") as archive:
            archive.extractall(extracted_dir)

    tar_path = source_folder / "tts-inference.tar"
    tts_root = settings.runtime_root / language / "tts-inference"
    tts_app_dir = tts_root / "TTS"
    if not tts_app_dir.exists():
        tts_root.parent.mkdir(parents=True, exist_ok=True)
        with tarfile.open(tar_path) as archive:
            archive.extractall(tts_root.parent)

    checkpts_dir = tts_app_dir / "checkpts"
    speaker_dir = tts_app_dir / "spk_encoder"
    resources_dir = tts_app_dir / "resources" / "filelists"
    for path in (checkpts_dir, speaker_dir, resources_dir, tts_app_dir / "logs"):
        path.mkdir(parents=True, exist_ok=True)

    checkpoint_dest = tts_app_dir / "logs" / "tts.pt"
    hifigan_dest = checkpts_dir / "hifigan.pt"
    speaker_dest = speaker_dir / "speaker_encoder.pt"
    if not checkpoint_dest.exists():
        shutil.copyfile(source_folder / payload["checkpoint"], checkpoint_dest)
    if not hifigan_dest.exists():
        shutil.copyfile(source_folder / "hifigan.pt", hifigan_dest)
    if not speaker_dest.exists():
        shutil.copyfile(source_folder / "speaker_encoder.pt", speaker_dest)

    patch_friend_runtime(tts_app_dir)
    return {
        "tts_app_dir": str(tts_app_dir),
        "inference_script": str(tts_app_dir / "inference.py"),
        "checkpoint_path": str(checkpoint_dest),
        "lang_arg": payload["lang_arg"],
    }


def patch_friend_runtime(tts_app_dir: Path) -> None:
    speaker_encoder_path = tts_app_dir / "speaker_encoder.py"
    tts_model_path = tts_app_dir / "model" / "tts.py"
    inference_path = tts_app_dir / "inference.py"

    if speaker_encoder_path.exists():
        speaker_encoder_code = speaker_encoder_path.read_text(encoding="utf-8")
        if "self.use_fallback" not in speaker_encoder_code:
            speaker_encoder_path.write_text(
                """import json\nimport torch\nimport torchaudio\n\ntry:\n    from spk_encoder.speaker_encoder.ecapa_tdnn import ECAPA_TDNN_SMALL\nexcept Exception:\n    ECAPA_TDNN_SMALL = None\n\nfrom spk_encoder.util import HParams\n\n\nclass SpeakerEncoder:\n    def __init__(self, speaker_encoder_path, config_path):\n        with open(config_path, \"r\") as f:\n            data = f.read()\n        config = json.loads(data)\n        self.hps = HParams(**config)\n        self.device = torch.device(\"cuda\" if torch.cuda.is_available() else \"cpu\")\n        self.embedding_dim = 256\n        self.use_fallback = False\n\n        if ECAPA_TDNN_SMALL is None:\n            self.use_fallback = True\n            self.spk_embedder = None\n            return\n\n        try:\n            self.spk_embedder = ECAPA_TDNN_SMALL(feat_dim=1024, feat_type=\"wavlm_large\", config_path=None)\n            state_dict = torch.load(speaker_encoder_path, map_location=lambda storage, loc: storage)\n            self.spk_embedder.load_state_dict(state_dict[\"model\"], strict=False)\n            self.spk_embedder = self.spk_embedder.to(self.device).eval()\n        except Exception:\n            self.use_fallback = True\n            self.spk_embedder = None\n\n    def get_spk_embd(self, audio, sr):\n        if self.use_fallback or self.spk_embedder is None:\n            return torch.zeros(self.embedding_dim, device=self.device)\n\n        if sr != 16000:\n            resample_fn = torchaudio.transforms.Resample(sr, 16000).to(self.device)\n            audio = resample_fn(audio.to(self.device))\n        else:\n            audio = audio.to(self.device)\n\n        spk_emb = self.spk_embedder(audio)\n        spk_emb = spk_emb / spk_emb.norm()\n        return spk_emb\n""",
                encoding="utf-8",
            )

    if tts_model_path.exists():
        tts_model_code = tts_model_path.read_text(encoding="utf-8")
        if "from model import monotonic_align" in tts_model_code:
            tts_model_code = tts_model_code.replace("from model import monotonic_align\n", "")
            tts_model_code = tts_model_code.replace(
                "        with torch.no_grad(): \n            const = -0.5 * math.log(2 * math.pi) * self.n_feats\n",
                "        from model import monotonic_align\n\n        with torch.no_grad(): \n            const = -0.5 * math.log(2 * math.pi) * self.n_feats\n",
            )
            tts_model_path.write_text(tts_model_code, encoding="utf-8")

    if inference_path.exists():
        inference_code = inference_path.read_text(encoding="utf-8")
        if "sys.stdout.reconfigure" not in inference_code:
            inference_code = inference_code.replace(
                "import os\nimport sys\nimport argparse\n",
                "import os\nimport sys\nimport argparse\n\nif hasattr(sys.stdout, 'reconfigure'):\n    sys.stdout.reconfigure(encoding='utf-8', errors='replace')\nif hasattr(sys.stderr, 'reconfigure'):\n    sys.stderr.reconfigure(encoding='utf-8', errors='replace')\n",
            )
            inference_code = inference_code.replace(
                "        print(f\"Processing [{idx+1}/{len(lines)}]: {line}\")\n",
                "        safe_line = line.encode('utf-8', errors='replace').decode('utf-8', errors='replace')\n        print(f\"Processing [{idx+1}/{len(lines)}]: {safe_line}\")\n",
            )
            inference_path.write_text(inference_code, encoding="utf-8")


async def synthesize_edge_tts(text: str, output_path: Path, voice: str) -> None:
    try:
        import edge_tts
    except ImportError as exc:  # pragma: no cover
        raise TtsServiceError("edge-tts is not installed. Add it to the TTS service environment.") from exc

    temp_mp3 = output_path.with_suffix(".edge.mp3")
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(str(temp_mp3))
    run_command(
        [
            get_settings().ffmpeg_bin,
            "-y",
            "-i",
            str(temp_mp3),
            "-ar",
            "16000",
            "-ac",
            "1",
            str(output_path),
        ]
    )
    temp_mp3.unlink(missing_ok=True)


def synthesize_friend_local(text: str, output_path: Path, language: LanguageValue, request_id: str) -> None:
    settings = get_settings()
    if not settings.tts_python_bin:
        raise TtsServiceError("TTS_PYTHON_BIN is not configured for the friend-local runtime.")

    assets = ensure_friend_language_assets(language)
    tts_app_dir = Path(assets["tts_app_dir"])
    synthesis_file = tts_app_dir / "resources" / "filelists" / f"{request_id}.txt"
    synthesis_file.write_text(f"{text}\n", encoding="utf-8")
    reference_audio = settings.tts_reference_audio or str(tts_app_dir / "abhi_voice.wav")

    run_command(
        [
            settings.tts_python_bin,
            assets["inference_script"],
            "--checkpoint",
            assets["checkpoint_path"],
            "--audio",
            reference_audio,
            "--file",
            str(synthesis_file),
            "--log_dir",
            str(output_path.parent),
            "--language",
            assets["lang_arg"],
            "--gender",
            settings.tts_gender,
        ],
        cwd=str(tts_app_dir),
        env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
    )

    generated_audio = output_path.parent / f"{assets['lang_arg']}_{settings.tts_gender}_1.wav"
    if generated_audio.exists() and generated_audio.resolve() != output_path.resolve():
        shutil.copyfile(generated_audio, output_path)
    if not output_path.exists():
        raise TtsServiceError(f"Expected synthesized WAV was not found at {output_path}")


def synthesize_indic_parler(text: str, output_path: Path, language: LanguageValue) -> None:
    try:
        get_indic_parler_runtime().synthesize_to_path(text=text, language=language, output_path=output_path)
    except IndicParlerError as exc:
        raise TtsServiceError(str(exc)) from exc


def synthesize_with_provider(provider: ProviderValue, text: str, output_path: Path, language: LanguageValue, request_id: str) -> None:
    if provider == "edge-tts":
        voice = os.getenv(LANGUAGE_METADATA[language].get("voice_env", ""), LANGUAGE_METADATA[language].get("voice_default", ""))
        asyncio.run(synthesize_edge_tts(text, output_path, voice))
        return
    if provider == "friend-local":
        synthesize_friend_local(text, output_path, language, request_id)
        return
    synthesize_indic_parler(text, output_path, language)


def build_synthesize_response(
    *,
    request_id: str,
    language: LanguageValue,
    provider: ProviderValue,
    output_path: Path,
    cache_hit: bool,
    warnings: list[str],
) -> SynthesizeResponse:
    return SynthesizeResponse(
        request_id=request_id,
        language=language,
        provider=provider,
        audio_url=output_url_for(output_path),
        audio_path=str(output_path),
        cache_hit=cache_hit,
        warnings=warnings,
        cache_key_version=cache_key_version_for(provider),
    )


def synthesize_audio(payload: SynthesizeRequest) -> SynthesizeResponse:
    text = collapse_whitespace(payload.text)
    if not text:
        raise TtsServiceError("Text is required.")

    chain = provider_chain_for(payload.language)
    primary_provider = chain[0]
    request_id = payload.request_id or f"tts_{uuid.uuid4().hex}"
    errors: list[str] = []

    for provider in chain:
        output_dir = cache_dir_for(
            provider,
            payload.language,
            text,
            cache_salt=internal_cache_salt_for(provider, payload.language),
        )
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / "output.wav"
        warnings: list[str] = []

        if provider != primary_provider:
            if errors:
                warnings.extend(errors)
            warnings.append(f"Used fallback provider {provider} instead of primary provider {primary_provider}.")

        if output_path.exists():
            return build_synthesize_response(
                request_id=request_id,
                language=payload.language,
                provider=provider,
                output_path=output_path,
                cache_hit=True,
                warnings=warnings,
            )

        try:
            synthesize_with_provider(provider, text, output_path, payload.language, request_id)
            return build_synthesize_response(
                request_id=request_id,
                language=payload.language,
                provider=provider,
                output_path=output_path,
                cache_hit=False,
                warnings=warnings,
            )
        except TtsServiceError as exc:
            errors.append(f"{provider} failed: {exc}")

    raise TtsServiceError("; ".join(errors) or "No TTS provider is available for this request.")


settings = get_settings()
settings.ensure_dirs()

app = FastAPI(
    title="TTS Service",
    description="Sidecar multilingual text-to-speech service for the real-time avatar demo.",
    version="0.2.0",
)
app.mount("/generated", StaticFiles(directory=str(settings.generated_root)), name="generated")


@app.get("/")
def index() -> dict[str, object]:
    return {
        "service": "tts-service",
        "status": "ok",
        "health": "/health",
        "languages": "/languages",
        "warmup": "/warmup",
        "synthesize": "/synthesize",
    }


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        service="tts-service",
        languages=list(LANGUAGE_METADATA.keys()),
        provider_chains=provider_chains_payload(),
        fallback_only_languages=fallback_only_languages(),
        indic_parler=get_indic_parler_runtime().health_snapshot(),
    )


@app.post("/warmup", response_model=WarmupResponse)
def warmup() -> WarmupResponse:
    runtime = get_indic_parler_runtime()
    try:
        snapshot = runtime.warmup()
        return WarmupResponse(
            status="ok",
            provider="indic-parler",
            ready=True,
            fallback_only_languages=fallback_only_languages(),
            indic_parler=snapshot,
        )
    except IndicParlerError as exc:
        return WarmupResponse(
            status="ok",
            provider="indic-parler",
            ready=False,
            detail=str(exc),
            fallback_only_languages=fallback_only_languages(),
            indic_parler=runtime.health_snapshot(),
        )


@app.get("/languages", response_model=LanguagesResponse)
def languages() -> LanguagesResponse:
    return LanguagesResponse(
        languages=[
            LanguageDescriptor(
                id=language_id,
                label=payload["label"],
                provider=get_primary_provider(language_id),
                provider_chain=list(provider_chain_for(language_id)),
            )
            for language_id, payload in LANGUAGE_METADATA.items()
        ]
    )


@app.post("/synthesize", response_model=SynthesizeResponse)
def synthesize(payload: SynthesizeRequest) -> SynthesizeResponse:
    try:
        return synthesize_audio(payload)
    except TtsServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
