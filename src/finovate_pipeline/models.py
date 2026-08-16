"""Data contracts shared with diarization and downstream pipeline stages."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class SpeakerRole(StrEnum):
    CALLER = "caller"
    CUSTOMER = "customer"
    UNKNOWN = "unknown"


class SignalKind(StrEnum):
    CLAIMED_IDENTITY = "claimed_identity"
    CLAIMED_TRANSACTION = "claimed_transaction"
    REQUESTED_TRANSFER = "requested_transfer"
    REQUESTED_CREDENTIALS = "requested_credentials"
    URGENCY = "urgency"
    AUTHORITY = "authority"
    SECRECY = "secrecy"
    ISOLATION = "isolation"
    THREAT = "threat"


class ScamStage(StrEnum):
    IDENTITY = "identity"
    CREDIBILITY = "credibility"
    URGENCY = "urgency"
    ISOLATION = "isolation"
    FINANCIAL_ACTION = "financial_action"


@dataclass(frozen=True, slots=True)
class TranscriptTurn:
    speaker_id: str
    text: str
    start_ms: int
    end_ms: int
    role: SpeakerRole = SpeakerRole.UNKNOWN

    def __post_init__(self) -> None:
        if not self.speaker_id.strip():
            raise ValueError("speaker_id cannot be empty")
        if not self.text.strip():
            raise ValueError("text cannot be empty")
        if self.start_ms < 0:
            raise ValueError("start_ms cannot be negative")
        if self.end_ms < self.start_ms:
            raise ValueError("end_ms cannot be before start_ms")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TranscriptTurn:
        return cls(
            speaker_id=str(data["speaker_id"]),
            text=str(data["text"]),
            start_ms=int(data["start_ms"]),
            end_ms=int(data["end_ms"]),
            role=SpeakerRole(data.get("role", SpeakerRole.UNKNOWN)),
        )


@dataclass(frozen=True, slots=True)
class Transcript:
    conversation_id: str
    turns: tuple[TranscriptTurn, ...]
    caller_speaker_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.conversation_id.strip():
            raise ValueError("conversation_id cannot be empty")
        if not self.turns:
            raise ValueError("transcript must contain at least one turn")
        for previous, current in zip(self.turns, self.turns[1:]):
            if current.start_ms < previous.start_ms:
                raise ValueError("turns must be ordered by start_ms")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Transcript:
        return cls(
            conversation_id=str(data["conversation_id"]),
            turns=tuple(TranscriptTurn.from_dict(turn) for turn in data["turns"]),
            caller_speaker_id=data.get("caller_speaker_id"),
            metadata=dict(data.get("metadata", {})),
        )

    def is_caller_turn(self, turn: TranscriptTurn) -> bool:
        if turn.role == SpeakerRole.CALLER:
            return True
        if turn.role == SpeakerRole.CUSTOMER:
            return False
        if self.caller_speaker_id is not None:
            return turn.speaker_id == self.caller_speaker_id
        return True


@dataclass(frozen=True, slots=True)
class EvidenceSignal:
    signal_id: str
    kind: SignalKind
    stage: ScamStage
    speaker_id: str
    turn_index: int
    start_ms: int
    evidence_text: str
    confidence: float
    attributes: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class AnalysisResult:
    conversation_id: str
    signals: tuple[EvidenceSignal, ...]
    stages_reached: tuple[ScamStage, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
