"""Turn evidence and risk into specific, safe verification actions."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .financial import FinancialFinding, FindingKind
from .memory import MemoryFinding, MemoryFindingKind
from .models import AnalysisResult, SignalKind
from .risk import RiskAssessment, RiskLevel


class RecommendationKind(StrEnum):
    END_CALL = "end_call"
    USE_OFFICIAL_CHANNEL = "use_official_channel"
    DO_NOT_SHARE_CREDENTIALS = "do_not_share_credentials"
    PAUSE_TRANSFER = "pause_transfer"
    VERIFY_RECIPIENT = "verify_recipient"
    REVIEW_ACCOUNT = "review_account"
    REPORT_REPEAT_SCAM = "report_repeat_scam"


class RecommendationPriority(StrEnum):
    URGENT = "urgent"
    HIGH = "high"
    MEDIUM = "medium"


@dataclass(frozen=True, slots=True)
class VerificationRecommendation:
    recommendation_id: str
    kind: RecommendationKind
    priority: RecommendationPriority
    action: str
    rationale: str
    source_ids: tuple[str, ...]


class RecommendationEngine:
    """Generate ordered recommendations without taking irreversible action."""

    def recommend(
        self,
        analysis: AnalysisResult,
        financial_findings: tuple[FinancialFinding, ...],
        memory_findings: tuple[MemoryFinding, ...],
        risk: RiskAssessment,
    ) -> tuple[VerificationRecommendation, ...]:
        recommendations: list[VerificationRecommendation] = []

        def add(
            kind: RecommendationKind,
            priority: RecommendationPriority,
            action: str,
            rationale: str,
            source_ids: tuple[str, ...],
        ) -> None:
            if any(item.kind == kind for item in recommendations):
                return
            recommendations.append(
                VerificationRecommendation(
                    recommendation_id=f"recommendation-{len(recommendations) + 1:04d}",
                    kind=kind,
                    priority=priority,
                    action=action,
                    rationale=rationale,
                    source_ids=source_ids,
                )
            )

        if risk.level in {RiskLevel.HIGH, RiskLevel.CRITICAL}:
            source_ids = tuple(factor.factor_id for factor in risk.factors)
            add(
                RecommendationKind.END_CALL,
                RecommendationPriority.URGENT,
                "End the call before sharing information or moving money.",
                "The combined conversation and financial evidence indicates high risk.",
                source_ids,
            )
            add(
                RecommendationKind.USE_OFFICIAL_CHANNEL,
                RecommendationPriority.URGENT,
                "Contact the institution using the number on the card or its official app.",
                "Caller-provided contact information cannot be independently trusted.",
                source_ids,
            )

        credential_signals = tuple(
            signal.signal_id
            for signal in analysis.signals
            if signal.kind == SignalKind.REQUESTED_CREDENTIALS
        )
        if credential_signals:
            add(
                RecommendationKind.DO_NOT_SHARE_CREDENTIALS,
                RecommendationPriority.URGENT,
                "Do not share passwords, PINs, or one-time verification codes.",
                "A legitimate institution should not request authentication secrets by phone.",
                credential_signals,
            )

        transfer_signals = tuple(
            signal.signal_id
            for signal in analysis.signals
            if signal.kind == SignalKind.REQUESTED_TRANSFER
        )
        if transfer_signals:
            add(
                RecommendationKind.PAUSE_TRANSFER,
                RecommendationPriority.URGENT,
                "Pause the transfer until the request is independently verified.",
                "The caller directed the customer to move funds.",
                transfer_signals,
            )

        for finding in financial_findings:
            if finding.kind == FindingKind.NEW_RECIPIENT:
                add(
                    RecommendationKind.VERIFY_RECIPIENT,
                    RecommendationPriority.HIGH,
                    "Verify the recipient through a previously trusted contact method.",
                    finding.description,
                    (finding.finding_id,),
                )
            elif finding.kind == FindingKind.CLAIMED_TRANSACTION_NOT_FOUND:
                add(
                    RecommendationKind.REVIEW_ACCOUNT,
                    RecommendationPriority.HIGH,
                    "Review account activity in the official banking app.",
                    finding.description,
                    (finding.finding_id,),
                )

        repeat_findings = tuple(
            finding
            for finding in memory_findings
            if finding.kind == MemoryFindingKind.REPEAT_FLAGGED_SPEAKER
        )
        if repeat_findings:
            add(
                RecommendationKind.REPORT_REPEAT_SCAM,
                RecommendationPriority.HIGH,
                "Report this repeat interaction to the bank's fraud team.",
                repeat_findings[0].description,
                tuple(finding.finding_id for finding in repeat_findings),
            )

        return tuple(recommendations)
