-- Action runtime state that must survive restarts: toggle on/off, counter values, timers.
-- Keyed by a namespaced string such as "toggle:<button id>" or "counter:<name>".
-- Existing configuration tables are unchanged.

CREATE TABLE runtime_state (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
