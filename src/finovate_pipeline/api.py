"""FastAPI transport for the post-transcript scam intelligence pipeline."""

from __future__ import annotations

import os
import secrets
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, Literal
from uuid import uuid4

from fastapi import Body, Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .api_storage import (
    ConversationExistsError,
    ConversationNotFoundError,
    SegmentConflictError,
    SQLiteConversationRepository,
    StoredConversation,
    StoredTurn,
)
from .financial import FinancialContext
from .memory import EncounterMemory, SpeakerIdentity, SQLiteEncounterRepository
from .models import Transcript
from .pipeline import ScamAssessmentPipeline
from .voice import (
    DEFAULT_MATCH_THRESHOLD,
    VoiceEmbedder,
    VoiceMatcher,
    VoiceMatch,
    SQLiteSpeakerProfileRepository,
)


@dataclass(frozen=True, slots=True)
class ApiSettings:
    database_path: str = ":memory:"
    database_url: str | None = None
    supabase_url: str | None = None
    supabase_secret_key: str | None = None
    ingest_api_key: str = "dev-only-change-me"
    cors_origins: tuple[str, ...] = ("http://localhost:3000",)
    environment: str = "development"
    voice_match_threshold: float = DEFAULT_MATCH_THRESHOLD

    def __post_init__(self) -> None:
        if not self.ingest_api_key:
            raise ValueError("ingest_api_key cannot be empty")
        if (
            self.environment.lower() == "production"
            and self.ingest_api_key == "dev-only-change-me"
        ):
            raise ValueError(
                "TRANSCRIPT_INGEST_API_KEY must be set in production"
            )
        if bool(self.supabase_url) != bool(self.supabase_secret_key):
            raise ValueError(
                "SUPABASE_URL and SUPABASE_SECRET_KEY must be set together"
            )

    @classmethod
    def from_env(cls) -> ApiSettings:
        origins = tuple(
            origin.strip()
            for origin in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
            if origin.strip()
        )
        return cls(
            database_path=os.getenv("DATABASE_PATH", ":memory:"),
            database_url=os.getenv("DATABASE_URL") or None,
            supabase_url=os.getenv("SUPABASE_URL") or None,
            supabase_secret_key=os.getenv("SUPABASE_SECRET_KEY") or None,
            ingest_api_key=os.getenv(
                "TRANSCRIPT_INGEST_API_KEY", "dev-only-change-me"
            ),
            cors_origins=origins,
            environment=os.getenv("APP_ENV", "development"),
            voice_match_threshold=float(
                os.getenv("VOICE_MATCH_THRESHOLD", DEFAULT_MATCH_THRESHOLD)
            ),
        )


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateConversationRequest(ApiModel):
    conversation_id: str | None = Field(default=None, min_length=1, max_length=128)
    caller_speaker_id: str | None = Field(default=None, min_length=1, max_length=128)
    metadata: dict[str, Any] = Field(default_factory=dict)


class TranscriptTurnRequest(ApiModel):
    segment_id: str = Field(min_length=1, max_length=128)
    speaker_id: str = Field(min_length=1, max_length=128)
    role: Literal["caller", "customer", "unknown"] = "unknown"
    text: str = Field(min_length=1)
    start_ms: int = Field(ge=0)
    end_ms: int = Field(ge=0)
    is_final: bool

    @model_validator(mode="after")
    def validate_timestamps(self) -> TranscriptTurnRequest:
        if self.end_ms < self.start_ms:
            raise ValueError("end_ms cannot be before start_ms")
        return self


MoneyValue = str | int | float


class TransactionRequest(ApiModel):
    transaction_id: str = Field(min_length=1)
    amount: MoneyValue
    merchant: str = "Unknown merchant"
    status: str = "posted"


class RecipientRequest(ApiModel):
    recipient_id: str = Field(min_length=1)
    name: str = "Unknown recipient"
    previous_transfer_count: int = Field(default=0, ge=0)


class AccountRequest(ApiModel):
    account_id: str = Field(min_length=1)
    available_balance: MoneyValue
    transactions: list[TransactionRequest] = Field(default_factory=list)
    recipients: list[RecipientRequest] = Field(default_factory=list)


class TransferIntentRequest(ApiModel):
    amount: MoneyValue
    recipient_id: str = Field(min_length=1)
    recipient_name: str = "Unknown recipient"


class FinancialContextRequest(ApiModel):
    customer_id: str = Field(min_length=1)
    primary_account_id: str = Field(min_length=1)
    accounts: list[AccountRequest] = Field(min_length=1)
    transfer_intent: TransferIntentRequest | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SpeakerIdentityRequest(ApiModel):
    profile_id: str = Field(min_length=1)
    match_confidence: float = Field(ge=0.0, le=1.0)
    source: str = "upstream_speaker_match"


class ConversationResponse(ApiModel):
    conversation_id: str
    status: Literal["collecting", "assessed"]
    assessment: dict[str, Any] | None


class TurnIngestResponse(ConversationResponse):
    segment_id: str
    duplicate_segment: bool


class VoiceMatchResponse(ApiModel):
    profile_id: str
    confidence: float
    is_new: bool
    similarity: float


class SpeakerIdentityInferResponse(ConversationResponse):
    speaker_identity: dict[str, Any] | None
    voice_match: VoiceMatchResponse | None


class HealthResponse(ApiModel):
    status: Literal["ok"]
    service: str


def create_app(settings: ApiSettings | None = None) -> FastAPI:
    resolved_settings = settings or ApiSettings.from_env()
    if resolved_settings.supabase_url and resolved_settings.supabase_secret_key:
        from .supabase_storage import (
            SupabaseConversationRepository,
            SupabaseEncounterRepository,
            SupabaseSpeakerProfileRepository,
        )

        conversation_repository = SupabaseConversationRepository(
            resolved_settings.supabase_url,
            resolved_settings.supabase_secret_key,
        )
        encounter_repository = SupabaseEncounterRepository(
            resolved_settings.supabase_url,
            resolved_settings.supabase_secret_key,
        )
        speaker_profile_repository = SupabaseSpeakerProfileRepository(
            resolved_settings.supabase_url,
            resolved_settings.supabase_secret_key,
        )
    elif resolved_settings.database_url:
        from .postgres_storage import (
            PostgresConversationRepository,
            PostgresEncounterRepository,
        )

        conversation_repository = PostgresConversationRepository(
            resolved_settings.database_url
        )
        encounter_repository = PostgresEncounterRepository(
            resolved_settings.database_url
        )
        speaker_profile_repository = SQLiteSpeakerProfileRepository(
            resolved_settings.database_path
        )
    else:
        conversation_repository = SQLiteConversationRepository(
            resolved_settings.database_path
        )
        encounter_repository = SQLiteEncounterRepository(
            resolved_settings.database_path
        )
        speaker_profile_repository = SQLiteSpeakerProfileRepository(
            resolved_settings.database_path
        )
    pipeline = ScamAssessmentPipeline(
        encounter_memory=EncounterMemory(encounter_repository)
    )
    voice_matcher = VoiceMatcher(
        speaker_profile_repository,
        threshold=resolved_settings.voice_match_threshold,
    )
    bearer = HTTPBearer(auto_error=False)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        conversation_repository.close()
        encounter_repository.close()
        if hasattr(speaker_profile_repository, "close"):
            speaker_profile_repository.close()

    application = FastAPI(
        title="Finovate Scam Intelligence API",
        description=(
            "Accept finalized speaker-labelled transcript turns and return "
            "explainable financial scam assessments."
        ),
        version="0.1.0",
        lifespan=lifespan,
    )
    application.state.settings = resolved_settings
    application.state.conversation_repository = conversation_repository

    if resolved_settings.cors_origins:
        application.add_middleware(
            CORSMiddleware,
            allow_origins=list(resolved_settings.cors_origins),
            allow_credentials=False,
            allow_methods=["GET", "POST", "PUT", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type"],
        )

    def require_ingest_auth(
        credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    ) -> None:
        if (
            credentials is None
            or credentials.scheme.lower() != "bearer"
            or not secrets.compare_digest(
                credentials.credentials,
                resolved_settings.ingest_api_key,
            )
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or missing ingestion API key",
                headers={"WWW-Authenticate": "Bearer"},
            )

    def get_conversation_or_404(conversation_id: str) -> StoredConversation:
        try:
            return conversation_repository.get_conversation(conversation_id)
        except ConversationNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(exc),
            ) from exc

    def analyze_conversation(conversation_id: str) -> dict[str, Any] | None:
        conversation = get_conversation_or_404(conversation_id)
        turns = conversation_repository.list_turns(conversation_id)
        if not turns:
            return None

        transcript = Transcript.from_dict(
            {
                "conversation_id": conversation.conversation_id,
                "caller_speaker_id": conversation.caller_speaker_id,
                "turns": [turn.to_transcript_dict() for turn in turns],
                "metadata": conversation.metadata,
            }
        )
        financial_context = (
            FinancialContext.from_dict(conversation.financial_context)
            if conversation.financial_context is not None
            else None
        )
        speaker_identity = (
            SpeakerIdentity.from_dict(conversation.speaker_identity)
            if conversation.speaker_identity is not None
            else None
        )
        result = pipeline.analyze(
            transcript,
            financial_context,
            speaker_identity,
        ).to_dict()
        conversation_repository.save_assessment(conversation_id, result)
        return result

    def response_for(
        conversation_id: str,
        assessment: dict[str, Any] | None,
    ) -> ConversationResponse:
        return ConversationResponse(
            conversation_id=conversation_id,
            status="assessed" if assessment is not None else "collecting",
            assessment=assessment,
        )

    @application.get("/health", response_model=HealthResponse, tags=["system"])
    def health() -> HealthResponse:
        return HealthResponse(status="ok", service="finovate-scam-intelligence")

    @application.post(
        "/v1/conversations",
        response_model=ConversationResponse,
        status_code=status.HTTP_201_CREATED,
        tags=["conversations"],
        dependencies=[Depends(require_ingest_auth)],
    )
    def create_conversation(
        payload: CreateConversationRequest,
    ) -> ConversationResponse:
        conversation_id = payload.conversation_id or str(uuid4())
        try:
            conversation_repository.create_conversation(
                conversation_id,
                payload.caller_speaker_id,
                payload.metadata,
            )
        except ConversationExistsError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
            ) from exc
        return response_for(conversation_id, None)

    @application.post(
        "/v1/conversations/{conversation_id}/turns",
        response_model=TurnIngestResponse,
        tags=["transcript"],
        dependencies=[Depends(require_ingest_auth)],
    )
    def ingest_turn(
        conversation_id: str,
        payload: TranscriptTurnRequest,
    ) -> TurnIngestResponse:
        if not payload.is_final:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Only finalized transcript turns are accepted",
            )
        try:
            inserted = conversation_repository.add_turn(
                conversation_id,
                StoredTurn(
                    segment_id=payload.segment_id,
                    speaker_id=payload.speaker_id,
                    role=payload.role,
                    text=payload.text,
                    start_ms=payload.start_ms,
                    end_ms=payload.end_ms,
                ),
            )
        except ConversationNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(exc),
            ) from exc
        except SegmentConflictError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
            ) from exc

        assessment = (
            analyze_conversation(conversation_id)
            if inserted
            else get_conversation_or_404(conversation_id).assessment
        )
        return TurnIngestResponse(
            conversation_id=conversation_id,
            status="assessed",
            assessment=assessment,
            segment_id=payload.segment_id,
            duplicate_segment=not inserted,
        )

    @application.put(
        "/v1/conversations/{conversation_id}/financial-context",
        response_model=ConversationResponse,
        tags=["financial context"],
        dependencies=[Depends(require_ingest_auth)],
    )
    def set_financial_context(
        conversation_id: str,
        payload: FinancialContextRequest,
    ) -> ConversationResponse:
        context_data = payload.model_dump(mode="json")
        try:
            FinancialContext.from_dict(context_data)
            conversation_repository.set_financial_context(
                conversation_id,
                context_data,
            )
        except ConversationNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(exc),
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(exc),
            ) from exc
        return response_for(conversation_id, analyze_conversation(conversation_id))

    @application.put(
        "/v1/conversations/{conversation_id}/speaker-identity",
        response_model=ConversationResponse,
        tags=["speaker identity"],
        dependencies=[Depends(require_ingest_auth)],
    )
    def set_speaker_identity(
        conversation_id: str,
        payload: SpeakerIdentityRequest,
    ) -> ConversationResponse:
        identity_data = payload.model_dump(mode="json")
        try:
            SpeakerIdentity.from_dict(identity_data)
            conversation_repository.set_speaker_identity(
                conversation_id,
                identity_data,
            )
        except ConversationNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(exc),
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(exc),
            ) from exc
        return response_for(conversation_id, analyze_conversation(conversation_id))

    @application.post(
        "/v1/conversations/{conversation_id}/speaker-identity/from-audio",
        response_model=SpeakerIdentityInferResponse,
        tags=["speaker identity"],
        dependencies=[Depends(require_ingest_auth)],
    )
    def infer_speaker_identity_from_audio(
        conversation_id: str,
        audio: bytes = Body(default=b""),
        start_ms: int | None = None,
        end_ms: int | None = None,
    ) -> SpeakerIdentityInferResponse:
        """Identify the caller from a raw audio slice using local voice embeddings.

        The body is the raw audio (WebM/Ogg/WAV) covering the caller's speech
        window. A matched profile folds the new voice into its rolling
        embedding; a first-time caller gets a fresh profile. The resulting
        identity is stored on the conversation and the assessment recomputed,
        so repeat callers immediately surface ``REPEAT_FLAGGED_SPEAKER``.
        """
        get_conversation_or_404(conversation_id)
        if not audio:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Audio body is empty",
            )
        if start_ms is not None and end_ms is not None and end_ms < start_ms:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="end_ms cannot be before start_ms",
            )

        embedding = voice_matcher.embedder.embed(audio, start_ms, end_ms)
        if embedding is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    "Voice embedding is unavailable on this deployment; "
                    "install resemblyzer/torch or supply an upstream "
                    "speaker identity instead"
                ),
            )

        match: VoiceMatch = voice_matcher.identify(embedding)
        identity_data = {
            "profile_id": match.profile_id,
            "match_confidence": match.confidence,
            "source": "local_voice_embedding",
        }
        try:
            SpeakerIdentity.from_dict(identity_data)
            conversation_repository.set_speaker_identity(
                conversation_id,
                identity_data,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(exc),
            ) from exc

        assessment = analyze_conversation(conversation_id)
        return SpeakerIdentityInferResponse(
            conversation_id=conversation_id,
            status="assessed" if assessment is not None else "collecting",
            assessment=assessment,
            speaker_identity=identity_data,
            voice_match=VoiceMatchResponse(
                profile_id=match.profile_id,
                confidence=match.confidence,
                is_new=match.is_new,
                similarity=match.similarity,
            ),
        )

    @application.post(
        "/v1/conversations/{conversation_id}/analyze",
        response_model=ConversationResponse,
        tags=["analysis"],
        dependencies=[Depends(require_ingest_auth)],
    )
    def analyze(
        conversation_id: str,
    ) -> ConversationResponse:
        return response_for(conversation_id, analyze_conversation(conversation_id))

    @application.get(
        "/v1/conversations/{conversation_id}/assessment",
        response_model=ConversationResponse,
        tags=["analysis"],
    )
    def get_assessment(conversation_id: str) -> ConversationResponse:
        conversation = get_conversation_or_404(conversation_id)
        return response_for(conversation_id, conversation.assessment)

    return application


app = create_app()
