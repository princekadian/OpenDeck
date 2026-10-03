"""Icon asset storage: small PNGs on disk, addressed by content hash.

The database stores only a reference (`asset:<sha256>.png`), never image bytes.
Identical icons are stored once.
"""

from __future__ import annotations

import hashlib
import re
import struct
from pathlib import Path

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
MAX_BYTES = 512 * 1024
MAX_EDGE = 512
_NAME = re.compile(r"^[0-9a-f]{64}\.png$")


class AssetError(ValueError):
    pass


class AssetStore:
    def __init__(self, directory: Path) -> None:
        self._dir = directory
        self._dir.mkdir(parents=True, exist_ok=True)

    def save_png(self, data: bytes) -> str:
        """Validate and store a PNG. Returns its icon reference."""
        _validate_png(data)
        name = f"{hashlib.sha256(data).hexdigest()}.png"
        target = self._dir / name
        if not target.exists():
            tmp = target.with_suffix(".tmp")
            tmp.write_bytes(data)
            tmp.replace(target)
        return f"asset:{name}"

    def exists(self, name: str) -> bool:
        return bool(_NAME.match(name)) and (self._dir / name).is_file()

    def path_for(self, name: str) -> Path | None:
        return self._dir / name if self.exists(name) else None


def _validate_png(data: bytes) -> None:
    if len(data) > MAX_BYTES:
        raise AssetError("Icon is too large. Use an image under 512 KB.")
    if len(data) < 33 or not data.startswith(PNG_SIGNATURE) or data[12:16] != b"IHDR":
        raise AssetError("Icon must be a PNG image.")
    width, height = struct.unpack(">II", data[16:24])
    if not (0 < width <= MAX_EDGE and 0 < height <= MAX_EDGE):
        raise AssetError(f"Icon must be at most {MAX_EDGE}×{MAX_EDGE} pixels.")
