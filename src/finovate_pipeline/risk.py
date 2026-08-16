"""Explainable, deterministic scam risk scoring."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .financial import FinancialFinding
from .models import AnalysisResult, SignalKind


class RiskLevel(StrEnum):
    LOW = "low"
    GUARDED = "guarded"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass(frozen=True, slots=True)
class RiskFactor:
    factor_id: str
    code: str
    description: str
    weight: int
    source_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RiskAssessment:
    score: int
    level: RiskLevel
    factors: tuple[RiskFactor, ...]


_SIGNAL_WEIGHTS: dict[SignalKind, tuple[int, str]] = {
    SignalKind.CLAIMED_IDENTITY: (3, "Caller claimed an institutional identity."),
    SignalKind.CLAIMED_TRANSACTION: (4, "Caller claimed a financial event."),
    SignalKind.REQUESTED_TRANSFER: (25, "Caller requested movement of funds."),
    SignalKind.REQUESTED_CREDENTIALS: (35, "Caller requested sensitive credentials."),
    SignalKind.URGENCY: (10, "Caller used urgency or time pressure."),
    SignalKind.AUTHORITY: (5, "Caller invoked institutional authority."),
    SignalKind.SECRECY: (18, "Caller asked the customer to keep the interaction secret."),
    SignalKind.ISOLATION: (15, "Caller attempted to isolate the customer."),
    SignalKind.THREAT: (14, "Caller used a financial or legal threat."),
}


class RiskEngine:
    """Score unique signal categories plus verified financial findings."""

    def assess(
        self,
        analysis: AnalysisResult,
        findings: tuple[FinancialFinding, ...],
    ) -> RiskAssessment:
        factors: list[RiskFactor] = []

        for kind in SignalKind:
            matching = tuple(signal for signal in analysis.signals if signal.kind == kind)
            if not matching:
                continue
            weight, description = _SIGNAL_WEIGHTS[kind]
            factors.append(
                RiskFactor(
                    factor_id=f"factor-signal-{kind.value}",
                    code=kind.value,
                    description=description,
                    weight=weight,
                    source_ids=tuple(signal.signal_id for signal in matching),
                )
            )

        for finding in findings:
            factors.append(
                RiskFactor(
                    factor_id=f"factor-{finding.finding_id}",
                    code=finding.kind.value,
                    description=finding.description,
                    weight=finding.risk_weight,
                    source_ids=(finding.finding_id,),
                )
            )

        score = min(100, sum(factor.weight for factor in factors))
        return RiskAssessment(
            score=score,
            level=self._level(score),
            factors=tuple(factors),
        )

    @staticmethod
    def _level(score: int) -> RiskLevel:
        if score >= 75:
            return RiskLevel.CRITICAL
        if score >= 50:
            return RiskLevel.HIGH
        if score >= 25:
            return RiskLevel.GUARDED
        return RiskLevel.LOW
