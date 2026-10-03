"""Synthesised keyboard input via SendInput (keys, combinations, Unicode text, media keys).

Input goes to whichever window is focused on the PC, exactly like a physical
keyboard. Windows blocks input into elevated (administrator) windows unless this
app is elevated too (UIPI); that case cannot be detected from here.
"""

from __future__ import annotations

import ctypes
import time
from ctypes import wintypes

from .session import PlatformError, _require_windows

INPUT_KEYBOARD = 1
KEYEVENTF_EXTENDEDKEY = 0x1
KEYEVENTF_KEYUP = 0x2
KEYEVENTF_UNICODE = 0x4

ULONG_PTR = ctypes.c_size_t


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


MODIFIERS: dict[str, int] = {"CTRL": 0x11, "ALT": 0x12, "SHIFT": 0x10, "WIN": 0x5B}
MODIFIER_ORDER = ("CTRL", "ALT", "SHIFT", "WIN")

# Key names are the stored, structured form (e.g. {"modifiers": ["CTRL"], "key": "S"}).
KEYS: dict[str, int] = {
    **{chr(c): c for c in range(ord("A"), ord("Z") + 1)},
    **{str(d): 0x30 + d for d in range(10)},
    **{f"F{n}": 0x6F + n for n in range(1, 25)},
    "ENTER": 0x0D, "ESCAPE": 0x1B, "SPACE": 0x20, "TAB": 0x09, "BACKSPACE": 0x08, "DELETE": 0x2E,
    "INSERT": 0x2D, "HOME": 0x24, "END": 0x23, "PAGE_UP": 0x21, "PAGE_DOWN": 0x22,
    "LEFT": 0x25, "UP": 0x26, "RIGHT": 0x27, "DOWN": 0x28,
    "CAPS_LOCK": 0x14, "NUM_LOCK": 0x90, "SCROLL_LOCK": 0x91, "PRINT_SCREEN": 0x2C, "PAUSE": 0x13,
    "CONTEXT_MENU": 0x5D,
    **{f"NUMPAD_{d}": 0x60 + d for d in range(10)},
    "NUMPAD_MULTIPLY": 0x6A, "NUMPAD_ADD": 0x6B, "NUMPAD_SUBTRACT": 0x6D, "NUMPAD_DECIMAL": 0x6E,
    "NUMPAD_DIVIDE": 0x6F,
    "SEMICOLON": 0xBA, "EQUALS": 0xBB, "COMMA": 0xBC, "MINUS": 0xBD, "PERIOD": 0xBE, "SLASH": 0xBF,
    "BACKQUOTE": 0xC0, "BRACKET_LEFT": 0xDB, "BACKSLASH": 0xDC, "BRACKET_RIGHT": 0xDD, "QUOTE": 0xDE,
    "MEDIA_PLAY_PAUSE": 0xB3, "MEDIA_NEXT": 0xB0, "MEDIA_PREVIOUS": 0xB1, "MEDIA_STOP": 0xB2,
    "VOLUME_UP": 0xAF, "VOLUME_DOWN": 0xAE, "VOLUME_MUTE": 0xAD,
    "BROWSER_BACK": 0xA6, "BROWSER_FORWARD": 0xA7, "BROWSER_REFRESH": 0xA8, "BROWSER_HOME": 0xAC,
}

# Keys whose scan codes live in the extended set; needed so apps see e.g. arrows, not numpad.
_EXTENDED = {0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2D, 0x2E, 0x5B, 0x5D, 0x6F, 0x90,
             0x2C, 0xA6, 0xA7, 0xA8, 0xAC, 0xAD, 0xAE, 0xAF, 0xB0, 0xB1, 0xB2, 0xB3}

_user32 = None


def _api():
    global _user32
    if _user32 is None:
        _require_windows()
        _user32 = ctypes.WinDLL("user32", use_last_error=True)
        _user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
        _user32.SendInput.restype = wintypes.UINT
        _user32.MapVirtualKeyW.argtypes = [wintypes.UINT, wintypes.UINT]
    return _user32


def _key_input(vk: int, up: bool) -> INPUT:
    flags = (KEYEVENTF_KEYUP if up else 0) | (KEYEVENTF_EXTENDEDKEY if vk in _EXTENDED else 0)
    scan = _api().MapVirtualKeyW(vk, 0)  # MAPVK_VK_TO_VSC
    return INPUT(type=INPUT_KEYBOARD, u=_INPUTUNION(ki=KEYBDINPUT(wVk=vk, wScan=scan, dwFlags=flags)))


def _send(events: list[INPUT]) -> None:
    if not events:
        return
    array = (INPUT * len(events))(*events)
    sent = _api().SendInput(len(events), array, ctypes.sizeof(INPUT))
    if sent != len(events):
        raise PlatformError(f"Windows blocked the keyboard input (error {ctypes.get_last_error()}).")


def vk_for(key: str) -> int:
    try:
        return KEYS[key]
    except KeyError:
        raise PlatformError(f"Unknown key '{key}'.") from None


def tap_key(key: str) -> None:
    """Press and release one key (e.g. VOLUME_UP, which Windows answers with its volume pop-up)."""
    vk = vk_for(key)
    _send([_key_input(vk, False), _key_input(vk, True)])


def press_combo(modifiers: list[str], key: str | None) -> None:
    """Hold modifiers in canonical order, tap `key` (optional), release in reverse."""
    mod_vks = [MODIFIERS[m] for m in MODIFIER_ORDER if m in modifiers]
    key_vks = [vk_for(key)] if key else []
    down = [_key_input(vk, False) for vk in mod_vks + key_vks]
    up = [_key_input(vk, True) for vk in reversed(mod_vks + key_vks)]
    _send(down + up)


def type_text(text: str, chunk: int = 64) -> None:
    """Type Unicode text (any script, emoji) as if from a keyboard. Newlines press Enter."""
    events: list[INPUT] = []
    for line_index, line in enumerate(text.replace("\r\n", "\n").split("\n")):
        if line_index:
            events += [_key_input(0x0D, False), _key_input(0x0D, True)]
        utf16 = line.encode("utf-16-le")
        for i in range(0, len(utf16), 2):
            unit = int.from_bytes(utf16[i:i + 2], "little")  # surrogate pairs are sent as two units
            for up in (False, True):
                flags = KEYEVENTF_UNICODE | (KEYEVENTF_KEYUP if up else 0)
                events.append(INPUT(type=INPUT_KEYBOARD,
                                    u=_INPUTUNION(ki=KEYBDINPUT(wVk=0, wScan=unit, dwFlags=flags))))
    # Send in chunks so a long text cannot flood the target application's input queue.
    for start in range(0, len(events), chunk * 2):
        _send(events[start:start + chunk * 2])
        time.sleep(0.005)


def key_catalog() -> list[dict[str, str]]:
    """Keys for the editor's pickers, grouped and labelled. Same names as KEYS."""
    def label(name: str) -> str:
        special = {"PAGE_UP": "Page Up", "PAGE_DOWN": "Page Down", "MEDIA_PLAY_PAUSE": "Media Play/Pause",
                   "MEDIA_NEXT": "Media Next", "MEDIA_PREVIOUS": "Media Previous", "MEDIA_STOP": "Media Stop",
                   "PRINT_SCREEN": "Print Screen", "BACKQUOTE": "` (backquote)", "BRACKET_LEFT": "[",
                   "BRACKET_RIGHT": "]", "BACKSLASH": "\\", "SEMICOLON": ";", "EQUALS": "=", "COMMA": ",",
                   "MINUS": "-", "PERIOD": ".", "SLASH": "/", "QUOTE": "'", "CONTEXT_MENU": "Menu",
                   "LEFT": "Left arrow", "RIGHT": "Right arrow", "UP": "Up arrow", "DOWN": "Down arrow"}
        return special.get(name, name.replace("_", " ").title())

    def group(name: str) -> str:
        if len(name) == 1 and name.isalpha():
            return "Letters"
        if len(name) == 1 and name.isdigit():
            return "Numbers"
        if name.startswith("F") and name[1:].isdigit():
            return "Function keys"
        if name.startswith(("MEDIA_", "VOLUME_")):
            return "Media"
        if name.startswith("BROWSER_"):
            return "Browser"
        if name.startswith("NUMPAD_"):
            return "Numpad"
        if name in {"LEFT", "RIGHT", "UP", "DOWN", "HOME", "END", "PAGE_UP", "PAGE_DOWN"}:
            return "Navigation"
        if name in {"SEMICOLON", "EQUALS", "COMMA", "MINUS", "PERIOD", "SLASH", "BACKQUOTE", "BRACKET_LEFT",
                    "BACKSLASH", "BRACKET_RIGHT", "QUOTE"}:
            return "Symbols"
        return "Editing and system"

    return [{"name": n, "label": label(n), "group": group(n)} for n in KEYS]
