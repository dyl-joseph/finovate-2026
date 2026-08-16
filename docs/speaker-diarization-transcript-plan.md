# Speaker diarization and transcript plan

## Scope

This plan defines how finalized, word-level diarization results become the
canonical transcript consumed by the fraud pipeline. It also defines the
Deepgram keyterm vocabulary used to preserve institution names, payment
products, government agencies, and high-value scam language.

The following work is intentionally deferred:

- Live audio capture, mixing, or channel routing
- Opening and maintaining the Deepgram streaming ASR connection
- WebSocket authentication and temporary-token delivery
- Reconnection, buffering, and backpressure behavior
- Persistent voice similarity across separate calls

The future ASR adapter must supply finalized word records containing text,
speaker, start time, and end time. This transcript layer should not depend on
how those records arrived.

## Canonical final transcript

The final artifact must validate against
[`schemas/final-transcript.schema.json`](../schemas/final-transcript.schema.json).

```json
{
  "conversation_id": "demo-call-001",
  "caller_speaker_id": "SPEAKER_01",
  "turns": [
    {
      "speaker_id": "SPEAKER_01",
      "role": "caller",
      "text": "I'm calling from Chase fraud department.",
      "start_ms": 0,
      "end_ms": 1800
    },
    {
      "speaker_id": "SPEAKER_00",
      "role": "customer",
      "text": "What happened?",
      "start_ms": 1900,
      "end_ms": 2600
    },
    {
      "speaker_id": "SPEAKER_01",
      "role": "caller",
      "text": "There was a charge for $900. You need to act immediately.",
      "start_ms": 2700,
      "end_ms": 5200
    }
  ],
  "metadata": {
    "source": "diarization-service",
    "language": "en-US"
  }
}
```

## Input contract

The transcript assembler accepts only finalized words. Each word must provide:

```text
text: non-empty string
speaker: non-negative Deepgram speaker number
start: non-negative time in seconds
end: time in seconds greater than or equal to start
```

Interim ASR results must not enter this layer. If a future integration needs
interim UI captions, it must keep those values in a replaceable display buffer
that is separate from the finalized transcript state.

## Speaker and role normalization

- Map Deepgram speaker `0` to `SPEAKER_00`, `1` to `SPEAKER_01`, and so on.
- Preserve that mapping for the entire `conversation_id`.
- Deepgram speaker numbers do not identify caller versus customer.
- Prefer an explicit role mapping from call direction or separate audio
  channels when the future audio layer can provide one.
- Otherwise set `role` to `unknown` until the caller is identified.
- Once identified, set `caller_speaker_id` and apply the corresponding role to
  that speaker's turns. Other speakers are not automatically customers unless
  the call context establishes that fact.
- Speaker IDs are scoped to one call and must not be treated as cross-call
  identity evidence.

## Turn assembly algorithm

1. Reject malformed or non-finalized word records.
2. Sort committed words by start time while retaining source order for ties.
3. Convert seconds to integer milliseconds with `Math.round(value * 1000)`.
4. Start a turn from the first word.
5. Append subsequent words while the normalized speaker ID remains the same.
6. Close the current turn immediately when the speaker changes.
7. Use the first word's start time and last word's end time for the turn bounds.
8. Preserve recognized wording; do not summarize, correct grammar, remove
   repetition, or soften urgency and threats.
9. Reconstruct punctuation from the ASR word representation when available.
10. Emit turns in ascending `start_ms` order.

Pauses by the same speaker do not require a new turn in the final transcript.
The future streaming integration may emit a finalized live turn at a detected
utterance boundary, but the canonical transcript may merge adjacent finalized
segments when they belong to the same speaker and no intervening speaker spoke.

## Financial detail preservation

The assembler must preserve institution names, account names, phone numbers,
verification codes, transfer destinations, and monetary amounts. For the MVP,
unambiguous recognized currency should use forms such as `$900`, `$2,000`, and
`$125.50` when the ASR formatter supplies enough evidence. It must never invent
an amount when the audio or finalized words are unclear.

The keyterm configuration improves recognition but is not fraud evidence by
itself. For example, recognizing `Chase` means the caller mentioned Chase; it
does not prove the caller represents Chase.

## Planned streaming event contract

The deferred streaming layer should eventually publish finalized turns as:

```json
{
  "conversation_id": "demo-call-001",
  "event": "transcript_turn",
  "turn": {
    "speaker_id": "SPEAKER_01",
    "role": "caller",
    "text": "Move $2,000 to a secure account.",
    "start_ms": 5300,
    "end_ms": 7200
  },
  "is_final": true
}
```

Only `is_final: true` turns may enter the fraud pipeline. If partial turns are
introduced later, they must carry a stable segment ID and replacement semantics
so the same words are not analyzed repeatedly.

## Verification plan

Focused transcript-assembler tests should cover:

- Stable speaker normalization throughout a conversation
- Splitting exactly when the speaker changes
- Ascending turn order and integer millisecond timestamps
- Unknown roles until an explicit mapping is supplied
- Caller ID propagation after the caller is identified
- Preservation of punctuation, repetition, threats, account names, codes,
  transfer destinations, phone numbers, and formatted currency
- Rejection or isolation of interim results
- Deduplication at the future ASR-adapter boundary
- No invented currency when recognition is ambiguous

Those behavioral tests should be added alongside the transcript assembler when
it is implemented. The current keyterm CLI has its own focused unit and CLI
tests.
