"""Deterministic transcript intelligence for the hackathon MVP.

The extractor intentionally emits a stable evidence contract. A model-backed
extractor can replace these rules later without changing downstream consumers.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from .models import (
    AnalysisResult,
    EvidenceSignal,
    ScamStage,
    SignalKind,
    Transcript,
    TranscriptTurn,
)


@dataclass(frozen=True, slots=True)
class _Rule:
    kind: SignalKind
    stage: ScamStage
    pattern: re.Pattern[str]
    confidence: float


_RULES: tuple[_Rule, ...] = (
    _Rule(
        SignalKind.CLAIMED_IDENTITY,
        ScamStage.IDENTITY,
        re.compile(
            r"\b(?:i(?:'m| am) (?:calling )?from|calling (?:you )?from|"
            r"this is .{0,30}? (?:at|with|from))\s+(?P<institution>"
            r"chase|paypal|bank of america|comerica|microsoft|the irs|irs|"
            r"your bank|the fraud department)\b",
            re.IGNORECASE,
        ),
        0.92,
    ),
    _Rule(
        SignalKind.CLAIMED_TRANSACTION,
        ScamStage.CREDIBILITY,
        re.compile(
            r"\b(?:charge|transaction|payment|purchase|withdrawal)\b.{0,55}?"
            r"(?P<amount>\$\s?\d[\d,]*(?:\.\d{2})?)",
            re.IGNORECASE,
        ),
        0.88,
    ),
    _Rule(
        SignalKind.REQUESTED_TRANSFER,
        ScamStage.FINANCIAL_ACTION,
        re.compile(
            r"\b(?:transfer|send|move|wire|deposit)\b.{0,50}?"
            r"(?:(?P<amount>\$\s?\d[\d,]*(?:\.\d{2})?)|"
            r"(?:money|funds|balance|account))\b",
            re.IGNORECASE,
        ),
        0.96,
    ),
    _Rule(
        SignalKind.REQUESTED_CREDENTIALS,
        ScamStage.FINANCIAL_ACTION,
        re.compile(
            r"\b(?:tell|give|read|send|share|confirm)\b.{0,45}?"
            r"\b(?:password|passcode|pin|one[- ]time code|verification code|"
            r"security code|social security number|ssn)\b",
            re.IGNORECASE,
        ),
        0.97,
    ),
    _Rule(
        SignalKind.URGENCY,
        ScamStage.URGENCY,
        re.compile(
            r"\b(?:right now|immediately|urgent|act now|today only|"
            r"before it(?:'s| is) too late|do not delay|time is running out)\b",
            re.IGNORECASE,
        ),
        0.87,
    ),
    _Rule(
        SignalKind.AUTHORITY,
        ScamStage.CREDIBILITY,
        re.compile(
            r"\b(?:fraud department|security team|federal agent|police|"
            r"the irs|irs agent|bank investigator|government)\b",
            re.IGNORECASE,
        ),
        0.84,
    ),
    _Rule(
        SignalKind.SECRECY,
        ScamStage.ISOLATION,
        re.compile(
            r"\b(?:don't|do not|must not|never)\s+(?:tell|notify|contact|inform|"
            r"mention this to)\b",
            re.IGNORECASE,
        ),
        0.94,
    ),
    _Rule(
        SignalKind.ISOLATION,
        ScamStage.ISOLATION,
        re.compile(
            r"\b(?:stay on the (?:line|phone)|do not hang up|don't hang up|"
            r"do not call|don't call|keep this between us)\b",
            re.IGNORECASE,
        ),
        0.95,
    ),
    _Rule(
        SignalKind.THREAT,
        ScamStage.URGENCY,
        re.compile(
            r"\b(?:account (?:will be|is) (?:closed|frozen|suspended)|"
            r"you(?:'ll| will) be arrested|warrant|legal action|lose your money|"
            r"funds? (?:will be|are) at risk)\b",
            re.IGNORECASE,
        ),
        0.91,
    ),
)

_STAGE_ORDER = {
    ScamStage.IDENTITY: 0,
    ScamStage.CREDIBILITY: 1,
    ScamStage.URGENCY: 2,
    ScamStage.ISOLATION: 3,
    ScamStage.FINANCIAL_ACTION: 4,
}


class TranscriptIntelligence:
    """Extract explainable scam signals from speaker-labelled transcript turns."""

    def analyze(self, transcript: Transcript) -> AnalysisResult:
        signals: list[EvidenceSignal] = []

        for turn_index, turn in enumerate(transcript.turns):
            if not transcript.is_caller_turn(turn):
                continue
            signals.extend(self._extract_turn(turn, turn_index, len(signals)))

        stages = tuple(
            sorted({signal.stage for signal in signals}, key=_STAGE_ORDER.__getitem__)
        )
        return AnalysisResult(
            conversation_id=transcript.conversation_id,
            signals=tuple(signals),
            stages_reached=stages,
        )

    def _extract_turn(
        self,
        turn: TranscriptTurn,
        turn_index: int,
        signal_offset: int,
    ) -> Iterable[EvidenceSignal]:
        match_count = 0
        for rule in _RULES:
            match = rule.pattern.search(turn.text)
            if match is None:
                continue

            match_count += 1
            attributes = {
                key: value.strip()
                for key, value in match.groupdict().items()
                if value is not None
            }
            yield EvidenceSignal(
                signal_id=f"sig-{signal_offset + match_count:04d}",
                kind=rule.kind,
                stage=rule.stage,
                speaker_id=turn.speaker_id,
                turn_index=turn_index,
                start_ms=turn.start_ms,
                evidence_text=match.group(0),
                confidence=rule.confidence,
                attributes=attributes,
            )
