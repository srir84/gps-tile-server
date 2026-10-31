"""DESIGN §9.2's box rule in plain Python, written apart from src/area.c: bbox text → world units, and the
slow count that looks at every point. The answer source for box counts, hover counts and exports."""
import math
import re

MAX_LAT = 85.05112877980659
WORLD = 2 ** 32
NUMBER = re.compile(r"[-+]?([0-9]+\.?[0-9]*|\.[0-9]+)([eE][-+]?[0-9]+)?")


def world_x(lon):
    """x of a box edge (§9.4's formula). Longitude 180 is the world's east edge, the last unit, as a box
    edge on either side. (A point imported at 180 is stored at x = 0, with -180.)"""
    if lon == 180.0:
        return WORLD - 1
    return min(math.floor((lon + 180.0) / 360.0 * WORLD), WORLD - 1)


def world_y(lat):
    y = math.floor((1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * WORLD)
    return min(max(y, 0), WORLD - 1)


def parse_bbox(text):
    """'w,s,e,n' → (x0, y0, x1, y1), or None if the API must refuse it (400). Limits: the bbox text at most
    127 characters (after %XX decoding), each number at most 63."""
    parts = text.split(",")
    if len(text) > 127 or len(parts) != 4 or not all(NUMBER.fullmatch(p) and len(p) < 64 for p in parts):
        return None
    w, s, e, n = map(float, parts)
    if not (-180 <= w <= 180 and -180 <= e <= 180 and -MAX_LAT <= s <= MAX_LAT and -MAX_LAT <= n <= MAX_LAT):
        return None
    if w > e or s > n:
        return None
    return world_x(w), world_y(n), world_x(e), world_y(s)


def inside(x, y, box):
    x0, y0, x1, y1 = box
    return x0 <= x <= x1 and y0 <= y <= y1


def slow_count(points, box):
    """points: (x, y) pairs. Every point is looked at."""
    return sum(1 for x, y in points if inside(x, y, box))


def lon_of_x(x):
    return x / WORLD * 360.0 - 180.0


def lat_of_y(y):
    return math.degrees(math.atan(math.sinh(math.pi * (1.0 - 2.0 * y / WORLD))))
