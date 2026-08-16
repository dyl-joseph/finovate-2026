# Finovate 2026

Planning and supporting tools for the Financial Scam Intelligence Layer.

## Live diarization app

The local app records browser microphone audio, proxies it through the local
Node server, streams it to Deepgram Nova-3, and assembles finalized word results
into the required speaker-turn JSON.

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
diarization. After finalized speakers appear, assign one speaker as `caller`
and optionally assign the other as `customer`. Stop the session, then copy or
download the final transcript JSON.

The API key remains on the local server and is never returned to the browser.
Only Deepgram results with `is_final: true` enter the transcript assembler or
emit `transcript_turn` browser events. Live audio and transcripts are sent to
Deepgram when this app is running; use synthetic demo calls rather than real
financial or personal data.

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
