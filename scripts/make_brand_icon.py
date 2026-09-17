"""Write a 256x256 PNG icon for HACS brand assets and the Supervisor add-on."""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SIZE = 256
BG = (27, 54, 93, 255)
INK = (245, 242, 232, 255)
ACCENT = (196, 154, 76, 255)


def _crc(chunk_type: bytes, data: bytes) -> int:
    return zlib.crc32(chunk_type + data) & 0xFFFFFFFF


def _chunk(chunk_type: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + chunk_type + data + struct.pack(">I", _crc(chunk_type, data))


def _png(pixels: list[list[tuple[int, int, int, int]]]) -> bytes:
    raw = b"".join(b"\x00" + b"".join(struct.pack("BBBB", *px) for px in row) for row in pixels)
    ihdr = struct.pack(">IIBBBBB", SIZE, SIZE, 8, 6, 0, 0, 0)
    return b"".join(
        [
            b"\x89PNG\r\n\x1a\n",
            _chunk(b"IHDR", ihdr),
            _chunk(b"IDAT", zlib.compress(raw, 9)),
            _chunk(b"IEND", b""),
        ]
    )


def _fill(pixels, x0, y0, x1, y1, color) -> None:
    for y in range(max(0, y0), min(SIZE, y1)):
        row = pixels[y]
        for x in range(max(0, x0), min(SIZE, x1)):
            row[x] = color


def _circle(pixels, cx, cy, radius, color) -> None:
    r2 = radius * radius
    for y in range(max(0, cy - radius), min(SIZE, cy + radius + 1)):
        dy = y - cy
        for x in range(max(0, cx - radius), min(SIZE, cx + radius + 1)):
            dx = x - cx
            if dx * dx + dy * dy <= r2:
                pixels[y][x] = color


def build() -> bytes:
    pixels = [[BG for _ in range(SIZE)] for _ in range(SIZE)]
    _circle(pixels, 128, 128, 118, (22, 44, 76, 255))
    _fill(pixels, 78, 52, 186, 198, INK)
    _fill(pixels, 86, 60, 178, 190, BG)
    _fill(pixels, 98, 78, 166, 88, INK)
    _fill(pixels, 98, 100, 158, 108, INK)
    _fill(pixels, 98, 120, 150, 128, INK)
    _fill(pixels, 98, 140, 142, 148, INK)
    _fill(pixels, 168, 86, 214, 102, ACCENT)
    _fill(pixels, 184, 70, 198, 168, ACCENT)
    _circle(pixels, 191, 64, 16, ACCENT)
    return _png(pixels)


def main() -> None:
    data = build()
    targets = [
        ROOT / "brand" / "icon.png",
        ROOT / "placer_probate_monitor" / "icon.png",
        ROOT / "placer_probate_monitor" / "logo.png",
    ]
    for path in targets:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        print(path)


if __name__ == "__main__":
    main()
