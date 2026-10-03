"""Minimal PNG encoder (stdlib only) for icons extracted from Windows executables."""

from __future__ import annotations

import struct
import zlib


def encode_png_rgba(width: int, height: int, rgba: bytes) -> bytes:
    """Encode top-down, non-premultiplied 8-bit RGBA pixels as PNG."""
    if len(rgba) != width * height * 4:
        raise ValueError("pixel buffer size does not match dimensions")
    stride = width * 4
    raw = b"".join(b"\x00" + rgba[y * stride:(y + 1) * stride] for y in range(height))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)  # 8-bit RGBA
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))
