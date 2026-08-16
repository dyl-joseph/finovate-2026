import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from finovate_pipeline.api import ApiSettings, create_app


TEST_API_KEY = "test-ingestion-secret"
AUTH_HEADERS = {"Authorization": f"Bearer {TEST_API_KEY}"}


def load_json(path: str) -> dict:
    with open(path, encoding="utf-8") as file:
        return json.load(file)


def create_conversation(
    client: TestClient,
    conversation_id: str,
    caller_speaker_id: str = "SPEAKER_01",
) -> None:
    response = client.post(
        "/v1/conversations",
        headers=AUTH_HEADERS,
        json={
            "conversation_id": conversation_id,
            "caller_speaker_id": caller_speaker_id,
            "metadata": {"source": "test"},
        },
    )
    if response.status_code != 201:
        raise AssertionError(response.text)


def put_context(client: TestClient, conversation_id: str) -> None:
    response = client.put(
        f"/v1/conversations/{conversation_id}/financial-context",
        headers=AUTH_HEADERS,
        json=load_json("examples/sample_financial_context.json"),
    )
    if response.status_code != 200:
        raise AssertionError(response.text)


def put_identity(
    client: TestClient,
    conversation_id: str,
    profile_id: str = "voice-profile-7",
    confidence: float = 0.93,
) -> None:
    response = client.put(
        f"/v1/conversations/{conversation_id}/speaker-identity",
        headers=AUTH_HEADERS,
        json={
            "profile_id": profile_id,
            "match_confidence": confidence,
            "source": "test-speaker-service",
        },
    )
    if response.status_code != 200:
        raise AssertionError(response.text)


def ingest_turns(
    client: TestClient,
    conversation_id: str,
    turns: list[dict],
) -> dict:
    result: dict = {}
    for index, turn in enumerate(turns, start=1):
        response = client.post(
            f"/v1/conversations/{conversation_id}/turns",
            headers=AUTH_HEADERS,
            json={
                "segment_id": f"segment-{index:04d}",
                "is_final": True,
                **turn,
            },
        )
        if response.status_code != 200:
            raise AssertionError(response.text)
        result = response.json()
    return result


class ApiContractTests(unittest.TestCase):
    def make_app(self, database_path: str = ":memory:"):
        return create_app(
            ApiSettings(
                database_path=database_path,
                ingest_api_key=TEST_API_KEY,
                cors_origins=("http://localhost:3000",),
                environment="test",
            )
        )

    def test_health_and_openapi(self) -> None:
        with TestClient(self.make_app()) as client:
            health = client.get("/health")
            schema = client.get("/openapi.json")

        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json()["status"], "ok")
        self.assertEqual(schema.status_code, 200)
        schema_body = schema.json()
        self.assertIn(
            "/v1/conversations/{conversation_id}/turns", schema_body["paths"]
        )
        self.assertTrue(schema_body["paths"]["/v1/conversations"]["post"]["security"])

    def test_production_requires_nondefault_secret(self) -> None:
        with self.assertRaisesRegex(ValueError, "must be set"):
            ApiSettings(environment="production")

    def test_reads_postgres_url_from_environment(self) -> None:
        with mock.patch.dict(
            "os.environ",
            {
                "DATABASE_URL": "postgresql://example.test/finovate",
                "DATABASE_PATH": "ignored.db",
            },
            clear=True,
        ):
            settings = ApiSettings.from_env()

        self.assertEqual(
            settings.database_url, "postgresql://example.test/finovate"
        )

    def test_mutations_require_bearer_authentication(self) -> None:
        with TestClient(self.make_app()) as client:
            missing = client.post("/v1/conversations", json={})
            incorrect = client.post(
                "/v1/conversations",
                headers={"Authorization": "Bearer wrong"},
                json={},
            )

        self.assertEqual(missing.status_code, 401)
        self.assertEqual(incorrect.status_code, 401)
        self.assertEqual(missing.headers["www-authenticate"], "Bearer")

    def test_rejects_nonfinal_and_conflicting_segments(self) -> None:
        with TestClient(self.make_app()) as client:
            create_conversation(client, "call-conflict")
            payload = {
                "segment_id": "segment-1",
                "speaker_id": "SPEAKER_01",
                "role": "caller",
                "text": "I'm calling from Chase.",
                "start_ms": 0,
                "end_ms": 1000,
                "is_final": False,
            }
            partial = client.post(
                "/v1/conversations/call-conflict/turns",
                headers=AUTH_HEADERS,
                json=payload,
            )
            payload["is_final"] = True
            accepted = client.post(
                "/v1/conversations/call-conflict/turns",
                headers=AUTH_HEADERS,
                json=payload,
            )
            duplicate = client.post(
                "/v1/conversations/call-conflict/turns",
                headers=AUTH_HEADERS,
                json=payload,
            )
            payload["text"] = "Different finalized text."
            conflict = client.post(
                "/v1/conversations/call-conflict/turns",
                headers=AUTH_HEADERS,
                json=payload,
            )

        self.assertEqual(partial.status_code, 422)
        self.assertEqual(accepted.status_code, 200)
        self.assertFalse(accepted.json()["duplicate_segment"])
        self.assertEqual(duplicate.status_code, 200)
        self.assertTrue(duplicate.json()["duplicate_segment"])
        self.assertEqual(conflict.status_code, 409)

    def test_assesses_transcript_before_financial_context_arrives(self) -> None:
        with TestClient(self.make_app()) as client:
            create_conversation(client, "call-live")
            response = client.post(
                "/v1/conversations/call-live/turns",
                headers=AUTH_HEADERS,
                json={
                    "segment_id": "segment-1",
                    "speaker_id": "SPEAKER_01",
                    "role": "caller",
                    "text": "Move $2,000 to an account immediately.",
                    "start_ms": 1000,
                    "end_ms": 2200,
                    "is_final": True,
                },
            )

        body = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(body["status"], "assessed")
        self.assertEqual(body["assessment"]["financial_findings"], [])
        self.assertGreaterEqual(body["assessment"]["risk"]["score"], 35)

    def test_sorts_out_of_order_turn_arrival(self) -> None:
        with TestClient(self.make_app()) as client:
            create_conversation(client, "call-order")
            later = client.post(
                "/v1/conversations/call-order/turns",
                headers=AUTH_HEADERS,
                json={
                    "segment_id": "later",
                    "speaker_id": "SPEAKER_01",
                    "role": "caller",
                    "text": "Move $2,000 to an account immediately.",
                    "start_ms": 2000,
                    "end_ms": 3000,
                    "is_final": True,
                },
            )
            earlier = client.post(
                "/v1/conversations/call-order/turns",
                headers=AUTH_HEADERS,
                json={
                    "segment_id": "earlier",
                    "speaker_id": "SPEAKER_01",
                    "role": "caller",
                    "text": "I'm calling from Chase fraud department.",
                    "start_ms": 0,
                    "end_ms": 1000,
                    "is_final": True,
                },
            )

        self.assertEqual(later.status_code, 200)
        self.assertEqual(earlier.status_code, 200)
        signals = earlier.json()["assessment"]["transcript_analysis"]["signals"]
        identity = next(
            signal for signal in signals if signal["kind"] == "claimed_identity"
        )
        transfer = next(
            signal for signal in signals if signal["kind"] == "requested_transfer"
        )
        self.assertEqual(identity["turn_index"], 0)
        self.assertEqual(transfer["turn_index"], 1)

    def test_complete_single_call_pipeline_over_http(self) -> None:
        transcript = load_json("examples/sample_transcript.json")
        with TestClient(self.make_app()) as client:
            create_conversation(client, transcript["conversation_id"])
            put_context(client, transcript["conversation_id"])
            put_identity(client, transcript["conversation_id"])
            final = ingest_turns(
                client,
                transcript["conversation_id"],
                transcript["turns"],
            )
            fetched = client.get(
                f"/v1/conversations/{transcript['conversation_id']}/assessment"
            )

        assessment = final["assessment"]
        self.assertEqual(assessment["risk"]["score"], 100)
        self.assertEqual(assessment["risk"]["level"], "critical")
        self.assertEqual(len(assessment["financial_findings"]), 3)
        self.assertGreater(len(assessment["recommendations"]), 3)
        self.assertEqual(fetched.status_code, 200)
        self.assertEqual(fetched.json()["assessment"], assessment)

    def test_two_call_memory_survives_api_restart(self) -> None:
        first_transcript = load_json("examples/sample_transcript.json")
        second_turns = [
            {
                "speaker_id": "SPEAKER_01",
                "role": "caller",
                "text": "I'm calling from PayPal fraud department.",
                "start_ms": 0,
                "end_ms": 1400,
            },
            {
                "speaker_id": "SPEAKER_01",
                "role": "caller",
                "text": "Move $2,000 to an account immediately.",
                "start_ms": 1500,
                "end_ms": 3100,
            },
        ]

        with tempfile.TemporaryDirectory() as directory:
            database_path = str(Path(directory) / "finovate-test.db")
            with TestClient(self.make_app(database_path)) as first_client:
                create_conversation(first_client, "persistent-call-1")
                put_context(first_client, "persistent-call-1")
                put_identity(first_client, "persistent-call-1")
                first = ingest_turns(
                    first_client,
                    "persistent-call-1",
                    first_transcript["turns"],
                )

            with TestClient(self.make_app(database_path)) as second_client:
                create_conversation(second_client, "persistent-call-2")
                put_context(second_client, "persistent-call-2")
                put_identity(second_client, "persistent-call-2")
                second = ingest_turns(
                    second_client,
                    "persistent-call-2",
                    second_turns,
                )

        self.assertEqual(first["assessment"]["risk"]["level"], "critical")
        memory_kinds = {
            finding["kind"]
            for finding in second["assessment"]["memory_findings"]
        }
        recommendation_kinds = {
            recommendation["kind"]
            for recommendation in second["assessment"]["recommendations"]
        }
        self.assertIn("repeat_flagged_speaker", memory_kinds)
        self.assertIn("identity_switch", memory_kinds)
        self.assertIn("report_repeat_scam", recommendation_kinds)


if __name__ == "__main__":
    unittest.main()
