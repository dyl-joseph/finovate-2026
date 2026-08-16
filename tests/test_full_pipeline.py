import json
import shutil
import subprocess
import unittest

from finovate_pipeline import FinancialContext, ScamAssessmentPipeline, Transcript


class FullPipelineIntegrationTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node.js is required")
    def test_diarized_words_flow_into_explainable_risk_assessment(self) -> None:
        node_script = r"""
import { TranscriptAssembler } from "./src/transcript-assembler.mjs";

const assembler = new TranscriptAssembler({ conversationId: "full-pipeline-001" });
assembler.ingestDeepgramPrerecorded({
  results: { channels: [{ alternatives: [{ words: [
    { speaker: 1, punctuated_word: "I'm", start: 0.0, end: 0.2 },
    { speaker: 1, punctuated_word: "calling", start: 0.2, end: 0.5 },
    { speaker: 1, punctuated_word: "from", start: 0.5, end: 0.7 },
    { speaker: 1, punctuated_word: "Chase", start: 0.7, end: 1.0 },
    { speaker: 1, punctuated_word: "fraud", start: 1.0, end: 1.2 },
    { speaker: 1, punctuated_word: "department.", start: 1.2, end: 1.5 },
    { speaker: 0, punctuated_word: "What", start: 1.7, end: 1.9 },
    { speaker: 0, punctuated_word: "happened?", start: 1.9, end: 2.3 },
    { speaker: 1, punctuated_word: "Move", start: 2.5, end: 2.8 },
    { speaker: 1, punctuated_word: "$2,000", start: 2.8, end: 3.1 },
    { speaker: 1, punctuated_word: "to", start: 3.1, end: 3.2 },
    { speaker: 1, punctuated_word: "a", start: 3.2, end: 3.3 },
    { speaker: 1, punctuated_word: "new", start: 3.3, end: 3.5 },
    { speaker: 1, punctuated_word: "account", start: 3.5, end: 3.8 },
    { speaker: 1, punctuated_word: "immediately.", start: 3.8, end: 4.2 },
    { speaker: 1, punctuated_word: "Do", start: 4.4, end: 4.6 },
    { speaker: 1, punctuated_word: "not", start: 4.6, end: 4.8 },
    { speaker: 1, punctuated_word: "tell", start: 4.8, end: 5.0 },
    { speaker: 1, punctuated_word: "anyone.", start: 5.0, end: 5.4 },
  ] }] }] },
});
assembler.setSpeakerRole("SPEAKER_01", "caller");
assembler.setSpeakerRole("SPEAKER_00", "customer");
process.stdout.write(JSON.stringify(assembler.buildFinalTranscript()));
"""
        completed = subprocess.run(
            ["node", "--input-type=module", "--eval", node_script],
            check=True,
            capture_output=True,
            text=True,
        )
        transcript = Transcript.from_dict(json.loads(completed.stdout))
        with open(
            "examples/sample_financial_context.json", encoding="utf-8"
        ) as file:
            financial_context = FinancialContext.from_dict(json.load(file))

        result = ScamAssessmentPipeline().analyze(transcript, financial_context)

        self.assertEqual(transcript.caller_speaker_id, "SPEAKER_01")
        self.assertEqual(len(transcript.turns), 3)
        self.assertGreaterEqual(result.risk.score, 80)
        self.assertIn(result.risk.level.value, {"high", "critical"})
        self.assertGreaterEqual(len(result.transcript_analysis.signals), 3)
        self.assertGreaterEqual(len(result.financial_findings), 2)
        self.assertTrue(result.graph.edges)


if __name__ == "__main__":
    unittest.main()
