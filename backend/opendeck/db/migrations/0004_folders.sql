-- Folders: a folder is a button (kind = 'folder') that contains other buttons.
-- parent_id points at the containing folder button; NULL means the page itself.
-- Deleting a folder deletes its contents (cascade). Existing buttons become
-- kind 'action' with no parent, so nothing changes for them.

ALTER TABLE buttons ADD COLUMN kind TEXT NOT NULL DEFAULT 'action';
ALTER TABLE buttons ADD COLUMN parent_id TEXT REFERENCES buttons(id) ON DELETE CASCADE;
CREATE INDEX idx_buttons_container ON buttons(page_id, parent_id, sort_order);
