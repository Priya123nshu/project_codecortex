from __future__ import annotations

import asyncio
import hashlib
import os
import shutil
import subprocess
import tarfile
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field


ProviderValue = Literal["edge-tts", "friend-local"]
LanguageValue = Literal["en", "hi", "pa", "ta"]

SUPPORTED_LANGUAGES = {
    "en": {
        "label": "English",
        "provider": "edge-tts",
        "voice_env": "TTS_EDGE_EN_VOICE",
        "voice_default": "en-US-JennyNeural",
    },
    "hi": {
        "label": "Hindi",
        "provider": "edge-tts",
        "voice_env": "TTS_EDGE_HI_VOICE",
        "voice_default": "hi-IN-SwaraNeural",
    },
    "pa": {
        "label": "Punjabi",
        "provider": "friend-local",
        "zip_name": "tts_with_spk_adapt_punjabi_Version_1.zip",
        "checkpoint": "punjabi.pt",
        "folder": "Punjabi",
        "lang_arg": "punjabi",
    },
    "ta": {
        "label": "Tamil",
        "provider": "friend-local",
        "zip_name": "tts_with_spk_adapt_tamil_Version_1.zip",
        "checkpoint": "tamil.pt",
        "folder": "Tamil",
        "lang_arg": "tamil",
    },
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

    def ensure_dirs(self) -> None:
        for path in (self.generated_root, self.models_root, self.runtime_root):
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


class LanguageDescriptor(BaseModel):
    id: LanguageValue
    label: str
    provider: ProviderValue


class LanguagesResponse(BaseModel):
    languages: list[LanguageDescriptor]


class HealthResponse(BaseModel):
    status: Literal["ok"]
    service: str
    languages: list[str]


_SETTINGS: Settings | None = None


def get_settings() -> Settings:
    global _SETTINGS
    if _SETTINGS is not None:
        return _SETTINGS

    service_root = Path(__file__).resolve().parent
    settings = Settings(
        service_root=service_root,
        public_base_url=(os.getenv("TTS_PUBLIC_BASE_URL") or "http://127.0.0.1:8200").rstrip("/"),
        generated_root=Path(os.getenv("TTS_GENERATED_ROOT") or service_root / "storage" / "generated"),
        models_root=Path(os.getenv("TTS_MODELS_ROOT") or service_root / "models"),
        runtime_root=Path(os.getenv("TTS_RUNTIME_ROOT") or service_root / "runtime"),
        downloads_root=Path(os.getenv("TTS_MODEL_DOWNLOADS_DIR") or Path.home() / "Downloads"),
        tts_python_bin=os.getenv("TTS_PYTHON_BIN"),
        tts_reference_audio=os.getenv("TTS_REFERENCE_AUDIO"),
        tts_gender=os.getenv("TTS_GENDER") or "female",
        ffmpeg_bin=os.getenv("TTS_FFMPEG_BIN") or "ffmpeg",
    )
    settings.ensure_dirs()
    _SETTINGS = settings
    return settings


def collapse_whitespace(text: str) -> str:
    return " ".join((text or "").split())


def cache_dir_for(provider: str, language: str, text: str) -> Path:
    digest = hashlib.sha256(f"{provider}|{language}|{collapse_whitespace(text)}".encode("utf-8")).hexdigest()
    settings = get_settings()
    return settings.generated_root / provider / language / digest


def output_url_for(file_path: Path) -> str:
    settings = get_settings()
    relative = file_path.resolve().relative_to(settings.generated_root.resolve())
    return f"{settings.public_base_url}/generated/{'/'.join(relative.parts)}"


def get_provider(language: str) -> ProviderValue:
    payload = SUPPORTED_LANGUAGES.get(language)
    if not payload:
        raise TtsServiceError(f"Unsupported language: {language}")
    return payload["provider"]


def run_command(command: list[str], *, cwd: str | None = None, env: dict[str, str] | None = None) -> None:
    result = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise TtsServiceError(result.stderr.strip() or result.stdout.strip() or "Command execution failed.")


def ensure_friend_language_assets(language: str) -> dict[str, str]:
    settings = get_settings()
    payload = SUPPORTED_LANGUAGES[language]
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
    run_command([
        get_settings().ffmpeg_bin,
        "-y",
        "-i",
        str(temp_mp3),
        "-ar",
        "16000",
        "-ac",
        "1",
        str(output_path),
    ])
    temp_mp3.unlink(missing_ok=True)


def synthesize_friend_local(text: str, output_path: Path, language: str, request_id: str) -> None:
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


def synthesize_audio(payload: SynthesizeRequest) -> SynthesizeResponse:
    text = collapse_whitespace(payload.text)
    if not text:
        raise TtsServiceError("Text is required.")

    provider = get_provider(payload.language)
    request_id = payload.request_id or f"tts_{uuid.uuid4().hex}"
    output_dir = cache_dir_for(provider, payload.language, text)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "output.wav"
    warnings: list[str] = []

    if output_path.exists():
        return SynthesizeResponse(
            request_id=request_id,
            language=payload.language,
            provider=provider,
            audio_url=output_url_for(output_path),
            audio_path=str(output_path),
            cache_hit=True,
            warnings=warnings,
        )

    if provider == "edge-tts":
        voice = os.getenv(SUPPORTED_LANGUAGES[payload.language]["voice_env"], SUPPORTED_LANGUAGES[payload.language]["voice_default"])
        asyncio.run(synthesize_edge_tts(text, output_path, voice))
    else:
        synthesize_friend_local(text, output_path, payload.language, request_id)

    return SynthesizeResponse(
        request_id=request_id,
        language=payload.language,
        provider=provider,
        audio_url=output_url_for(output_path),
        audio_path=str(output_path),
        cache_hit=False,
        warnings=warnings,
    )


settings = get_settings()
settings.ensure_dirs()

app = FastAPI(
    title="TTS Service",
    description="Sidecar multilingual text-to-speech service for the real-time avatar demo.",
    version="0.1.0",
)
app.mount("/generated", StaticFiles(directory=str(settings.generated_root)), name="generated")


@app.get("/")
def index() -> dict[str, object]:
    return {
        "service": "tts-service",
        "status": "ok",
        "health": "/health",
        "languages": "/languages",
        "synthesize": "/synthesize",
    }


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", service="tts-service", languages=list(SUPPORTED_LANGUAGES.keys()))


@app.get("/languages", response_model=LanguagesResponse)
def languages() -> LanguagesResponse:
    return LanguagesResponse(
        languages=[
            LanguageDescriptor(id=language_id, label=payload["label"], provider=payload["provider"])
            for language_id, payload in SUPPORTED_LANGUAGES.items()
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
