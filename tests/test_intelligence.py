import unittest

from finovate_pipeline.intelligence import TranscriptIntelligence
from finovate_pipeline.models import (
    ScamStage,
    SignalKind,
    SpeakerRole,
    Transcript,
    TranscriptTurn,
)


class TranscriptContractTests(unittest.TestCase):
    def test_rejects_out_of_order_turns(self) -> None:
        with self.assertRaisesRegex(ValueError, "ordered"):
            Transcript(
                conversation_id="call-1",
                turns=(
                    TranscriptTurn("A", "Later", 200, 300),
                    TranscriptTurn("B", "Earlier", 100, 150),
                ),
            )

    def test_builds_from_diarization_json(self) -> None:
        transcript = Transcript.from_dict(
            {
                "conversation_id": "call-2",
                "caller_speaker_id": "SPEAKER_01",
                "turns": [
                    {
                        "speaker_id": "SPEAKER_00",
                        "text": "Hello?",
                        "start_ms": 0,
                        "end_ms": 400,
                    },
                    {
                        "speaker_id": "SPEAKER_01",
                        "text": "I'm calling from Chase.",
                        "start_ms": 500,
                        "end_ms": 1500,
                    },
                ],
            }
        )

        self.assertEqual(transcript.caller_speaker_id, "SPEAKER_01")
        self.assertEqual(len(transcript.turns), 2)


class TranscriptIntelligenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.analyzer = TranscriptIntelligence()

    def test_extracts_full_scam_progression(self) -> None:
        transcript = Transcript(
            conversation_id="scam-call",
            caller_speaker_id="scammer",
            turns=(
                TranscriptTurn(
                    "scammer", "I'm calling from Chase fraud department.", 0, 2000
                ),
                TranscriptTurn(
                    "scammer",
                    "There was a charge for $900 and you must act immediately.",
                    2100,
                    5000,
                ),
                TranscriptTurn(
                    "scammer", "Do not tell your family and stay on the line.", 5100, 7500
                ),
                TranscriptTurn(
                    "scammer", "Move $2,000 to a secure account.", 7600, 9000
                ),
            ),
        )

        result = self.analyzer.analyze(transcript)
        kinds = {signal.kind for signal in result.signals}
        signal_ids = {signal.signal_id for signal in result.signals}

        self.assertIn(SignalKind.CLAIMED_IDENTITY, kinds)
        self.assertIn(SignalKind.CLAIMED_TRANSACTION, kinds)
        self.assertIn(SignalKind.URGENCY, kinds)
        self.assertIn(SignalKind.SECRECY, kinds)
        self.assertIn(SignalKind.ISOLATION, kinds)
        self.assertIn(SignalKind.REQUESTED_TRANSFER, kinds)
        self.assertEqual(len(signal_ids), len(result.signals))
        self.assertEqual(
            result.stages_reached,
            (
                ScamStage.IDENTITY,
                ScamStage.CREDIBILITY,
                ScamStage.URGENCY,
                ScamStage.ISOLATION,
                ScamStage.FINANCIAL_ACTION,
            ),
        )

    def test_ignores_customer_language_when_roles_are_known(self) -> None:
        transcript = Transcript(
            conversation_id="legitimate-call",
            turns=(
                TranscriptTurn(
                    "customer",
                    "Should I transfer money immediately?",
                    0,
                    1000,
                    role=SpeakerRole.CUSTOMER,
                ),
                TranscriptTurn(
                    "caller",
                    "No. Hang up and call the number on your card.",
                    1100,
                    2300,
                    role=SpeakerRole.CALLER,
                ),
            ),
        )

        result = self.analyzer.analyze(transcript)
        self.assertEqual(result.signals, ())

    def test_live_analysis_recovers_risk_across_fragmented_speaker_labels(self) -> None:
        transcript = Transcript(
            conversation_id="live-call",
            caller_speaker_id="SPEAKER_00",
            metadata={"source": "live-transcription"},
            turns=(
                TranscriptTurn(
                    "SPEAKER_00",
                    "Hello. This is Michael from",
                    0,
                    4800,
                    role=SpeakerRole.CALLER,
                ),
                TranscriptTurn(
                    "SPEAKER_01",
                    "Chase Bank calling. If you just put your password",
                    5000,
                    9800,
                    role=SpeakerRole.CUSTOMER,
                ),
            ),
        )

        result = self.analyzer.analyze(transcript)
        kinds = {signal.kind for signal in result.signals}

        self.assertIn(SignalKind.CLAIMED_IDENTITY, kinds)
        self.assertIn(SignalKind.REQUESTED_CREDENTIALS, kinds)

    def test_extracts_requested_credentials(self) -> None:
        transcript = Transcript(
            conversation_id="credential-call",
            caller_speaker_id="A",
            turns=(
                TranscriptTurn(
                    "A", "Please read me your one-time verification code.", 0, 1200
                ),
            ),
        )

        result = self.analyzer.analyze(transcript)
        self.assertEqual(result.signals[0].kind, SignalKind.REQUESTED_CREDENTIALS)

    def test_extracts_conversational_credential_requests(self) -> None:
        for text in (
            "Can I have your password?",
            "We need your PIN to continue.",
            "What is your Social Security number?",
        ):
            with self.subTest(text=text):
                transcript = Transcript(
                    conversation_id="credential-variant",
                    caller_speaker_id="A",
                    turns=(TranscriptTurn("A", text, 0, 1200),),
                )

                result = self.analyzer.analyze(transcript)

                self.assertEqual(
                    result.signals[0].kind,
                    SignalKind.REQUESTED_CREDENTIALS,
                )
        self.assertEqual(result.signals[0].stage, ScamStage.FINANCIAL_ACTION)


if __name__ == "__main__":
    unittest.main()
