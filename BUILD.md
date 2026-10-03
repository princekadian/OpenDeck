# Building OpenDeck

Everything below runs on a Windows 10/11 x64 developer PC. End users need none of it: they run the
installer.

## Tools (developer machine only)

| Tool | Version | Used for |
|---|---|---|
| Python | 3.12, 64-bit | engine, desktop app, PyInstaller |
| Node.js | 20 or newer | frontend build and tests |
| Inno Setup | 6 | the installer (`winget install JRSoftware.InnoSetup`) |
| Git | any | cloning |

Python packages come from `backend/requirements*.txt`; npm packages from `frontend/package-lock.json`.

## One command

```powershell
git clone https://github.com/princekadian/OpenDeck.git
cd OpenDeck
powershell -ExecutionPolicy Bypass -File scripts\build.ps1
```

The script:

1. creates `.venv` if needed and installs `backend\requirements-dev.txt` + `requirements-build.txt`;
2. runs `npm ci`, `npm run build` (output `frontend\dist`) and the frontend tests;
3. runs the backend tests;
4. builds `dist\OpenDeck\OpenDeck.exe` with PyInstaller (`packaging\OpenDeck.spec`);
5. builds `dist\installer\OpenDeck-Setup-<version>.exe` with Inno Setup (`installer\OpenDeck.iss`).

Options: `-SkipTests` (faster), `-NoInstaller` (stop after step 4).

## Build modes

| Mode | How | Result |
|---|---|---|
| Development | `cd backend; ..\.venv\Scripts\python -m opendeck.desktop` | desktop app from source (frontend must be built once) |
| Development, server only | `cd backend; ..\.venv\Scripts\python -m opendeck` | headless server; editor at `http://localhost:8765/editor` |
| Production | `scripts\build.ps1 -NoInstaller` | `dist\OpenDeck\` — portable folder, double-click `OpenDeck.exe` |
| Installer | `scripts\build.ps1` | `dist\installer\OpenDeck-Setup-<version>.exe` |

## Version

The version lives in one place: `backend/opendeck/__init__.py` (`__version__`). The build reads
it for the exe version resource, the installer name and the uninstall entry; the app shows it in
Settings → About, the status bar, Diagnostics and every log. Keep `frontend/package.json` and
`backend/pyproject.toml` in step when releasing, and add a `CHANGELOG.md` entry.

## Icons

`assets/icons/*.ico` are generated from the favicon design and committed. After changing the design:

```powershell
python scripts\make_icons.py
```

## What the installer does

- Installs to `Program Files\OpenDeck` (or per user with `/CURRENTUSER`, without admin rights).
- Start menu shortcut; optional desktop shortcut; optional "start when I sign in" (HKCU Run value).
- Adds a Windows Firewall rule for `OpenDeck.exe` on **private** networks (admin installs only),
  removed on uninstall.
- On upgrade, asks a running copy to quit cleanly (`OpenDeck.exe --exit`) before replacing files.
  User data in `%LOCALAPPDATA%\OpenDeck` is never touched.
- Uninstall removes the program, shortcuts, firewall rule and Run value, then asks whether to delete
  user data (default No; silent uninstalls keep it).

Silent install for testing: `OpenDeck-Setup-1.0.0.exe /VERYSILENT /CURRENTUSER /DIR=C:\Temp\OpenDeck`.
