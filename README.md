# Finovate 2026 Scam Intelligence Pipeline

This branch contains the post-transcript portion of the financial scam detection
prototype:

```text
speaker-labelled transcript
        ↓
claims, tactics, and scam stages
        ↓
financial-context verification
        ↓
explainable risk assessment
        ↓
frontend-ready evidence graph
```

The implementation is deterministic and has no external API dependency. A
model-backed extractor or real banking-data adapter can be added later without
changing the downstream contracts.

The pipeline also accepts an optional speaker-profile match from the upstream
audio service. Matches at or above 80% confidence are used to link prior
flagged encounters and detect changes in claimed institutional identity. The
post-transcript service does not compare voices itself.

## Input contracts

- Transcript example: `examples/sample_transcript.json`
- Financial context example: `examples/sample_financial_context.json`
- Speaker identity example: `examples/sample_speaker_identity.json`

Transcript turns must be ordered by `start_ms`, use a stable `speaker_id`, and
include either a `role` or a top-level `caller_speaker_id`.

## Python usage

```python
import json

from finovate_pipeline import (
    FinancialContext,
    ScamAssessmentPipeline,
    SpeakerIdentity,
    Transcript,
)

with open("examples/sample_transcript.json", encoding="utf-8") as file:
    transcript = Transcript.from_dict(json.load(file))

with open("examples/sample_financial_context.json", encoding="utf-8") as file:
    context = FinancialContext.from_dict(json.load(file))

with open("examples/sample_speaker_identity.json", encoding="utf-8") as file:
    identity = SpeakerIdentity.from_dict(json.load(file))

pipeline = ScamAssessmentPipeline()
result = pipeline.analyze(transcript, context, identity)
print(json.dumps(result.to_dict(), indent=2))
```

Reuse the same `ScamAssessmentPipeline` instance to retain encounter memory in
a single process. For local persistence, inject `EncounterMemory` with a
`SQLiteEncounterRepository`. The HTTP service uses Supabase/Postgres whenever
`SUPABASE_URL` and `SUPABASE_SECRET_KEY` are set. A direct `DATABASE_URL` is
also supported, and the service falls back to SQLite otherwise.

## Tests

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

The evidence graph returns typed `nodes` and `edges`. Every financial finding
links back to the transcript signal that triggered it and forward to the final
risk node, allowing the frontend to explain why the score changed. High-risk
results also include ordered recommendations such as ending the call, using an
official contact channel, pausing a transfer, and verifying a new recipient.

## HTTP service

Install the package and test dependencies:

```bash
python3 -m pip install -e '.[test]'
```

Configure the service using the variables in `.env.example`, then export them
into the shell that starts Uvicorn. A nondefault ingestion key is mandatory
when `APP_ENV=production`.

```bash
export APP_ENV=development
export DATABASE_PATH=./finovate.db
export TRANSCRIPT_INGEST_API_KEY=replace-with-a-random-secret
export CORS_ORIGINS=http://localhost:3000

uvicorn finovate_pipeline.api:app --host 0.0.0.0 --port 8000
```

Interactive OpenAPI documentation is available at `http://localhost:8000/docs`.

### Supabase and Render

The Supabase schema is versioned in
`supabase/migrations/20260816100000_post_transcript_pipeline.sql`. The API also
creates the same tables idempotently when using a direct Postgres connection.

Create a Render Blueprint from `render.yaml`, then provide the server-side
`SUPABASE_SECRET_KEY` from the Supabase API Keys settings. Never expose this key
to a browser or commit it. Render generates
`TRANSCRIPT_INGEST_API_KEY`; copy that secret into the upstream transcript
service. Set `CORS_ORIGINS` to a comma-separated list of deployed frontend
origins, or leave it empty when browser clients should not call the API.

### Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Service health check |
| `POST` | `/v1/conversations` | Start a conversation |
| `POST` | `/v1/conversations/{id}/turns` | Add a finalized transcript turn |
| `PUT` | `/v1/conversations/{id}/financial-context` | Set or replace financial context |
| `PUT` | `/v1/conversations/{id}/speaker-identity` | Set an upstream speaker-profile match |
| `POST` | `/v1/conversations/{id}/analyze` | Recompute the complete assessment |
| `GET` | `/v1/conversations/{id}/assessment` | Fetch the latest assessment |

Mutating endpoints require this header:

```text
Authorization: Bearer <TRANSCRIPT_INGEST_API_KEY>
```

Each turn must include a stable `segment_id` and `is_final: true`. Retrying an
identical segment is safe and returns `duplicate_segment: true`; reusing the ID
with different content returns HTTP 409. Turns are analyzed in timestamp order
even if finalized segments arrive out of order.

Financial context and speaker identity are optional. The API begins transcript
analysis immediately and recomputes the complete assessment whenever either
context is supplied later.
