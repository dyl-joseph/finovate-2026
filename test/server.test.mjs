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
  assert.deepEqual(await response.json(), { ok: true, deepgram_configured: false, keyterm_count: 98 });
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
