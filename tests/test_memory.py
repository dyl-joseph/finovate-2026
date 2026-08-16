import unittest

from finovate_pipeline.intelligence import TranscriptIntelligence
from finovate_pipeline.memory import (
    EncounterMemory,
    EncounterRecord,
    MemoryFindingKind,
    SpeakerIdentity,
    SQLiteEncounterRepository,
)
from finovate_pipeline.models import Transcript, TranscriptTurn


class SQLiteEncounterRepositoryTests(unittest.TestCase):
    def test_round_trips_and_upserts_encounters(self) -> None:
        with SQLiteEncounterRepository() as repository:
            repository.save(
                EncounterRecord(
                    conversation_id="call-1",
                    speaker_profile_id="voice-7",
                    risk_score=91,
                    risk_level="critical",
                    claimed_institutions=("chase",),
                    signal_kinds=("requested_transfer",),
                )
            )
            repository.save(
                EncounterRecord(
                    conversation_id="call-1",
                    speaker_profile_id="voice-7",
                    risk_score=94,
                    risk_level="critical",
                    claimed_institutions=("chase",),
                    signal_kinds=("requested_transfer", "secrecy"),
                )
            )

            records = repository.find_by_speaker("voice-7")

            self.assertEqual(len(records), 1)
            self.assertEqual(records[0].risk_score, 94)
            self.assertEqual(records[0].signal_kinds[-1], "secrecy")

    def test_excludes_current_conversation(self) -> None:
        with SQLiteEncounterRepository() as repository:
            repository.save(
                EncounterRecord("call-1", "voice-7", 90, "critical")
            )

            records = repository.find_by_speaker(
                "voice-7", exclude_conversation_id="call-1"
            )

            self.assertEqual(records, ())


class EncounterMemoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = SQLiteEncounterRepository()
        self.memory = EncounterMemory(self.repository)
        self.analyzer = TranscriptIntelligence()

    def tearDown(self) -> None:
        self.repository.close()

    def _analysis(self, conversation_id: str, institution: str):
        return self.analyzer.analyze(
            Transcript(
                conversation_id,
                (
                    TranscriptTurn(
                        "caller",
                        f"I'm calling from {institution} fraud department.",
                        0,
                        1200,
                    ),
                ),
                caller_speaker_id="caller",
            )
        )

    def test_links_flagged_speaker_and_detects_identity_switch(self) -> None:
        identity = SpeakerIdentity("voice-7", 0.93)
        first_analysis = self._analysis("call-1", "Chase")
        self.memory.remember("call-1", identity, first_analysis, 91, "critical")

        findings = self.memory.evaluate(
            "call-2",
            identity,
            self._analysis("call-2", "PayPal"),
        )
        kinds = {finding.kind for finding in findings}

        self.assertEqual(
            kinds,
            {
                MemoryFindingKind.REPEAT_FLAGGED_SPEAKER,
                MemoryFindingKind.IDENTITY_SWITCH,
            },
        )
        self.assertEqual(findings[0].prior_conversation_ids, ("call-1",))

    def test_ignores_low_confidence_match(self) -> None:
        identity = SpeakerIdentity("voice-7", 0.79)
        first_analysis = self._analysis("call-1", "Chase")
        self.memory.remember("call-1", identity, first_analysis, 91, "critical")

        findings = self.memory.evaluate(
            "call-2", identity, self._analysis("call-2", "PayPal")
        )

        self.assertEqual(findings, ())
        self.assertEqual(self.repository.find_by_speaker("voice-7"), ())


if __name__ == "__main__":
    unittest.main()
