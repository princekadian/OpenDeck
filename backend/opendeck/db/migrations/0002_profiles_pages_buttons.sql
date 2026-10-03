-- Milestone 2: profile/page metadata, order-based button positions, enable flag.
-- Buttons switch from (row, col) grid cells to a per-page sort_order: the frontend
-- reflows keys for each screen, so only their order is configuration. Existing
-- buttons keep their order (row-major).

ALTER TABLE profiles ADD COLUMN description TEXT NOT NULL DEFAULT '';
ALTER TABLE profiles ADD COLUMN icon_ref TEXT;
ALTER TABLE profiles ADD COLUMN updated_at TEXT;
UPDATE profiles SET updated_at = created_at;

ALTER TABLE pages ADD COLUMN icon_ref TEXT;
ALTER TABLE pages ADD COLUMN updated_at TEXT;
UPDATE pages SET updated_at = created_at;

CREATE TABLE buttons_v2 (
    id             TEXT PRIMARY KEY,
    page_id        TEXT NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
    sort_order     INTEGER NOT NULL,
    label          TEXT NOT NULL DEFAULT '',
    description    TEXT NOT NULL DEFAULT '',
    icon_ref       TEXT,
    action_type    TEXT NOT NULL,
    action_config  TEXT NOT NULL DEFAULT '{}',
    appearance     TEXT NOT NULL DEFAULT '{}',
    state_config   TEXT NOT NULL DEFAULT '{}',
    enabled        INTEGER NOT NULL DEFAULT 1,
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);

INSERT INTO buttons_v2 (id, page_id, sort_order, label, icon_ref, action_type, action_config,
                        appearance, state_config, created_at, updated_at)
SELECT id, page_id,
       ROW_NUMBER() OVER (PARTITION BY page_id ORDER BY row, col) - 1,
       label, icon_ref, action_type, action_config, appearance, state_config,
       created_at, updated_at
FROM buttons;

DROP TABLE buttons;
ALTER TABLE buttons_v2 RENAME TO buttons;
CREATE INDEX idx_buttons_page ON buttons(page_id, sort_order);
