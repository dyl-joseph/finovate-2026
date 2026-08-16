from typing import Literal

from pydantic import BaseModel


class SessionStartedEvent(BaseModel):
    type: Literal["session_started"] = "session_started"
    session_id: str
    sample_rate: int
    started_at: str


class SessionEndedEvent(BaseModel):
    type: Literal["session_ended"] = "session_ended"
    session_id: str
    ended_at: str


class TranscriptEvent(BaseModel):
    """Emitted for every ASR result on /ws/transcript.

    Downstream consumers (diarization, evidence graph) subscribe to
    /ws/transcript and key state off `session_id` + `sequence`.
    """

    type: Literal["transcript"] = "transcript"
    session_id: str
    sequence: int
    is_final: bool
    speech_final: bool
    text: str
    confidence: float
    start: float
    duration: float
    timestamp: str


class ErrorEvent(BaseModel):
    type: Literal["error"] = "error"
    session_id: str | None = None
    message: str


class AudioChunkMeta(BaseModel):
    """Precedes the binary PCM16LE payload on /ws/audio-stream."""

    type: Literal["audio_chunk"] = "audio_chunk"
    session_id: str
    sequence: int
    offset_ms: float
    byte_length: int
