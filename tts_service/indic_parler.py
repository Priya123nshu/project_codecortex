from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any


DESCRIPTION_TEMPLATE_VERSION = "indic-parler-v1"

DEFAULT_DESCRIPTION_TEMPLATES: dict[str, str] = {
    "en": (
        "A calm professional female assistant speaks in English with very clear audio, moderate pace, "
        "natural phrasing, and a warm helpful tone. The recording is studio quality and very close up."
    ),
    "hi": (
        "A calm professional female assistant speaks in Hindi with very clear audio, moderate pace, "
        "natural phrasing, and a warm helpful tone. The recording is studio quality and very close up."
    ),
    "ta": (
        "A calm professional female assistant speaks in Tamil with very clear audio, moderate pace, "
        "natural phrasing, and a warm helpful tone. The recording is studio quality and very close up."
    ),
    "pa": (
        "A calm professional female assistant speaks in Punjabi with very clear audio, moderate pace, "
        "natural phrasing, and a warm helpful tone. The recording is studio quality and very close up."
    ),
}


class IndicParlerError(RuntimeError):
    pass


@dataclass(frozen=True)
class IndicParlerSettings:
    model_id: str
    device: str
    token: str | None
    enabled_languages: tuple[str, ...]
    cache_dir: Path | None = None
    description_templates: dict[str, str] | None = None


class IndicParlerRuntime:
    def __init__(self, settings: IndicParlerSettings) -> None:
        self.settings = settings
        self._lock = Lock()
        self._model: Any | None = None
        self._prompt_tokenizer: Any | None = None
        self._description_tokenizer: Any | None = None
        self._torch: Any | None = None
        self._soundfile: Any | None = None
        self._resolved_device: str | None = None
        self._sampling_rate: int | None = None
        self._load_error: str | None = None

    @property
    def templates(self) -> dict[str, str]:
        return self.settings.description_templates or DEFAULT_DESCRIPTION_TEMPLATES

    def is_enabled_for_language(self, language: str) -> bool:
        return language in self.settings.enabled_languages

    def cache_signature(self, language: str) -> str:
        description = self.description_for(language)
        return f"{DESCRIPTION_TEMPLATE_VERSION}|{self.settings.model_id}|{description}"

    def description_for(self, language: str) -> str:
        description = self.templates.get(language)
        if not description:
            raise IndicParlerError(f"No Indic Parler description template is configured for language '{language}'.")
        return description

    def health_snapshot(self) -> dict[str, Any]:
        return {
            "model_id": self.settings.model_id,
            "requested_device": self.settings.device,
            "resolved_device": self._resolved_device,
            "loaded": self._model is not None,
            "token_configured": bool(self.settings.token),
            "enabled_languages": list(self.settings.enabled_languages),
            "load_error": self._load_error,
        }

    def warmup(self) -> dict[str, Any]:
        self._ensure_loaded()
        return self.health_snapshot()

    def synthesize_to_path(self, *, text: str, language: str, output_path: Path) -> None:
        if not self.is_enabled_for_language(language):
            raise IndicParlerError(f"Indic Parler is not enabled for language '{language}'.")

        self._ensure_loaded()
        assert self._model is not None
        assert self._prompt_tokenizer is not None
        assert self._description_tokenizer is not None
        assert self._torch is not None
        assert self._soundfile is not None
        assert self._resolved_device is not None
        assert self._sampling_rate is not None

        description_inputs = self._description_tokenizer(self.description_for(language), return_tensors="pt")
        prompt_inputs = self._prompt_tokenizer(text, return_tensors="pt")
        description_inputs = {key: value.to(self._resolved_device) for key, value in description_inputs.items()}
        prompt_inputs = {key: value.to(self._resolved_device) for key, value in prompt_inputs.items()}

        with self._torch.inference_mode():
            generation = self._model.generate(
                input_ids=description_inputs["input_ids"],
                attention_mask=description_inputs.get("attention_mask"),
                prompt_input_ids=prompt_inputs["input_ids"],
                prompt_attention_mask=prompt_inputs.get("attention_mask"),
            )

        audio_arr = generation.detach().cpu().numpy().squeeze()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        self._soundfile.write(str(output_path), audio_arr, self._sampling_rate)

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return

        with self._lock:
            if self._model is not None:
                return
            try:
                import soundfile as soundfile
                import torch
                from parler_tts import ParlerTTSForConditionalGeneration
                from transformers import AutoTokenizer
            except ImportError as exc:  # pragma: no cover
                self._load_error = str(exc)
                raise IndicParlerError(
                    "Indic Parler dependencies are missing. Install parler-tts, transformers, soundfile, and torch."
                ) from exc

            resolved_device = self._resolve_device(torch)
            load_kwargs: dict[str, Any] = {}
            if self.settings.token:
                load_kwargs["token"] = self.settings.token
            if self.settings.cache_dir:
                load_kwargs["cache_dir"] = str(self.settings.cache_dir)

            try:
                model = ParlerTTSForConditionalGeneration.from_pretrained(self.settings.model_id, **load_kwargs)
                prompt_tokenizer = AutoTokenizer.from_pretrained(self.settings.model_id, **load_kwargs)
                text_encoder_path = getattr(getattr(model.config, "text_encoder", None), "_name_or_path", None)
                description_model_id = text_encoder_path or self.settings.model_id
                description_tokenizer = AutoTokenizer.from_pretrained(description_model_id, **load_kwargs)
                model = model.to(resolved_device)
                sampling_rate = int(getattr(model.config, "sampling_rate", 24000))
            except Exception as exc:  # pragma: no cover
                self._load_error = str(exc)
                raise IndicParlerError(f"Unable to load Indic Parler model '{self.settings.model_id}': {exc}") from exc

            self._torch = torch
            self._soundfile = soundfile
            self._model = model
            self._prompt_tokenizer = prompt_tokenizer
            self._description_tokenizer = description_tokenizer
            self._resolved_device = resolved_device
            self._sampling_rate = sampling_rate
            self._load_error = None

    def _resolve_device(self, torch: Any) -> str:
        requested = (self.settings.device or "auto").strip().lower()
        if requested in {"", "auto"}:
            return "cuda" if torch.cuda.is_available() else "cpu"
        if requested.startswith("cuda") and not torch.cuda.is_available():
            return "cpu"
        return self.settings.device
