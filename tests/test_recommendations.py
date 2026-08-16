import unittest

from finovate_pipeline.financial import FinancialFinding, FindingKind
from finovate_pipeline.memory import MemoryFinding, MemoryFindingKind
from finovate_pipeline.models import (
    AnalysisResult,
    EvidenceSignal,
    ScamStage,
    SignalKind,
)
from finovate_pipeline.recommendations import (
    RecommendationEngine,
    RecommendationKind,
)
from finovate_pipeline.risk import RiskAssessment, RiskFactor, RiskLevel


class RecommendationEngineTests(unittest.TestCase):
    def test_generates_specific_actions_from_evidence(self) -> None:
        analysis = AnalysisResult(
            conversation_id="call-1",
            signals=(
                EvidenceSignal(
                    "sig-1",
                    SignalKind.REQUESTED_TRANSFER,
                    ScamStage.FINANCIAL_ACTION,
                    "caller",
                    0,
                    0,
                    "move $2,000",
                    0.96,
                ),
                EvidenceSignal(
                    "sig-2",
                    SignalKind.REQUESTED_CREDENTIALS,
                    ScamStage.FINANCIAL_ACTION,
                    "caller",
                    0,
                    0,
                    "share your code",
                    0.97,
                ),
            ),
            stages_reached=(ScamStage.FINANCIAL_ACTION,),
        )
        financial_findings = (
            FinancialFinding(
                "finding-1",
                FindingKind.NEW_RECIPIENT,
                "Recipient is new.",
                18,
                "checking-1",
            ),
        )
        memory_findings = (
            MemoryFinding(
                "memory-1",
                MemoryFindingKind.REPEAT_FLAGGED_SPEAKER,
                "Speaker appeared before.",
                25,
                "voice-7",
                0.93,
                ("prior-call",),
            ),
        )
        risk = RiskAssessment(
            100,
            RiskLevel.CRITICAL,
            (RiskFactor("factor-1", "test", "High risk.", 100, ("sig-1",)),),
        )

        recommendations = RecommendationEngine().recommend(
            analysis, financial_findings, memory_findings, risk
        )
        kinds = {recommendation.kind for recommendation in recommendations}

        self.assertIn(RecommendationKind.END_CALL, kinds)
        self.assertIn(RecommendationKind.USE_OFFICIAL_CHANNEL, kinds)
        self.assertIn(RecommendationKind.DO_NOT_SHARE_CREDENTIALS, kinds)
        self.assertIn(RecommendationKind.PAUSE_TRANSFER, kinds)
        self.assertIn(RecommendationKind.VERIFY_RECIPIENT, kinds)
        self.assertIn(RecommendationKind.REPORT_REPEAT_SCAM, kinds)
        self.assertEqual(
            len({item.recommendation_id for item in recommendations}),
            len(recommendations),
        )


if __name__ == "__main__":
    unittest.main()
