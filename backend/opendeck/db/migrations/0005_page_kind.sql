-- Page kinds: 'deck' pages hold buttons (every existing page); 'monitor' pages show the
-- live System Monitoring dashboard instead. Monitoring readings are never stored here.

ALTER TABLE pages ADD COLUMN kind TEXT NOT NULL DEFAULT 'deck';
