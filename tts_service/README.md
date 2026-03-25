# TTS Service

`tts_service` is the multilingual speech sidecar for the real-time avatar demo.

## What it does

- `POST /synthesize` for English, Hindi, Punjabi, and Tamil.
- Tries Indic Parler first for English, Hindi, and Tamil, with safe fallback to the existing providers.
- Keeps Punjabi on the current friend-local runtime first, with Indic Parler available as a fallback.
- Exposes configured provider chains from `GET /languages`.
- Exposes Indic Parler readiness and fallback state from `GET /health` and `POST /warmup`.
- Caches generated WAV files under `tts_service/storage/generated`.
- Serves generated WAV files from `/generated/...`.

## Run

```bash
pip install -r tts_service/requirements.txt
uvicorn tts_service.api:app --host 0.0.0.0 --port 8200
```

## Required environment

- `TTS_PUBLIC_BASE_URL=http://127.0.0.1:8200`
- `TTS_MODEL_DOWNLOADS_DIR=C:\Users\<you>\Downloads`
- `TTS_PYTHON_BIN=C:\path\to\python38\python.exe`
- `TTS_REFERENCE_AUDIO=C:\path\to\reference.wav` (optional)
- `TTS_EDGE_EN_VOICE=en-US-JennyNeural` (optional)
- `TTS_EDGE_HI_VOICE=hi-IN-SwaraNeural` (optional)
- `TTS_FFMPEG_BIN=ffmpeg` (optional)
- `HUGGINGFACE_HUB_TOKEN=...` for the gated Indic Parler checkpoint
- `INDIC_PARLER_MODEL_ID=ai4bharat/indic-parler-tts` (optional)
- `INDIC_PARLER_DEVICE=cuda` (optional)
- `TTS_INDIC_PARLER_ENABLED_LANGUAGES=en,hi,pa,ta` (optional)
- `TTS_PROVIDER_CHAINS_JSON={"en":["indic-parler","edge-tts"],"hi":["indic-parler","edge-tts"],"pa":["friend-local","indic-parler"],"ta":["indic-parler","friend-local"]}` (optional)
- `TTS_INDIC_PARLER_DESCRIPTIONS_JSON={...}` (optional)

## Notes

- Punjabi and Tamil still support the friend-local model zips and Python runtime.
- English and Hindi still support Edge TTS fallback.
- Indic Parler loads lazily on first use or from `POST /warmup`, so service startup stays fast.
- The service always normalizes final output to WAV so the avatar render service can consume it directly.
