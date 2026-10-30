"""DESIGN §8's row rules written again in Python, independently of src/import.c: the answer
source for import counts and codes (TESTING.md §6). Slow but simple: bytes in, counts and codes out.
"""
import math
import re

MAX_LAT = 85.05112877980659
MAX_LINE = 65536  # bytes before the '\n'; longer lines are malformed
NUMBER = re.compile(rb"[-+]?([0-9]+\.?[0-9]*|\.[0-9]+)([eE][-+]?[0-9]+)?")
WORLD = 2 ** 32


def _spread_table():
    """SPREAD[v] = the 16 bits of v with a 0 after each, built bit by bit."""
    table = []
    for v in range(1 << 16):
        table.append(sum(((v >> i) & 1) << (2 * i) for i in range(16)))
    return table


SPREAD = _spread_table()


def code(lon, lat):
    """Z-order code of a valid place (DESIGN §9.4): x in the even bits, y in the odd bits."""
    x = 0 if lon == 180.0 else min(math.floor((lon + 180.0) / 360.0 * WORLD), WORLD - 1)
    y = math.floor((1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * WORLD)
    y = min(max(y, 0), WORLD - 1)

    def spread(v):
        return SPREAD[v & 0xFFFF] | (SPREAD[v >> 16] << 32)

    return spread(x) | (spread(y) << 1)


def classify(line, lon_col, lat_col, delim=b","):
    """One line without its '\\n' → ('blank' | 'point' | 'zero' | 'out_of_range' | 'malformed', code or None)."""
    if len(line) > MAX_LINE:
        return "malformed", None
    if line.endswith(b"\r"):
        line = line[:-1]
    if line == b"":
        return "blank", None
    fields = line.split(delim)
    if len(fields) < max(lon_col, lat_col):
        return "malformed", None
    lon_text, lat_text = fields[lon_col - 1], fields[lat_col - 1]
    if not NUMBER.fullmatch(lon_text) or not NUMBER.fullmatch(lat_text):
        return "malformed", None
    lon, lat = float(lon_text), float(lat_text)  # "1e999" → inf, which is out of range below
    if lon == 0.0 and lat == 0.0:
        return "zero", None
    if not (-180.0 <= lon <= 180.0 and -MAX_LAT <= lat <= MAX_LAT):
        return "out_of_range", None
    return "point", code(lon, lat)


def import_files(paths, lon_col, lat_col, delim=b",", skip=0):
    """What `gpstiles import` must print and write: (counts dict, list of codes in file order)."""
    counts = dict(rows=0, imported=0, skipped_zero=0, skipped_out_of_range=0, skipped_malformed=0)
    codes = []
    for path in paths:
        with open(path, "rb") as f:
            lines = f.read().split(b"\n")
        if lines[-1] == b"":  # text after the last '\n' is a line only if it isn't empty
            lines.pop()
        for line in lines[skip:]:
            kind, point = classify(line, lon_col, lat_col, delim)
            if kind == "blank":
                continue
            counts["rows"] += 1
            if kind == "point":
                counts["imported"] += 1
                codes.append(point)
            else:
                counts["skipped_" + kind] += 1
    return counts, codes


def counts_line(counts):
    """The line `gpstiles import` prints."""
    return " ".join(f"{name}={counts[name]}" for name in
                    ["rows", "imported", "skipped_zero", "skipped_out_of_range", "skipped_malformed"])
