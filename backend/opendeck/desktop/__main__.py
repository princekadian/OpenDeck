"""Entry point for the desktop app and the packaged OpenDeck.exe.

    OpenDeck.exe [--minimized]      the desktop app (tray + window)
    OpenDeck.exe --engine ...       the engine process (started by the desktop app)
    OpenDeck.exe --ui ...           the window process (started by the desktop app)
    OpenDeck.exe --headless         the server alone, like `python -m opendeck`
"""

from __future__ import annotations

import multiprocessing
import sys


def main() -> None:
    multiprocessing.freeze_support()
    argv = sys.argv[1:]
    if "--engine" in argv or "--headless" in argv:
        from ..__main__ import engine_main

        sys.exit(engine_main([a for a in argv if a != "--headless"]))
    if "--ui" in argv:
        from .ui import main as ui_main

        sys.exit(ui_main(argv))
    from .host import main as host_main

    sys.exit(host_main(argv))


if __name__ == "__main__":
    main()
