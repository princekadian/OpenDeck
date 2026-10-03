# PyInstaller build for OpenDeck.exe (one folder: fast start, no unpacking at launch).
#   Built by scripts/build.ps1; output: dist/OpenDeck/
# The same exe is the desktop app, the engine (--engine) and the window (--ui).

import re
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules
from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo, StringFileInfo, StringStruct, StringTable, VarFileInfo, VarStruct, VSVersionInfo,
)

ROOT = Path(SPECPATH).resolve().parent  # noqa: F821 (SPECPATH is provided by PyInstaller)
BACKEND = ROOT / "backend"
VERSION = re.search(r'__version__ = "([^"]+)"', (BACKEND / "opendeck" / "__init__.py").read_text()).group(1)
numbers = tuple(int(p) for p in VERSION.split(".")) + (0,) * (4 - len(VERSION.split(".")))

web = ROOT / "frontend" / "dist"
if not (web / "index.html").exists():
    raise SystemExit("Build the frontend first: npm --prefix frontend run build")

datas = [
    (str(web), "web"),
    (str(ROOT / "assets" / "icons"), "assets/icons"),
    (str(BACKEND / "opendeck" / "db" / "migrations"), "opendeck/db/migrations"),
]
hiddenimports = (
    collect_submodules("opendeck")  # actions are discovered at runtime
    + collect_submodules("uvicorn")  # protocols and loops are imported by name
    + ["webview.platforms.winforms", "webview.platforms.edgechromium"]
)

a = Analysis(  # noqa: F821
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(BACKEND)],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "unittest", "pytest", "pydoc", "test", "lib2to3", "PIL", "numpy"],
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821

version = VSVersionInfo(
    ffi=FixedFileInfo(filevers=numbers, prodvers=numbers),
    kids=[
        StringFileInfo([StringTable("040904B0", [
            StringStruct("CompanyName", "OpenDeck contributors"),
            StringStruct("FileDescription", "OpenDeck"),
            StringStruct("FileVersion", VERSION),
            StringStruct("InternalName", "OpenDeck"),
            StringStruct("LegalCopyright", "MIT License"),
            StringStruct("OriginalFilename", "OpenDeck.exe"),
            StringStruct("ProductName", "OpenDeck"),
            StringStruct("ProductVersion", VERSION),
        ])]),
        VarFileInfo([VarStruct("Translation", [0x0409, 1200])]),
    ],
)

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="OpenDeck",
    console=False,  # no terminal window, ever
    icon=str(ROOT / "assets" / "icons" / "app.ico"),
    version=version,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="OpenDeck")  # noqa: F821
