"""Minimal RGB image type with PNG/PPM read-write, standard library only (zlib). Used by the card detector and the
synthetic test scenes; no OpenCV/numpy/PIL is installed in this environment, and none is required.

PNG support: 8-bit RGB / RGBA / grayscale, non-interlaced, all five filter types on read; filter 0 on write.
"""
from __future__ import annotations

from dataclasses import dataclass
import struct
import zlib

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


@dataclass
class Image:
    width: int
    height: int
    pixels: bytearray  # RGB, row-major, 3 bytes per pixel

    @classmethod
    def blank(cls, width: int, height: int, rgb=(0, 0, 0)) -> "Image":
        return cls(width, height, bytearray(bytes(rgb) * (width * height)))

    def get(self, x: int, y: int) -> tuple[int, int, int]:
        i = 3 * (y * self.width + x)
        return self.pixels[i], self.pixels[i + 1], self.pixels[i + 2]

    def set(self, x: int, y: int, rgb) -> None:
        if 0 <= x < self.width and 0 <= y < self.height:
            i = 3 * (y * self.width + x)
            self.pixels[i:i + 3] = bytes(max(0, min(255, int(c))) for c in rgb)


def _chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


def to_png(img: Image) -> bytes:
    raw = b"".join(b"\x00" + bytes(img.pixels[3 * img.width * y:3 * img.width * (y + 1)]) for y in range(img.height))
    header = struct.pack(">IIBBBBB", img.width, img.height, 8, 2, 0, 0, 0)
    return PNG_SIGNATURE + _chunk(b"IHDR", header) + _chunk(b"IDAT", zlib.compress(raw, 9)) + _chunk(b"IEND", b"")


def _paeth(a, b, c):
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    return a if pa <= pb and pa <= pc else (b if pb <= pc else c)


def from_png(data: bytes) -> Image:
    if data[:8] != PNG_SIGNATURE:
        raise ValueError("not a PNG file")
    pos, idat, header = 8, b"", None
    while pos < len(data):
        length = struct.unpack(">I", data[pos:pos + 4])[0]
        kind, body = data[pos + 4:pos + 8], data[pos + 8:pos + 8 + length]
        pos += 12 + length
        if kind == b"IHDR":
            header = struct.unpack(">IIBBBBB", body)
        elif kind == b"IDAT":
            idat += body
        elif kind == b"IEND":
            break
    if header is None:
        raise ValueError("PNG without IHDR")
    width, height, depth, color, _, _, interlace = header
    channels = {0: 1, 2: 3, 6: 4}.get(color)
    if depth != 8 or channels is None or interlace:
        raise ValueError(f"unsupported PNG (bit depth {depth}, color type {color}, interlace {interlace})")
    raw, stride = zlib.decompress(idat), width * channels
    out, prev, i = bytearray(), bytearray(stride), 0
    for _ in range(height):
        f, line = raw[i], bytearray(raw[i + 1:i + 1 + stride])
        i += 1 + stride
        for x in range(stride):
            a = line[x - channels] if x >= channels else 0
            b, c = prev[x], (prev[x - channels] if x >= channels else 0)
            line[x] = (line[x] + (0, a, b, (a + b) // 2, _paeth(a, b, c))[f]) & 0xFF
        prev = line
        if channels == 3:
            out += line
        elif channels == 4:
            out += b"".join(bytes(line[k:k + 3]) for k in range(0, stride, 4))
        else:
            out += b"".join(bytes((v, v, v)) for v in line)
    return Image(width, height, out)


def to_ppm(img: Image) -> bytes:
    return f"P6 {img.width} {img.height} 255\n".encode() + bytes(img.pixels)
