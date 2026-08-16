import assert from "node:assert/strict";
import test from "node:test";
import WebSocket from "ws";
import { WebSocketServer } from "ws";
import { createAppServer } from "../server/index.mjs";

async function listen(server) {
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
  return server.address().port;
}

test("health endpoint reports keyterm and secret configuration state", async (context) => {
  const { server } = await createAppServer({ apiKey: null });
  context.after(() => server.close());
  const port = await listen(server);
  const response = await fetch(`http://127.0.0.1:${port}/api/health`);
  assert.deepEqual(await response.json(), {
    ok: true,
    deepgram_configured: false,
    post_transcript_configured: false,
    keyterm_count: 98,
  });
});

test("ingests a canonical transcript into the post-transcript API", async (context) => {
  const upstreamRequests = [];
  const postTranscriptFetch = async (url, options) => {
    const request = {
      url: new URL(url),
      authorization: options.headers.Authorization,
      body: JSON.parse(options.body),
    };
    upstreamRequests.push(request);
    if (request.url.pathname === "/v1/conversations") {
      return Response.json({ conversation_id: "call-1", status: "collecting", assessment: null }, { status: 201 });
    }
    const score = upstreamRequests.length === 2 ? 20 : 85;
    return Response.json({
      conversation_id: "call-1",
      status: "assessed",
      segment_id: request.body.segment_id,
      duplicate_segment: false,
      assessment: { risk: { score, level: score >= 80 ? "critical" : "low" } },
    });
  };
  const { server } = await createAppServer({
    apiKey: null,
    postTranscriptUrl: "http://post-transcript.test:8000",
    ingestApiKey: "ingest-secret",
    postTranscriptFetch,
  });
  context.after(() => server.close());
  const port = await listen(server);
  const transcript = {
    conversation_id: "call-1",
    caller_speaker_id: "SPEAKER_01",
    metadata: { source: "diarization-service" },
    turns: [
      {
        speaker_id: "SPEAKER_01",
        role: "caller",
        text: "I'm calling from Chase fraud department.",
        start_ms: 0,
        end_ms: 1200,
      },
      {
        speaker_id: "SPEAKER_01",
        role: "caller",
        text: "Move $2,000 immediately.",
        start_ms: 1300,
        end_ms: 2400,
      },
    ],
  };

  const response = await fetch(`http://127.0.0.1:${port}/api/analyze-transcript`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(transcript),
  });

  assert.equal(response.status, 200);
  assert.equal((await response.json()).assessment.risk.score, 85);
  assert.equal(upstreamRequests.length, 3);
  assert.deepEqual(upstreamRequests.map((request) => request.url.pathname), [
    "/v1/conversations",
    "/v1/conversations/call-1/turns",
    "/v1/conversations/call-1/turns",
  ]);
  assert.ok(upstreamRequests.every((request) => request.authorization === "Bearer ingest-secret"));
  assert.equal(upstreamRequests[1].body.segment_id, "final-0001");
  assert.equal(upstreamRequests[2].body.segment_id, "final-0002");
  assert.equal(upstreamRequests[2].body.is_final, true);
});

test("fails safely when post-transcript analysis is unconfigured or malformed", async (context) => {
  const { server } = await createAppServer({ apiKey: null, postTranscriptUrl: null });
  context.after(() => server.close());
  const port = await listen(server);
  const unconfigured = await fetch(`http://127.0.0.1:${port}/api/analyze-transcript`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: "{}",
  });

  assert.equal(unconfigured.status, 503);
  assert.equal((await unconfigured.json()).error, "Post-transcript pipeline is not configured");

  const configured = await createAppServer({
    apiKey: null,
    postTranscriptUrl: "http://post-transcript.test:8000",
    ingestApiKey: "ingest-secret",
  });
  context.after(() => configured.server.close());
  const configuredPort = await listen(configured.server);
  const malformed = await fetch(`http://127.0.0.1:${configuredPort}/api/analyze-transcript`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ conversation_id: "call-1", caller_speaker_id: "SPEAKER_01", turns: [] }),
  });

  assert.equal(malformed.status, 400);
  assert.match((await malformed.json()).error, /at least one turn/);
});

test("WebSocket fails safely when the API key is missing", async (context) => {
  const { server } = await createAppServer({ apiKey: null });
  context.after(() => server.close());
  const port = await listen(server);
  const socket = new WebSocket(`ws://127.0.0.1:${port}/api/live-transcription`);
  context.after(() => socket.terminate());
  const message = await new Promise((resolve, reject) => {
    socket.once("message", (data) => resolve(JSON.parse(data.toString())));
    socket.once("error", reject);
  });
  assert.deepEqual(message, {
    type: "configuration_error",
    message: "DEEPGRAM_API_KEY is not configured on the server",
  });
});

test("WebSocket accepts the app's own origin", async (context) => {
  const { server } = await createAppServer({ apiKey: null });
  context.after(() => server.close());
  const port = await listen(server);
  const socket = new WebSocket(`ws://127.0.0.1:${port}/api/live-transcription`, {
    headers: { Origin: `http://127.0.0.1:${port}` },
  });
  context.after(() => socket.terminate());
  const message = await new Promise((resolve, reject) => {
    socket.once("message", (data) => resolve(JSON.parse(data.toString())));
    socket.once("error", reject);
  });
  assert.equal(message.type, "configuration_error");
});

test("proxies binary audio to an authenticated Deepgram socket and returns results", async (context) => {
  const upstreamServer = new WebSocketServer({ host: "127.0.0.1", port: 0 });
  await new Promise((resolve) => upstreamServer.once("listening", resolve));
  context.after(() => upstreamServer.close());
  const upstreamPort = upstreamServer.address().port;
  let authorization;
  const receivedAudio = new Promise((resolve) => {
    upstreamServer.once("connection", (upstreamSocket, request) => {
      authorization = request.headers.authorization;
      upstreamSocket.once("message", (data, isBinary) => {
        resolve({ bytes: [...data], isBinary });
        upstreamSocket.send(JSON.stringify({
          type: "Results",
          is_final: true,
          channel: { alternatives: [{ transcript: "Chase fraud department.", words: [] }] },
        }));
      });
    });
  });

  const { server } = await createAppServer({
    apiKey: "server-secret",
    deepgramUrl: new URL(`ws://127.0.0.1:${upstreamPort}/v1/listen`),
  });
  context.after(() => server.close());
  const port = await listen(server);
  const client = new WebSocket(`ws://127.0.0.1:${port}/api/live-transcription`);
  context.after(() => client.terminate());
  const messages = [];
  client.on("message", (data) => messages.push(JSON.parse(data.toString())));
  await new Promise((resolve, reject) => {
    client.once("open", resolve);
    client.once("error", reject);
  });
  while (!messages.some((message) => message.type === "ready")) {
    await new Promise((resolve) => setTimeout(resolve, 5));
  }
  client.send(Buffer.from([1, 2, 3]));
  assert.deepEqual(await receivedAudio, { bytes: [1, 2, 3], isBinary: true });
  while (!messages.some((message) => message.type === "Results")) {
    await new Promise((resolve) => setTimeout(resolve, 5));
  }
  assert.equal(authorization, "Token server-secret");
  assert.equal(messages.find((message) => message.type === "Results").is_final, true);
});

test("uploads the complete recording to the v2 batch diarizer", async (context) => {
  const expectedResponse = {
    results: { channels: [{ alternatives: [{ words: [
      { speaker: 0, word: "Hello", start: 0, end: .4 },
      { speaker: 1, word: "Hi", start: .5, end: .8 },
    ] }] }] },
  };
  let upstreamRequest;
  const deepgramFetch = async (url, options) => {
    upstreamRequest = { url: new URL(url), options };
    return new Response(JSON.stringify(expectedResponse), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  };
  const { server } = await createAppServer({ apiKey: "server-secret", deepgramFetch });
  context.after(() => server.close());
  const port = await listen(server);
  const audio = new Uint8Array([10, 20, 30, 40]);
  const response = await fetch(`http://127.0.0.1:${port}/api/transcribe-call`, {
    method: "POST",
    headers: { "Content-Type": "audio/webm;codecs=opus" },
    body: audio,
  });

  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), expectedResponse);
  assert.equal(upstreamRequest.url.searchParams.get("diarize_model"), "v2");
  assert.equal(upstreamRequest.url.searchParams.get("model"), "nova-3");
  assert.equal(upstreamRequest.options.headers.Authorization, "Token server-secret");
  assert.equal(upstreamRequest.options.headers["Content-Type"], "audio/webm");
  assert.deepEqual([...upstreamRequest.options.body], [...audio]);
});

test("rejects empty or unsupported full-call recordings before contacting Deepgram", async (context) => {
  let upstreamCalls = 0;
  const { server } = await createAppServer({
    apiKey: "server-secret",
    deepgramFetch: async () => { upstreamCalls += 1; },
  });
  context.after(() => server.close());
  const port = await listen(server);
  const unsupported = await fetch(`http://127.0.0.1:${port}/api/transcribe-call`, {
    method: "POST", headers: { "Content-Type": "text/plain" }, body: "audio",
  });
  const empty = await fetch(`http://127.0.0.1:${port}/api/transcribe-call`, {
    method: "POST", headers: { "Content-Type": "audio/webm" }, body: new Uint8Array(),
  });

  assert.equal(unsupported.status, 415);
  assert.equal(empty.status, 400);
  assert.equal(upstreamCalls, 0);
});
