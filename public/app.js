import { TranscriptAssembler } from "/src/transcript-assembler.mjs";

const elements = Object.fromEntries([
  "actions-panel", "active-view", "error", "ready-view", "recommendations",
  "restart", "result", "result-icon", "result-message", "result-title", "risk-label",
  "start", "state-detail", "state-symbol", "state-title", "stop", "timer",
  "warning-panel", "warning-signs",
].map((id) => [id.replace(/-([a-z])/g, (_, letter) => letter.toUpperCase()), document.querySelector(`#${id}`)]));

let assembler;
let mediaRecorder;
let mediaStream;
let socket;
let recordedChunks = [];
let recordedMimeType;
let isFinalizing = false;
let timerId;
let recordingStartedAt;

const RISK_CONTENT = {
  critical: {
    label: "Very high risk",
    title: "This call may be dangerous",
    message: "End contact with the caller. Do not send money or share any personal information.",
    icon: "!",
  },
  high: {
    label: "High risk",
    title: "This call has serious warning signs",
    message: "Do not trust the caller's instructions. Hang up and contact the organization yourself.",
    icon: "!",
  },
  guarded: {
    label: "Use caution",
    title: "This call has some warning signs",
    message: "Pause before taking action. Verify the caller using a phone number you already trust.",
    icon: "?",
  },
  low: {
    label: "No strong warning signs",
    title: "We did not hear clear signs of a scam",
    message: "Still be careful. CallCheck can miss things, and unexpected callers should always be verified.",
    icon: "✓",
  },
};

const SIGNAL_LABELS = {
  authority: "The caller used official-sounding authority",
  claimed_identity: "The caller claimed to represent an organization",
  claimed_transaction: "The caller mentioned an unexpected transaction",
  requested_credentials: "The caller asked for a password or security code",
  requested_transfer: "The caller asked you to move or send money",
  urgency: "The caller pressured you to act quickly",
  secrecy: "The caller asked you to keep the call secret",
  isolation: "The caller tried to keep you on the line",
  threat: "The caller used threats or frightening consequences",
};

function conversationId() {
  return `call-${crypto.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(16).slice(2)}`}`;
}

function showReady() {
  clearInterval(timerId);
  elements.readyView.hidden = false;
  elements.activeView.hidden = true;
  elements.result.hidden = true;
  elements.error.hidden = true;
  elements.start.disabled = false;
  document.body.dataset.phase = "ready";
  elements.start.focus();
}

function showActive(title, detail, state = "listening") {
  elements.readyView.hidden = true;
  elements.activeView.hidden = false;
  elements.result.hidden = true;
  elements.stateTitle.textContent = title;
  elements.stateDetail.textContent = detail;
  elements.stateSymbol.className = `state-symbol ${state}`;
  document.body.dataset.phase = state;
}

function showError(message) {
  elements.error.textContent = message;
  elements.error.hidden = false;
  elements.readyView.hidden = false;
  elements.activeView.hidden = true;
  elements.start.disabled = false;
  document.body.dataset.phase = "error";
}

function clearError() {
  elements.error.textContent = "";
  elements.error.hidden = true;
}

function friendlyError(error) {
  if (error?.name === "NotAllowedError") {
    return "Microphone access is needed to check the call. Choose Allow and try again.";
  }
  if (error?.name === "NotFoundError") {
    return "We could not find a microphone on this device.";
  }
  if (error?.message === "No call audio was recorded") {
    return "We did not hear any audio. Move the phone closer and try again.";
  }
  return "We could not complete the call check. Please try again.";
}

function preferredMimeType() {
  return ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus"]
    .find((type) => MediaRecorder.isTypeSupported(type));
}

function updateTimer() {
  const elapsedSeconds = Math.floor((Date.now() - recordingStartedAt) / 1000);
  const minutes = String(Math.floor(elapsedSeconds / 60)).padStart(2, "0");
  const seconds = String(elapsedSeconds % 60).padStart(2, "0");
  elements.timer.textContent = `${minutes}:${seconds}`;
}

function renderAssessment(assessment) {
  const risk = assessment.risk ?? { level: "low" };
  const content = RISK_CONTENT[risk.level] ?? RISK_CONTENT.guarded;
  elements.result.dataset.risk = risk.level;
  elements.riskLabel.textContent = content.label;
  elements.resultTitle.textContent = content.title;
  elements.resultMessage.textContent = content.message;
  elements.resultIcon.textContent = content.icon;

  const recommendations = assessment.recommendations ?? [];
  elements.recommendations.replaceChildren();
  const fallbackActions = risk.level === "low"
    ? ["If the caller asks for money or a security code, hang up.", "Contact organizations using a phone number you already trust."]
    : ["End the call without sharing information.", "Call the organization using the number on your card or official website."];
  for (const action of recommendations.map((item) => item.action).concat(recommendations.length ? [] : fallbackActions)) {
    const item = document.createElement("li");
    item.textContent = action;
    elements.recommendations.append(item);
  }

  const signals = assessment.transcript_analysis?.signals ?? [];
  const warningLabels = [...new Set(signals.map((signal) => SIGNAL_LABELS[signal.kind]).filter(Boolean))];
  elements.warningSigns.replaceChildren();
  for (const label of warningLabels) {
    const item = document.createElement("li");
    item.textContent = label;
    elements.warningSigns.append(item);
  }
  elements.warningPanel.hidden = warningLabels.length === 0;
  elements.result.hidden = false;
  elements.activeView.hidden = true;
  document.body.dataset.phase = "result";
  elements.result.focus?.();
  elements.result.scrollIntoView({ behavior: "smooth", block: "start" });
}

async function analyzeTranscript(finalTranscript) {
  showActive("Checking for scam warning signs…", "This usually takes only a few seconds.", "processing");
  const response = await fetch("/api/analyze-transcript", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(finalTranscript),
    });
  const body = await response.json();
  if (!response.ok) throw new Error(body.detail ?? body.error ?? "We could not check this call. Please try again.");
  renderAssessment(body.assessment ?? body);
}

function cleanupMedia() {
  mediaStream?.getTracks().forEach((track) => track.stop());
  mediaStream = undefined;
  mediaRecorder = undefined;
  elements.stop.disabled = true;
}

async function finalizeRecordedCall() {
  isFinalizing = true;
  clearInterval(timerId);
  cleanupMedia();
  showActive("Preparing your safety check…", "We are separating the voices and reviewing the call.", "processing");
  elements.timer.textContent = "";
  elements.stop.hidden = true;
  try {
    const recording = new Blob(recordedChunks, { type: recordedMimeType });
    if (recording.size === 0) throw new Error("No call audio was recorded");
    const response = await fetch("/api/transcribe-call", {
      method: "POST",
      headers: { "Content-Type": recordedMimeType },
      body: recording,
    });
    const body = await response.json();
    if (!response.ok) throw new Error("The recorded call could not be processed");

    const activeConversationId = assembler.conversationId;
    assembler = new TranscriptAssembler({ conversationId: activeConversationId });
    assembler.ingestDeepgramPrerecorded(body);
    assembler.assignSpeakerRolesAutomatically();
    const finalTranscript = assembler.buildFinalTranscript();
    await analyzeTranscript(finalTranscript);
  } catch (error) {
    showError(friendlyError(error));
  } finally {
    isFinalizing = false;
    elements.stop.hidden = false;
    cleanupMedia();
  }
}

function startRecording() {
  const mimeType = preferredMimeType();
  if (!mimeType) throw new Error("This browser does not support WebM or Ogg Opus recording");
  mediaRecorder = new MediaRecorder(mediaStream, { mimeType });
  recordedChunks = [];
  recordedMimeType = mimeType;
  mediaRecorder.addEventListener("dataavailable", (event) => {
    if (event.data.size === 0) return;
    recordedChunks.push(event.data);
    if (socket?.readyState === WebSocket.OPEN) socket.send(event.data);
  });
  mediaRecorder.addEventListener("stop", () => {
    if (socket?.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ type: "CloseStream" }));
    }
    void finalizeRecordedCall();
  });
  mediaRecorder.start(250);
  recordingStartedAt = Date.now();
  updateTimer();
  timerId = setInterval(updateTimer, 1000);
  showActive("Listening to the call…", "Keep the phone on speaker and near this device.", "listening");
  elements.stop.disabled = false;
}

async function startSession() {
  clearError();
  try {
    assembler = new TranscriptAssembler({ conversationId: conversationId() });
    elements.start.disabled = true;
    showActive("Getting ready…", "Checking that CallCheck is available.", "processing");
    elements.stop.disabled = true;
    const healthResponse = await fetch("/api/health", { cache: "no-store" });
    const health = await healthResponse.json();
    if (!healthResponse.ok || !health.deepgram_configured) {
      throw new Error("CallCheck is unavailable");
    }
    elements.stateTitle.textContent = "Allow microphone access";
    elements.stateDetail.textContent = "Choose Allow when your browser asks for permission.";
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
        // Live results keep the Deepgram stream active. The complete recording is
        // analyzed after the user ends the call so speaker separation is consistent.
      } else if (message.type === "configuration_error" || message.type === "proxy_error") {
        showError(message.message);
      } else if (message.type === "stream_closed") {
        if (!isFinalizing) showError("The listening connection closed. Please try again.");
      }
    });
    socket.addEventListener("error", () => {
      showError("The transcription WebSocket failed");
      cleanupMedia();
    });
    socket.addEventListener("close", () => {
      if (!isFinalizing && document.body.dataset.phase !== "error") showError("The listening connection closed. Please try again.");
      cleanupMedia();
    });
  } catch (error) {
    showError(friendlyError(error));
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
elements.restart.addEventListener("click", showReady);
