"""Runtime configuration: filesystem locations and server settings.

User data lives in one per-user folder, separate from the installed program, so
upgrades and reinstalls never touch it:

    %LOCALAPPDATA%\\OpenDeck\\
        data\\data.sqlite3     profiles, pages, buttons, devices, settings
        data\\assets\\         button icons
        logs\\                 server.log, desktop.log (rotated)
        backups\\              database copies made before migrations / on request
        cache\\                disposable files
"""

from __future__ import annotations

import logging
import os
import shutil
import socket
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from .branding import DEFAULT_PORT, PRODUCT_SLUG

log = logging.getLogger(__name__)


def _default_root() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / PRODUCT_SLUG


# Earlier releases were called MyStreamDeck. Their data is imported on first start.
OLD_NAME = "MyStreamDeck"


def legacy_sources() -> list[tuple[Path, Path]]:
    """(database, icons folder) of earlier installs, newest layout first."""
    local = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / OLD_NAME
    roaming = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / OLD_NAME
    return [
        (local / "data" / "data.sqlite3", local / "data" / "assets"),  # MyStreamDeck 1.0
        (roaming / "data.sqlite3", roaming / "assets"),  # MyStreamDeck before 1.0
    ]


@dataclass(frozen=True)
class AppConfig:
    # Root of the user-data folder (see module docstring).
    data_dir: Path = field(default_factory=_default_root)
    host: str = "0.0.0.0"
    port: int = DEFAULT_PORT
    # True when OPENDECK_PORT pins the port (tests, development); otherwise the saved setting wins.
    port_from_env: bool = False
    static_dir: Path | None = None
    pc_name: str = field(default_factory=socket.gethostname)

    @property
    def db_path(self) -> Path:
        return self.data_dir / "data" / "data.sqlite3"

    @property
    def assets_dir(self) -> Path:
        return self.data_dir / "data" / "assets"

    @property
    def log_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def backup_dir(self) -> Path:
        return self.data_dir / "backups"

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"

    def ensure_dirs(self) -> None:
        for path in (self.data_dir, self.db_path.parent, self.log_dir, self.assets_dir, self.backup_dir,
                     self.cache_dir):
            path.mkdir(parents=True, exist_ok=True)

    @classmethod
    def from_env(cls) -> "AppConfig":
        """Build config with optional MSD_* environment overrides (dev/testing)."""
        kwargs: dict[str, object] = {}
        if data_dir := os.environ.get("OPENDECK_DATA_DIR"):
            kwargs["data_dir"] = Path(data_dir)
        if port := os.environ.get("OPENDECK_PORT"):
            kwargs["port"] = int(port)
            kwargs["port_from_env"] = True
        if static_dir := os.environ.get("OPENDECK_STATIC_DIR"):
            kwargs["static_dir"] = Path(static_dir)
        return cls(**kwargs)  # type: ignore[arg-type]


def adopt_legacy_data(config: AppConfig, sources: list[tuple[Path, Path]] | None = None) -> bool:
    """First start: COPY the database and icons of an earlier install (MyStreamDeck) into
    the new folder.

    The old folder is never modified or deleted; it stays as a backup. Runs only when
    the new folder has no database yet, so it happens at most once. The copy uses
    SQLite's online backup, which is consistent even if an old copy still has the
    database open.
    """
    if config.db_path.exists():
        return False
    found = next(((db, assets) for db, assets in (sources or legacy_sources()) if db.exists()), None)
    if found is None:
        return False
    source, assets = found
    config.ensure_dirs()
    staging = config.db_path.with_suffix(".importing")
    src = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    try:
        dst = sqlite3.connect(staging)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
    staging.replace(config.db_path)  # appears only when complete
    if assets.is_dir():
        shutil.copytree(assets, config.assets_dir, dirs_exist_ok=True)
    (config.db_path.parent / "imported-from.txt").write_text(
        f"Copied from {source.parent} on first start. The original folder was left unchanged.\n",
        encoding="utf-8")
    log.info("Imported existing configuration from %s (original left in place)", source.parent)
    return True
