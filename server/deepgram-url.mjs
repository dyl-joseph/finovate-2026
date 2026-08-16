import { collectKeyterms, loadKeytermConfig } from "../src/deepgram-keyterms.mjs";

export async function buildDeepgramListenUrl() {
  const config = await loadKeytermConfig();
  const keyterms = collectKeyterms(config);
  const url = new URL("wss://api.deepgram.com/v1/listen");
  const options = {
    model: "nova-3",
    language: "en-US",
    diarize_model: "latest",
    smart_format: "true",
    interim_results: "true",
    endpointing: "300",
    utterance_end_ms: "1000",
    vad_events: "true",
    tag: "finovate-diarization-mvp",
  };
  for (const [name, value] of Object.entries(options)) url.searchParams.set(name, value);
  for (const keyterm of keyterms) url.searchParams.append("keyterm", keyterm);
  return { url, keytermCount: keyterms.length };
}

export async function buildDeepgramPrerecordedUrl() {
  const config = await loadKeytermConfig();
  const keyterms = collectKeyterms(config);
  const url = new URL("https://api.deepgram.com/v1/listen");
  const options = {
    model: "nova-3",
    language: "en-US",
    diarize_model: "v2",
    smart_format: "true",
    utterances: "true",
    tag: "finovate-full-call-diarization-mvp",
  };
  for (const [name, value] of Object.entries(options)) url.searchParams.set(name, value);
  for (const keyterm of keyterms) url.searchParams.append("keyterm", keyterm);
  return { url, keytermCount: keyterms.length };
}
