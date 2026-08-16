import { createReadStream } from "node:fs";
import { stat } from "node:fs/promises";
import { createServer } from "node:http";
import { extname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

import WebSocket, { WebSocketServer } from "ws";

import { buildDeepgramListenUrl, buildDeepgramPrerecordedUrl } from "./deepgram-url.mjs";

const ROOT = resolve(fileURLToPath(new URL("..", import.meta.url)));
const PUBLIC_FILES = new Map([
  ["/", "public/index.html"],
  ["/app.js", "public/app.js"],
  ["/assessment-memory.mjs", "public/assessment-memory.mjs"],
  ["/styles.css", "public/styles.css"],
  ["/src/transcript-assembler.mjs", "src/transcript-assembler.mjs"],
]);
const CONTENT_TYPES = new Map([
  [".html", "text/html; charset=utf-8"],
  [".js", "text/javascript; charset=utf-8"],
  [".mjs", "text/javascript; charset=utf-8"],
  [".css", "text/css; charset=utf-8"],
]);
const MAX_CALL_BYTES = 50_000_000;
const MAX_TRANSCRIPT_BYTES = 1_000_000;
const MAX_ANALYZE_TRANSCRIPT_BYTES = 50_000_000;
const AUDIO_CONTENT_TYPES = new Set(["audio/webm", "audio/ogg", "audio/wav", "audio/x-wav"]);

function jsonResponse(response, statusCode, body) {
  response.writeHead(statusCode, {
    "Content-Type": "application/json; charset=utf-8",
    "Cache-Control": "no-store",
  });
  response.end(JSON.stringify(body));
}

function setSecurityHeaders(response) {
  response.setHeader("X-Content-Type-Options", "nosniff");
  response.setHeader("Referrer-Policy", "no-referrer");
  response.setHeader(
    "Content-Security-Policy",
    "default-src 'self'; connect-src 'self' ws://127.0.0.1:* ws://localhost:*; media-src 'self' blob:; script-src 'self'; style-src 'self'",
  );
}

function readRequestBody(request, maxBytes = MAX_CALL_BYTES) {
  return new Promise((resolveBody, reject) => {
    const chunks = [];
    let byteLength = 0;
    let tooLarge = false;
    request.on("data", (chunk) => {
      byteLength += chunk.length;
      if (byteLength > maxBytes) {
        tooLarge = true;
        return;
      }
      chunks.push(chunk);
    });
    request.on("end", () => {
      if (tooLarge) reject(Object.assign(new Error("Request body is too large"), { statusCode: 413 }));
      else resolveBody(Buffer.concat(chunks));
    });
    request.on("error", reject);
  });
}

function validateFinalTranscript(transcript) {
  if (!transcript || typeof transcript !== "object" || Array.isArray(transcript)) {
    throw Object.assign(new Error("Final transcript must be a JSON object"), { statusCode: 400 });
  }
  if (typeof transcript.conversation_id !== "string" || !transcript.conversation_id.trim()) {
    throw Object.assign(new Error("conversation_id is required"), { statusCode: 400 });
  }
  if (typeof transcript.caller_speaker_id !== "string" || !transcript.caller_speaker_id.trim()) {
    throw Object.assign(new Error("caller_speaker_id is required"), { statusCode: 400 });
  }
  if (!Array.isArray(transcript.turns) || transcript.turns.length === 0) {
    throw Object.assign(new Error("Final transcript must contain at least one turn"), { statusCode: 400 });
  }
  for (const [index, turn] of transcript.turns.entries()) {
    const validRole = new Set(["caller", "customer", "unknown"]).has(turn?.role);
    if (
      !turn
      || typeof turn.speaker_id !== "string"
      || !validRole
      || typeof turn.text !== "string"
      || !turn.text.trim()
      || !Number.isInteger(turn.start_ms)
      || !Number.isInteger(turn.end_ms)
      || turn.start_ms < 0
      || turn.end_ms < turn.start_ms
    ) {
      throw Object.assign(new Error(`turns[${index}] is invalid`), { statusCode: 400 });
    }
  }
  return transcript;
}

function validateLiveAssessment(request) {
  if (!request || typeof request !== "object" || Array.isArray(request)) {
    throw Object.assign(new Error("Live assessment must be a JSON object"), { statusCode: 400 });
  }
  if (typeof request.conversation_id !== "string" || !request.conversation_id.trim()) {
    throw Object.assign(new Error("conversation_id is required"), { statusCode: 400 });
  }
  if (typeof request.caller_speaker_id !== "string" || !request.caller_speaker_id.trim()) {
    throw Object.assign(new Error("caller_speaker_id is required"), { statusCode: 400 });
  }
  if (!Array.isArray(request.turns)) {
    throw Object.assign(new Error("turns must be an array"), { statusCode: 400 });
  }
  for (const [index, turn] of request.turns.entries()) {
    if (typeof turn?.segment_id !== "string" || !turn.segment_id.trim()) {
      throw Object.assign(new Error(`turns[${index}].segment_id is required`), { statusCode: 400 });
    }
    validateFinalTranscript({
      conversation_id: request.conversation_id,
      caller_speaker_id: request.caller_speaker_id,
      turns: [turn],
    });
  }
  return request;
}

async function parseJsonRequest(request, maxBytes = MAX_TRANSCRIPT_BYTES) {
  const contentType = (request.headers["content-type"] ?? "").split(";", 1)[0].trim().toLowerCase();
  if (contentType !== "application/json") {
    throw Object.assign(new Error("Final transcript must use application/json"), { statusCode: 415 });
  }
  const body = await readRequestBody(request, maxBytes);
  try {
    return JSON.parse(body.toString("utf8"));
  } catch {
    throw Object.assign(new Error("Final transcript body is not valid JSON"), { statusCode: 400 });
  }
}

async function readUpstreamJson(response) {
  const text = await response.text();
  if (!text) return {};
  try {
    return JSON.parse(text);
  } catch {
    return { detail: text.slice(0, 500) };
  }
}

async function analyzeFinalTranscript(
  request,
  response,
  { ingestApiKey, postTranscriptFetch, postTranscriptUrl },
) {
  if (!postTranscriptUrl || !ingestApiKey) {
    jsonResponse(response, 503, { error: "Post-transcript pipeline is not configured" });
    return;
  }
  const parsed = await parseJsonRequest(request, MAX_ANALYZE_TRANSCRIPT_BYTES);
  const { recording, ...transcriptFields } = parsed;
  const transcript = validateFinalTranscript(transcriptFields);
  const headers = {
    Authorization: `Bearer ${ingestApiKey}`,
    "Content-Type": "application/json",
  };
  const createResponse = await postTranscriptFetch(
    new URL("/v1/conversations", postTranscriptUrl),
    {
      method: "POST",
      headers,
      body: JSON.stringify({
        conversation_id: transcript.conversation_id,
        caller_speaker_id: transcript.caller_speaker_id,
        metadata: transcript.metadata ?? {},
      }),
    },
  );
  if (!createResponse.ok && createResponse.status !== 409) {
    const body = await readUpstreamJson(createResponse);
    jsonResponse(response, 502, {
      error: "Post-transcript pipeline rejected the conversation",
      upstream_status: createResponse.status,
      detail: body.detail,
    });
    return;
  }

  let result;
  for (const [index, turn] of transcript.turns.entries()) {
    const segmentId = `final-${String(index + 1).padStart(4, "0")}`;
    const turnResponse = await postTranscriptFetch(
      new URL(
        `/v1/conversations/${encodeURIComponent(transcript.conversation_id)}/turns`,
        postTranscriptUrl,
      ),
      {
        method: "POST",
        headers,
        body: JSON.stringify({ segment_id: segmentId, is_final: true, ...turn }),
      },
    );
    result = await readUpstreamJson(turnResponse);
    if (!turnResponse.ok) {
      jsonResponse(response, 502, {
        error: `Post-transcript pipeline rejected turn ${index + 1}`,
        upstream_status: turnResponse.status,
        detail: result.detail,
      });
      return;
    }
  }

  if (typeof recording === "string" && recording.length > 0) {
    const enhanced = await attachVoiceIdentity(
      transcript,
      recording,
      ingestApiKey,
      postTranscriptFetch,
      postTranscriptUrl,
    );
    if (enhanced) result = enhanced;
  }
  jsonResponse(response, 200, result);
}

function callerWindowMs(transcript) {
  const callerTurns = (transcript.turns ?? []).filter((turn) => turn.role === "caller");
  if (callerTurns.length === 0) return null;
  return {
    start_ms: Math.min(...callerTurns.map((turn) => turn.start_ms)),
    end_ms: Math.max(...callerTurns.map((turn) => turn.end_ms)),
  };
}

async function attachVoiceIdentity(transcript, recordingBase64, ingestApiKey, postTranscriptFetch, postTranscriptUrl) {
  try {
    const window = callerWindowMs(transcript);
    const query = new URLSearchParams();
    if (window) {
      query.set("start_ms", String(window.start_ms));
      query.set("end_ms", String(window.end_ms));
    }
    const audio = Buffer.from(recordingBase64, "base64");
    const identityUrl = new URL(
      `/v1/conversations/${encodeURIComponent(transcript.conversation_id)}/speaker-identity/from-audio`,
      postTranscriptUrl,
    );
    if (query.toString()) identityUrl.search = query.toString();
    const identityResponse = await postTranscriptFetch(identityUrl, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${ingestApiKey}`,
        "Content-Type": "application/octet-stream",
      },
      body: audio,
    });
    if (identityResponse.ok) return await readUpstreamJson(identityResponse);
  } catch (error) {
    console.warn("Voice identity skipped:", error.message);
  }
  return null;
}

async function assessLiveTranscript(
  request,
  response,
  { ingestApiKey, postTranscriptFetch, postTranscriptUrl },
) {
  if (!postTranscriptUrl || !ingestApiKey) {
    jsonResponse(response, 503, { error: "Post-transcript pipeline is not configured" });
    return;
  }
  const liveRequest = validateLiveAssessment(await parseJsonRequest(request));
  const headers = {
    Authorization: `Bearer ${ingestApiKey}`,
    "Content-Type": "application/json",
  };
  const conversationUrl = new URL("/v1/conversations", postTranscriptUrl);
  const createResponse = await postTranscriptFetch(conversationUrl, {
    method: "POST",
    headers,
    body: JSON.stringify({
      conversation_id: liveRequest.conversation_id,
      caller_speaker_id: liveRequest.caller_speaker_id,
      metadata: { source: "live-transcription", ...liveRequest.metadata },
    }),
  });
  if (!createResponse.ok && createResponse.status !== 409) {
    const body = await readUpstreamJson(createResponse);
    jsonResponse(response, 502, {
      error: "Post-transcript pipeline rejected the live conversation",
      upstream_status: createResponse.status,
      detail: body.detail,
    });
    return;
  }

  let result;
  for (const turn of liveRequest.turns) {
    const turnResponse = await postTranscriptFetch(
      new URL(
        `/v1/conversations/${encodeURIComponent(liveRequest.conversation_id)}/turns`,
        postTranscriptUrl,
      ),
      {
        method: "POST",
        headers,
        body: JSON.stringify({ is_final: true, ...turn }),
      },
    );
    result = await readUpstreamJson(turnResponse);
    if (!turnResponse.ok) {
      jsonResponse(response, 502, {
        error: "Post-transcript pipeline rejected a live transcript turn",
        upstream_status: turnResponse.status,
        detail: result.detail,
      });
      return;
    }
  }
  if (!result) {
    const assessmentResponse = await postTranscriptFetch(
      new URL(
        `/v1/conversations/${encodeURIComponent(liveRequest.conversation_id)}/analyze`,
        postTranscriptUrl,
      ),
      { method: "POST", headers },
    );
    result = await readUpstreamJson(assessmentResponse);
    if (!assessmentResponse.ok) {
      jsonResponse(response, 502, {
        error: "Post-transcript pipeline could not refresh the live assessment",
        upstream_status: assessmentResponse.status,
        detail: result.detail,
      });
      return;
    }
  }
  jsonResponse(response, 200, result);
}

async function transcribeRecordedCall(request, response, { apiKey, deepgramBatchUrl, deepgramFetch }) {
  if (!apiKey) {
    jsonResponse(response, 503, { error: "DEEPGRAM_API_KEY is not configured on the server" });
    return;
  }
  const contentType = (request.headers["content-type"] ?? "").split(";", 1)[0].trim().toLowerCase();
  if (!AUDIO_CONTENT_TYPES.has(contentType)) {
    jsonResponse(response, 415, { error: "Recorded call must be WebM, Ogg, or WAV audio" });
    return;
  }
  const body = await readRequestBody(request);
  if (body.length === 0) {
    jsonResponse(response, 400, { error: "Recorded call is empty" });
    return;
  }
  const upstream = await deepgramFetch(deepgramBatchUrl, {
    method: "POST",
    headers: {
      Authorization: `Token ${apiKey}`,
      "Content-Type": contentType,
    },
    body,
  });
  const upstreamBody = await upstream.text();
  if (!upstream.ok) {
    jsonResponse(response, 502, {
      error: "Deepgram could not diarize the recorded call",
      status: upstream.status,
    });
    return;
  }
  response.writeHead(200, {
    "Content-Type": "application/json; charset=utf-8",
    "Cache-Control": "no-store",
  });
  response.end(upstreamBody);
}

async function serveRequest(request, response, dependencies) {
  const { keytermCount, configured, postTranscriptConfigured } = dependencies;
  setSecurityHeaders(response);
  const requestUrl = new URL(request.url, "http://localhost");
  if (request.method === "GET" && requestUrl.pathname === "/api/health") {
    jsonResponse(response, 200, {
      ok: true,
      deepgram_configured: configured,
      post_transcript_configured: postTranscriptConfigured,
      keyterm_count: keytermCount,
    });
    return;
  }
  if (request.method === "POST" && requestUrl.pathname === "/api/transcribe-call") {
    await transcribeRecordedCall(request, response, dependencies);
    return;
  }
  if (request.method === "POST" && requestUrl.pathname === "/api/analyze-transcript") {
    await analyzeFinalTranscript(request, response, dependencies);
    return;
  }
  if (request.method === "POST" && requestUrl.pathname === "/api/live-assessment") {
    await assessLiveTranscript(request, response, dependencies);
    return;
  }
  if (request.method !== "GET" || !PUBLIC_FILES.has(requestUrl.pathname)) {
    jsonResponse(response, 404, { error: "Not found" });
    return;
  }
  const filePath = resolve(ROOT, PUBLIC_FILES.get(requestUrl.pathname));
  await stat(filePath);
  response.writeHead(200, {
    "Content-Type": CONTENT_TYPES.get(extname(filePath)) ?? "application/octet-stream",
    "Cache-Control": "no-store",
  });
  createReadStream(filePath).pipe(response);
}

function sendJson(socket, value) {
  if (socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify(value));
}

function isAllowedWebSocketOrigin(request) {
  const origin = request.headers.origin;
  if (!origin) return true;
  try {
    const originUrl = new URL(origin);
    const forwardedHost = request.headers["x-forwarded-host"]?.split(",")[0].trim();
    const requestHost = forwardedHost || request.headers.host;
    if (requestHost && originUrl.host === requestHost) return true;
    return new Set(["127.0.0.1", "localhost", "::1"]).has(originUrl.hostname);
  } catch {
    return false;
  }
}

function bridgeDeepgram(clientSocket, deepgramUrl, apiKey) {
  const deepgramSocket = new WebSocket(deepgramUrl, {
    headers: { Authorization: `Token ${apiKey}` },
  });
  let keepAliveTimer;

  deepgramSocket.on("open", () => {
    sendJson(clientSocket, { type: "ready" });
    keepAliveTimer = setInterval(() => {
      if (deepgramSocket.readyState === WebSocket.OPEN) {
        deepgramSocket.send(JSON.stringify({ type: "KeepAlive" }));
      }
    }, 5000);
  });
  deepgramSocket.on("message", (data) => {
    if (clientSocket.readyState === WebSocket.OPEN) clientSocket.send(data.toString());
  });
  deepgramSocket.on("error", (error) => {
    sendJson(clientSocket, {
      type: "proxy_error",
      message: "Deepgram streaming connection failed",
      detail: error.message,
    });
  });
  deepgramSocket.on("close", (code, reason) => {
    clearInterval(keepAliveTimer);
    sendJson(clientSocket, { type: "stream_closed", code, reason: reason.toString() });
    if (clientSocket.readyState === WebSocket.OPEN) {
      clientSocket.close(1000, "Deepgram stream closed");
    }
  });

  clientSocket.on("message", (data, isBinary) => {
    if (deepgramSocket.readyState !== WebSocket.OPEN) return;
    if (isBinary) {
      deepgramSocket.send(data, { binary: true });
      return;
    }
    try {
      const message = JSON.parse(data.toString());
      if (message.type === "Finalize" || message.type === "CloseStream") {
        deepgramSocket.send(JSON.stringify({ type: message.type }));
      }
    } catch {
      sendJson(clientSocket, { type: "proxy_error", message: "Invalid client control message" });
    }
  });
  clientSocket.on("close", () => {
    clearInterval(keepAliveTimer);
    if (deepgramSocket.readyState === WebSocket.OPEN) {
      deepgramSocket.close(1000, "Client disconnected");
    } else if (deepgramSocket.readyState === WebSocket.CONNECTING) {
      deepgramSocket.terminate();
    }
  });
}

export async function createAppServer(options = {}) {
  const configuredApiKey = Object.hasOwn(options, "apiKey")
    ? options.apiKey
    : process.env.DEEPGRAM_API_KEY;
  const apiKey = typeof configuredApiKey === "string" ? configuredApiKey.trim() : "";
  const { url: configuredDeepgramUrl, keytermCount } = await buildDeepgramListenUrl();
  const { url: configuredDeepgramBatchUrl } = await buildDeepgramPrerecordedUrl();
  const deepgramUrl = options.deepgramUrl ?? configuredDeepgramUrl;
  const deepgramBatchUrl = options.deepgramBatchUrl ?? configuredDeepgramBatchUrl;
  const deepgramFetch = options.deepgramFetch ?? globalThis.fetch;
  const configuredPostTranscriptUrl = Object.hasOwn(options, "postTranscriptUrl")
    ? options.postTranscriptUrl
    : process.env.POST_TRANSCRIPT_URL;
  const postTranscriptUrl = configuredPostTranscriptUrl
    ? new URL(configuredPostTranscriptUrl)
    : null;
  const configuredIngestApiKey = Object.hasOwn(options, "ingestApiKey")
    ? options.ingestApiKey
    : process.env.TRANSCRIPT_INGEST_API_KEY;
  const ingestApiKey = typeof configuredIngestApiKey === "string"
    ? configuredIngestApiKey.trim()
    : "";
  const postTranscriptFetch = options.postTranscriptFetch ?? globalThis.fetch;
  const configured = Boolean(apiKey);
  const postTranscriptConfigured = Boolean(postTranscriptUrl && ingestApiKey);
  const server = createServer((request, response) => {
    serveRequest(request, response, {
      apiKey,
      configured,
      deepgramBatchUrl,
      deepgramFetch,
      ingestApiKey,
      keytermCount,
      postTranscriptConfigured,
      postTranscriptFetch,
      postTranscriptUrl,
    }).catch((error) => {
      jsonResponse(response, error.statusCode ?? 500, { error: error.message });
    });
  });
  const socketServer = new WebSocketServer({ noServer: true, maxPayload: 2_000_000 });

  server.on("upgrade", (request, socket, head) => {
    const requestUrl = new URL(request.url, "http://localhost");
    if (requestUrl.pathname !== "/api/live-transcription") {
      socket.destroy();
      return;
    }
    if (!isAllowedWebSocketOrigin(request)) {
      socket.destroy();
      return;
    }
    socketServer.handleUpgrade(request, socket, head, (clientSocket) => {
      if (!apiKey) {
        sendJson(clientSocket, {
          type: "configuration_error",
          message: "DEEPGRAM_API_KEY is not configured on the server",
        });
        clientSocket.close(1011, "Deepgram is not configured");
        return;
      }
      bridgeDeepgram(clientSocket, deepgramUrl, apiKey);
    });
  });
  return {
    server,
    keytermCount,
    deepgramUrl,
    deepgramBatchUrl,
    postTranscriptConfigured,
  };
}

async function start() {
  const port = Number.parseInt(process.env.PORT ?? "3000", 10);
  const host = process.env.HOST?.trim() || "0.0.0.0";
  if (!Number.isInteger(port) || port < 0 || port > 65535) {
    throw new Error("PORT must be an integer between 0 and 65535");
  }
  const { server, keytermCount } = await createAppServer();
  server.listen(port, host, () => {
    const address = server.address();
    console.log(`Diarization app listening on ${host}:${address.port}`);
    console.log(`Deepgram keyterms: ${keytermCount}`);
    if (!process.env.DEEPGRAM_API_KEY) {
      console.warn("DEEPGRAM_API_KEY is missing; live transcription will not start.");
    }
  });
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  start().catch((error) => {
    console.error(error.message);
    process.exitCode = 1;
  });
}
