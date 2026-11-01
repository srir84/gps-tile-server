#!/bin/bash
# step-10.sh: validates step 10 (DESIGN §12.4) on GeoLife: `gpstiles import --lat-col 1 --lon-col 2 --skip 6` on all
# 18,670 .plt files prints DESIGN §13's counts, `info` holds every point and Beijing's zoom-6 tile = its 4 zoom-7
# tiles added up. Served: the tile at Microsoft Research Asia holds the points Python counts in its slice of the .pts,
# the count API for a box there = Python's slow count, and its CSV export has as many rows, each inside the box. Then
# the page in headless Chrome lists geolife with its point count, over the real base map: build/validate/step-10.png
# (Beijing inside the 5th ring road, to compare with Figure 1 of the user guide, data/raw/geolife/Geolife
# Trajectories 1.3/User Guide-1.3.pdf) and step-10-street.png (zoom 16 at Zhongguancun). SKIPPED without GeoLife
# or Chrome.
set -u
. "$(dirname "$0")/lib.sh"
cd "$ROOT" || exit 1

if [ ! -d "$GEOLIFE_DATA" ]; then
    echo "SKIPPED: no GeoLife files in data/raw/geolife"
    exit 0
fi
if [ ! -x "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" ]; then
    echo "SKIPPED: no Google Chrome"
    exit 0
fi
make --no-print-directory -s all > /dev/null || fail "build failed"
geolife_gpt
expected="rows=24876978 imported=24876977 skipped_zero=0 skipped_out_of_range=1 skipped_malformed=0"
[ "$GEOLIFE_COUNTS" = "$expected" ] || fail "import printed '$GEOLIFE_COUNTS', expected '$expected' (DESIGN §13)"
ok "import of the 18,670 .plt files → $GEOLIFE_COUNTS (DESIGN §13)"

info=$(build/gpstiles info "$GEOLIFE_GPT") || fail "info failed"
echo "$info" | grep -qx 'points=24876977' || fail "info: $info"
parent=$(build/gpstiles count "$GEOLIFE_GPT" 6 52 24 | sed 's/^points=//')
sum=0
for x in 104 105; do
    for y in 48 49; do
        n=$(build/gpstiles count "$GEOLIFE_GPT" 7 $x $y | sed 's/^points=//')
        sum=$((sum + n))
    done
done
[ "$parent" = "$sum" ] && [ "$parent" -gt 20000000 ] || fail "count 6/52/24 = $parent, its 4 zoom-7 tiles add up to $sum"
ok "info: points=24876977 · count 6/52/24 (Beijing) = $parent = its 4 zoom-7 tiles added up"

log=$ROOT/build/validate/step-10.log
build/gpstiles serve --port 0 "$GEOLIFE_GPT" > "$log" 2>&1 &
server=$!
trap 'kill $server 2> /dev/null; wait $server 2> /dev/null' EXIT
for _ in $(seq 50); do
    port=$(sed -n 's|^gpstiles serve: http://127.0.0.1:\([0-9]*\)/$|\1|p' "$log")
    [ -n "$port" ] && break
    sleep 0.1
done
[ -n "$port" ] || fail "the server didn't say its port: $(cat "$log")"

python3 -I -B - "http://127.0.0.1:$port" "$GEOLIFE_PTS" "$ROOT/tests" "$ROOT/build/validate" <<'PY' || fail "a GeoLife check failed (see above)"
import array, csv, io, json, sys, urllib.request
url, pts, tests, out = sys.argv[1:5]
sys.path[:0] = [f"{tests}/oracle", f"{tests}/e2e"]
import box_rules, browser, gpt_rules, osm_tile

def codes_with(prefix, shift):
    """The .pts codes whose top bits are `prefix` (the slice of one tile), read a chunk at a time."""
    found = []
    with open(pts, "rb") as f:
        while data := f.read(8 << 20):
            chunk = array.array("Q")
            chunk.frombytes(data)
            if sys.byteorder == "big":
                chunk.byteswap()
            found += [c for c in chunk if c >> shift == prefix]
    return found

# The zoom-11 tile at Microsoft Research Asia, Zhongguancun (the densest in GeoLife): its X-Points header.
z, x, y = map(int, osm_tile.tile(116.3100, 39.9800, 11).split("/"))
with urllib.request.urlopen(f"{url}/tiles/geolife/{z}/{x}/{y}.png", timeout=60) as r:
    shown = int(r.headers["X-Points"])
slow = len(codes_with(gpt_rules.code_of(x, y), 64 - 2 * z))
assert shown == slow and shown > 5000000, (shown, slow)
print(f"  ok  tile {z}/{x}/{y} (Microsoft Research Asia) holds {shown:,} points = Python's count of its slice of the .pts")

# A box at the lab: the count API = the slow count over the codes of the zoom-13 tile holding the whole box.
bbox = "116.3060,39.9790,116.3100,39.9820"
box = box_rules.parse_bbox(bbox)
z13 = [osm_tile.tile(lon, lat, 13) for lon, lat in [(116.3060, 39.9820), (116.3100, 39.9790)]]
assert z13[0] == z13[1], z13
_, tx, ty = map(int, z13[0].split("/"))
near = codes_with(gpt_rules.code_of(tx, ty), 64 - 26)
want = box_rules.slow_count(((gpt_rules.x_of(c), gpt_rules.y_of(c)) for c in near), box)
with urllib.request.urlopen(f"{url}/api/datasets/geolife/count?bbox={bbox}", timeout=60) as r:
    count = json.loads(r.read())["count"]
assert count == want and count > 10000, (count, want)
with urllib.request.urlopen(f"{url}/api/datasets/geolife/export.csv?bbox={bbox}&limit={count}", timeout=120) as r:
    rows = list(csv.reader(io.StringIO(r.read().decode())))
w, s, e, n = map(float, bbox.split(","))
assert rows[0] == ["lon", "lat"] and len(rows) - 1 == count, (rows[:2], len(rows))
assert all(w <= float(lon) <= e and s <= float(lat) <= n for lon, lat in rows[1:])
print(f"  ok  bbox={bbox}: count {count:,} = Python's slow count · export.csv: {count:,} rows, each inside the box")

LOADED = """(() => { const t = [...document.querySelectorAll("#map .heat-tile img")];
  return t.length > 0 && t.every((i) => i.complete && i.naturalWidth === 256); })()"""
BASE_LOADED = """(() => { const t = [...document.querySelectorAll("#map .base-dark img")];
  return t.length > 0 && t.every((i) => i.complete); })()"""
BASE_SHOWN = """[...document.querySelectorAll("#map .base-dark img")].filter((i) => i.naturalWidth === 256).length"""
FADED_IN = """[...document.querySelectorAll("#map .leaflet-tile-loaded")].every((t) => getComputedStyle(t).opacity === "1")"""
with browser.Browser(1400, 860, internet=True) as chrome:
    text = lambda id: chrome.js(f"document.getElementById('{id}').textContent")
    for view, name in [("11/39.9100/116.3800", "step-10.png"), ("16/39.9800/116.3100", "step-10-street.png")]:
        chrome.open(f"{url}/#geolife/{view}")
        chrome.wait(LOADED, timeout=60)
        chrome.wait(BASE_LOADED, timeout=30)
        chrome.wait(FADED_IN)
        assert text("points") == "24,876,977" and text("file") == "geolife.gpt", (text("points"), text("file"))
        # A failed image is "complete" too: the streets are there only if the base tile under the center decoded.
        zoom, lat, lon = view.split("/")
        base_tile = f"https://tile.openstreetmap.org/{osm_tile.tile(float(lon), float(lat), int(zoom))}.png"
        assert chrome.js(f"[...document.querySelectorAll('#map .base-dark img')].some((i) => i.src === '{base_tile}' && i.naturalWidth === 256)"), \
            f"the base map didn't load (no internet?): {base_tile}, {chrome.js(BASE_SHOWN)} base tiles shown"
        chrome.screenshot(f"{out}/{name}")
        print(f"  ok  #geolife/{view}: shows 24,876,977 points (DESIGN §13), {text('in-view')} in view, over"
              f" {chrome.js(BASE_SHOWN)} base map tiles ({base_tile} among them) · build/validate/{name}")
    assert not chrome.problems(), chrome.problems()
PY
ok "screenshots for a person to check: build/validate/step-10.png (compare with the user guide's Figure 1), step-10-street.png"
