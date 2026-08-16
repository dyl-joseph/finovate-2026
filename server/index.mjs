import { createReadStream } from "node:fs";
import { stat } from "node:fs/promises";
import { createServer } from "node:http";
import { extname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

import WebSocket, { WebSocketServer } from "ws";

import { buildDeepgramListenUrl } from "./deepgram-url.mjs";

const ROOT = resolve(fileURLToPath(new URL("..", import.meta.url)));
const PUBLIC_FILES = new Map([
  ["/", "public/index.html"],
  ["/app.js", "public/app.js"],
  ["/styles.css", "public/styles.css"],
  ["/src/transcript-assembler.mjs", "src/transcript-assembler.mjs"],
]);
const CONTENT_TYPES = new Map([
  [".html", "text/html; charset=utf-8"],
  [".js", "text/javascript; charset=utf-8"],
  [".mjs", "text/javascript; charset=utf-8"],
  [".css", "text/css; charset=utf-8"],
]);

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

async function serveRequest(request, response, keytermCount, configured) {
  setSecurityHeaders(response);
  const requestUrl = new URL(request.url, "http://localhost");
  if (request.method === "GET" && requestUrl.pathname === "/api/health") {
    jsonResponse(response, 200, {
      ok: true,
      deepgram_configured: configured,
      keyterm_count: keytermCount,
    });
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
      if (message.type === "CloseStream") {
        deepgramSocket.send(JSON.stringify({ type: "CloseStream" }));
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
  const deepgramUrl = options.deepgramUrl ?? configuredDeepgramUrl;
  const configured = Boolean(apiKey);
  const server = createServer((request, response) => {
    serveRequest(request, response, keytermCount, configured).catch((error) => {
      jsonResponse(response, 500, { error: error.message });
    });
  });
  const socketServer = new WebSocketServer({ noServer: true, maxPayload: 2_000_000 });

  server.on("upgrade", (request, socket, head) => {
    const requestUrl = new URL(request.url, "http://localhost");
    if (requestUrl.pathname !== "/api/live-transcription") {
      socket.destroy();
      return;
    }
    const origin = request.headers.origin;
    if (origin) {
      const originHostname = new URL(origin).hostname;
      if (!new Set(["127.0.0.1", "localhost", "::1"]).has(originHostname)) {
        socket.destroy();
        return;
      }
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
  return { server, keytermCount, deepgramUrl };
}

async function start() {
  const port = Number.parseInt(process.env.PORT ?? "3000", 10);
  if (!Number.isInteger(port) || port < 0 || port > 65535) {
    throw new Error("PORT must be an integer between 0 and 65535");
  }
  const { server, keytermCount } = await createAppServer();
  server.listen(port, "127.0.0.1", () => {
    const address = server.address();
    console.log(`Diarization app: http://127.0.0.1:${address.port}`);
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
