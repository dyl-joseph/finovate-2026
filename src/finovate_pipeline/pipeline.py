"""End-to-end orchestration from transcript through explainable risk."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal
from enum import Enum
from typing import Any

from .financial import FinancialContext, FinancialContextVerifier, FinancialFinding
from .graph import EvidenceGraph, EvidenceGraphBuilder
from .intelligence import TranscriptIntelligence
from .models import AnalysisResult, Transcript
from .risk import RiskAssessment, RiskEngine


@dataclass(frozen=True, slots=True)
class PipelineResult:
    conversation_id: str
    transcript_analysis: AnalysisResult
    financial_findings: tuple[FinancialFinding, ...]
    risk: RiskAssessment
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
    ) -> None:
        self._intelligence = intelligence or TranscriptIntelligence()
        self._financial_verifier = financial_verifier or FinancialContextVerifier()
        self._risk_engine = risk_engine or RiskEngine()
        self._graph_builder = graph_builder or EvidenceGraphBuilder()

    def analyze(
        self,
        transcript: Transcript,
        financial_context: FinancialContext,
    ) -> PipelineResult:
        analysis = self._intelligence.analyze(transcript)
        findings = self._financial_verifier.verify(analysis, financial_context)
        risk = self._risk_engine.assess(analysis, findings)
        graph = self._graph_builder.build(analysis, financial_context, findings, risk)
        return PipelineResult(
            conversation_id=transcript.conversation_id,
            transcript_analysis=analysis,
            financial_findings=findings,
            risk=risk,
            graph=graph,
        )


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
