import json
import unittest

from finovate_pipeline.financial import FinancialContext, FindingKind
from finovate_pipeline.graph import EdgeType, NodeType
from finovate_pipeline.models import Transcript
from finovate_pipeline.pipeline import ScamAssessmentPipeline
from finovate_pipeline.risk import RiskLevel


class PipelineIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        with open("examples/sample_transcript.json", encoding="utf-8") as file:
            cls.transcript = Transcript.from_dict(json.load(file))
        with open("examples/sample_financial_context.json", encoding="utf-8") as file:
            cls.financial_context = FinancialContext.from_dict(json.load(file))

    def setUp(self) -> None:
        self.result = ScamAssessmentPipeline().analyze(
            self.transcript,
            self.financial_context,
        )

    def test_produces_critical_explainable_risk(self) -> None:
        finding_kinds = {finding.kind for finding in self.result.financial_findings}

        self.assertEqual(self.result.risk.score, 100)
        self.assertEqual(self.result.risk.level, RiskLevel.CRITICAL)
        self.assertIn(FindingKind.CLAIMED_TRANSACTION_NOT_FOUND, finding_kinds)
        self.assertIn(FindingKind.NEW_RECIPIENT, finding_kinds)
        self.assertIn(FindingKind.LARGE_TRANSFER, finding_kinds)
        self.assertGreaterEqual(len(self.result.risk.factors), 8)

    def test_graph_contains_traceable_contradiction_and_risk(self) -> None:
        node_types = {node.type for node in self.result.graph.nodes}
        edge_types = {edge.type for edge in self.result.graph.edges}

        self.assertIn(NodeType.CLAIM, node_types)
        self.assertIn(NodeType.CONTRADICTION, node_types)
        self.assertIn(NodeType.ACCOUNT, node_types)
        self.assertIn(NodeType.RISK, node_types)
        self.assertIn(EdgeType.CONTRADICTS, edge_types)
        self.assertIn(EdgeType.ELEVATES_RISK, edge_types)

    def test_every_edge_references_existing_nodes(self) -> None:
        node_ids = {node.id for node in self.result.graph.nodes}
        for edge in self.result.graph.edges:
            self.assertIn(edge.source, node_ids)
            self.assertIn(edge.target, node_ids)

    def test_result_serializes_to_json(self) -> None:
        encoded = json.dumps(self.result.to_dict())
        decoded = json.loads(encoded)

        self.assertEqual(decoded["risk"]["level"], "critical")
        self.assertEqual(decoded["risk"]["score"], 100)


if __name__ == "__main__":
    unittest.main()
