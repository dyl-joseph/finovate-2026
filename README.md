# Finovate 2026 Scam Intelligence Pipeline

This repository contains the complete financial scam detection prototype:

```text
microphone audio
        ↓
Deepgram full-call transcription and speaker diarization
        ↓
canonical speaker-labelled transcript
        ↓
claims, scam tactics, and financial-context verification
        ↓
explainable risk assessment and evidence graph
```

## Live diarization app

The local Node app records the complete browser microphone session while
streaming provisional captions. When the call stops, it uploads the recording
to Deepgram Nova-3's batch diarizer and assembles finalized word-level results
into `schemas/final-transcript.schema.json`.

Copy `.env.example` to `.env`, set `DEEPGRAM_API_KEY`, and give both services
the same nondefault `TRANSCRIPT_INGEST_API_KEY`. Then start the post-transcript
API and the audio app in separate terminals:

```sh
python3 -m pip install -e '.[test]'
uvicorn finovate_pipeline.api:app --host 127.0.0.1 --port 8000
```

```sh
npm install
npm start
```

Open `http://127.0.0.1:3000`, record a synthetic demo call, stop and finalize
it, then identify the caller and customer. The finalized transcript can be sent
through the post-transcript pipeline for a risk assessment.

The Node server exposes `POST /api/analyze-transcript` for this handoff. It
accepts the canonical final-transcript JSON, creates the corresponding
conversation in the Python service, and ingests each turn with a stable segment
ID. `POST_TRANSCRIPT_URL` selects the Python service and the shared
`TRANSCRIPT_INGEST_API_KEY` authenticates the server-to-server requests.

The Deepgram key remains on the local Node server. The Supabase secret and
transcript ingestion key remain on their respective servers and are never
returned to the browser. Use synthetic calls rather than real financial or
personal data.

## Transcript and analysis contracts

- Canonical transcript schema: `schemas/final-transcript.schema.json`
- Transcript example: `examples/sample_transcript.json`
- Financial context example: `examples/sample_financial_context.json`
- Speaker identity example: `examples/sample_speaker_identity.json`
- Audio/ASR contract: `docs/audio-asr-contract.md`
- Diarization plan: `docs/speaker-diarization-transcript-plan.md`

Transcript turns must be finalized and ordered by `start_ms`, use a stable
`speaker_id`, and include either a role or a top-level `caller_speaker_id`.

## Post-transcript service

The deterministic Python pipeline extracts claims and tactics, verifies
optional financial context, calculates an explainable risk score, generates
recommendations, and returns a frontend-ready evidence graph. Optional upstream
speaker-profile matches can link prior flagged encounters.

For local persistence it uses SQLite. Set `SUPABASE_URL` and
`SUPABASE_SECRET_KEY` for Supabase, or `DATABASE_URL` for direct Postgres.

Interactive API documentation is available at `http://127.0.0.1:8000/docs`.
Mutating endpoints require:

```text
Authorization: Bearer <TRANSCRIPT_INGEST_API_KEY>
```

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Service health check |
| `POST` | `/v1/conversations` | Start a conversation |
| `POST` | `/v1/conversations/{id}/turns` | Add a finalized transcript turn |
| `PUT` | `/v1/conversations/{id}/financial-context` | Set financial context |
| `PUT` | `/v1/conversations/{id}/speaker-identity` | Set an upstream speaker match |
| `POST` | `/v1/conversations/{id}/analyze` | Recompute the assessment |
| `GET` | `/v1/conversations/{id}/assessment` | Fetch the latest assessment |

Finalized turn ingestion is idempotent by `segment_id`. Financial context and
speaker identity can arrive later and cause the complete assessment to be
recomputed.

## Deepgram keyterms

The curated Nova-3 vocabulary is in `config/deepgram-keyterms.json`.

```sh
npm run deepgram:keyterms
npm run deepgram:keyterms -- --category businesses --format query
```

## Supabase and Render

The schema migration is
`supabase/migrations/20260816100000_post_transcript_pipeline.sql`; RLS is enabled
on all application tables. `render.yaml` defines the post-transcript service.

## Tests

```sh
npm test
PYTHONPATH=src python3 -m unittest discover -s tests -v
```
