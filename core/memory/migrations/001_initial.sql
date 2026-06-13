-- migrations/001_initial.sql
CREATE TABLE IF NOT EXISTS memory_entries (
    id          TEXT PRIMARY KEY,
    memory_type TEXT NOT NULL,
    key         TEXT NOT NULL,
    value       TEXT NOT NULL,
    tags        TEXT DEFAULT '[]',
    created_at  TEXT NOT NULL,
    accessed_at TEXT,
    access_count INTEGER DEFAULT 0,
    UNIQUE(memory_type, key)
);

CREATE TABLE IF NOT EXISTS command_history (
    id           TEXT PRIMARY KEY,
    raw_input    TEXT NOT NULL,
    intent       TEXT,
    plan_id      TEXT,
    status       TEXT NOT NULL,
    executed_at  TEXT NOT NULL,
    duration_ms  INTEGER
);

CREATE TABLE IF NOT EXISTS execution_logs (
    id          TEXT PRIMARY KEY,
    plan_id     TEXT NOT NULL,
    step_number INTEGER NOT NULL,
    tool_name   TEXT NOT NULL,
    tool_args   TEXT NOT NULL,
    result      TEXT,
    status      TEXT NOT NULL,
    started_at  TEXT NOT NULL,
    ended_at    TEXT
);

CREATE INDEX IF NOT EXISTS idx_memory_type_key ON memory_entries(memory_type, key);
CREATE INDEX IF NOT EXISTS idx_command_history_executed ON command_history(executed_at DESC);
CREATE INDEX IF NOT EXISTS idx_logs_plan_id ON execution_logs(plan_id);
