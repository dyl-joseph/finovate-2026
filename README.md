# Finovate 2026

Planning and supporting tools for the Financial Scam Intelligence Layer.

## Deepgram keyterms

The curated Nova-3 keyterm vocabulary lives in
[`config/deepgram-keyterms.json`](config/deepgram-keyterms.json). Generate the
repeated, URL-encoded `keyterm` query parameters with:

```sh
npm run deepgram:keyterms
```

Other useful formats and category filters are available through the CLI:

```sh
npm run deepgram:keyterms -- --format json
npm run deepgram:keyterms -- --format lines
npm run deepgram:keyterms -- --category businesses --format query
```

This command only produces configuration output. It does not contact Deepgram,
read `DEEPGRAM_API_KEY`, or start a streaming transcription connection.

## Diarized transcript contract

The planned speaker-normalization, role-mapping, and final transcript behavior
is documented in
[`docs/speaker-diarization-transcript-plan.md`](docs/speaker-diarization-transcript-plan.md).
The machine-readable output contract is
[`schemas/final-transcript.schema.json`](schemas/final-transcript.schema.json).

Live audio capture and the streaming ASR connection are intentionally outside
the current scope.
