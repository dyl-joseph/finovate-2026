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
`SQLiteEncounterRepository`. The repository interface is the boundary for the
planned Supabase/Postgres adapter.

## Tests

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

The evidence graph returns typed `nodes` and `edges`. Every financial finding
links back to the transcript signal that triggered it and forward to the final
risk node, allowing the frontend to explain why the score changed. High-risk
results also include ordered recommendations such as ending the call, using an
official contact channel, pausing a transfer, and verifying a new recipient.
