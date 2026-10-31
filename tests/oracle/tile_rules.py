"""A map tile in plain Python (DESIGN §5.5), written apart from src/render.c: points counted per pixel
from x and y taken out of each code, the log color scale from its written rule, and a PNG decoder
(chunks, CRCs, zlib, row filters). Used by tests/e2e/test_render.py and the server tests."""
import math
import struct
import zlib

SIDE = 256
# The color rule (render.h): t = ln(count) / ln(max), 1 if max <= 1, at most 1; 5 stops evenly spaced,
# each channel interpolated and rounded half up.
STOPS = [(0x8c, 0x29, 0x81), (0xb7, 0x37, 0x79), (0xde, 0x49, 0x68), (0xfe, 0x9f, 0x6d), (0xfc, 0xfd, 0xbf)]


def pixel_counts(codes, zoom, x, y, x_of, y_of):
    """{(px, py): points} for tile zoom/x/y: px, py = the 8 bits of world x, y below the tile's own bits."""
    counts = {}
    for code in codes:
        wx, wy = x_of(code), y_of(code)
        if wx >> (32 - zoom) == x and wy >> (32 - zoom) == y:
            pixel = ((wx >> (24 - zoom)) & 255, (wy >> (24 - zoom)) & 255)
            counts[pixel] = counts.get(pixel, 0) + 1
    return counts


def color(count, max_count):
    """(r, g, b, a) of a pixel with `count` points when the densest pixel at its zoom has max_count."""
    if count == 0:
        return (0, 0, 0, 0)
    t = 1.0 if max_count <= 1 else min(math.log(count) / math.log(max_count), 1.0)
    position = t * 4
    stop = min(int(position), 3)
    f = position - stop
    low, high = STOPS[stop], STOPS[stop + 1]
    return tuple(int(a + (b - a) * f + 0.5) for a, b in zip(low, high)) + (255,)  # halves round up


def decode_png(data):
    """(width, height, rows of (r, g, b, a) tuples) of an 8-bit RGBA PNG. Raises ValueError if it isn't one,
    if a CRC is wrong or a chunk is cut short."""
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("no PNG signature")
    position, chunks = 8, []
    while position < len(data):
        if position + 12 > len(data):
            raise ValueError("chunk cut short")
        length, kind = struct.unpack(">I4s", data[position:position + 8])
        body = data[position + 8:position + 8 + length]
        crc = struct.unpack(">I", data[position + 8 + length:position + 12 + length])[0]
        if len(body) != length or zlib.crc32(kind + body) != crc:
            raise ValueError(f"bad {kind!r} chunk")
        chunks.append((kind, body))
        position += 12 + length
    if not chunks or chunks[0][0] != b"IHDR" or chunks[-1][0] != b"IEND":
        raise ValueError("IHDR must come first and IEND last")
    width, height, depth, kind, compression, filtering, interlace = struct.unpack(">IIBBBBB", chunks[0][1])
    if (depth, kind, compression, filtering, interlace) != (8, 6, 0, 0, 0):
        raise ValueError("not an 8-bit RGBA PNG")
    raw = zlib.decompress(b"".join(body for kind, body in chunks if kind == b"IDAT"))
    stride = 4 * width
    if len(raw) != height * (1 + stride):
        raise ValueError("wrong amount of image data")
    rows, previous = [], bytearray(stride)
    for r in range(height):
        method, line = raw[r * (1 + stride)], bytearray(raw[r * (1 + stride) + 1:(r + 1) * (1 + stride)])
        for i in range(stride):
            left = line[i - 4] if i >= 4 else 0
            up, up_left = previous[i], previous[i - 4] if i >= 4 else 0
            if method == 1:
                line[i] = (line[i] + left) & 255
            elif method == 2:
                line[i] = (line[i] + up) & 255
            elif method == 3:
                line[i] = (line[i] + (left + up) // 2) & 255
            elif method == 4:
                p = left + up - up_left
                pa, pb, pc = abs(p - left), abs(p - up), abs(p - up_left)
                line[i] = (line[i] + (left if pa <= pb and pa <= pc else up if pb <= pc else up_left)) & 255
            elif method != 0:
                raise ValueError(f"unknown row filter {method}")
        rows.append([tuple(line[i:i + 4]) for i in range(0, stride, 4)])
        previous = line
    return width, height, rows
