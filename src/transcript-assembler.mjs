const SPEAKER_ID_PATTERN = /^SPEAKER_\d{2,}$/;
const ALLOWED_ROLES = new Set(["caller", "customer", "unknown"]);

function assertConversationId(conversationId) {
  if (typeof conversationId !== "string" || !conversationId.trim()) {
    throw new Error("conversation_id must be a non-empty string");
  }
}

function normalizeSpeakerId(speaker) {
  if (!Number.isInteger(speaker) || speaker < 0) {
    throw new Error("Deepgram speaker must be a non-negative integer");
  }
  return `SPEAKER_${String(speaker).padStart(2, "0")}`;
}

function secondsToMilliseconds(seconds, fieldName) {
  if (typeof seconds !== "number" || !Number.isFinite(seconds) || seconds < 0) {
    throw new Error(`${fieldName} must be a non-negative finite number`);
  }
  return Math.round(seconds * 1000);
}

function wordText(word) {
  const text = word.punctuated_word ?? word.word;
  if (typeof text !== "string" || !text.trim()) {
    throw new Error("Finalized words must include non-empty text");
  }
  return text.trim();
}

function joinWords(words) {
  return words
    .map((word) => word.text)
    .join(" ")
    .replace(/\s+([,.;!?%:)\]}])/g, "$1")
    .replace(/([([{])\s+/g, "$1")
    .trim();
}

function groupWordsIntoTurns(words, roleForSpeaker) {
  const turns = [];
  for (const word of words) {
    const current = turns.at(-1);
    if (!current || current.speaker_id !== word.speaker_id) {
      turns.push({
        speaker_id: word.speaker_id,
        role: roleForSpeaker(word.speaker_id),
        words: [word],
        start_ms: word.start_ms,
        end_ms: word.end_ms,
      });
      continue;
    }
    current.words.push(word);
    current.end_ms = Math.max(current.end_ms, word.end_ms);
  }
  return turns.map(({ words: turnWords, ...turn }) => ({
    ...turn,
    text: joinWords(turnWords),
  }));
}

export class TranscriptAssembler {
  #conversationId;
  #finalizedWords = new Map();
  #speakerRoles = new Map();
  #callerSpeakerId = null;

  constructor({ conversationId }) {
    assertConversationId(conversationId);
    this.#conversationId = conversationId.trim();
  }

  get conversationId() { return this.#conversationId; }
  get callerSpeakerId() { return this.#callerSpeakerId; }

  getSpeakerIds() {
    return [...new Set(this.#sortedWords().map((word) => word.speaker_id))];
  }

  getSpeakerRole(speakerId) {
    return this.#speakerRoles.get(speakerId) ?? "unknown";
  }

  setSpeakerRole(speakerId, role) {
    if (!SPEAKER_ID_PATTERN.test(speakerId)) {
      throw new Error("speaker_id must use the SPEAKER_XX format");
    }
    if (!ALLOWED_ROLES.has(role)) {
      throw new Error("role must be caller, customer, or unknown");
    }
    if (role === "caller") {
      if (this.#callerSpeakerId && this.#callerSpeakerId !== speakerId) {
        this.#speakerRoles.set(this.#callerSpeakerId, "unknown");
      }
      this.#callerSpeakerId = speakerId;
    } else if (this.#callerSpeakerId === speakerId) {
      this.#callerSpeakerId = null;
    }
    this.#speakerRoles.set(speakerId, role);
  }

  ingestDeepgramResult(result) {
    if (result?.type !== "Results" || result.is_final !== true) return [];
    const words = result.channel?.alternatives?.[0]?.words ?? [];
    const newWords = [];
    for (const [sourceIndex, word] of words.entries()) {
      const startMs = secondsToMilliseconds(word.start, "word.start");
      const endMs = secondsToMilliseconds(word.end, "word.end");
      if (endMs < startMs) {
        throw new Error("Finalized word end time cannot precede its start time");
      }
      const normalized = {
        speaker_id: normalizeSpeakerId(word.speaker),
        text: wordText(word),
        start_ms: startMs,
        end_ms: endMs,
        source_index: sourceIndex,
      };
      const identity = [normalized.speaker_id, startMs, endMs, normalized.text].join(":");
      if (!this.#finalizedWords.has(identity)) {
        this.#finalizedWords.set(identity, normalized);
        newWords.push(normalized);
      }
    }
    newWords.sort((left, right) =>
      left.start_ms - right.start_ms || left.source_index - right.source_index,
    );
    return groupWordsIntoTurns(newWords, (speakerId) => this.getSpeakerRole(speakerId))
      .map((turn) => ({
        conversation_id: this.#conversationId,
        event: "transcript_turn",
        turn,
        is_final: true,
      }));
  }

  buildFinalTranscript() {
    const words = this.#sortedWords();
    if (words.length === 0) {
      throw new Error("Cannot finalize a transcript without finalized words");
    }
    if (!this.#callerSpeakerId) {
      throw new Error("Identify the caller before finalizing the transcript");
    }
    if (!words.some((word) => word.speaker_id === this.#callerSpeakerId)) {
      throw new Error("caller_speaker_id must belong to a transcribed speaker");
    }
    return {
      conversation_id: this.#conversationId,
      caller_speaker_id: this.#callerSpeakerId,
      turns: groupWordsIntoTurns(words, (speakerId) => this.getSpeakerRole(speakerId)),
      metadata: { source: "diarization-service", language: "en-US" },
    };
  }

  #sortedWords() {
    return [...this.#finalizedWords.values()].sort((left, right) =>
      left.start_ms - right.start_ms || left.source_index - right.source_index,
    );
  }
}
