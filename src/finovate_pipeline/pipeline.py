"""End-to-end orchestration from transcript through explainable risk."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal
from enum import Enum
from typing import Any

from .financial import FinancialContext, FinancialContextVerifier, FinancialFinding
from .graph import EvidenceGraph, EvidenceGraphBuilder
from .intelligence import TranscriptIntelligence
from .memory import EncounterMemory, MemoryFinding, SpeakerIdentity
from .models import AnalysisResult, Transcript
from .recommendations import RecommendationEngine, VerificationRecommendation
from .risk import RiskAssessment, RiskEngine


@dataclass(frozen=True, slots=True)
class PipelineResult:
    conversation_id: str
    transcript_analysis: AnalysisResult
    financial_findings: tuple[FinancialFinding, ...]
    memory_findings: tuple[MemoryFinding, ...]
    risk: RiskAssessment
    recommendations: tuple[VerificationRecommendation, ...]
    graph: EvidenceGraph

    def to_dict(self) -> dict[str, Any]:
        return _to_json_value(asdict(self))


class ScamAssessmentPipeline:
    """Run all post-transcript analysis stages through evidence graph creation."""

    def __init__(
        self,
        intelligence: TranscriptIntelligence | None = None,
        financial_verifier: FinancialContextVerifier | None = None,
        risk_engine: RiskEngine | None = None,
        graph_builder: EvidenceGraphBuilder | None = None,
        encounter_memory: EncounterMemory | None = None,
        recommendation_engine: RecommendationEngine | None = None,
    ) -> None:
        self._intelligence = intelligence or TranscriptIntelligence()
        self._financial_verifier = financial_verifier or FinancialContextVerifier()
        self._risk_engine = risk_engine or RiskEngine()
        self._graph_builder = graph_builder or EvidenceGraphBuilder()
        self._encounter_memory = encounter_memory or EncounterMemory()
        self._recommendation_engine = recommendation_engine or RecommendationEngine()

    def analyze(
        self,
        transcript: Transcript,
        financial_context: FinancialContext,
        speaker_identity: SpeakerIdentity | None = None,
    ) -> PipelineResult:
        analysis = self._intelligence.analyze(transcript)
        findings = self._financial_verifier.verify(analysis, financial_context)
        memory_findings = self._encounter_memory.evaluate(
            transcript.conversation_id,
            speaker_identity,
            analysis,
        )
        risk = self._risk_engine.assess(analysis, findings, memory_findings)
        recommendations = self._recommendation_engine.recommend(
            analysis,
            findings,
            memory_findings,
            risk,
        )
        graph = self._graph_builder.build(
            analysis,
            financial_context,
            findings,
            risk,
            memory_findings,
            recommendations,
        )
        result = PipelineResult(
            conversation_id=transcript.conversation_id,
            transcript_analysis=analysis,
            financial_findings=findings,
            memory_findings=memory_findings,
            risk=risk,
            recommendations=recommendations,
            graph=graph,
        )
        self._encounter_memory.remember(
            transcript.conversation_id,
            speaker_identity,
            analysis,
            risk.score,
            risk.level.value,
        )
        return result


def _to_json_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {key: _to_json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_json_value(item) for item in value]
    return value
