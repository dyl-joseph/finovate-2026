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
