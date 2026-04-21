# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

K230 Smart Voice Assistant — a two-part system: a Kendryte K230 AI vision device (MicroPython) as the front-end sensor, and a Windows PC backend (Python/FastAPI) that integrates OpenClaw AI for conversation and TTS for voice output. The K230 captures face detection, gesture recognition, and voice; the PC processes events through an LLM pipeline and speaks responses.

## Commands

```bash
# Backend setup (from backend/)
cd D:/code/py/AIassistant/backend
python -m venv venv
source venv/Scripts/activate   # Git Bash on Windows
pip install -r requirements.txt

# Configure environment
cp .env.example .env           # Edit .env with actual values

# Run backend server
python main.py                 # Starts uvicorn on 0.0.0.0:8000 (reload=False due to httpx stream bug)

# K230: upload k230/ scripts to device via CanMV IDE, then run main.py
```

No test suite currently exists.

## Architecture

```
K230 (MicroPython)  ──HTTP JSON──►  PC Backend (FastAPI :8000)
  face_detect.py                       main.py (routes + event dispatch)
  gesture_recog.py                       ├── openclaw_client.py (SSE stream to Gateway :18790)
  voice_capture.py                       │     └── OpenClaw → vllm/Qwen3.6-35B-A3B-AWQ
  http_client.py                         ├── asr_engine.py (faster-whisper large-v3, lazy-loaded)
  wifi_connect.py                        ├── tts_engine.py (edge-tts online → pyttsx3 offline fallback)
                                         └── audio_player.py (pygame.mixer, queued playback)
```

### Data Flow

1. K230 detects event (face/gesture/voice) → `POST /api/event` or `POST /api/voice`
2. Backend builds context-aware prompt via `_build_prompt()` in `main.py`
3. `openclaw_client.chat_stream()` sends SSE request to OpenClaw Gateway, filters out `tool_calls` deltas, yields text chunks
4. Full reply collected → background `asyncio.create_task(_speak(reply))`
5. Response returned to K230 immediately (TTS is non-blocking)
6. `tts_engine.synthesize()` → MP3/WAV → `audio_player.play()` → speaker

### Key Design Decisions

- **Streaming**: OpenClaw uses SSE streaming; `_extract_stream_text()` filters `delta.tool_calls` to prevent tool-call JSON from being spoken
- **TTS fallback chain**: edge-tts (online) → pyttsx3 (offline), configurable via `TTS_FALLBACK_OFFLINE`
- **Audio queue**: `audio_player.py` uses a `deque` queue to prevent overlapping playback; temp files auto-deleted after playback
- **ASR**: `asr_engine.py` lazily loads faster-whisper large-v3 model on first call
- **uvicorn reload=False**: `reload=True` breaks httpx streaming behavior

### K230 Constraints

- Runs CanMV MicroPython (not standard Python) — uses `sensor`, `KPU`, `lcd`, `urequests` modules
- WiFi only supports 2.4GHz
- KPU models must be deployed to `/sdcard/kmodel/` on device
- Face detection uses YOLOv2 post-processing; gesture uses KPU classification
- Both face and gesture modules have debounce (3s and 2s intervals respectively)

### Configuration

All config via `backend/.env` (see `.env.example`). Key variables: `OPENCLAW_GATEWAY_URL`, `OPENCLAW_API_KEY`, `BACKEND_PORT`, `TTS_VOICE`, `TTS_RATE`.

### API Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/health` | GET | Health check |
| `/api/event` | POST | Receive face/gesture/voice events from K230 |
| `/api/voice` | POST | Upload audio file (multipart), runs ASR then full pipeline |

### Known Issues / TODO

- Gesture kmodel needs deployment to `/sdcard/kmodel/gesture.kmodel`
- Face detection only detects presence, not identity (no feature extraction)
- Concurrent events (face + gesture simultaneously) are not merged
- `wifi_connect.py` has hardcoded credentials that should be parameterized
