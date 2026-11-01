#!/bin/bash
# step-11.sh: validates step 11 (DESIGN §12.4) on the USGS earthquakes, points over the whole world: the import prints
# DESIGN §13's counts, and the 4 zoom-1 tiles all hold points and add up. Served with GeoLife: the count API for a box
# across the 180° line (two boxes, Fiji and Tonga) and one around Japan = Python's slow counts; on the page (headless
# Chrome) a box drawn across the 180° line is counted as its two halves, added up = Python's count; the world map over
# the base map (build/validate/step-11.png, the Pacific's Ring of Fire); and the opening views of DESIGN §9.3's rule
# (5 % from each end, the developer's choice B): GeoLife opens on eastern China at zoom 6, not on half the world.
# Then `gpstiles bench` for both datasets: the stage 2 report's speeds. SKIPPED without the data or Chrome.
set -u
. "$(dirname "$0")/lib.sh"
cd "$ROOT" || exit 1

if [ ! -f "$USGS_DATA/MANIFEST.txt" ] || [ ! -d "$GEOLIFE_DATA" ]; then
    echo "SKIPPED: no USGS files (tools/fetch-usgs.py data/raw/usgs) or no GeoLife files"
    exit 0
fi
if [ ! -x "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" ]; then
    echo "SKIPPED: no Google Chrome"
    exit 0
fi
make --no-print-directory -s all > /dev/null || fail "build failed"
usgs_gpt
geolife_gpt
# DESIGN §13's line is the 2026-11-01 download's (known by its files' SHA-256s); any download must equal awk.
expected=$(cd "$USGS_DATA" && LC_ALL=C awk -v LON=3 -v LAT=2 -v SKIP=1 -f "$ROOT/tests/data/row_counts.awk" usgs-*.csv)
[ "$USGS_COUNTS" = "$expected" ] || fail "import printed '$USGS_COUNTS', awk '$expected'"
snapshot=$(cd "$USGS_DATA" && shasum -a 256 usgs-*.csv | shasum -a 256 | cut -c1-64)  # the files, by content
if [ "$snapshot" = 2adc72f5357478301bec95b69b1ebb731f05fe23d92f58a6f518aa082d91e375 ]; then
    [ "$USGS_COUNTS" = "rows=4771181 imported=4770607 skipped_zero=9 skipped_out_of_range=565 skipped_malformed=0" ] ||
        fail "the 2026-11-01 download imported as '$USGS_COUNTS', not DESIGN §13's line"
    ok "import of the 58 USGS files → $USGS_COUNTS (= awk = DESIGN §13)"
else
    ok "import of the USGS files → $USGS_COUNTS (= awk; not DESIGN §13's download)"
fi
sum=0
for x in 0 1; do
    for y in 0 1; do
        n=$(build/gpstiles count "$USGS_GPT" 1 $x $y | sed 's/^points=//')
        [ "$n" -gt 0 ] || fail "no quake in the zoom-1 tile 1/$x/$y"
        sum=$((sum + n))
    done
done
points=$(echo "$USGS_COUNTS" | sed 's/.*imported=\([0-9]*\).*/\1/')
[ "$sum" = "$points" ] || fail "the 4 zoom-1 tiles hold $sum points, not $points"
ok "the 4 quarters of the world (zoom-1 tiles) all hold quakes and add up to $points"

log=$ROOT/build/validate/step-11.log
build/gpstiles serve --port 0 "$USGS_GPT" "$GEOLIFE_GPT" > "$log" 2>&1 &
server=$!
trap 'kill $server 2> /dev/null; wait $server 2> /dev/null' EXIT
for _ in $(seq 50); do
    port=$(sed -n 's|^gpstiles serve: http://127.0.0.1:\([0-9]*\)/$|\1|p' "$log")
    [ -n "$port" ] && break
    sleep 0.1
done
[ -n "$port" ] || fail "the server didn't say its port: $(cat "$log")"

python3 -I -B - "http://127.0.0.1:$port" "$USGS_PTS" "$ROOT/tests" "$ROOT/build/validate" <<'PY' || fail "a worldwide check failed (see above)"
import array, json, sys, urllib.parse, urllib.request
url, pts, tests, out = sys.argv[1:5]
sys.path[:0] = [f"{tests}/oracle", f"{tests}/e2e"]
import box_rules, browser, gpt_rules, osm_tile

codes = array.array("Q")
codes.frombytes(open(pts, "rb").read())
if sys.byteorder == "big":
    codes.byteswap()

def slow(bbox):
    """Python's count of the quakes in a box: every code is looked at."""
    box = box_rules.parse_bbox(bbox)
    return sum(1 for c in codes if box_rules.inside(gpt_rules.x_of(c), gpt_rules.y_of(c), box))

def api(bbox):
    with urllib.request.urlopen(f"{url}/api/datasets/earthquakes/count?bbox={bbox}", timeout=60) as r:
        return json.loads(r.read())["count"]

# Fiji and Tonga: a box from 170° E across the 180° line to 170° W is two boxes for the API.
halves = ["170,-30,180,-10", "-180,-30,-170,-10"]
got, want = [api(b) for b in halves], [slow(b) for b in halves]
assert got == want and min(got) > 1000, (got, want)
japan = "128,30,146,46"
assert api(japan) == slow(japan) > 10000, (api(japan), slow(japan))
print(f"  ok  across the 180° line: {got[0]:,} quakes west of it + {got[1]:,} east of it = Python's slow counts ·"
      f" Japan ({japan}): {api(japan):,} = Python")

LOADED = """(() => { const t = [...document.querySelectorAll("#map .heat-tile img")];
  return t.length > 0 && t.every((i) => i.complete && i.naturalWidth === 256); })()"""
BASE_LOADED = """(() => { const t = [...document.querySelectorAll("#map .base-dark img")];
  return t.length > 0 && t.every((i) => i.complete); })()"""
FADED_IN = """[...document.querySelectorAll("#map .leaflet-tile-loaded")].every((t) => getComputedStyle(t).opacity === "1")"""
ASKED = "performance.getEntriesByType('resource').map((e) => e.name).filter((n) => n.includes('/count?'))"
with browser.Browser(1400, 860, internet=True) as chrome:
    text = lambda id: chrome.js(f"document.getElementById('{id}').textContent")
    # A box drawn across the 180° line, around Fiji and Tonga.
    chrome.open(f"{url}/#earthquakes/4/-20.0000/180.0000")
    chrome.wait(LOADED, timeout=60)
    before = len(chrome.js(ASKED))
    chrome.click("#box-tool")
    chrome.drag((560, 330), (840, 530))
    chrome.wait("/^[0-9,]+ points?$/.test(document.getElementById('box-count').textContent)", timeout=60)
    shown = int(text("box-count").split()[0].replace(",", ""))
    # The page asks for both halves at once, so they may come back in either order.
    boxes = sorted((urllib.parse.unquote(n.split("bbox=")[1]) for n in chrome.js(ASKED)[before:] if "180.000000000" in n),
                   key=lambda b: b.startswith("-180"))
    assert len(boxes) == 2 and boxes[0].split(",")[2] == "180.000000000" and boxes[1].split(",")[0] == "-180.000000000", boxes
    assert shown == sum(slow(b) for b in boxes) > 1000 and "across the 180° line" in text("box-text"), (shown, boxes, text("box-text"))
    print(f"  ok  page: a box drawn across the 180° line is counted as {boxes[0]} + {boxes[1]}: {shown:,} quakes = Python's slow counts")

    # The world, centered on the Pacific, over the real base map.
    chrome.open(f"{url}/#earthquakes/2/15.0000/-170.0000")
    chrome.wait(LOADED, timeout=60)
    chrome.wait(BASE_LOADED, timeout=30)
    chrome.wait(FADED_IN)
    base_tile = f"https://tile.openstreetmap.org/{osm_tile.tile(-170.0, 15.0, 2)}.png"
    assert chrome.js(f"[...document.querySelectorAll('#map .base-dark img')].some((i) => i.src === '{base_tile}' && i.naturalWidth === 256)"), \
        f"the base map didn't load (no internet?): {base_tile}"
    chrome.screenshot(f"{out}/step-11.png")
    print(f"  ok  #earthquakes/2/15.0000/-170.0000: {text('points')} quakes, the world map over the base map · build/validate/step-11.png")

    # Opening views (no view in the address): DESIGN §9.3's 5 % rule.
    for dataset, zoom in [("geolife", 6), ("earthquakes", 2)]:
        chrome.open(f"{url}/#{dataset}")
        chrome.wait(LOADED, timeout=60)
        z, center = chrome.js("map.getZoom()"), chrome.js("[map.getCenter().lat, map.getCenter().lng]")
        assert z == zoom, (dataset, z, center)
        if dataset == "geolife":  # eastern China, not half the world
            assert 30 < center[0] < 41 and 108 < center[1] < 118, (dataset, z, center)
        print(f"  ok  #{dataset} opens at zoom {z}, centered on {center[0]:.2f}, {center[1]:.2f}")
    chrome.screenshot(f"{out}/step-11-open.png")
    assert not chrome.problems(), chrome.problems()
PY

for gpt in "$GEOLIFE_GPT" "$USGS_GPT"; do
    name=$(basename "$gpt" .gpt)
    build/gpstiles bench "$gpt" > "$ROOT/build/validate/step-11-bench-$name.txt" || fail "bench $name failed"
    ok "bench $name: zoom 0, 5, 10, 15, 18 p50/p99 (ms): $(awk '$1 ~ /^(0|5|10|15|18)$/ { printf "%s:%s/%s ", $1, $4, $5 }' "$ROOT/build/validate/step-11-bench-$name.txt")"
done
ok "screenshots for a person to check: build/validate/step-11.png (the Ring of Fire), step-11-open.png"
