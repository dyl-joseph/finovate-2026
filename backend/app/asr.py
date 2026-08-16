import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

from deepgram import (
    DeepgramClient,
    DeepgramClientOptions,
    LiveOptions,
    LiveTranscriptionEvents,
)

from app.config import settings

logger = logging.getLogger(__name__)

TranscriptCallback = Callable[[dict], Awaitable[None]]
ErrorCallback = Callable[[str], Awaitable[None]]


class DeepgramASRSession:
    """Wraps one Deepgram live-transcription connection for one call session.

    See docs/audio-asr-contract.md for the transcript event shape this
    produces via `on_transcript`.
    """

    def __init__(
        self,
        session_id: str,
        on_transcript: TranscriptCallback,
        on_error: ErrorCallback,
    ) -> None:
        self.session_id = session_id
        self._on_transcript = on_transcript
        self._on_error = on_error
        self._sequence = 0
        self._connection = None

    async def start(self) -> None:
        if not settings.deepgram_api_key:
            raise RuntimeError("DEEPGRAM_API_KEY is not set")

        client = DeepgramClient(
            settings.deepgram_api_key,
            DeepgramClientOptions(options={"keepalive": "true"}),
        )
        self._connection = client.listen.asynclive.v("1")
        self._connection.on(LiveTranscriptionEvents.Transcript, self._handle_transcript)
        self._connection.on(LiveTranscriptionEvents.Error, self._handle_error)

        options = LiveOptions(
            model=settings.deepgram_model,
            language=settings.deepgram_language,
            smart_format=True,
            encoding="linear16",
            channels=1,
            sample_rate=settings.deepgram_sample_rate,
            interim_results=True,
            utterance_end_ms="1000",
        )

        started = await self._connection.start(options)
        if started is False:
            raise RuntimeError("Deepgram connection failed to start")

    async def send_audio(self, chunk: bytes) -> None:
        if self._connection is None:
            raise RuntimeError("ASR session not started")
        await self._connection.send(chunk)

    async def finish(self) -> None:
        if self._connection is not None:
            await self._connection.finish()

    async def _handle_transcript(self, _client, result, **_kwargs) -> None:
        alternative = result.channel.alternatives[0]
        if not alternative.transcript:
            return

        self._sequence += 1
        event = {
            "session_id": self.session_id,
            "sequence": self._sequence,
            "is_final": bool(result.is_final),
            "speech_final": bool(getattr(result, "speech_final", False)),
            "text": alternative.transcript,
            "confidence": float(alternative.confidence),
            "start": float(result.start),
            "duration": float(result.duration),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await self._on_transcript(event)

    async def _handle_error(self, _client, error, **_kwargs) -> None:
        logger.error("Deepgram error for session %s: %s", self.session_id, error)
        await self._on_error(str(error))
