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

## Input contracts

- Transcript example: `examples/sample_transcript.json`
- Financial context example: `examples/sample_financial_context.json`

Transcript turns must be ordered by `start_ms`, use a stable `speaker_id`, and
include either a `role` or a top-level `caller_speaker_id`.

## Python usage

```python
import json

from finovate_pipeline import FinancialContext, ScamAssessmentPipeline, Transcript

with open("examples/sample_transcript.json", encoding="utf-8") as file:
    transcript = Transcript.from_dict(json.load(file))

with open("examples/sample_financial_context.json", encoding="utf-8") as file:
    context = FinancialContext.from_dict(json.load(file))

result = ScamAssessmentPipeline().analyze(transcript, context)
print(json.dumps(result.to_dict(), indent=2))
```

## Tests

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

The evidence graph returns typed `nodes` and `edges`. Every financial finding
links back to the transcript signal that triggered it and forward to the final
risk node, allowing the frontend to explain why the score changed.
