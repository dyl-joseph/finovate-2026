"""Local voice embeddings for cross-call repeat offender detection.

The pipeline itself never compares voices; it relies on an upstream
speaker-profile match (see memory.SpeakerIdentity). This module provides a
local, offline matcher built on Resemblyzer's speaker encoder so a stable
``voice-profile-*`` identity can be produced from raw call audio.

The model is loaded lazily on first use and any failure degrades gracefully:
if Resemblyzer/torch cannot be imported or an audio buffer cannot be decoded,
``VoiceEmbedder.embed`` returns ``None`` and callers skip voice matching
instead of crashing the pipeline.
"""

from __future__ import annotations

import math
import shutil
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Protocol

try:
    import numpy as np
    import librosa

    _AUDIO_LIBS_AVAILABLE = True
except ImportError:  # pragma: no cover - depends on optional deps
    np = None
    librosa = None
    _AUDIO_LIBS_AVAILABLE = False

_VOICE_ENCODER = None
_RESEMBLYZER_IMPORT_ERROR: Exception | None = None

SAMPLE_RATE = 16_000
VOICE_PROFILE_ID_PATTERN = "voice-profile-{:08x}"

DEFAULT_MATCH_THRESHOLD = 0.80
NEW_PROFILE_CONFIDENCE = 0.90
CONFIDENCE_FLOOR = 0.80  # same-person confidence reported exactly at the match threshold
_SAME_PERSON_STEEPNESS = 35.0
_SAME_PERSON_CENTER_OFFSET = math.log(4.0) / _SAME_PERSON_STEEPNESS


@dataclass(frozen=True, slots=True)
class SpeakerProfile:
    """A stable speaker identity backed by a rolling-average 256-vec embedding."""

    profile_id: str
    embedding: tuple[float, ...]
    sample_count: int
    last_seen_at: str


class SpeakerProfileRepository(Protocol):
    def list_profiles(self) -> tuple[SpeakerProfile, ...]: ...

    def upsert(self, profile: SpeakerProfile) -> None: ...


def _cosine_similarity(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if not left_norm or not right_norm:
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    return dot / (left_norm * right_norm)


def similarity_to_confidence(similarity: float, threshold: float) -> float:
    """Map a cosine similarity to *probability the caller is the same person*.

    Uses a logistic calibrated so that a score at the match threshold reports
    ``CONFIDENCE_FLOOR`` (0.80) — the same gate the pipeline uses before it
    will consult prior encounters — and a perfect score approaches certainty.
    Similar gating to Resemblyzer's own speaker-verification threshold (≈0.78).
    """
    probability = 1.0 / (
        1.0
        + math.exp(
            -_SAME_PERSON_STEEPNESS
            * (similarity - threshold + _SAME_PERSON_CENTER_OFFSET)
        )
    )
    return round(max(0.0, min(1.0, probability)), 3)


@dataclass(frozen=True, slots=True)
class VoiceMatch:
    """Result of matching a caller's voice against known profiles.

    ``confidence`` is the probability (0..1) that the caller is the same person
    as ``profile_id``. For a brand-new profile it reflects enrollment certainty
    (we trust the freshly captured voice); for a repeat it reflects the
    similarity of this voice to the averaged prior captures.
    """

    profile_id: str
    confidence: float
    is_new: bool
    similarity: float


def _load_encoder():
    """Import Resemblyzer lazily (torch is expensive to import)."""
    global _VOICE_ENCODER, _RESEMBLYZER_IMPORT_ERROR
    if _VOICE_ENCODER is not None:
        return _VOICE_ENCODER
    if _RESEMBLYZER_IMPORT_ERROR is not None:
        raise _RESEMBLYZER_IMPORT_ERROR
    if not _AUDIO_LIBS_AVAILABLE:
        _RESEMBLYZER_IMPORT_ERROR = ImportError(
            "numpy/librosa are required for voice embeddings"
        )
        raise _RESEMBLYZER_IMPORT_ERROR
    try:
        from resemblyzer import VoiceEncoder

        _VOICE_ENCODER = VoiceEncoder()
        return _VOICE_ENCODER
    except Exception as exc:  # pragma: no cover - environment dependent
        _RESEMBLYZER_IMPORT_ERROR = exc
        raise


def _load_wav_16k_mono(data: bytes) -> np.ndarray:
    """Decode arbitrary audio bytes to a 16kHz mono float32 array in [-1, 1]."""
    if not _AUDIO_LIBS_AVAILABLE:
        raise ImportError("numpy/librosa are required for voice embeddings")
    try:
        samples, rate = librosa.load(BytesIO(data), sr=SAMPLE_RATE, mono=True)
        return samples
    except Exception:
        if not shutil.which("ffmpeg"):
            raise
        with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as raw_file:
            raw_file.write(data)
            raw_path = Path(raw_file.name)
        try:
            with tempfile.NamedTemporaryFile(
                suffix=".wav", delete=False
            ) as wav_file:
                wav_path = Path(wav_file.name)
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-loglevel",
                    "error",
                    "-i",
                    str(raw_path),
                    "-ac",
                    "1",
                    "-ar",
                    str(SAMPLE_RATE),
                    str(wav_path),
                ],
                check=True,
                capture_output=True,
            )
            samples, _rate = librosa.load(wav_path, sr=SAMPLE_RATE, mono=True)
            return samples
        finally:
            raw_path.unlink(missing_ok=True)
            wav_path.unlink(missing_ok=True)


class VoiceEmbedder:
    """Compute a 256-dim speaker embedding from raw audio via Resemblyzer."""

    def embed(
        self,
        audio_bytes: bytes,
        start_ms: int | None = None,
        end_ms: int | None = None,
    ) -> list[float] | None:
        if not audio_bytes:
            return None
        try:
            encoder = _load_encoder()
            samples = _load_wav_16k_mono(audio_bytes)
            if samples.size == 0:
                return None
            if start_ms is not None or end_ms is not None:
                start_sample = int((start_ms or 0) / 1000 * SAMPLE_RATE)
                end_sample = int(
                    ((end_ms if end_ms is not None else len(samples) / SAMPLE_RATE * 1000))
                    / 1000 * SAMPLE_RATE
                )
                window = samples[start_sample:end_sample]
                if window.size > 0:
                    samples = window
            embedding = encoder.embed_utterance(samples)
            return [float(value) for value in embedding]
        except Exception:  # pragma: no cover - environment dependent
            return None


class VoiceMatcher:
    """Match an embedding against known profiles; create one when unmatched."""

    def __init__(
        self,
        repository: SpeakerProfileRepository,
        threshold: float = DEFAULT_MATCH_THRESHOLD,
        embedder: VoiceEmbedder | None = None,
    ) -> None:
        self.repository = repository
        self.threshold = threshold
        self.embedder = embedder or VoiceEmbedder()

    def identify(
        self,
        embedding: list[float] | tuple[float, ...],
    ) -> VoiceMatch:
        """Return a :class:`VoiceMatch` for the caller's voice.

        A similarity above ``threshold`` reuses the existing profile and folds
        the new embedding into a rolling average. Otherwise a fresh profile is
        created with a high enrollment confidence so the caller is remembered
        from the very first call.
        """
        vector = tuple(embedding)
        best: SpeakerProfile | None = None
        best_score = -1.0
        for candidate in self.repository.list_profiles():
            score = _cosine_similarity(vector, candidate.embedding)
            if score > best_score:
                best = candidate
                best_score = score

        now = datetime.now(timezone.utc).isoformat()
        if best is not None and best_score >= self.threshold:
            averaged = tuple(
                (new + old * best.sample_count) / (best.sample_count + 1)
                for new, old in zip(vector, best.embedding)
            )
            updated = SpeakerProfile(
                profile_id=best.profile_id,
                embedding=averaged,
                sample_count=best.sample_count + 1,
                last_seen_at=now,
            )
            self.repository.upsert(updated)
            return VoiceMatch(
                profile_id=best.profile_id,
                confidence=similarity_to_confidence(best_score, self.threshold),
                is_new=False,
                similarity=best_score,
            )

        profile_id = VOICE_PROFILE_ID_PATTERN.format(uuid.uuid4().int & 0xFFFFFFFF)
        self.repository.upsert(
            SpeakerProfile(
                profile_id=profile_id,
                embedding=vector,
                sample_count=1,
                last_seen_at=now,
            )
        )
        return VoiceMatch(
            profile_id=profile_id,
            confidence=NEW_PROFILE_CONFIDENCE,
            is_new=True,
            similarity=1.0,
        )


class SQLiteSpeakerProfileRepository:
    """SQLite-backed profile store matching the Supabase table schema."""

    def __init__(self, database: str | Path = ":memory:") -> None:
        import sqlite3
        from threading import RLock

        self._connection = sqlite3.connect(str(database), check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._lock = RLock()
        self._create_schema()

    def _create_schema(self) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS speaker_profiles (
                    profile_id TEXT PRIMARY KEY,
                    embedding_json TEXT NOT NULL,
                    sample_count INTEGER NOT NULL,
                    last_seen_at TEXT NOT NULL
                )
                """
            )

    def list_profiles(self) -> tuple[SpeakerProfile, ...]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT profile_id, embedding_json, sample_count, last_seen_at "
                "FROM speaker_profiles ORDER BY profile_id"
            ).fetchall()
        return tuple(self._row_to_profile(row) for row in rows)

    def upsert(self, profile: SpeakerProfile) -> None:
        import json

        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO speaker_profiles (
                    profile_id, embedding_json, sample_count, last_seen_at
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(profile_id) DO UPDATE SET
                    embedding_json = excluded.embedding_json,
                    sample_count = excluded.sample_count,
                    last_seen_at = excluded.last_seen_at
                """,
                (
                    profile.profile_id,
                    json.dumps(list(profile.embedding)),
                    profile.sample_count,
                    profile.last_seen_at,
                ),
            )

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def __enter__(self) -> SQLiteSpeakerProfileRepository:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    @staticmethod
    def _row_to_profile(row) -> SpeakerProfile:
        import json

        return SpeakerProfile(
            profile_id=row["profile_id"],
            embedding=tuple(json.loads(row["embedding_json"])),
            sample_count=row["sample_count"],
            last_seen_at=row["last_seen_at"],
        )