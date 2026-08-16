"""Persistent conversation state for the HTTP service."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any


class ConversationNotFoundError(LookupError):
    pass


class ConversationExistsError(ValueError):
    pass


class SegmentConflictError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class StoredConversation:
    conversation_id: str
    caller_speaker_id: str | None
    metadata: dict[str, Any]
    financial_context: dict[str, Any] | None
    speaker_identity: dict[str, Any] | None
    assessment: dict[str, Any] | None


@dataclass(frozen=True, slots=True)
class StoredTurn:
    segment_id: str
    speaker_id: str
    role: str
    text: str
    start_ms: int
    end_ms: int

    def to_transcript_dict(self) -> dict[str, Any]:
        return {
            "speaker_id": self.speaker_id,
            "role": self.role,
            "text": self.text,
            "start_ms": self.start_ms,
            "end_ms": self.end_ms,
        }


class SQLiteConversationRepository:
    """Store conversations and finalized transcript turns in SQLite."""

    def __init__(self, database: str | Path = ":memory:") -> None:
        self._connection = sqlite3.connect(str(database), check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._lock = RLock()
        self._create_schema()

    def _create_schema(self) -> None:
        with self._lock, self._connection:
            self._connection.execute("PRAGMA foreign_keys = ON")
            self._connection.execute("PRAGMA busy_timeout = 5000")
            self._connection.execute("PRAGMA journal_mode = WAL")
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    conversation_id TEXT PRIMARY KEY,
                    caller_speaker_id TEXT,
                    metadata_json TEXT NOT NULL,
                    financial_context_json TEXT,
                    speaker_identity_json TEXT,
                    assessment_json TEXT
                )
                """
            )
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS transcript_turns (
                    conversation_id TEXT NOT NULL,
                    segment_id TEXT NOT NULL,
                    speaker_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    text TEXT NOT NULL,
                    start_ms INTEGER NOT NULL,
                    end_ms INTEGER NOT NULL,
                    PRIMARY KEY (conversation_id, segment_id),
                    FOREIGN KEY (conversation_id)
                        REFERENCES conversations(conversation_id)
                        ON DELETE CASCADE
                )
                """
            )
            self._connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_transcript_turns_time
                ON transcript_turns (conversation_id, start_ms, end_ms)
                """
            )

    def create_conversation(
        self,
        conversation_id: str,
        caller_speaker_id: str | None,
        metadata: dict[str, Any],
    ) -> StoredConversation:
        try:
            with self._lock, self._connection:
                self._connection.execute(
                    """
                    INSERT INTO conversations (
                        conversation_id,
                        caller_speaker_id,
                        metadata_json
                    ) VALUES (?, ?, ?)
                    """,
                    (
                        conversation_id,
                        caller_speaker_id,
                        json.dumps(metadata),
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise ConversationExistsError(
                f"conversation {conversation_id} already exists"
            ) from exc
        return self.get_conversation(conversation_id)

    def get_conversation(self, conversation_id: str) -> StoredConversation:
        with self._lock:
            row = self._connection.execute(
                """
                SELECT conversation_id, caller_speaker_id, metadata_json,
                       financial_context_json, speaker_identity_json,
                       assessment_json
                FROM conversations
                WHERE conversation_id = ?
                """,
                (conversation_id,),
            ).fetchone()
        if row is None:
            raise ConversationNotFoundError(
                f"conversation {conversation_id} was not found"
            )
        return StoredConversation(
            conversation_id=row["conversation_id"],
            caller_speaker_id=row["caller_speaker_id"],
            metadata=json.loads(row["metadata_json"]),
            financial_context=self._load_optional_json(
                row["financial_context_json"]
            ),
            speaker_identity=self._load_optional_json(row["speaker_identity_json"]),
            assessment=self._load_optional_json(row["assessment_json"]),
        )

    def add_turn(self, conversation_id: str, turn: StoredTurn) -> bool:
        self.get_conversation(conversation_id)
        with self._lock:
            existing = self._connection.execute(
                """
                SELECT segment_id, speaker_id, role, text, start_ms, end_ms
                FROM transcript_turns
                WHERE conversation_id = ? AND segment_id = ?
                """,
                (conversation_id, turn.segment_id),
            ).fetchone()
            if existing is not None:
                stored = self._row_to_turn(existing)
                if stored == turn:
                    return False
                raise SegmentConflictError(
                    f"segment {turn.segment_id} already exists with different content"
                )

            with self._connection:
                self._connection.execute(
                    """
                    INSERT INTO transcript_turns (
                        conversation_id, segment_id, speaker_id, role,
                        text, start_ms, end_ms
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        conversation_id,
                        turn.segment_id,
                        turn.speaker_id,
                        turn.role,
                        turn.text,
                        turn.start_ms,
                        turn.end_ms,
                    ),
                )
        return True

    def list_turns(self, conversation_id: str) -> tuple[StoredTurn, ...]:
        self.get_conversation(conversation_id)
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT segment_id, speaker_id, role, text, start_ms, end_ms
                FROM transcript_turns
                WHERE conversation_id = ?
                ORDER BY start_ms, end_ms, segment_id
                """,
                (conversation_id,),
            ).fetchall()
        return tuple(self._row_to_turn(row) for row in rows)

    def set_financial_context(
        self,
        conversation_id: str,
        context: dict[str, Any],
    ) -> None:
        self._set_json_field(
            conversation_id,
            "financial_context_json",
            context,
        )

    def set_speaker_identity(
        self,
        conversation_id: str,
        identity: dict[str, Any],
    ) -> None:
        self._set_json_field(
            conversation_id,
            "speaker_identity_json",
            identity,
        )

    def save_assessment(
        self,
        conversation_id: str,
        assessment: dict[str, Any],
    ) -> None:
        self._set_json_field(conversation_id, "assessment_json", assessment)

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def _set_json_field(
        self,
        conversation_id: str,
        column: str,
        value: dict[str, Any],
    ) -> None:
        allowed_columns = {
            "financial_context_json",
            "speaker_identity_json",
            "assessment_json",
        }
        if column not in allowed_columns:
            raise ValueError(f"unsupported JSON field: {column}")
        self.get_conversation(conversation_id)
        with self._lock, self._connection:
            self._connection.execute(
                f"UPDATE conversations SET {column} = ? WHERE conversation_id = ?",
                (json.dumps(value), conversation_id),
            )

    @staticmethod
    def _load_optional_json(value: str | None) -> dict[str, Any] | None:
        return json.loads(value) if value is not None else None

    @staticmethod
    def _row_to_turn(row: sqlite3.Row) -> StoredTurn:
        return StoredTurn(
            segment_id=row["segment_id"],
            speaker_id=row["speaker_id"],
            role=row["role"],
            text=row["text"],
            start_ms=row["start_ms"],
            end_ms=row["end_ms"],
        )
