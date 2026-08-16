"""Cross-conversation speaker memory and persistence."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from threading import RLock
from typing import Any, Protocol

from .models import AnalysisResult, SignalKind


@dataclass(frozen=True, slots=True)
class SpeakerIdentity:
    """An upstream speaker-profile match; this module does not compare voices."""

    profile_id: str
    match_confidence: float
    source: str = "upstream_speaker_match"

    def __post_init__(self) -> None:
        if not self.profile_id.strip():
            raise ValueError("profile_id cannot be empty")
        if not 0.0 <= self.match_confidence <= 1.0:
            raise ValueError("match_confidence must be between 0 and 1")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SpeakerIdentity:
        return cls(
            profile_id=str(data["profile_id"]),
            match_confidence=float(data["match_confidence"]),
            source=str(data.get("source", "upstream_speaker_match")),
        )


@dataclass(frozen=True, slots=True)
class EncounterRecord:
    conversation_id: str
    speaker_profile_id: str
    risk_score: int
    risk_level: str
    claimed_institutions: tuple[str, ...] = ()
    signal_kinds: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.conversation_id.strip():
            raise ValueError("conversation_id cannot be empty")
        if not self.speaker_profile_id.strip():
            raise ValueError("speaker_profile_id cannot be empty")
        if not 0 <= self.risk_score <= 100:
            raise ValueError("risk_score must be between 0 and 100")


class EncounterRepository(Protocol):
    def save(self, encounter: EncounterRecord) -> None: ...

    def find_by_speaker(
        self,
        speaker_profile_id: str,
        exclude_conversation_id: str | None = None,
    ) -> tuple[EncounterRecord, ...]: ...


class InMemoryEncounterRepository:
    """Default repository for tests and single-process demos."""

    def __init__(self) -> None:
        self._records: dict[str, EncounterRecord] = {}

    def save(self, encounter: EncounterRecord) -> None:
        self._records[encounter.conversation_id] = encounter

    def find_by_speaker(
        self,
        speaker_profile_id: str,
        exclude_conversation_id: str | None = None,
    ) -> tuple[EncounterRecord, ...]:
        return tuple(
            record
            for record in self._records.values()
            if record.speaker_profile_id == speaker_profile_id
            and record.conversation_id != exclude_conversation_id
        )


class SQLiteEncounterRepository:
    """SQLite implementation matching the repository planned for Postgres."""

    def __init__(self, database: str | Path = ":memory:") -> None:
        self._connection = sqlite3.connect(str(database), check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._lock = RLock()
        self._create_schema()

    def _create_schema(self) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS speaker_encounters (
                    conversation_id TEXT PRIMARY KEY,
                    speaker_profile_id TEXT NOT NULL,
                    risk_score INTEGER NOT NULL,
                    risk_level TEXT NOT NULL,
                    claimed_institutions_json TEXT NOT NULL,
                    signal_kinds_json TEXT NOT NULL
                )
                """
            )
            self._connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_speaker_encounters_profile
                ON speaker_encounters (speaker_profile_id)
                """
            )

    def save(self, encounter: EncounterRecord) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO speaker_encounters (
                    conversation_id,
                    speaker_profile_id,
                    risk_score,
                    risk_level,
                    claimed_institutions_json,
                    signal_kinds_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(conversation_id) DO UPDATE SET
                    speaker_profile_id = excluded.speaker_profile_id,
                    risk_score = excluded.risk_score,
                    risk_level = excluded.risk_level,
                    claimed_institutions_json = excluded.claimed_institutions_json,
                    signal_kinds_json = excluded.signal_kinds_json
                """,
                (
                    encounter.conversation_id,
                    encounter.speaker_profile_id,
                    encounter.risk_score,
                    encounter.risk_level,
                    json.dumps(encounter.claimed_institutions),
                    json.dumps(encounter.signal_kinds),
                ),
            )

    def find_by_speaker(
        self,
        speaker_profile_id: str,
        exclude_conversation_id: str | None = None,
    ) -> tuple[EncounterRecord, ...]:
        query = """
            SELECT conversation_id, speaker_profile_id, risk_score, risk_level,
                   claimed_institutions_json, signal_kinds_json
            FROM speaker_encounters
            WHERE speaker_profile_id = ?
        """
        parameters: list[str] = [speaker_profile_id]
        if exclude_conversation_id is not None:
            query += " AND conversation_id != ?"
            parameters.append(exclude_conversation_id)
        query += " ORDER BY conversation_id"

        with self._lock:
            rows = self._connection.execute(query, parameters).fetchall()
        return tuple(self._row_to_record(row) for row in rows)

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def __enter__(self) -> SQLiteEncounterRepository:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> EncounterRecord:
        return EncounterRecord(
            conversation_id=row["conversation_id"],
            speaker_profile_id=row["speaker_profile_id"],
            risk_score=row["risk_score"],
            risk_level=row["risk_level"],
            claimed_institutions=tuple(
                json.loads(row["claimed_institutions_json"])
            ),
            signal_kinds=tuple(json.loads(row["signal_kinds_json"])),
        )


class MemoryFindingKind(StrEnum):
    REPEAT_FLAGGED_SPEAKER = "repeat_flagged_speaker"
    IDENTITY_SWITCH = "identity_switch"


@dataclass(frozen=True, slots=True)
class MemoryFinding:
    finding_id: str
    kind: MemoryFindingKind
    description: str
    risk_weight: int
    speaker_profile_id: str
    match_confidence: float
    prior_conversation_ids: tuple[str, ...]
    attributes: dict[str, Any] = field(default_factory=dict)


_MINIMUM_MATCH_CONFIDENCE = 0.80
_FLAGGED_RISK_LEVELS = {"high", "critical"}


class EncounterMemory:
    """Interpret prior encounters associated with an upstream speaker profile."""

    def __init__(self, repository: EncounterRepository | None = None) -> None:
        self.repository = repository or InMemoryEncounterRepository()

    def evaluate(
        self,
        conversation_id: str,
        identity: SpeakerIdentity | None,
        analysis: AnalysisResult,
    ) -> tuple[MemoryFinding, ...]:
        if identity is None or identity.match_confidence < _MINIMUM_MATCH_CONFIDENCE:
            return ()

        prior = self.repository.find_by_speaker(
            identity.profile_id,
            exclude_conversation_id=conversation_id,
        )
        flagged = tuple(
            encounter
            for encounter in prior
            if encounter.risk_level in _FLAGGED_RISK_LEVELS
        )
        if not flagged:
            return ()

        findings: list[MemoryFinding] = [
            MemoryFinding(
                finding_id="memory-0001",
                kind=MemoryFindingKind.REPEAT_FLAGGED_SPEAKER,
                description=(
                    "A similar speaker profile appeared in "
                    f"{len(flagged)} previously flagged financial interaction(s)."
                ),
                risk_weight=25,
                speaker_profile_id=identity.profile_id,
                match_confidence=identity.match_confidence,
                prior_conversation_ids=tuple(
                    encounter.conversation_id for encounter in flagged
                ),
                attributes={
                    "prior_risk_scores": [
                        encounter.risk_score for encounter in flagged
                    ],
                    "prior_institutions": sorted(
                        {
                            institution
                            for encounter in flagged
                            for institution in encounter.claimed_institutions
                        }
                    ),
                    "source": identity.source,
                },
            )
        ]

        current_institutions = set(self.claimed_institutions(analysis))
        prior_institutions = {
            institution
            for encounter in flagged
            for institution in encounter.claimed_institutions
        }
        if (
            current_institutions
            and prior_institutions
            and current_institutions.isdisjoint(prior_institutions)
        ):
            findings.append(
                MemoryFinding(
                    finding_id="memory-0002",
                    kind=MemoryFindingKind.IDENTITY_SWITCH,
                    description=(
                        "The speaker previously claimed a different institutional "
                        "identity."
                    ),
                    risk_weight=10,
                    speaker_profile_id=identity.profile_id,
                    match_confidence=identity.match_confidence,
                    prior_conversation_ids=tuple(
                        encounter.conversation_id for encounter in flagged
                    ),
                    attributes={
                        "current_institutions": sorted(current_institutions),
                        "prior_institutions": sorted(prior_institutions),
                    },
                )
            )
        return tuple(findings)

    def remember(
        self,
        conversation_id: str,
        identity: SpeakerIdentity | None,
        analysis: AnalysisResult,
        risk_score: int,
        risk_level: str,
    ) -> None:
        if identity is None or identity.match_confidence < _MINIMUM_MATCH_CONFIDENCE:
            return
        self.repository.save(
            EncounterRecord(
                conversation_id=conversation_id,
                speaker_profile_id=identity.profile_id,
                risk_score=risk_score,
                risk_level=risk_level,
                claimed_institutions=self.claimed_institutions(analysis),
                signal_kinds=tuple(
                    sorted({signal.kind.value for signal in analysis.signals})
                ),
            )
        )

    @staticmethod
    def claimed_institutions(analysis: AnalysisResult) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    str(signal.attributes["institution"]).strip().lower()
                    for signal in analysis.signals
                    if signal.kind == SignalKind.CLAIMED_IDENTITY
                    and signal.attributes.get("institution")
                }
            )
        )
