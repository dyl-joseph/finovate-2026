"""Supabase/Postgres persistence for conversations and speaker encounters."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

import psycopg
from psycopg import Connection
from psycopg.errors import ForeignKeyViolation, UniqueViolation
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .api_storage import (
    ConversationExistsError,
    ConversationNotFoundError,
    SegmentConflictError,
    StoredConversation,
    StoredTurn,
)
from .memory import EncounterRecord


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS conversations (
    conversation_id TEXT PRIMARY KEY,
    caller_speaker_id TEXT,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    financial_context_json JSONB,
    speaker_identity_json JSONB,
    assessment_json JSONB
);

CREATE TABLE IF NOT EXISTS transcript_turns (
    conversation_id TEXT NOT NULL REFERENCES conversations(conversation_id)
        ON DELETE CASCADE,
    segment_id TEXT NOT NULL,
    speaker_id TEXT NOT NULL,
    role TEXT NOT NULL,
    text TEXT NOT NULL,
    start_ms BIGINT NOT NULL,
    end_ms BIGINT NOT NULL,
    PRIMARY KEY (conversation_id, segment_id)
);

CREATE INDEX IF NOT EXISTS idx_transcript_turns_time
    ON transcript_turns (conversation_id, start_ms, end_ms);

CREATE TABLE IF NOT EXISTS speaker_encounters (
    conversation_id TEXT PRIMARY KEY,
    speaker_profile_id TEXT NOT NULL,
    risk_score INTEGER NOT NULL,
    risk_level TEXT NOT NULL,
    claimed_institutions_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    signal_kinds_json JSONB NOT NULL DEFAULT '[]'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_speaker_encounters_profile
    ON speaker_encounters (speaker_profile_id);

ALTER TABLE conversations ENABLE ROW LEVEL SECURITY;
ALTER TABLE transcript_turns ENABLE ROW LEVEL SECURITY;
ALTER TABLE speaker_encounters ENABLE ROW LEVEL SECURITY;
"""


class _PostgresRepository:
    def __init__(self, database_url: str) -> None:
        if not database_url.strip():
            raise ValueError("database_url cannot be empty")
        self._database_url = database_url
        self._create_schema()

    @contextmanager
    def _connection(self) -> Iterator[Connection[dict[str, Any]]]:
        # Supabase's transaction pooler does not support named prepared statements.
        with psycopg.connect(
            self._database_url,
            row_factory=dict_row,
            prepare_threshold=None,
            connect_timeout=10,
        ) as connection:
            yield connection

    def _create_schema(self) -> None:
        with self._connection() as connection:
            connection.execute(SCHEMA_SQL)

    def close(self) -> None:
        """Connections are short lived, so there is no pool to close."""


class PostgresConversationRepository(_PostgresRepository):
    """Persist API state in Supabase or another PostgreSQL database."""

    def create_conversation(
        self,
        conversation_id: str,
        caller_speaker_id: str | None,
        metadata: dict[str, Any],
    ) -> StoredConversation:
        try:
            with self._connection() as connection:
                connection.execute(
                    """
                    INSERT INTO conversations (
                        conversation_id, caller_speaker_id, metadata_json
                    ) VALUES (%s, %s, %s)
                    """,
                    (conversation_id, caller_speaker_id, Jsonb(metadata)),
                )
        except UniqueViolation as exc:
            raise ConversationExistsError(
                f"conversation {conversation_id} already exists"
            ) from exc
        return self.get_conversation(conversation_id)

    def get_conversation(self, conversation_id: str) -> StoredConversation:
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT conversation_id, caller_speaker_id, metadata_json,
                       financial_context_json, speaker_identity_json,
                       assessment_json
                FROM conversations
                WHERE conversation_id = %s
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
            metadata=row["metadata_json"],
            financial_context=row["financial_context_json"],
            speaker_identity=row["speaker_identity_json"],
            assessment=row["assessment_json"],
        )

    def add_turn(self, conversation_id: str, turn: StoredTurn) -> bool:
        self.get_conversation(conversation_id)
        try:
            with self._connection() as connection:
                inserted = connection.execute(
                    """
                    INSERT INTO transcript_turns (
                        conversation_id, segment_id, speaker_id, role,
                        text, start_ms, end_ms
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (conversation_id, segment_id) DO NOTHING
                    RETURNING segment_id
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
                ).fetchone()
                if inserted is not None:
                    return True
                existing = connection.execute(
                    """
                    SELECT segment_id, speaker_id, role, text, start_ms, end_ms
                    FROM transcript_turns
                    WHERE conversation_id = %s AND segment_id = %s
                    """,
                    (conversation_id, turn.segment_id),
                ).fetchone()
        except ForeignKeyViolation as exc:
            raise ConversationNotFoundError(
                f"conversation {conversation_id} was not found"
            ) from exc

        stored = self._row_to_turn(existing)
        if stored == turn:
            return False
        raise SegmentConflictError(
            f"segment {turn.segment_id} already exists with different content"
        )

    def list_turns(self, conversation_id: str) -> tuple[StoredTurn, ...]:
        self.get_conversation(conversation_id)
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT segment_id, speaker_id, role, text, start_ms, end_ms
                FROM transcript_turns
                WHERE conversation_id = %s
                ORDER BY start_ms, end_ms, segment_id
                """,
                (conversation_id,),
            ).fetchall()
        return tuple(self._row_to_turn(row) for row in rows)

    def set_financial_context(
        self, conversation_id: str, context: dict[str, Any]
    ) -> None:
        self._set_json_field(conversation_id, "financial_context_json", context)

    def set_speaker_identity(
        self, conversation_id: str, identity: dict[str, Any]
    ) -> None:
        self._set_json_field(conversation_id, "speaker_identity_json", identity)

    def save_assessment(
        self, conversation_id: str, assessment: dict[str, Any]
    ) -> None:
        self._set_json_field(conversation_id, "assessment_json", assessment)

    def _set_json_field(
        self, conversation_id: str, column: str, value: dict[str, Any]
    ) -> None:
        allowed_columns = {
            "financial_context_json",
            "speaker_identity_json",
            "assessment_json",
        }
        if column not in allowed_columns:
            raise ValueError(f"unsupported JSON field: {column}")
        with self._connection() as connection:
            result = connection.execute(
                f"UPDATE conversations SET {column} = %s "
                "WHERE conversation_id = %s",
                (Jsonb(value), conversation_id),
            )
            if result.rowcount == 0:
                raise ConversationNotFoundError(
                    f"conversation {conversation_id} was not found"
                )

    @staticmethod
    def _row_to_turn(row: dict[str, Any] | None) -> StoredTurn:
        if row is None:
            raise RuntimeError("stored transcript turn disappeared")
        return StoredTurn(
            segment_id=row["segment_id"],
            speaker_id=row["speaker_id"],
            role=row["role"],
            text=row["text"],
            start_ms=row["start_ms"],
            end_ms=row["end_ms"],
        )


class PostgresEncounterRepository(_PostgresRepository):
    """Persist cross-call speaker memory in Supabase/Postgres."""

    def save(self, encounter: EncounterRecord) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO speaker_encounters (
                    conversation_id, speaker_profile_id, risk_score, risk_level,
                    claimed_institutions_json, signal_kinds_json
                ) VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (conversation_id) DO UPDATE SET
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
                    Jsonb(encounter.claimed_institutions),
                    Jsonb(encounter.signal_kinds),
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
            WHERE speaker_profile_id = %s
        """
        parameters: list[str] = [speaker_profile_id]
        if exclude_conversation_id is not None:
            query += " AND conversation_id != %s"
            parameters.append(exclude_conversation_id)
        query += " ORDER BY conversation_id"

        with self._connection() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return tuple(
            EncounterRecord(
                conversation_id=row["conversation_id"],
                speaker_profile_id=row["speaker_profile_id"],
                risk_score=row["risk_score"],
                risk_level=row["risk_level"],
                claimed_institutions=tuple(row["claimed_institutions_json"]),
                signal_kinds=tuple(row["signal_kinds_json"]),
            )
            for row in rows
        )
