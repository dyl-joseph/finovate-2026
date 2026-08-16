import assert from "node:assert/strict";
import test from "node:test";
import { buildDeepgramListenUrl } from "../server/deepgram-url.mjs";

test("builds Nova-3 diarization streaming configuration with all keyterms", async () => {
  const { url, keytermCount } = await buildDeepgramListenUrl();
  assert.equal(url.origin, "wss://api.deepgram.com");
  assert.equal(url.pathname, "/v1/listen");
  for (const [name, value] of Object.entries({
    model: "nova-3", language: "en-US", diarize_model: "latest",
    smart_format: "true", interim_results: "true", endpointing: "300",
    utterance_end_ms: "1000", vad_events: "true",
  })) assert.equal(url.searchParams.get(name), value);
  assert.equal(url.searchParams.getAll("keyterm").length, keytermCount);
  assert.equal(keytermCount, 98);
  assert.ok(url.searchParams.getAll("keyterm").includes("Chase"));
  assert.ok(!url.toString().includes("DEEPGRAM_API_KEY"));
});
