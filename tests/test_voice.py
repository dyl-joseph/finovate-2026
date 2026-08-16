import math
import unittest

from finovate_pipeline.voice import (
    DEFAULT_MATCH_THRESHOLD,
    NEW_PROFILE_CONFIDENCE,
    VoiceMatch,
    VoiceMatcher,
    SQLiteSpeakerProfileRepository,
    similarity_to_confidence,
)


def normalized(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    return [value / norm for value in vector]


class SimilarityConfidenceTests(unittest.TestCase):
    def test_threshold_maps_to_pipeline_gate(self) -> None:
        self.assertEqual(similarity_to_confidence(0.80, 0.80), 0.8)

    def test_perfect_match_approaches_certainty(self) -> None:
        self.assertGreater(similarity_to_confidence(1.0, 0.80), 0.99)

    def test_higher_similarity_means_higher_confidence(self) -> None:
        low = similarity_to_confidence(0.81, 0.80)
        high = similarity_to_confidence(0.90, 0.80)
        self.assertGreater(high, low)
        self.assertLess(low, 1.0)


class VoiceMatcherTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = SQLiteSpeakerProfileRepository(":memory:")
        self.matcher = VoiceMatcher(self.repository)

    def base_embedding(self) -> list[float]:
        vector = [0.01] * 256
        vector[0] = 1.0
        return normalized(vector)

    def test_first_call_creates_profile_with_enrollment_confidence(self) -> None:
        match = self.matcher.identify(self.base_embedding())
        self.assertIsInstance(match, VoiceMatch)
        self.assertTrue(match.is_new)
        self.assertTrue(match.profile_id.startswith("voice-profile-"))
        self.assertEqual(match.confidence, NEW_PROFILE_CONFIDENCE)
        self.assertEqual(len(self.repository.list_profiles()), 1)

    def test_same_voice_maps_to_same_profile(self) -> None:
        first = self.matcher.identify(self.base_embedding())
        repeat = self.matcher.identify(
            normalized([value * 1.02 for value in self.base_embedding()])
        )
        self.assertFalse(repeat.is_new)
        self.assertEqual(repeat.profile_id, first.profile_id)
        self.assertGreaterEqual(repeat.confidence, 0.8)
        self.assertEqual(len(self.repository.list_profiles()), 1)

    def test_rolling_average_folds_new_sample(self) -> None:
        self.matcher.identify(self.base_embedding())
        self.matcher.identify(
            normalized([value * 1.02 for value in self.base_embedding()])
        )
        profiles = self.repository.list_profiles()
        self.assertEqual(profiles[0].sample_count, 2)

    def test_different_voice_gets_new_profile(self) -> None:
        first = self.matcher.identify(self.base_embedding())
        other = normalized([0.01] * 256)
        other[1] = 1.0
        different = self.matcher.identify(other)
        self.assertTrue(different.is_new)
        self.assertNotEqual(different.profile_id, first.profile_id)


class SQLiteSpeakerProfileRepositoryTests(unittest.TestCase):
    def test_round_trips_profiles(self) -> None:
        from finovate_pipeline.voice import SpeakerProfile

        with SQLiteSpeakerProfileRepository(":memory:") as repository:
            profile = SpeakerProfile(
                profile_id="voice-profile-abc",
                embedding=tuple(range(10)),
                sample_count=3,
                last_seen_at="2026-08-16T00:00:00+00:00",
            )
            repository.upsert(profile)
            repository.upsert(profile)
            profiles = repository.list_profiles()
            self.assertEqual(len(profiles), 1)
            self.assertEqual(profiles[0].embedding, tuple(range(10)))
            self.assertEqual(profiles[0].sample_count, 3)
            self.assertEqual(profiles[0].last_seen_at, "2026-08-16T00:00:00+00:00")


if __name__ == "__main__":
    unittest.main()