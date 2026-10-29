"""OpenStreetMap's tile formula (wiki.openstreetmap.org/wiki/Slippy_map_tilenames), written
independently of src/geo.c: the answer source for place → tile (TESTING.md §6).
The edge rules are DESIGN §9.4's: lon 180 wraps to tile 0, a lon just below 180 (where lon + 180
rounds up to 360) stays in the last column, and the south edge stays in the last row.
"""
import math


def tile(lon, lat, zoom):
    """Returns 'zoom/x/y' for a place in the valid range."""
    n = 2 ** zoom
    x = 0 if lon == 180.0 else min(int((lon + 180.0) / 360.0 * n), n - 1)
    y = int((1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * n)
    return f"{zoom}/{x}/{min(max(y, 0), n - 1)}"
