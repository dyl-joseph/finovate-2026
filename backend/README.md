# Audio / Streaming ASR backend

Implements the contract in `../docs/audio-asr-contract.md`: ingests live
mic audio and streams transcript events out over WebSocket.

## Setup

```bash
cd backend
python -m venv .venv
.venv/Scripts/activate   # or `source .venv/bin/activate` on macOS/Linux
pip install -r requirements.txt
cp .env.example .env
# edit .env and set DEEPGRAM_API_KEY (get one at https://console.deepgram.com/)
```

## Run the server

```bash
uvicorn app.main:app --reload --port 8000
```

Endpoints:
- `GET /health`
- `WS /ws/audio` — mic ingest (raw PCM16LE binary frames, 16kHz mono)
- `WS /ws/transcript` — subscribe for transcript/session JSON events
- `WS /ws/audio-stream` — subscribe for raw audio fan-out (JSON meta + binary pairs)

## Quick smoke test without the frontend

Confirms the Deepgram wiring works end-to-end using a local WAV file
instead of a live mic:

```bash
python scripts/test_transcribe_file.py path/to/16khz_mono.wav
```

If your source audio isn't already 16kHz mono 16-bit PCM, convert it first:

```bash
ffmpeg -i input.mp3 -ar 16000 -ac 1 -sample_fmt s16 audio.wav
```
