# TTS Service

`tts_service` is the multilingual speech sidecar for the real-time avatar demo.

## What it does

- `POST /synthesize` for English, Hindi, Punjabi, and Tamil.
- Uses Edge TTS for English and Hindi.
- Uses the friend-local multilingual runtime for Punjabi and Tamil.
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

## Notes

- Punjabi and Tamil require the friend-local model zips and Python runtime.
- English and Hindi require internet access for Edge TTS.
- The service always normalizes final output to WAV so the avatar render service can consume it directly.
