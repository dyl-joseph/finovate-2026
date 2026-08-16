import { TranscriptAssembler } from "/src/transcript-assembler.mjs";

const elements = Object.fromEntries([
  "conversation-id", "copy", "download", "error", "interim", "output",
  "output-help", "speakers", "start", "status", "stop", "turns",
].map((id) => [id.replace(/-([a-z])/g, (_, letter) => letter.toUpperCase()), document.querySelector(`#${id}`)]));

let assembler;
let mediaRecorder;
let mediaStream;
let socket;
let finalTranscript;

function setStatus(label, state = "idle") {
  elements.status.textContent = label;
  elements.status.dataset.state = state;
}

function showError(message) {
  elements.error.textContent = message;
  elements.error.hidden = false;
  setStatus("Error", "error");
}

function clearError() {
  elements.error.textContent = "";
  elements.error.hidden = true;
}

function preferredMimeType() {
  return ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus"]
    .find((type) => MediaRecorder.isTypeSupported(type));
}

function appendTurnEvent(event) {
  const item = document.createElement("li");
  item.className = "turn";
  const metadata = document.createElement("span");
  metadata.className = "turn-meta";
  metadata.textContent = `${event.turn.speaker_id} · ${event.turn.role} · ${event.turn.start_ms}–${event.turn.end_ms} ms`;
  const text = document.createElement("span");
  text.textContent = event.turn.text;
  item.append(metadata, text);
  elements.turns.append(item);
}

function renderSpeakers() {
  const speakerIds = assembler?.getSpeakerIds() ?? [];
  elements.speakers.replaceChildren();
  if (speakerIds.length === 0) {
    const empty = document.createElement("p");
    empty.textContent = "No finalized speakers yet.";
    elements.speakers.append(empty);
    return;
  }
  for (const speakerId of speakerIds) {
    const row = document.createElement("div");
    row.className = "speaker-row";
    const label = document.createElement("span");
    label.className = "speaker-id";
    label.textContent = speakerId;
    const select = document.createElement("select");
    select.setAttribute("aria-label", `Role for ${speakerId}`);
    for (const role of ["unknown", "caller", "customer"]) {
      const option = document.createElement("option");
      option.value = role;
      option.textContent = role;
      option.selected = assembler.getSpeakerRole(speakerId) === role;
      select.append(option);
    }
    select.addEventListener("change", () => {
      assembler.setSpeakerRole(speakerId, select.value);
      renderSpeakers();
      renderFinalTranscript();
    });
    row.append(label, select);
    elements.speakers.append(row);
  }
}

function renderFinalTranscript() {
  finalTranscript = undefined;
  elements.copy.disabled = true;
  elements.download.disabled = true;
  try {
    finalTranscript = assembler.buildFinalTranscript();
    elements.output.textContent = JSON.stringify(finalTranscript, null, 2);
    elements.outputHelp.textContent = "Ready for the fraud pipeline.";
    elements.copy.disabled = false;
    elements.download.disabled = false;
  } catch (error) {
    elements.output.textContent = "Waiting for finalized transcript data.";
    elements.outputHelp.textContent = error.message;
  }
}

function cleanupMedia() {
  mediaStream?.getTracks().forEach((track) => track.stop());
  mediaStream = undefined;
  mediaRecorder = undefined;
  elements.start.disabled = false;
  elements.stop.disabled = true;
}

function startRecording() {
  const mimeType = preferredMimeType();
  if (!mimeType) throw new Error("This browser does not support WebM or Ogg Opus recording");
  mediaRecorder = new MediaRecorder(mediaStream, { mimeType });
  mediaRecorder.addEventListener("dataavailable", (event) => {
    if (event.data.size > 0 && socket?.readyState === WebSocket.OPEN) socket.send(event.data);
  });
  mediaRecorder.addEventListener("stop", () => {
    if (socket?.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ type: "CloseStream" }));
      setStatus("Finalizing");
    }
  });
  mediaRecorder.start(250);
  setStatus("Listening", "live");
  elements.stop.disabled = false;
}

async function startSession() {
  clearError();
  try {
    assembler = new TranscriptAssembler({ conversationId: elements.conversationId.value.trim() });
    elements.turns.replaceChildren();
    elements.interim.textContent = "Waiting for speech…";
    renderSpeakers();
    renderFinalTranscript();
    elements.start.disabled = true;
    setStatus("Checking server");
    const healthResponse = await fetch("/api/health", { cache: "no-store" });
    const health = await healthResponse.json();
    if (!healthResponse.ok || !health.deepgram_configured) {
      throw new Error("Add DEEPGRAM_API_KEY to .env and restart the server");
    }
    setStatus("Requesting microphone");
    mediaStream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
    const protocol = location.protocol === "https:" ? "wss:" : "ws:";
    socket = new WebSocket(`${protocol}//${location.host}/api/live-transcription`);
    socket.addEventListener("message", (event) => {
      const message = JSON.parse(event.data);
      if (message.type === "ready") {
        startRecording();
      } else if (message.type === "Results") {
        const transcript = message.channel?.alternatives?.[0]?.transcript ?? "";
        if (message.is_final === true) {
          for (const turnEvent of assembler.ingestDeepgramResult(message)) {
            appendTurnEvent(turnEvent);
            window.dispatchEvent(new CustomEvent("transcript-turn", { detail: turnEvent }));
          }
          elements.interim.textContent = "";
          renderSpeakers();
          renderFinalTranscript();
        } else if (transcript) {
          elements.interim.textContent = transcript;
        }
      } else if (message.type === "configuration_error" || message.type === "proxy_error") {
        showError(message.message);
      } else if (message.type === "stream_closed") {
        setStatus("Finalized");
      }
    });
    socket.addEventListener("error", () => {
      showError("The transcription WebSocket failed");
      cleanupMedia();
    });
    socket.addEventListener("close", () => {
      if (elements.status.dataset.state !== "error") setStatus("Finalized");
      cleanupMedia();
    });
  } catch (error) {
    showError(error.message);
    cleanupMedia();
  }
}

function stopSession() {
  elements.stop.disabled = true;
  if (mediaRecorder?.state === "recording") mediaRecorder.stop();
  mediaStream?.getTracks().forEach((track) => track.stop());
}

elements.start.addEventListener("click", startSession);
elements.stop.addEventListener("click", stopSession);
elements.copy.addEventListener("click", async () => {
  if (!finalTranscript) return;
  await navigator.clipboard.writeText(JSON.stringify(finalTranscript, null, 2));
  elements.outputHelp.textContent = "Copied final transcript JSON.";
});
elements.download.addEventListener("click", () => {
  if (!finalTranscript) return;
  const blob = new Blob([JSON.stringify(finalTranscript, null, 2)], { type: "application/json" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = `${finalTranscript.conversation_id}.json`;
  link.click();
  URL.revokeObjectURL(link.href);
});
