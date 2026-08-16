CREATE TABLE IF NOT EXISTS conversations (
    conversation_id TEXT PRIMARY KEY,
    caller_speaker_id TEXT,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    financial_context_json JSONB,
    speaker_identity_json JSONB,
    assessment_json JSONB
);

CREATE TABLE IF NOT EXISTS transcript_turns (
    conversation_id TEXT NOT NULL REFERENCES conversations(conversation_id)
        ON DELETE CASCADE,
    segment_id TEXT NOT NULL,
    speaker_id TEXT NOT NULL,
    role TEXT NOT NULL,
    text TEXT NOT NULL,
    start_ms BIGINT NOT NULL,
    end_ms BIGINT NOT NULL,
    PRIMARY KEY (conversation_id, segment_id)
);

CREATE INDEX IF NOT EXISTS idx_transcript_turns_time
    ON transcript_turns (conversation_id, start_ms, end_ms);

CREATE TABLE IF NOT EXISTS speaker_encounters (
    conversation_id TEXT PRIMARY KEY,
    speaker_profile_id TEXT NOT NULL,
    risk_score INTEGER NOT NULL,
    risk_level TEXT NOT NULL,
    claimed_institutions_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    signal_kinds_json JSONB NOT NULL DEFAULT '[]'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_speaker_encounters_profile
    ON speaker_encounters (speaker_profile_id);

ALTER TABLE conversations ENABLE ROW LEVEL SECURITY;
ALTER TABLE transcript_turns ENABLE ROW LEVEL SECURITY;
ALTER TABLE speaker_encounters ENABLE ROW LEVEL SECURITY;
