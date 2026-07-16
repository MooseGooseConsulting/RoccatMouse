CREATE TABLE sessions (
    id TEXT PRIMARY KEY,
    trial TEXT NOT NULL,
    mode TEXT NOT NULL,
    tier TEXT NOT NULL CHECK (tier IN ('continuous', 'high_fidelity')),
    state TEXT NOT NULL,
    started_monotonic_ns INTEGER NOT NULL,
    started_utc TEXT NOT NULL,
    ended_monotonic_ns INTEGER,
    ended_utc TEXT,
    clean_shutdown INTEGER,
    retained INTEGER NOT NULL DEFAULT 0,
    fingerprint_json TEXT,
    notes TEXT
);

CREATE TABLE events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    monotonic_ns INTEGER NOT NULL,
    utc TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    source TEXT NOT NULL,
    kind TEXT NOT NULL,
    phase TEXT NOT NULL,
    device_id TEXT,
    payload_json TEXT NOT NULL,
    UNIQUE(session_id, sequence)
);

CREATE TABLE aggregates (
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    bucket_start_ns INTEGER NOT NULL,
    bucket_start_utc TEXT NOT NULL,
    sample_count INTEGER NOT NULL,
    wheel_event_count INTEGER NOT NULL,
    wheel_delta_sum INTEGER NOT NULL,
    wheel_reversals INTEGER NOT NULL,
    movement_count INTEGER NOT NULL,
    movement_dx_sum INTEGER NOT NULL,
    movement_dy_sum INTEGER NOT NULL,
    button_event_count INTEGER NOT NULL,
    anomaly_count INTEGER NOT NULL,
    payload_json TEXT NOT NULL,
    PRIMARY KEY(session_id, bucket_start_ns)
);

CREATE TABLE anomalies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    monotonic_ns INTEGER NOT NULL,
    utc TEXT NOT NULL,
    kind TEXT NOT NULL,
    severity TEXT NOT NULL,
    note TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    user_marked INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE exports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    exported_utc TEXT NOT NULL,
    format TEXT NOT NULL,
    path TEXT NOT NULL
);

CREATE INDEX events_session_time ON events(session_id, monotonic_ns);
CREATE INDEX anomalies_session_time ON anomalies(session_id, monotonic_ns);
CREATE INDEX sessions_retention ON sessions(tier, ended_utc, retained);
