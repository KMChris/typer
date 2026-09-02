"""Renders the Typer icon (gradient tile with a T and a caret) into src/typer_app/assets/typer.ico.

Pure Python: analytic anti-aliasing through signed distance fields, PNG encoding with zlib,
PNG frames wrapped in an ICO container. No image library needed.
"""

from __future__ import annotations

import math
import struct
import sys
import zlib
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "src" / "typer_app" / "assets" / "typer.ico"
SIZES = (256, 64, 48, 32, 16)
GRADIENT = ((0x7C, 0x6C, 0xFF), (0x2E, 0xC4, 0xE6))


def rounded_box(px: float, py: float, cx: float, cy: float, hw: float, hh: float, r: float) -> float:
    qx = abs(px - cx) - (hw - r)
    qy = abs(py - cy) - (hh - r)
    outside = math.hypot(max(qx, 0.0), max(qy, 0.0))
    return outside + min(max(qx, qy), 0.0) - r


def coverage(distance: float) -> float:
    return max(0.0, min(1.0, 0.5 - distance))


def render(size: int) -> bytes:
    s = size / 32.0  # design units: a 32x32 grid
    rows = []
    for y in range(size):
        row = bytearray()
        for x in range(size):
            px, py = x + 0.5, y + 0.5
            tile = coverage(rounded_box(px, py, 16 * s, 16 * s, 16 * s, 16 * s, 9 * s))
            if tile <= 0:
                row += b"\x00\x00\x00\x00"
                continue
            t = (px + py) / (2 * size)
            base = tuple(round(GRADIENT[0][i] + (GRADIENT[1][i] - GRADIENT[0][i]) * t) for i in range(3))
            glyph = max(
                coverage(rounded_box(px, py, 15.5 * s, 10 * s, 8 * s, 1.7 * s, 1.6 * s)),  # top bar of the T
                coverage(rounded_box(px, py, 15.5 * s, 16 * s, 1.7 * s, 7.5 * s, 1.6 * s)),  # stem of the T
                coverage(rounded_box(px, py, 22.3 * s, 20 * s, 1.3 * s, 3.2 * s, 1.2 * s)),  # caret
            )
            color = tuple(round(base[i] + (255 - base[i]) * glyph) for i in range(3))
            row += bytes(color) + bytes([round(255 * tile)])
        rows.append(b"\x00" + bytes(row))
    return png(size, size, b"".join(rows))


def png(width: int, height: int, raw: bytes) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")


def ico(frames: list[tuple[int, bytes]]) -> bytes:
    header = struct.pack("<HHH", 0, 1, len(frames))
    offset = len(header) + 16 * len(frames)
    entries = b""
    payload = b""
    for size, data in frames:
        entries += struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(data), offset)
        payload += data
        offset += len(data)
    return header + entries + payload


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    frames = [(size, render(size)) for size in SIZES]
    OUT.write_bytes(ico(frames))
    (OUT.parent / "typer-256.png").write_bytes(frames[0][1])
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes)")


if __name__ == "__main__":
    sys.exit(main())
