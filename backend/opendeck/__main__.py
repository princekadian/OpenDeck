"""Command line entry points.

    python -m opendeck                         headless server (development / servers)
    python -m opendeck --engine --control-port N   engine for the desktop app (internal)
    python -m opendeck.desktop                 the desktop app (window + tray)

The packaged OpenDeck.exe starts the desktop app; see desktop/__main__.py.
"""

from __future__ import annotations

import argparse
import dataclasses
import os
import sys
from pathlib import Path

from .config import AppConfig, adopt_legacy_data
from .logging_setup import configure_logging


def static_dir_default() -> Path | None:
    """The built frontend: bundled next to the app, or frontend/dist in a checkout."""
    if getattr(sys, "frozen", False):
        bundled = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "web"
        return bundled if bundled.exists() else None
    repo_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    return repo_dist if repo_dist.exists() else None


def engine_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="opendeck")
    parser.add_argument("--engine", action="store_true", help="run as the desktop app's engine (internal)")
    parser.add_argument("--control-port", type=int, default=None)
    args, _unknown = parser.parse_known_args(argv)

    config = AppConfig.from_env()
    if config.static_dir is None:
        config = dataclasses.replace(config, static_dir=static_dir_default())
    configure_logging(config.log_dir, file_name="server.log", console=not args.engine)
    if "OPENDECK_DATA_DIR" not in os.environ:  # only the real per-user folder imports old data
        adopt_legacy_data(config)
    config.ensure_dirs()

    from .engine import run  # after logging, so import-time problems are recorded

    return run(config, control_port=args.control_port if args.engine else None)


def main() -> None:
    sys.exit(engine_main())


if __name__ == "__main__":
    main()
