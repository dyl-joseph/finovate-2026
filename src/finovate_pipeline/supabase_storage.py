"""Supabase Data API persistence for the post-transcript service."""

from __future__ import annotations

from typing import Any

import httpx

from .api_storage import (
    ConversationExistsError,
    ConversationNotFoundError,
    SegmentConflictError,
    StoredConversation,
    StoredTurn,
)
from .memory import EncounterRecord
from .voice import SpeakerProfile, SpeakerProfileRepository


class _SupabaseRepository:
    def __init__(self, supabase_url: str, secret_key: str) -> None:
        if not supabase_url.strip() or not secret_key.strip():
            raise ValueError("supabase_url and secret_key cannot be empty")
        self._client = httpx.Client(
            base_url=f"{supabase_url.rstrip('/')}/rest/v1/",
            headers={
                "apikey": secret_key,
                "Authorization": f"Bearer {secret_key}",
                "Content-Type": "application/json",
            },
            timeout=15.0,
        )

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = response.text[:500]
            raise RuntimeError(
                f"Supabase request failed ({response.status_code}): {detail}"
            ) from exc

    def close(self) -> None:
        self._client.close()


class SupabaseConversationRepository(_SupabaseRepository):
    """Persist API state through Supabase's server-side Data API."""

    _SELECT = (
        "conversation_id,caller_speaker_id,metadata_json,"
        "financial_context_json,speaker_identity_json,assessment_json"
    )

    def create_conversation(
        self,
        conversation_id: str,
        caller_speaker_id: str | None,
        metadata: dict[str, Any],
    ) -> StoredConversation:
        response = self._client.post(
            "conversations",
            headers={"Prefer": "return=representation"},
            json={
                "conversation_id": conversation_id,
                "caller_speaker_id": caller_speaker_id,
                "metadata_json": metadata,
            },
        )
        if response.status_code == 409:
            raise ConversationExistsError(
                f"conversation {conversation_id} already exists"
            )
        self._raise_for_status(response)
        return self._row_to_conversation(response.json()[0])

    def get_conversation(self, conversation_id: str) -> StoredConversation:
        response = self._client.get(
            "conversations",
            params={
                "conversation_id": f"eq.{conversation_id}",
                "select": self._SELECT,
                "limit": "1",
            },
        )
        self._raise_for_status(response)
        rows = response.json()
        if not rows:
            raise ConversationNotFoundError(
                f"conversation {conversation_id} was not found"
            )
        return self._row_to_conversation(rows[0])

    def add_turn(self, conversation_id: str, turn: StoredTurn) -> bool:
        self.get_conversation(conversation_id)
        response = self._client.post(
            "transcript_turns",
            params={"on_conflict": "conversation_id,segment_id"},
            headers={"Prefer": "resolution=ignore-duplicates,return=representation"},
            json={
                "conversation_id": conversation_id,
                **turn.to_transcript_dict(),
                "segment_id": turn.segment_id,
            },
        )
        self._raise_for_status(response)
        if response.json():
            return True

        existing_response = self._client.get(
            "transcript_turns",
            params={
                "conversation_id": f"eq.{conversation_id}",
                "segment_id": f"eq.{turn.segment_id}",
                "select": "segment_id,speaker_id,role,text,start_ms,end_ms",
                "limit": "1",
            },
        )
        self._raise_for_status(existing_response)
        rows = existing_response.json()
        if rows and self._row_to_turn(rows[0]) == turn:
            return False
        raise SegmentConflictError(
            f"segment {turn.segment_id} already exists with different content"
        )

    def list_turns(self, conversation_id: str) -> tuple[StoredTurn, ...]:
        self.get_conversation(conversation_id)
        response = self._client.get(
            "transcript_turns",
            params={
                "conversation_id": f"eq.{conversation_id}",
                "select": "segment_id,speaker_id,role,text,start_ms,end_ms",
                "order": "start_ms.asc,end_ms.asc,segment_id.asc",
            },
        )
        self._raise_for_status(response)
        return tuple(self._row_to_turn(row) for row in response.json())

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
        response = self._client.patch(
            "conversations",
            params={"conversation_id": f"eq.{conversation_id}"},
            headers={"Prefer": "return=representation"},
            json={column: value},
        )
        self._raise_for_status(response)
        if not response.json():
            raise ConversationNotFoundError(
                f"conversation {conversation_id} was not found"
            )

    @staticmethod
    def _row_to_conversation(row: dict[str, Any]) -> StoredConversation:
        return StoredConversation(
            conversation_id=row["conversation_id"],
            caller_speaker_id=row["caller_speaker_id"],
            metadata=row["metadata_json"],
            financial_context=row["financial_context_json"],
            speaker_identity=row["speaker_identity_json"],
            assessment=row["assessment_json"],
        )

    @staticmethod
    def _row_to_turn(row: dict[str, Any]) -> StoredTurn:
        return StoredTurn(
            segment_id=row["segment_id"],
            speaker_id=row["speaker_id"],
            role=row["role"],
            text=row["text"],
            start_ms=row["start_ms"],
            end_ms=row["end_ms"],
        )


class SupabaseEncounterRepository(_SupabaseRepository):
    """Persist speaker memory through Supabase's server-side Data API."""

    def save(self, encounter: EncounterRecord) -> None:
        response = self._client.post(
            "speaker_encounters",
            params={"on_conflict": "conversation_id"},
            headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
            json={
                "conversation_id": encounter.conversation_id,
                "speaker_profile_id": encounter.speaker_profile_id,
                "risk_score": encounter.risk_score,
                "risk_level": encounter.risk_level,
                "claimed_institutions_json": list(encounter.claimed_institutions),
                "signal_kinds_json": list(encounter.signal_kinds),
            },
        )
        self._raise_for_status(response)

    def find_by_speaker(
        self,
        speaker_profile_id: str,
        exclude_conversation_id: str | None = None,
    ) -> tuple[EncounterRecord, ...]:
        params = {
            "speaker_profile_id": f"eq.{speaker_profile_id}",
            "select": (
                "conversation_id,speaker_profile_id,risk_score,risk_level,"
                "claimed_institutions_json,signal_kinds_json"
            ),
            "order": "conversation_id.asc",
        }
        if exclude_conversation_id is not None:
            params["conversation_id"] = f"neq.{exclude_conversation_id}"
        response = self._client.get("speaker_encounters", params=params)
        self._raise_for_status(response)
        return tuple(
            EncounterRecord(
                conversation_id=row["conversation_id"],
                speaker_profile_id=row["speaker_profile_id"],
                risk_score=row["risk_score"],
                risk_level=row["risk_level"],
                claimed_institutions=tuple(row["claimed_institutions_json"]),
                signal_kinds=tuple(row["signal_kinds_json"]),
            )
            for row in response.json()
        )


class SupabaseSpeakerProfileRepository(_SupabaseRepository):
    """Persist voice profiles through Supabase's server-side Data API."""

    def list_profiles(self) -> tuple[SpeakerProfile, ...]:
        response = self._client.get(
            "speaker_profiles",
            params={
                "select": "profile_id,embedding_json,sample_count,last_seen_at",
                "order": "profile_id.asc",
                "limit": "10000",
            },
        )
        self._raise_for_status(response)
        return tuple(
            SpeakerProfile(
                profile_id=row["profile_id"],
                embedding=tuple(row["embedding_json"]),
                sample_count=row["sample_count"],
                last_seen_at=row["last_seen_at"],
            )
            for row in response.json()
        )

    def upsert(self, profile: SpeakerProfile) -> None:
        response = self._client.post(
            "speaker_profiles",
            params={"on_conflict": "profile_id"},
            headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
            json={
                "profile_id": profile.profile_id,
                "embedding_json": list(profile.embedding),
                "sample_count": profile.sample_count,
                "last_seen_at": profile.last_seen_at,
            },
        )
        self._raise_for_status(response)
