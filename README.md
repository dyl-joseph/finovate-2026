# Finovate 2026

Planning and supporting tools for the Financial Scam Intelligence Layer.

## Live diarization app

The local app records the complete browser microphone session while streaming
provisional captions through the local Node server. When you stop the call, it
uploads the complete recording to Deepgram Nova-3's batch `v2` diarizer and
assembles those word-level results into the required speaker-turn JSON. The
full-call pass has more context for distinguishing speakers than the streaming
diarizer.

Copy the environment template and add the Deepgram key you created:

```sh
cp .env.example .env
```

Edit `.env` so it contains:

```dotenv
DEEPGRAM_API_KEY=your_real_key
```

Then start the app:

```sh
npm install
npm start
```

Open `http://127.0.0.1:3000`, select **Start microphone**, and allow microphone
access. The microphone must hear both participants for single-channel speaker
diarization. Speak naturally with alternating turns, then select **Stop and
finalize**. Wait for **Finalized**, assign one speaker as `caller` and the other
as `customer`, then copy or download the final transcript JSON.

The API key remains on the local server and is never returned to the browser.
Streaming results are captions only. Final `transcript_turn` events and exported
JSON are rebuilt from the complete-call batch response. Live audio, the retained
in-memory recording, and transcripts are sent to Deepgram when this app is
running; use synthetic demo calls rather than real financial or personal data.

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

The browser microphone and streaming-caption path are implemented, but the final
speaker labels intentionally come from the more accurate full-call batch pass.
