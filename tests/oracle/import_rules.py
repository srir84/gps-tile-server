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


# Polyline rows (step 12, --polyline C): column C, a CSV field that may be quoted, holds [[lon,lat],...].
MAX_POLYLINE_LINE = 1000000
_BLANK = rb"[ \t]*"
_NUMBER = rb"([-+]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][-+]?[0-9]+)?)"  # no overlapping parts: linear time
_PAIR = rb"\[" + _BLANK + _NUMBER + _BLANK + rb"," + _BLANK + _NUMBER + _BLANK + rb"\]"
_LIST = re.compile(_BLANK + rb"\[" + _BLANK + rb"(?:" + _PAIR + rb"(?:" + _BLANK + rb"," + _BLANK + _PAIR + rb")*"
                   + _BLANK + rb")?\]" + _BLANK)
_PAIRS = re.compile(_PAIR)


def csv_field(line, col, delim=b","):
    """Column `col` (1-based) of a line whose fields may be quoted ("..." with "" for a quote inside), without its
    quotes; None when the line has fewer columns, or a quote anywhere in it isn't closed or has text after it."""
    fields, i, n = [], 0, len(line)
    while True:
        if line[i:i + 1] == b'"':
            j = i + 1
            while True:
                q = line.find(b'"', j)
                if q < 0:
                    return None
                if line[q + 1:q + 2] == b'"':
                    j = q + 2
                    continue
                break
            fields.append(line[i + 1:q])
            i = q + 1
            if i < n and line[i:i + 1] != delim:
                return None
        else:
            d = line.find(delim, i)
            end = n if d < 0 else d
            fields.append(line[i:end])
            i = end
        if i >= n:
            return fields[col - 1] if len(fields) >= col else None
        i += 1


def pairs(text):
    """The [lon, lat] pairs of a whole list, or None when it isn't exactly one (a number has at most 63 characters)."""
    if not _LIST.fullmatch(text):
        return None
    found = [(a, b) for a, b in _PAIRS.findall(text)]
    if any(len(a) > 63 or len(b) > 63 for a, b in found):
        return None
    return [(float(a), float(b)) for a, b in found]


def polyline_files(paths, col, delim=b",", skip=0):
    """What `gpstiles import --polyline col` must print and write: (counts dict with points, list of codes)."""
    counts = dict(rows=0, points=0, imported=0, skipped_zero=0, skipped_out_of_range=0, skipped_malformed=0)
    codes = []
    for path in paths:
        with open(path, "rb") as f:
            lines = f.read().split(b"\n")
        if lines[-1] == b"":
            lines.pop()
        for line in lines[skip:]:
            too_long = len(line) > MAX_POLYLINE_LINE
            if line.endswith(b"\r"):
                line = line[:-1]
            if line == b"" and not too_long:
                continue
            counts["rows"] += 1
            field = None if too_long else csv_field(line, col, delim)
            found = None if field is None else pairs(field)
            if found is None:
                counts["skipped_malformed"] += 1
                continue
            for lon, lat in found:
                counts["points"] += 1
                if lon == 0.0 and lat == 0.0:
                    counts["skipped_zero"] += 1
                elif not (-180.0 <= lon <= 180.0 and -MAX_LAT <= lat <= MAX_LAT):
                    counts["skipped_out_of_range"] += 1
                else:
                    counts["imported"] += 1
                    codes.append(code(lon, lat))
    return counts, codes


def polyline_counts_line(counts):
    """The line `gpstiles import --polyline` prints."""
    return " ".join(f"{name}={counts[name]}" for name in
                    ["rows", "points", "imported", "skipped_zero", "skipped_out_of_range", "skipped_malformed"])
