import asyncio
import logging

from fastapi import WebSocket
from pydantic import BaseModel

from app.schemas import AudioChunkMeta

logger = logging.getLogger(__name__)


class _Broadcaster:
    """Shared subscriber bookkeeping for the two fan-out endpoints."""

    def __init__(self) -> None:
        self._subscribers: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def subscribe(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._subscribers.add(websocket)

    async def unsubscribe(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._subscribers.discard(websocket)

    async def _snapshot(self) -> list[WebSocket]:
        async with self._lock:
            return list(self._subscribers)


class TranscriptBroadcaster(_Broadcaster):
    """Fans out session/transcript JSON events to /ws/transcript subscribers.

    The audio-ingest session (see asr.py) publishes here; the diarization
    and evidence-graph services (or the debug UI) receive a copy each.
    """

    async def publish(self, event: BaseModel) -> None:
        payload = event.model_dump_json()
        for websocket in await self._snapshot():
            try:
                await websocket.send_text(payload)
            except Exception:
                logger.exception("Failed to deliver transcript event to a subscriber; dropping it")
                await self.unsubscribe(websocket)


class AudioBroadcaster(_Broadcaster):
    """Fans out raw audio chunks to /ws/audio-stream subscribers.

    Each chunk is sent as a JSON AudioChunkMeta text frame immediately
    followed by the binary PCM16LE payload (see docs/audio-asr-contract.md).
    """

    async def publish_chunk(self, meta: AudioChunkMeta, payload: bytes) -> None:
        meta_json = meta.model_dump_json()
        for websocket in await self._snapshot():
            try:
                await websocket.send_text(meta_json)
                await websocket.send_bytes(payload)
            except Exception:
                logger.exception("Failed to deliver audio chunk to a subscriber; dropping it")
                await self.unsubscribe(websocket)


transcript_broadcaster = TranscriptBroadcaster()
audio_broadcaster = AudioBroadcaster()
