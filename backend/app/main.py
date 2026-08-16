import logging
import uuid
from datetime import datetime, timezone

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from app.asr import DeepgramASRSession
from app.broadcaster import audio_broadcaster, transcript_broadcaster
from app.config import settings
from app.schemas import (
    AudioChunkMeta,
    ErrorEvent,
    SessionEndedEvent,
    SessionStartedEvent,
    TranscriptEvent,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="finovate-2026 audio/ASR service")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_methods=["*"],
    allow_headers=["*"],
)

BYTES_PER_SAMPLE = 2  # PCM16LE


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.websocket("/ws/audio")
async def ws_audio(websocket: WebSocket) -> None:
    """Ingest endpoint: the browser mic connects here and streams raw
    PCM16LE binary frames. One connection = one call session. See
    docs/audio-asr-contract.md.
    """
    await websocket.accept()
    session_id = uuid.uuid4().hex[:12]
    sample_rate = settings.deepgram_sample_rate

    async def on_transcript(event: dict) -> None:
        await transcript_broadcaster.publish(TranscriptEvent(**event))

    async def on_error(message: str) -> None:
        await transcript_broadcaster.publish(ErrorEvent(session_id=session_id, message=message))

    asr_session = DeepgramASRSession(session_id, on_transcript, on_error)

    try:
        await asr_session.start()
    except Exception as exc:
        logger.exception("Failed to start Deepgram session %s", session_id)
        await websocket.send_text(ErrorEvent(session_id=session_id, message=str(exc)).model_dump_json())
        await websocket.close(code=1011)
        return

    await transcript_broadcaster.publish(
        SessionStartedEvent(
            session_id=session_id,
            sample_rate=sample_rate,
            started_at=datetime.now(timezone.utc).isoformat(),
        )
    )
    logger.info("Session %s started", session_id)

    total_bytes_received = 0
    chunk_sequence = 0

    try:
        while True:
            chunk = await websocket.receive_bytes()
            if not chunk:
                continue

            offset_ms = (total_bytes_received / BYTES_PER_SAMPLE) / sample_rate * 1000
            meta = AudioChunkMeta(
                session_id=session_id,
                sequence=chunk_sequence,
                offset_ms=offset_ms,
                byte_length=len(chunk),
            )
            total_bytes_received += len(chunk)
            chunk_sequence += 1

            await asr_session.send_audio(chunk)
            await audio_broadcaster.publish_chunk(meta, chunk)
    except WebSocketDisconnect:
        pass
    finally:
        await asr_session.finish()
        await transcript_broadcaster.publish(
            SessionEndedEvent(session_id=session_id, ended_at=datetime.now(timezone.utc).isoformat())
        )
        logger.info("Session %s ended", session_id)


@app.websocket("/ws/transcript")
async def ws_transcript(websocket: WebSocket) -> None:
    """Read-only fan-out of session/transcript events for downstream
    consumers (diarization, evidence-graph, debug UI)."""
    await websocket.accept()
    await transcript_broadcaster.subscribe(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await transcript_broadcaster.unsubscribe(websocket)


@app.websocket("/ws/audio-stream")
async def ws_audio_stream(websocket: WebSocket) -> None:
    """Read-only fan-out of raw audio chunks for downstream consumers
    that need the audio itself (e.g. speaker diarization/embeddings)."""
    await websocket.accept()
    await audio_broadcaster.subscribe(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await audio_broadcaster.unsubscribe(websocket)
