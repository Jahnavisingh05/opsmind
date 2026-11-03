-- OpsMind core schema

CREATE TABLE IF NOT EXISTS logs (
    id SERIAL PRIMARY KEY,
    ts TIMESTAMPTZ NOT NULL DEFAULT now(),
    service TEXT NOT NULL,
    severity TEXT NOT NULL,          -- INFO | WARN | ERROR
    error_type TEXT,
    message TEXT,
    request_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_logs_ts ON logs (ts);
CREATE INDEX IF NOT EXISTS idx_logs_service ON logs (service);
CREATE INDEX IF NOT EXISTS idx_logs_severity ON logs (severity);

CREATE TABLE IF NOT EXISTS metrics (
    id SERIAL PRIMARY KEY,
    ts TIMESTAMPTZ NOT NULL DEFAULT now(),
    service TEXT NOT NULL,
    cpu_pct REAL,
    latency_ms REAL,
    error_rate REAL,          -- 0..1
    memory_mb REAL,
    conn_pool_pct REAL
);
CREATE INDEX IF NOT EXISTS idx_metrics_ts ON metrics (ts);
CREATE INDEX IF NOT EXISTS idx_metrics_service ON metrics (service);

CREATE TABLE IF NOT EXISTS deployments (
    id SERIAL PRIMARY KEY,
    ts TIMESTAMPTZ NOT NULL DEFAULT now(),
    service TEXT NOT NULL,
    version TEXT NOT NULL,
    description TEXT
);

CREATE TABLE IF NOT EXISTS anomalies (
    id SERIAL PRIMARY KEY,
    ts TIMESTAMPTZ NOT NULL DEFAULT now(),
    service TEXT NOT NULL,
    metric_name TEXT NOT NULL,
    value REAL,
    score REAL,                -- isolation forest anomaly score (higher = more anomalous)
    consumed BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS incidents (
    id SERIAL PRIMARY KEY,
    started_at TIMESTAMPTZ NOT NULL,
    detected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    status TEXT NOT NULL DEFAULT 'OPEN',   -- OPEN | RESOLVED
    severity TEXT NOT NULL DEFAULT 'CRITICAL',
    primary_service TEXT,
    root_cause_service TEXT,
    root_cause_label TEXT,
    confidence REAL,
    ai_summary TEXT,
    ai_investigation_steps JSONB
);

CREATE TABLE IF NOT EXISTS incident_timeline (
    id SERIAL PRIMARY KEY,
    incident_id INTEGER REFERENCES incidents(id) ON DELETE CASCADE,
    ts TIMESTAMPTZ NOT NULL,
    label TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS incident_candidates (
    id SERIAL PRIMARY KEY,
    incident_id INTEGER REFERENCES incidents(id) ON DELETE CASCADE,
    candidate_cause TEXT NOT NULL,
    score REAL NOT NULL,
    evidence JSONB
);
