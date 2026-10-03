-- Initial schema. Never edit after release; add a new numbered file instead.

CREATE TABLE settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE profiles (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    sort_order  INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL
);

CREATE TABLE pages (
    id          TEXT PRIMARY KEY,
    profile_id  TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    sort_order  INTEGER NOT NULL DEFAULT 0,
    rows        INTEGER NOT NULL DEFAULT 3 CHECK (rows BETWEEN 1 AND 8),
    cols        INTEGER NOT NULL DEFAULT 5 CHECK (cols BETWEEN 1 AND 10),
    created_at  TEXT NOT NULL
);
CREATE INDEX idx_pages_profile ON pages(profile_id, sort_order);

CREATE TABLE buttons (
    id             TEXT PRIMARY KEY,
    page_id        TEXT NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
    row            INTEGER NOT NULL,
    col            INTEGER NOT NULL,
    row_span       INTEGER NOT NULL DEFAULT 1,
    col_span       INTEGER NOT NULL DEFAULT 1,
    label          TEXT NOT NULL DEFAULT '',
    icon_ref       TEXT,
    action_type    TEXT NOT NULL,
    action_config  TEXT NOT NULL DEFAULT '{}',
    appearance     TEXT NOT NULL DEFAULT '{}',
    state_config   TEXT NOT NULL DEFAULT '{}',
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL,
    UNIQUE (page_id, row, col)
);

CREATE TABLE devices (
    id            TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    token_hash    TEXT NOT NULL UNIQUE,
    paired_at     TEXT NOT NULL,
    last_seen_at  TEXT,
    revoked       INTEGER NOT NULL DEFAULT 0
);
