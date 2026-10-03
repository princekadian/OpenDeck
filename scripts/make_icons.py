"""Generate the Windows icons (app + tray states) from the favicon design, no dependencies.

    python scripts/make_icons.py      -> assets/icons/*.ico

The design matches frontend/public/favicon.svg: a dark housing with a 2x2 key grid. In
tray icons the bottom-right key shows the server state, and its shape changes too
(filled / hollow / bar / cross), so the state never relies on colour alone.
"""

from __future__ import annotations

import struct
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "assets" / "icons"
SS = 4  # supersampling per axis

HOUSING = (0x1A, 0x1B, 0x1E)
KEY = (0x9A, 0x9E, 0xA7)
GREEN = (0x3F, 0xD0, 0x8A)
AMBER = (0xF0, 0xA6, 0x3A)
RED = (0xFF, 0x5F, 0x5F)


def rounded_rect(x0, y0, x1, y1, r):
    def inside(x, y):
        if not (x0 <= x <= x1 and y0 <= y <= y1):
            return False
        cx = min(max(x, x0 + r), x1 - r)
        cy = min(max(y, y0 + r), y1 - r)
        return (x - cx) ** 2 + (y - cy) ** 2 <= r * r
    return inside


def render(size: int, shapes) -> bytes:
    """shapes: list of (inside(x, y) in 0..32 units, (r, g, b)). Returns BGRA rows, bottom-up."""
    rows = []
    for py in range(size - 1, -1, -1):
        row = bytearray()
        for px in range(size):
            acc = [0.0, 0.0, 0.0, 0.0]
            for sy in range(SS):
                for sx in range(SS):
                    x = (px + (sx + 0.5) / SS) * 32 / size
                    y = (py + (sy + 0.5) / SS) * 32 / size
                    colour = None
                    for inside, rgb in shapes:
                        if inside(x, y):
                            colour = rgb
                    if colour:
                        acc[0] += colour[0]; acc[1] += colour[1]; acc[2] += colour[2]; acc[3] += 1
            n = SS * SS
            a = acc[3] / n
            if acc[3]:
                r, g, b = (acc[i] / acc[3] for i in range(3))
            else:
                r = g = b = 0
            row += bytes((int(b), int(g), int(r), int(round(a * 255))))
        rows.append(bytes(row))
    return b"".join(rows)


def ico(images: dict[int, bytes]) -> bytes:
    header = struct.pack("<HHH", 0, 1, len(images))
    entries, blobs = b"", b""
    offset = 6 + 16 * len(images)
    for size, pixels in sorted(images.items()):
        mask_row = ((size + 31) // 32) * 4
        bmp = struct.pack("<IiiHHIIiiII", 40, size, size * 2, 1, 32, 0, len(pixels), 0, 0, 0, 0)
        blob = bmp + pixels + b"\x00" * (mask_row * size)
        entries += struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(blob), offset)
        blobs += blob
        offset += len(blob)
    return header + entries + blobs


def keys(last):
    shapes = [(rounded_rect(0, 0, 32, 32, 7), HOUSING)]
    for x, y in ((4, 4), (17, 4), (4, 17)):
        shapes.append((rounded_rect(x, y, x + 11, y + 11, 2.2), KEY))
    shapes += last
    return shapes


def state_key(kind: str):
    box = (17, 17, 28, 28)
    if kind == "running":
        return [(rounded_rect(*box, 2.2), GREEN)]
    if kind == "starting":
        return [(rounded_rect(*box, 2.2), HOUSING), (rounded_rect(17, 20.5, 28, 24.5, 1.5), AMBER)]
    if kind == "error":
        def cross(x, y):
            u, v = x - 22.5, y - 22.5
            return abs(u) <= 6 and abs(v) <= 6 and (abs(u - v) <= 2.2 or abs(u + v) <= 2.2)
        return [(rounded_rect(*box, 2.2), HOUSING), (cross, RED)]
    # stopped: hollow key outline
    outer = rounded_rect(*box, 2.2)
    inner = rounded_rect(19.2, 19.2, 25.8, 25.8, 1)
    return [(lambda x, y: outer(x, y) and not inner(x, y), KEY)]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    app_sizes = (16, 20, 24, 32, 40, 48, 64, 128, 256)
    (OUT / "app.ico").write_bytes(ico({s: render(s, keys(state_key("running"))) for s in app_sizes}))
    for kind in ("running", "stopped", "starting", "error"):
        (OUT / f"tray-{kind}.ico").write_bytes(ico({s: render(s, keys(state_key(kind))) for s in (16, 20, 24, 32, 48)}))
    print("Icons written to", OUT)


if __name__ == "__main__":
    main()
