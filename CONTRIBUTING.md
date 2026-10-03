# Contributing

Thanks for helping. OpenDeck is a small, local-first Windows app; changes should keep it
lightweight, secure and understandable.

## Getting started

Follow [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) to set up, run and test from source, and
[BUILD.md](BUILD.md) to build the exe and installer. Use a separate `OPENDECK_DATA_DIR` while developing
so your own configuration is not touched.

## Before opening a pull request

- `cd backend; ..\.venv\Scripts\python -m pytest -q` passes.
- `cd frontend; npm test; npm run typecheck` passes.
- New behaviour has tests. Tests must never lock the PC, send real keystrokes, shut anything down,
  or write to the real Run key; stub those (see `tests/conftest.py`).
- Database changes are a new numbered migration in `backend/opendeck/db/migrations/`; never edit
  an existing one, never drop user data.
- Windows calls use `ctypes` in `native/windows/` (no pywin32).
- Devices must only ever send IDs; never accept commands, paths or scripts from the network.
- UI text: plain, sentence case, says what happens ("Start server", not "Submit").
- Update `CHANGELOG.md` and docs that describe what you changed.

## Reporting bugs

Open an issue with steps to reproduce, what you expected, and the output of
Diagnostics → **Copy diagnostics**. Attach relevant lines from Logs (they contain no tokens or
passwords, but check before posting).

Security problems: see [SECURITY.md](SECURITY.md) instead of opening a public issue.
