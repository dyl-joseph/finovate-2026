CREATE TABLE IF NOT EXISTS speaker_profiles (
    profile_id TEXT PRIMARY KEY,
    embedding_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    sample_count INTEGER NOT NULL DEFAULT 1,
    last_seen_at TEXT
);

ALTER TABLE speaker_profiles ENABLE ROW LEVEL SECURITY;
