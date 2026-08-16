"""Frontend-ready evidence graph construction."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from .financial import FinancialContext, FinancialFinding, FindingKind
from .memory import MemoryFinding
from .models import AnalysisResult, EvidenceSignal, SignalKind
from .recommendations import VerificationRecommendation
from .risk import RiskAssessment


class NodeType(StrEnum):
    SPEAKER = "speaker"
    CLAIM = "claim"
    TACTIC = "tactic"
    REQUESTED_ACTION = "requested_action"
    ACCOUNT = "account"
    ACCOUNT_FINDING = "account_finding"
    CONTRADICTION = "contradiction"
    PRIOR_ENCOUNTER = "prior_encounter"
    MEMORY_FINDING = "memory_finding"
    RECOMMENDATION = "recommendation"
    RISK = "risk"


class EdgeType(StrEnum):
    MADE_CLAIM = "made_claim"
    USED_TACTIC = "used_tactic"
    REQUESTED = "requested"
    CONTRADICTS = "contradicts"
    VERIFIES = "verifies"
    SUPPORTS = "supports"
    MATCHES_PRIOR = "matches_prior"
    ELEVATES_RISK = "elevates_risk"
    TRIGGERS_ACTION = "triggers_action"


@dataclass(frozen=True, slots=True)
class EvidenceNode:
    id: str
    type: NodeType
    label: str
    confidence: float | None = None
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class EvidenceEdge:
    id: str
    source: str
    target: str
    type: EdgeType
    label: str


@dataclass(frozen=True, slots=True)
class EvidenceGraph:
    nodes: tuple[EvidenceNode, ...]
    edges: tuple[EvidenceEdge, ...]

    def __post_init__(self) -> None:
        node_ids = {node.id for node in self.nodes}
        edge_ids = {edge.id for edge in self.edges}
        if len(node_ids) != len(self.nodes):
            raise ValueError("evidence graph node IDs must be unique")
        if len(edge_ids) != len(self.edges):
            raise ValueError("evidence graph edge IDs must be unique")
        for edge in self.edges:
            if edge.source not in node_ids or edge.target not in node_ids:
                raise ValueError(f"edge {edge.id} references an unknown node")


_CLAIM_KINDS = {
    SignalKind.CLAIMED_IDENTITY,
    SignalKind.CLAIMED_TRANSACTION,
}
_ACTION_KINDS = {
    SignalKind.REQUESTED_TRANSFER,
    SignalKind.REQUESTED_CREDENTIALS,
}


class EvidenceGraphBuilder:
    """Turn transcript evidence, financial findings, and risk into nodes and edges."""

    def build(
        self,
        analysis: AnalysisResult,
        context: FinancialContext | None,
        findings: tuple[FinancialFinding, ...],
        risk: RiskAssessment,
        memory_findings: tuple[MemoryFinding, ...] = (),
        recommendations: tuple[VerificationRecommendation, ...] = (),
    ) -> EvidenceGraph:
        nodes: list[EvidenceNode] = []
        edges: list[EvidenceEdge] = []
        risk_node_id = "risk-current"

        speaker_ids = sorted({signal.speaker_id for signal in analysis.signals})
        for speaker_id in speaker_ids:
            nodes.append(
                EvidenceNode(
                    id=self._speaker_node_id(speaker_id),
                    type=NodeType.SPEAKER,
                    label=f"Caller {speaker_id}",
                    attributes={"speaker_id": speaker_id},
                )
            )

        for signal in analysis.signals:
            nodes.append(self._signal_node(signal))
            relationship, relationship_label = self._speaker_relationship(signal.kind)
            edges.append(
                EvidenceEdge(
                    id=f"edge-speaker-{signal.signal_id}",
                    source=self._speaker_node_id(signal.speaker_id),
                    target=signal.signal_id,
                    type=relationship,
                    label=relationship_label,
                )
            )
            edges.append(
                EvidenceEdge(
                    id=f"edge-risk-{signal.signal_id}",
                    source=signal.signal_id,
                    target=risk_node_id,
                    type=EdgeType.ELEVATES_RISK,
                    label="elevates risk",
                )
            )

        prior_node_ids: set[str] = set()
        for finding in memory_findings:
            nodes.append(
                EvidenceNode(
                    id=finding.finding_id,
                    type=NodeType.MEMORY_FINDING,
                    label=finding.description,
                    confidence=finding.match_confidence,
                    attributes={
                        "kind": finding.kind.value,
                        "speaker_profile_id": finding.speaker_profile_id,
                        **finding.attributes,
                    },
                )
            )
            for conversation_id in finding.prior_conversation_ids:
                prior_node_id = f"prior::{conversation_id}"
                if prior_node_id not in prior_node_ids:
                    nodes.append(
                        EvidenceNode(
                            id=prior_node_id,
                            type=NodeType.PRIOR_ENCOUNTER,
                            label=f"Prior call {conversation_id}",
                            attributes={"conversation_id": conversation_id},
                        )
                    )
                    prior_node_ids.add(prior_node_id)
                    for speaker_id in speaker_ids:
                        edges.append(
                            EvidenceEdge(
                                id=(
                                    f"edge-speaker-match-{speaker_id}-"
                                    f"{conversation_id}"
                                ),
                                source=self._speaker_node_id(speaker_id),
                                target=prior_node_id,
                                type=EdgeType.MATCHES_PRIOR,
                                label=(
                                    f"{finding.match_confidence:.0%} "
                                    "speaker-profile match"
                                ),
                            )
                        )
                edges.append(
                    EvidenceEdge(
                        id=(
                            f"edge-memory-{finding.finding_id}-{conversation_id}"
                        ),
                        source=prior_node_id,
                        target=finding.finding_id,
                        type=EdgeType.SUPPORTS,
                        label="supports cross-call finding",
                    )
                )
            edges.append(
                EvidenceEdge(
                    id=f"edge-risk-{finding.finding_id}",
                    source=finding.finding_id,
                    target=risk_node_id,
                    type=EdgeType.ELEVATES_RISK,
                    label=f"adds {finding.risk_weight} risk points",
                )
            )

        for account in context.accounts if context is not None else ():
            nodes.append(
                EvidenceNode(
                    id=self._account_node_id(account.account_id),
                    type=NodeType.ACCOUNT,
                    label=f"Account ending {account.account_id[-4:]}",
                    attributes={
                        "account_id": account.account_id,
                        "available_balance": str(account.available_balance),
                    },
                )
            )

        for finding in findings:
            finding_type = (
                NodeType.CONTRADICTION
                if finding.kind == FindingKind.CLAIMED_TRANSACTION_NOT_FOUND
                else NodeType.ACCOUNT_FINDING
            )
            nodes.append(
                EvidenceNode(
                    id=finding.finding_id,
                    type=finding_type,
                    label=finding.description,
                    confidence=1.0,
                    attributes={"kind": finding.kind.value, **finding.attributes},
                )
            )
            edges.append(
                EvidenceEdge(
                    id=f"edge-account-{finding.finding_id}",
                    source=self._account_node_id(finding.account_id),
                    target=finding.finding_id,
                    type=EdgeType.VERIFIES,
                    label="verifies against account activity",
                )
            )
            for source_signal_id in finding.source_signal_ids:
                edges.append(
                    EvidenceEdge(
                        id=f"edge-finding-{finding.finding_id}-{source_signal_id}",
                        source=source_signal_id,
                        target=finding.finding_id,
                        type=(
                            EdgeType.CONTRADICTS
                            if finding_type == NodeType.CONTRADICTION
                            else EdgeType.SUPPORTS
                        ),
                        label=(
                            "contradicts account activity"
                            if finding_type == NodeType.CONTRADICTION
                            else "supported by account context"
                        ),
                    )
                )
            edges.append(
                EvidenceEdge(
                    id=f"edge-risk-{finding.finding_id}",
                    source=finding.finding_id,
                    target=risk_node_id,
                    type=EdgeType.ELEVATES_RISK,
                    label=f"adds {finding.risk_weight} risk points",
                )
            )

        nodes.append(
            EvidenceNode(
                id=risk_node_id,
                type=NodeType.RISK,
                label=f"{risk.level.value.title()} risk: {risk.score}%",
                attributes={
                    "score": risk.score,
                    "level": risk.level.value,
                    "factor_count": len(risk.factors),
                },
            )
        )

        for recommendation in recommendations:
            nodes.append(
                EvidenceNode(
                    id=recommendation.recommendation_id,
                    type=NodeType.RECOMMENDATION,
                    label=recommendation.action,
                    attributes={
                        "kind": recommendation.kind.value,
                        "priority": recommendation.priority.value,
                        "rationale": recommendation.rationale,
                        "source_ids": recommendation.source_ids,
                    },
                )
            )
            edges.append(
                EvidenceEdge(
                    id=f"edge-action-{recommendation.recommendation_id}",
                    source=risk_node_id,
                    target=recommendation.recommendation_id,
                    type=EdgeType.TRIGGERS_ACTION,
                    label="recommends safe action",
                )
            )
        return EvidenceGraph(nodes=tuple(nodes), edges=tuple(edges))

    @staticmethod
    def _speaker_node_id(speaker_id: str) -> str:
        return f"speaker::{speaker_id}"

    @staticmethod
    def _account_node_id(account_id: str) -> str:
        return f"account::{account_id}"

    @staticmethod
    def _signal_node(signal: EvidenceSignal) -> EvidenceNode:
        if signal.kind in _CLAIM_KINDS:
            node_type = NodeType.CLAIM
        elif signal.kind in _ACTION_KINDS:
            node_type = NodeType.REQUESTED_ACTION
        else:
            node_type = NodeType.TACTIC
        return EvidenceNode(
            id=signal.signal_id,
            type=node_type,
            label=signal.evidence_text,
            confidence=signal.confidence,
            attributes={
                "signal_kind": signal.kind.value,
                "stage": signal.stage.value,
                "turn_index": signal.turn_index,
                "start_ms": signal.start_ms,
                **signal.attributes,
            },
        )

    @staticmethod
    def _speaker_relationship(kind: SignalKind) -> tuple[EdgeType, str]:
        if kind in _CLAIM_KINDS:
            return EdgeType.MADE_CLAIM, "made claim"
        if kind in _ACTION_KINDS:
            return EdgeType.REQUESTED, "requested"
        return EdgeType.USED_TACTIC, "used tactic"
