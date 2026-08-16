import assert from "node:assert/strict";
import test from "node:test";
import { buildDeepgramListenUrl, buildDeepgramPrerecordedUrl } from "../server/deepgram-url.mjs";

test("builds Nova-3 diarization streaming configuration with all keyterms", async () => {
  const { url, keytermCount } = await buildDeepgramListenUrl();
  assert.equal(url.origin, "wss://api.deepgram.com");
  assert.equal(url.pathname, "/v1/listen");
  for (const [name, value] of Object.entries({
    model: "nova-3", language: "en-US", diarize: "true", diarize_model: "latest",
    smart_format: "true", interim_results: "true", endpointing: "300",
    utterance_end_ms: "1000", vad_events: "true",
  })) assert.equal(url.searchParams.get(name), value);
  assert.equal(url.searchParams.getAll("keyterm").length, keytermCount);
  assert.equal(keytermCount, 98);
  assert.ok(url.searchParams.getAll("keyterm").includes("Chase"));
  assert.ok(!url.toString().includes("DEEPGRAM_API_KEY"));
});

test("uses the v2 diarizer for full-call prerecorded analysis", async () => {
  const { url, keytermCount } = await buildDeepgramPrerecordedUrl();
  assert.equal(url.origin, "https://api.deepgram.com");
  assert.equal(url.pathname, "/v1/listen");
  assert.equal(url.searchParams.get("model"), "nova-3");
  assert.equal(url.searchParams.get("language"), "en-US");
  assert.equal(url.searchParams.get("diarize"), "true");
  assert.equal(url.searchParams.get("diarize_model"), "v2");
  assert.equal(url.searchParams.get("smart_format"), "true");
  assert.equal(url.searchParams.get("utterances"), "true");
  assert.equal(url.searchParams.getAll("keyterm").length, keytermCount);
  assert.equal(keytermCount, 98);
});
