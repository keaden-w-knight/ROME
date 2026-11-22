"""Save raw RGBA pixels as a PNG, using only the standard library."""

from __future__ import annotations

import struct
import zlib


def save_png(path: str, width: int, height: int, rgba: bytes) -> None:
    """Write `width`x`height` RGBA8 bytes (top row first) to `path` as a PNG."""
    expected = width * height * 4
    if len(rgba) != expected:
        raise ValueError(f"expected {expected} bytes, got {len(rgba)}")

    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    stride = width * 4
    raw = bytearray()
    for y in range(height):
        raw.append(0)  # filter type 0 (none) for this scanline
        raw.extend(rgba[y * stride : (y + 1) * stride])

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)  # 8-bit, RGBA
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n")
        f.write(chunk(b"IHDR", ihdr))
        f.write(chunk(b"IDAT", zlib.compress(bytes(raw), 9)))
        f.write(chunk(b"IEND", b""))
