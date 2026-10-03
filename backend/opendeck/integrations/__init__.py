"""Third-party integrations (OBS first). Each integration owns its connection and
exposes a small async interface that actions call, so the core Button/Action
system never depends on a specific integration's protocol."""
