# Live Audio → Streaming ASR: interface contract

This document specifies what the Live Audio / Streaming ASR module (owned by
audio) produces, so the diarization/transcript module and the
evidence-graph/reasoning module can build against a fixed contract instead of
against this module's internals. Nothing here should change without updating
this doc first.

Status: draft, not yet implemented. Backend scaffolding on
`feature/live-audio-streaming-asr` implements this contract; treat this file
as the source of truth if code and doc ever disagree.

## 1. Scope

This module owns everything up to and including streaming ASR:

```
LIVE AUDIO → Streaming ASR
```

It does **not** do speaker diarization, speaker re-identification, claim
extraction, or risk scoring. It exposes two output streams — raw audio and
ASR transcript events — both keyed by the same `session_id` and the same
clock, so downstream modules can align on them however they need.

## 2. Audio capture format

Fixed for the hackathon — no negotiation, no format discovery:

| Property | Value |
| --- | --- |
| Source | Browser mic via `getUserMedia`, captured with an `AudioWorklet` (simulates a live call leg; no real telecom/proxy-number integration for the demo) |
| Encoding | PCM signed 16-bit little-endian (`linear16`) |
| Channels | 1 (mono) |
| Sample rate | 16000 Hz |
| Chunk size | ~100ms per chunk (3200 bytes = 1600 samples × 2 bytes), sent as soon as the worklet buffer fills. Downstream consumers must not assume a fixed chunk size — treat the audio stream as a continuous byte sequence and use `offset_ms`/`sequence` for timing, not chunk boundaries. |

If a teammate needs a different sample rate/encoding (e.g. a diarization
model that wants 8kHz or float32), resample on your side — the wire format
above is fixed so there's one source of truth.

## 3. Transport: two WebSocket endpoints

Backend: FastAPI, base URL `ws://localhost:8000` in dev.

### 3.1 `/ws/audio` — ingest only (producer: browser mic; not for teammates to connect to)

The browser connects here and pushes captured audio. One connection = one
call session. Closing the connection ends the session.

### 3.2 `/ws/audio-stream` — raw audio tap (for the diarization module)

Read-only fan-out of the exact bytes received on `/ws/audio`, for whoever
needs the raw audio (e.g. speaker diarization / voice-embedding extraction).
Connect any time; you get audio from that point forward (no backfill/replay
of audio before you connected).

### 3.3 `/ws/transcript` — ASR event stream (for diarization + evidence-graph modules)

Read-only fan-out of ASR results and session lifecycle events. This is the
one most consumers want — it does not require handling raw audio at all.

### `/ws/audio` ingest format (browser → server)

The browser sends **raw binary PCM16LE frames only** — no metadata. The
server is the authority on timing: it computes `sequence` and `offset_ms`
itself from cumulative bytes received (`offset_ms` is derived from audio
content position — total bytes / sample_rate — not wall-clock receipt time,
so it stays consistent with Deepgram's own content-relative `start`/
`duration` values regardless of network jitter).

### `/ws/audio-stream` fan-out format (server → consumers)

WebSocket connections carry both text and binary messages, delivered in
order. Every audio chunk is re-broadcast as **two messages back to back**:

1. A text frame: a JSON `AudioChunkMeta` object (schema below), with
   server-computed `sequence`/`offset_ms`.
2. A binary frame: the raw PCM16LE bytes described by that metadata
   (`byte_length` bytes).

Consumers must read messages in pairs — an `AudioChunkMeta` text frame is
always immediately followed by its binary payload, never interleaved with
another chunk's frames.

```json
{"type": "audio_chunk", "session_id": "a1b2c3", "sequence": 42, "offset_ms": 4200.0, "byte_length": 3200}
```
followed immediately by a binary WebSocket frame of exactly 3200 bytes.

| Field | Type | Meaning |
| --- | --- | --- |
| `session_id` | string | Identifies the call session. New session per `/ws/audio` connection. |
| `sequence` | int | 0-based, increments by 1 per chunk, no gaps. Use to detect drops. |
| `offset_ms` | float | Milliseconds from the start of the session (first chunk = 0) to the start of this chunk's audio. This is the shared clock — use it to align with `TranscriptEvent.start`. |
| `byte_length` | int | Byte length of the binary frame that follows. |

## 4. Transcript event schema (`/ws/transcript`)

All messages on this endpoint are JSON text frames (no binary). Every
message has a `type` field; consumers should ignore unknown `type` values
rather than erroring, so this can grow.

### 4.1 `session_started`

Sent once, the moment a browser connects to `/ws/audio` and a session is
created. Sent before any `transcript` events for that session.

```json
{
  "type": "session_started",
  "session_id": "a1b2c3",
  "sample_rate": 16000,
  "started_at": "2026-08-16T18:32:01.123Z"
}
```

### 4.2 `transcript`

Emitted for every ASR result — both interim (still-changing) and final
results. Interim results let downstream modules react early; only trust
finalized text for anything that feeds a stored evidence graph.

```json
{
  "type": "transcript",
  "session_id": "a1b2c3",
  "sequence": 17,
  "is_final": false,
  "speech_final": false,
  "text": "i'm calling from chase and we detected",
  "confidence": 0.91,
  "start": 4.2,
  "duration": 2.6,
  "timestamp": "2026-08-16T18:32:05.700Z"
}
```

| Field | Type | Meaning |
| --- | --- | --- |
| `session_id` | string | Same session identifier as on the audio stream — join on this. |
| `sequence` | int | Monotonically increasing per session across ASR results (its own counter, independent of audio chunk `sequence`). Later `sequence` with the same time range supersedes earlier ones as ASR revises interim text. |
| `is_final` | bool | `true` once Deepgram has locked in this text window and won't revise it further. `false` = interim, text may still change on a later event covering the same time range. |
| `speech_final` | bool | `true` when the ASR engine's endpointing detected the end of an utterance (a natural pause) — a good signal for "the speaker just finished a thought," useful for the scam-progression/evidence-graph module to segment claims. Implies `is_final: true`. |
| `text` | string | Transcript text for this window. Lowercase, punctuation only if `smart_format` produces it. |
| `confidence` | float | 0.0–1.0 ASR confidence for this result. |
| `start` | float | **Seconds** (not ms) from session start to the beginning of this text window. Directly comparable to `offset_ms / 1000` from the audio stream — this is the shared clock for aligning transcript to raw audio / speaker segments. |
| `duration` | float | Seconds — length of the audio window this text covers. So the window is `[start, start + duration]`. |
| `timestamp` | string | Wall-clock ISO 8601 UTC, for logging/UI display only. Do not use for alignment — use `start`/`duration`. |

No `speaker` or `channel` field is included here on purpose — speaker
attribution is the diarization module's job. Diarization should consume
`/ws/audio-stream` (or `/ws/transcript` for timing) and produce its own
speaker-labeled segments keyed by `session_id` + time range, then join those
against these `transcript` events by overlapping `[start, start+duration]`
windows.

### 4.3 `session_ended`

Sent once, when the `/ws/audio` connection closes (call ends).

```json
{
  "type": "session_ended",
  "session_id": "a1b2c3",
  "ended_at": "2026-08-16T18:34:40.001Z"
}
```

### 4.4 `error`

```json
{
  "type": "error",
  "session_id": "a1b2c3",
  "message": "upstream ASR connection dropped"
}
```

## 5. Ordering & delivery guarantees

- Within one `session_id`, `transcript` events are delivered in the order
  the ASR engine emits them, which is generally but not strictly increasing
  in `start` — interim results for an earlier window can occasionally arrive
  after a final result for a slightly later window. Don't assume strict
  monotonic `start` ordering; do assume strictly increasing `sequence`.
- `session_started` always precedes every `transcript`/`session_ended` for
  that `session_id`. `session_ended` always comes last for that session.
- Multiple concurrent sessions are possible (e.g. the two-act demo running
  two calls). All consumers must key all state off `session_id` — never
  assume a single global session.
- If a consumer connects to `/ws/transcript` or `/ws/audio-stream`
  mid-session, they get events from that point forward only. No replay/buffer
  of history — if you need the full session transcript, start listening
  before the session starts, or (future work, not in scope here) add a
  persistence layer.

## 6. What downstream modules need to build

- **Diarization/transcript module**: connect to `/ws/audio-stream` for raw
  audio (speaker embeddings/segmentation need actual audio, not text) and
  optionally `/ws/transcript` for timing to align speaker segments to ASR
  text windows via `start`/`duration` overlap.
- **Evidence-graph/reasoning module**: connect to `/ws/transcript` only.
  Primarily consume `is_final: true` events (use `speech_final: true` as a
  good utterance/claim boundary); interim events are optional, for a
  "live typing" feel in the UI if wanted.

## 7. Open questions / not yet decided

- Whether `/ws/audio-stream` and `/ws/transcript` need auth/session scoping
  beyond `session_id` for the hackathon (currently: no auth, local network
  only, trust all connections).
- Whether we need a persisted transcript store so a module that joins late
  can fetch history (currently: no, live-only).
