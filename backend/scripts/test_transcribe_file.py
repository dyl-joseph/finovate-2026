"""Smoke test for the Deepgram wiring, no frontend/WebSocket needed.

Streams a local 16kHz mono PCM16 WAV file through DeepgramASRSession at
roughly real-time pace and prints every transcript event as it arrives.

Usage:
    python scripts/test_transcribe_file.py path/to/audio.wav

The file must be 16kHz mono 16-bit PCM (matches DEEPGRAM_SAMPLE_RATE in
.env). Convert with ffmpeg if needed:
    ffmpeg -i input.mp3 -ar 16000 -ac 1 -sample_fmt s16 audio.wav
"""

import asyncio
import sys
import time
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.asr import DeepgramASRSession  # noqa: E402
from app.config import settings  # noqa: E402

CHUNK_MS = 100


async def main(wav_path: str) -> None:
    if not settings.deepgram_api_key:
        raise SystemExit("DEEPGRAM_API_KEY is not set. Copy backend/.env.example to backend/.env and fill it in.")

    with wave.open(wav_path, "rb") as wav_file:
        if wav_file.getframerate() != settings.deepgram_sample_rate:
            raise SystemExit(
                f"Expected {settings.deepgram_sample_rate}Hz audio, got {wav_file.getframerate()}Hz. "
                "Resample with ffmpeg first (see script docstring)."
            )
        if wav_file.getnchannels() != 1:
            raise SystemExit(f"Expected mono audio, got {wav_file.getnchannels()} channels.")
        if wav_file.getsampwidth() != 2:
            raise SystemExit(f"Expected 16-bit PCM, got {wav_file.getsampwidth() * 8}-bit.")

        frames = wav_file.readframes(wav_file.getnframes())

    async def on_transcript(event: dict) -> None:
        marker = "FINAL" if event["is_final"] else "interim"
        print(f"[{event['start']:6.2f}s +{event['duration']:.2f}s] ({marker}) {event['text']}")

    async def on_error(message: str) -> None:
        print(f"ERROR: {message}", file=sys.stderr)

    session = DeepgramASRSession("test-file", on_transcript, on_error)
    print("Connecting to Deepgram...")
    await session.start()
    print("Connected. Streaming audio...")

    bytes_per_chunk = int(settings.deepgram_sample_rate * 2 * (CHUNK_MS / 1000))
    for i in range(0, len(frames), bytes_per_chunk):
        chunk = frames[i : i + bytes_per_chunk]
        await session.send_audio(chunk)
        await asyncio.sleep(CHUNK_MS / 1000)

    print("Done streaming, waiting briefly for final results...")
    await asyncio.sleep(2)
    await session.finish()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(f"Usage: python {sys.argv[0]} path/to/audio.wav")
    start = time.monotonic()
    asyncio.run(main(sys.argv[1]))
    print(f"Total time: {time.monotonic() - start:.1f}s")
