"""The desktop window: a WebView2 window (via pywebview) showing the desktop UI the engine serves.

It runs as its own short-lived process, started when you open OpenDeck and ended
when you close the window, so the browser engine only uses memory while the window is
open. A tiny bridge (`window.pywebview.api`) lets the page ask the desktop app to
restart the engine, exit, or save a file.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import logging
import urllib.request
from pathlib import Path

from ..branding import PRODUCT_NAME
from ..config import AppConfig

log = logging.getLogger(__name__)

OFFLINE_PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>{title}</title>
<style>
 html,body{{height:100%;margin:0;background:#1a1b1e;color:#ecedef;font:15px "Segoe UI",system-ui,sans-serif}}
 main{{height:100%;display:grid;place-content:center;gap:12px;text-align:center;padding:24px}}
 h1{{font-size:20px;font-weight:600;margin:0}} p{{margin:0;color:#9a9ea7;max-width:52ch}}
 .row{{display:flex;gap:8px;justify-content:center;margin-top:8px}}
 button{{font:inherit;padding:8px 16px;border-radius:10px;border:1px solid #3a3d43;background:#2b2d31;color:#ecedef;cursor:pointer}}
 button.primary{{background:#ecedef;color:#1a1b1e;border-color:#ecedef}}
 button:focus-visible{{outline:2px solid #8ab4ff;outline-offset:2px}}
</style></head><body><main>
 <h1 id="title">Starting {title}…</h1>
 <p id="text">The engine that runs your buttons is starting.</p>
 <div class="row" id="actions" hidden>
  <button class="primary" onclick="pywebview.api.host_command('restart-engine')">Restart engine</button>
  <button onclick="pywebview.api.host_command('open-logs')">Open logs folder</button>
 </div>
</main><script>
 async function tick() {{
  try {{
   const s = await pywebview.api.host_state();
   if (s.engine === 'running') {{ location.replace(s.url); return; }}
   const crashed = s.engine === 'crashed';
   document.getElementById('title').textContent = crashed ? 'The engine stopped' : 'Starting {title}…';
   document.getElementById('text').textContent = crashed ? (s.error || 'It stopped unexpectedly.') : 'The engine that runs your buttons is starting.';
   document.getElementById('actions').hidden = !crashed;
  }} catch (e) {{}}
  setTimeout(tick, 1000);
 }}
 window.addEventListener('pywebviewready', tick);
</script></body></html>"""


class Bridge:
    """Methods callable from the page as window.pywebview.api.<name>(...)."""

    def __init__(self, host_url: str, token: str) -> None:
        self._host_url = host_url
        self._token = token
        self._window = None

    def _host(self, method: str, path: str) -> dict:
        request = urllib.request.Request(f"{self._host_url}{path}", method=method,
                                         headers={"X-Desktop-Token": self._token})
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read() or b"{}")

    def host_state(self) -> dict:
        return self._host("GET", "/state")

    def host_command(self, command: str) -> dict:
        return self._host("POST", f"/command/{command}")

    def take_requested_view(self) -> str | None:
        """A view the tray asked for ("settings", "logs"), once."""
        return self._host("POST", "/take-view").get("view")

    def save_text(self, file_name: str, text: str) -> bool:
        import webview

        if self._window is None:
            return False
        chosen = self._window.create_file_dialog(webview.FileDialog.SAVE, save_filename=file_name)
        if not chosen:
            return False
        path = chosen if isinstance(chosen, str) else chosen[0]
        Path(path).write_text(text, encoding="utf-8")
        return True


def _set_identity() -> None:
    """Taskbar groups the window as OpenDeck (not python.exe) when run from source."""
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("OpenDeck.Desktop")
    except (AttributeError, OSError):
        pass


def _apply_icon(window) -> None:
    """Title bar and taskbar icon from assets/icons/app.ico."""
    from .host import resource_dir

    icon = resource_dir() / "assets" / "icons" / "app.ico"
    try:
        hwnd = int(window.native.Handle.ToInt64())
    except Exception:
        return
    user32 = ctypes.windll.user32
    user32.LoadImageW.restype = ctypes.c_void_p
    user32.LoadImageW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint, ctypes.c_int, ctypes.c_int, ctypes.c_uint]
    user32.SendMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_void_p]
    for kind, size in ((1, 32), (0, 16)):  # ICON_BIG, ICON_SMALL
        handle = user32.LoadImageW(None, str(icon), 1, size, size, 0x10)  # IMAGE_ICON, LR_LOADFROMFILE
        if handle:
            user32.SendMessageW(hwnd, 0x0080, kind, handle)  # WM_SETICON


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ui", action="store_true")
    parser.add_argument("--host-url", required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--view", default="")
    return parser


def main(argv: list[str] | None = None) -> int:
    import webview

    args, _ = build_parser().parse_known_args(argv)

    bridge = Bridge(args.host_url, args.token)
    try:
        state = bridge.host_state()
    except OSError:
        state = {}
    url = state.get("url") if state.get("engine") == "running" else None
    if url and args.view:
        url = f"{url}#{args.view}"
    window = webview.create_window(
        PRODUCT_NAME,
        url=url,
        html=None if url else OFFLINE_PAGE.format(title=PRODUCT_NAME),
        js_api=bridge,
        width=1320, height=860, min_size=(960, 620),
        background_color="#1A1B1E",
        text_select=False,
    )
    bridge._window = window
    _set_identity()
    window.events.shown += lambda: _apply_icon(window)
    # private_mode=False keeps the window's local storage (remembered editor view) between opens;
    # WebView2's profile lives in our cache folder, not in a generic pywebview folder.
    storage = AppConfig.from_env().cache_dir / "webview"
    storage.mkdir(parents=True, exist_ok=True)
    webview.start(private_mode=False, storage_path=str(storage))
    return 0
