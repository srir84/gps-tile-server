"""The .gpt file in plain Python (DESIGN §5.3, §9.3), written apart from src/build.c: points sorted
with sorted(), x and y taken out of a code with a table built bit by bit, the densest pixel found
with a Counter, the view box from the sorted x and y values. Used by tests/e2e/test_build.py and
tests/data/check_tdrive.py."""
import array
import collections
import itertools
import math
import operator
import struct
import sys

MAX_ZOOM = 24
# magic, version, header size, count, bounds (min x, min y, max x, max y), densest pixel per zoom, view box
HEADER = struct.Struct("<8sIIQ4I25Q4I")
assert HEADER.size == 256


def _even_bits_table():
    """EVEN[v] = the 8 even bits of the 16-bit value v, packed together."""
    table = []
    for v in range(1 << 16):
        packed = 0
        for i in range(8):
            packed |= ((v >> (2 * i)) & 1) << i
        table.append(packed)
    return table


EVEN = _even_bits_table()


def x_of(code):
    """World x: the even bits of the code (DESIGN §9.4)."""
    return (EVEN[code & 0xFFFF] | EVEN[(code >> 16) & 0xFFFF] << 8 | EVEN[(code >> 32) & 0xFFFF] << 16
            | EVEN[code >> 48] << 24)


def y_of(code):
    """World y: the odd bits of the code."""
    return x_of(code >> 1)


def code_of(x, y):
    """The Z-order code of world x, y, bit by bit: x in the even bits, y in the odd bits."""
    code = 0
    for i in range(32):
        code |= ((x >> i) & 1) << (2 * i) | ((y >> i) & 1) << (2 * i + 1)
    return code


def tile_of(code, zoom):
    """The tile (x, y) holding a code at a zoom: the top `zoom` bits of x and of y."""
    return x_of(code) >> (32 - zoom), y_of(code) >> (32 - zoom)


def lon_of_x(x):
    """Degrees at the west edge of world unit x."""
    return x / 2**32 * 360.0 - 180.0


def lat_of_y(y):
    """Degrees at the north edge of world unit y (inverse Web Mercator)."""
    return math.degrees(math.atan(math.sinh(math.pi * (1.0 - 2.0 * y / 2**32))))


def header(codes):
    """The header fields for a list of codes, as a dict. Every stat is 0 when there are no points."""
    n = len(codes)
    if n == 0:
        return dict(count=0, bounds=(0, 0, 0, 0), max_pixel=[0] * (MAX_ZOOM + 1), view=(0, 0, 0, 0))
    xs = sorted(map(x_of, codes))
    ys = sorted(map(y_of, codes))
    # A pixel at zoom z is 1/256 of a tile: a zoom z + 8 tile, the top 2(z + 8) bits of the code.
    max_pixel = [max(collections.Counter(map(operator.rshift, codes, itertools.repeat(48 - 2 * z))).values())
                 for z in range(MAX_ZOOM + 1)]
    cut = n // 20  # the middle 90%: drop 5% at each end, then widen to 65,536-unit buckets
    view = (xs[cut] & ~0xFFFF, ys[cut] & ~0xFFFF, xs[n - 1 - cut] | 0xFFFF, ys[n - 1 - cut] | 0xFFFF)
    return dict(count=n, bounds=(xs[0], ys[0], xs[-1], ys[-1]), max_pixel=max_pixel, view=view)


def encode_header(fields):
    return HEADER.pack(b"GPSTILE\0", 1, 256, fields["count"], *fields["bounds"], *fields["max_pixel"],
                       *fields["view"])


def parse_header(data):
    """The header of .gpt bytes as a dict like header() returns, plus magic, version and header_size."""
    v = HEADER.unpack_from(data)
    return dict(magic=v[0], version=v[1], header_size=v[2], count=v[3], bounds=tuple(v[4:8]),
                max_pixel=list(v[8:33]), view=tuple(v[33:37]))


def to_le_bytes(codes):
    a = array.array("Q", codes)
    if sys.byteorder == "big":
        a.byteswap()
    return a.tobytes()


def gpt_bytes(codes):
    """The whole expected .gpt file for these codes (in any order)."""
    ordered = sorted(codes)
    return encode_header(header(ordered)) + to_le_bytes(ordered)
