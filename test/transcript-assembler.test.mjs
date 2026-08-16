import assert from "node:assert/strict";
import test from "node:test";

import { TranscriptAssembler } from "../src/transcript-assembler.mjs";

function result(words, overrides = {}) {
  return { type: "Results", is_final: true, channel: { alternatives: [{ words }] }, ...overrides };
}

test("builds the exact required final transcript contract", () => {
  const assembler = new TranscriptAssembler({ conversationId: "demo-call-001" });
  assembler.ingestDeepgramResult(result([
    { speaker: 1, word: "I'm", start: 0, end: .3 },
    { speaker: 1, word: "calling", start: .31, end: .7 },
    { speaker: 1, word: "from", start: .71, end: .9 },
    { speaker: 1, word: "Chase", start: .91, end: 1.2 },
    { speaker: 1, word: "fraud", start: 1.21, end: 1.45 },
    { speaker: 1, word: "department", punctuated_word: "department.", start: 1.46, end: 1.8 },
    { speaker: 0, word: "What", start: 1.9, end: 2.1 },
    { speaker: 0, word: "happened", punctuated_word: "happened?", start: 2.11, end: 2.6 },
    { speaker: 1, word: "There", start: 2.7, end: 2.9 },
    { speaker: 1, word: "was", start: 2.91, end: 3.1 },
    { speaker: 1, word: "a", start: 3.11, end: 3.2 },
    { speaker: 1, word: "charge", start: 3.21, end: 3.5 },
    { speaker: 1, word: "for", start: 3.51, end: 3.65 },
    { speaker: 1, word: "$900", punctuated_word: "$900.", start: 3.66, end: 4 },
    { speaker: 1, word: "You", start: 4.01, end: 4.15 },
    { speaker: 1, word: "need", start: 4.16, end: 4.35 },
    { speaker: 1, word: "to", start: 4.36, end: 4.45 },
    { speaker: 1, word: "act", start: 4.46, end: 4.7 },
    { speaker: 1, word: "immediately", punctuated_word: "immediately.", start: 4.71, end: 5.2 },
  ]));
  assembler.setSpeakerRole("SPEAKER_01", "caller");
  assembler.setSpeakerRole("SPEAKER_00", "customer");

  assert.deepEqual(assembler.buildFinalTranscript(), {
    conversation_id: "demo-call-001",
    caller_speaker_id: "SPEAKER_01",
    turns: [
      { speaker_id: "SPEAKER_01", role: "caller", start_ms: 0, end_ms: 1800, text: "I'm calling from Chase fraud department." },
      { speaker_id: "SPEAKER_00", role: "customer", start_ms: 1900, end_ms: 2600, text: "What happened?" },
      { speaker_id: "SPEAKER_01", role: "caller", start_ms: 2700, end_ms: 5200, text: "There was a charge for $900. You need to act immediately." },
    ],
    metadata: { source: "diarization-service", language: "en-US" },
  });
});

test("ignores interim results and deduplicates repeated finalized words", () => {
  const assembler = new TranscriptAssembler({ conversationId: "dedupe-call" });
  const words = [{ speaker: 0, word: "Hello", punctuated_word: "Hello.", start: 0, end: .5 }];
  assert.deepEqual(assembler.ingestDeepgramResult(result(words, { is_final: false })), []);
  assert.equal(assembler.ingestDeepgramResult(result(words)).length, 1);
  assert.deepEqual(assembler.ingestDeepgramResult(result(words)), []);
});

test("emits only finalized per-speaker turn events", () => {
  const assembler = new TranscriptAssembler({ conversationId: "event-call" });
  const events = assembler.ingestDeepgramResult(result([
    { speaker: 1, word: "Move", start: 5.3, end: 5.6 },
    { speaker: 1, word: "$2,000", start: 5.61, end: 6.1 },
    { speaker: 1, word: "to", start: 6.11, end: 6.3 },
    { speaker: 1, word: "a", start: 6.31, end: 6.4 },
    { speaker: 1, word: "secure", start: 6.41, end: 6.8 },
    { speaker: 1, word: "account", punctuated_word: "account.", start: 6.81, end: 7.2 },
  ]));
  assert.deepEqual(events, [{
    conversation_id: "event-call",
    event: "transcript_turn",
    turn: { speaker_id: "SPEAKER_01", role: "unknown", start_ms: 5300, end_ms: 7200, text: "Move $2,000 to a secure account." },
    is_final: true,
  }]);
});

test("preserves repetition, threats, codes, phone numbers, and currency", () => {
  const assembler = new TranscriptAssembler({ conversationId: "verbatim-call" });
  assembler.ingestDeepgramResult(result([
    { speaker: 2, word: "Immediately", punctuated_word: "Immediately.", start: 0, end: .4 },
    { speaker: 2, word: "Immediately", punctuated_word: "Immediately.", start: .5, end: .9 },
    { speaker: 2, word: "Do", start: 1, end: 1.1 }, { speaker: 2, word: "not", start: 1.11, end: 1.2 },
    { speaker: 2, word: "tell", start: 1.21, end: 1.35 }, { speaker: 2, word: "anyone", punctuated_word: "anyone.", start: 1.36, end: 1.6 },
    { speaker: 2, word: "Code", start: 1.7, end: 1.9 }, { speaker: 2, word: "483921", punctuated_word: "483921.", start: 1.91, end: 2.3 },
    { speaker: 2, word: "Call", start: 2.4, end: 2.55 }, { speaker: 2, word: "1-800-555-0199", punctuated_word: "1-800-555-0199.", start: 2.56, end: 3.2 },
    { speaker: 2, word: "Send", start: 3.3, end: 3.5 }, { speaker: 2, word: "$125.50", punctuated_word: "$125.50.", start: 3.51, end: 4 },
    { speaker: 2, word: "Your", start: 4.1, end: 4.2 }, { speaker: 2, word: "account", start: 4.21, end: 4.4 },
    { speaker: 2, word: "will", start: 4.41, end: 4.55 }, { speaker: 2, word: "be", start: 4.56, end: 4.65 },
    { speaker: 2, word: "frozen", punctuated_word: "frozen.", start: 4.66, end: 5 },
  ]));
  assembler.setSpeakerRole("SPEAKER_02", "caller");
  assert.equal(assembler.buildFinalTranscript().turns[0].text,
    "Immediately. Immediately. Do not tell anyone. Code 483921. Call 1-800-555-0199. Send $125.50. Your account will be frozen.");
});

test("requires a transcribed caller and rejects inverted timestamps", () => {
  const assembler = new TranscriptAssembler({ conversationId: "role-call" });
  assembler.ingestDeepgramResult(result([{ speaker: 0, word: "Hello", start: 0, end: .4 }]));
  assert.throws(() => assembler.buildFinalTranscript(), /Identify the caller/);
  assembler.setSpeakerRole("SPEAKER_01", "caller");
  assert.throws(() => assembler.buildFinalTranscript(), /must belong/);
  assert.throws(() => assembler.ingestDeepgramResult(result([{ speaker: 0, word: "No", start: 1, end: .5 }])), /cannot precede/);
});
