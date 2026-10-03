"""Read display name and icon from a Windows executable (or any file with an icon)."""

from __future__ import annotations

import ctypes
import logging
from ctypes import wintypes
from pathlib import Path

from ...imaging import encode_png_rgba
from .session import _require_windows

log = logging.getLogger(__name__)

ICON_SIZE = 256


class BITMAP(ctypes.Structure):
    _fields_ = [("bmType", wintypes.LONG), ("bmWidth", wintypes.LONG),
                ("bmHeight", wintypes.LONG), ("bmWidthBytes", wintypes.LONG),
                ("bmPlanes", wintypes.WORD), ("bmBitsPixel", wintypes.WORD),
                ("bmBits", ctypes.c_void_p)]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD)]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


class ICONINFO(ctypes.Structure):
    _fields_ = [("fIcon", wintypes.BOOL), ("xHotspot", wintypes.DWORD),
                ("yHotspot", wintypes.DWORD), ("hbmMask", wintypes.HBITMAP),
                ("hbmColor", wintypes.HBITMAP)]


class SHFILEINFOW(ctypes.Structure):
    _fields_ = [("hIcon", wintypes.HICON), ("iIcon", ctypes.c_int),
                ("dwAttributes", wintypes.DWORD), ("szDisplayName", wintypes.WCHAR * 260),
                ("szTypeName", wintypes.WCHAR * 80)]


def display_name(path: str) -> str:
    """FileDescription (e.g. "Google Chrome"), else ProductName, else the file name."""
    _require_windows()
    fallback = Path(path).stem
    version = ctypes.WinDLL("version")
    version.VerQueryValueW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR,
                                       ctypes.POINTER(ctypes.c_void_p),
                                       ctypes.POINTER(wintypes.UINT)]
    size = version.GetFileVersionInfoSizeW(path, None)
    if not size:
        return fallback
    buffer = ctypes.create_string_buffer(size)
    if not version.GetFileVersionInfoW(path, 0, size, buffer):
        return fallback

    def query(sub_block: str) -> tuple[ctypes.c_void_p, int] | None:
        pointer, length = ctypes.c_void_p(), wintypes.UINT()
        if version.VerQueryValueW(buffer, sub_block, ctypes.byref(pointer),
                                  ctypes.byref(length)) and length.value:
            return pointer, length.value
        return None

    translations: list[tuple[int, int]] = []
    found = query("\\VarFileInfo\\Translation")
    if found:
        words = ctypes.cast(found[0], ctypes.POINTER(wintypes.WORD))
        translations = [(words[i], words[i + 1]) for i in range(0, found[1] // 2, 2)]
    translations += [(0x0409, 0x04B0), (0x0409, 0x04E4)]  # en-US Unicode / Western
    for key in ("FileDescription", "ProductName"):
        for lang, codepage in translations:
            value = query(f"\\StringFileInfo\\{lang:04x}{codepage:04x}\\{key}")
            if value:
                text = ctypes.wstring_at(value[0], value[1]).rstrip("\x00").strip()
                if text:
                    return text[:40]
    return fallback


def extract_icon_png(path: str) -> bytes | None:
    """Best-quality icon of `path` as a 256×256 PNG, or None if it has none."""
    _require_windows()
    user32 = ctypes.WinDLL("user32")
    user32.PrivateExtractIconsW.argtypes = [wintypes.LPCWSTR, ctypes.c_int, ctypes.c_int,
                                            ctypes.c_int, ctypes.POINTER(wintypes.HICON),
                                            ctypes.POINTER(wintypes.UINT), wintypes.UINT,
                                            wintypes.UINT]
    user32.DestroyIcon.argtypes = [wintypes.HICON]
    icon = wintypes.HICON()
    icon_id = wintypes.UINT()
    count = user32.PrivateExtractIconsW(path, 0, ICON_SIZE, ICON_SIZE, ctypes.byref(icon),
                                        ctypes.byref(icon_id), 1, 0)
    if count < 1 or not icon:
        icon = _shell_icon(path)
        if not icon:
            return None
    try:
        return _icon_to_png(icon)
    except OSError as exc:
        log.warning("Icon conversion failed for %s: %s", path, exc)
        return None
    finally:
        user32.DestroyIcon(icon)


def _shell_icon(path: str) -> wintypes.HICON | None:
    """Fallback: the 32px icon Explorer shows for this file."""
    shell32 = ctypes.WinDLL("shell32")
    info = SHFILEINFOW()
    shgfi_icon, shgfi_large = 0x100, 0x0
    if shell32.SHGetFileInfoW(path, 0, ctypes.byref(info), ctypes.sizeof(info),
                              shgfi_icon | shgfi_large):
        return wintypes.HICON(info.hIcon)
    return None


def _icon_to_png(icon: wintypes.HICON) -> bytes | None:
    user32 = ctypes.WinDLL("user32")
    gdi32 = ctypes.WinDLL("gdi32")
    user32.GetIconInfo.argtypes = [wintypes.HICON, ctypes.POINTER(ICONINFO)]
    gdi32.GetObjectW.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p]
    gdi32.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT,
                                ctypes.c_void_p, ctypes.POINTER(BITMAPINFO), wintypes.UINT]
    gdi32.DeleteObject.argtypes = [wintypes.HANDLE]
    user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]

    info = ICONINFO()
    if not user32.GetIconInfo(icon, ctypes.byref(info)):
        raise OSError("GetIconInfo failed")
    hdc = user32.GetDC(None)
    try:
        if not info.hbmColor:
            return None  # monochrome icon: not worth supporting
        bitmap = BITMAP()
        gdi32.GetObjectW(info.hbmColor, ctypes.sizeof(bitmap), ctypes.byref(bitmap))
        width, height = bitmap.bmWidth, bitmap.bmHeight
        color = _read_bits(gdi32, hdc, info.hbmColor, width, height)
        if not any(color[3::4]):
            # Legacy icon without alpha channel: derive transparency from the AND mask.
            mask = _read_bits(gdi32, hdc, info.hbmMask, width, height)
            alpha = bytes(0 if mask[i] else 255 for i in range(0, len(mask), 4))
        else:
            alpha = color[3::4]
        rgba = bytearray(len(color))
        rgba[0::4], rgba[1::4], rgba[2::4] = color[2::4], color[1::4], color[0::4]
        rgba[3::4] = alpha
        return encode_png_rgba(width, height, bytes(rgba))
    finally:
        user32.ReleaseDC(None, hdc)
        if info.hbmColor:
            gdi32.DeleteObject(info.hbmColor)
        if info.hbmMask:
            gdi32.DeleteObject(info.hbmMask)


def _read_bits(gdi32, hdc, hbitmap, width: int, height: int) -> bytes:
    header = BITMAPINFOHEADER(biSize=ctypes.sizeof(BITMAPINFOHEADER), biWidth=width,
                              biHeight=-height, biPlanes=1, biBitCount=32, biCompression=0)
    bmi = BITMAPINFO(bmiHeader=header)
    buffer = ctypes.create_string_buffer(width * height * 4)
    if not gdi32.GetDIBits(hdc, hbitmap, 0, height, buffer, ctypes.byref(bmi), 0):
        raise OSError("GetDIBits failed")
    return buffer.raw
