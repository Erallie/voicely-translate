CREATE TABLE IF NOT EXISTS registrations (
    topup_code TEXT PRIMARY KEY,
    guild_id TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_registrations_guild_id
ON registrations(guild_id);

CREATE TABLE IF NOT EXISTS topups (
    message_id TEXT PRIMARY KEY,
    guild_id TEXT,
    topup_code TEXT,
    amount_microusd INTEGER NOT NULL,
    currency TEXT NOT NULL,
    claimed INTEGER NOT NULL DEFAULT 0,
    received_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_topups_pending
ON topups(guild_id, claimed, received_at);

CREATE INDEX IF NOT EXISTS idx_topups_code
ON topups(topup_code);
