#!/bin/bash
# step-12.sh: validates step 12 (DESIGN §12.5) on the Porto taxis: `gpstiles import --polyline 9 --skip 1` of all 1.7
# million trips prints DESIGN §13's counts; `build --mem 256M` sorts 83 million points in several runs (time and peak
# memory measured) to the same points `info` reports. Served: the count API for a box in central Porto = Python's slow
# count over the .pts, its export as many rows; the page in headless Chrome over the real base map at zoom 13 and 17
# (build/validate/step-12.png, step-12-street.png: trips on Porto's streets). The stage 3 report's tile speeds come from
# `gpstiles bench build/validate/porto.gpt`, run apart (about 3 minutes). SKIPPED without the data or Chrome.
set -u
. "$(dirname "$0")/lib.sh"
cd "$ROOT" || exit 1

if [ ! -f "$PORTO_DATA" ]; then
    echo "SKIPPED: no data/raw/porto/train.csv"
    exit 0
fi
if [ ! -x "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" ]; then
    echo "SKIPPED: no Google Chrome"
    exit 0
fi
make --no-print-directory -s all > /dev/null || fail "build failed"
porto_gpt
expected="rows=1710670 points=83409386 imported=83409386 skipped_zero=0 skipped_out_of_range=0 skipped_malformed=0"
[ "$PORTO_COUNTS" = "$expected" ] || fail "import printed '$PORTO_COUNTS', expected '$expected' (DESIGN §13)"
ok "import --polyline 9 of Porto's 1,710,670 trips → $PORTO_COUNTS (DESIGN §13)"

# The many-runs sort, measured: 83 million points with a 256 MiB sort buffer.
measure=$ROOT/build/validate/step-12-build.txt
/usr/bin/time -l build/gpstiles build --mem 256M --tmp "$ROOT/build/validate/runs" -o "$ROOT/build/validate/porto-again.gpt" \
    "$PORTO_PTS" > "$measure" 2>&1 || fail "build --mem 256M failed: $(tail -3 "$measure")"
cmp -s "$ROOT/build/validate/porto-again.gpt" "$PORTO_GPT" || fail "a second build differs from the first"
rm -f "$ROOT/build/validate/porto-again.gpt"
seconds=$(awk '$2 == "real" { print $1 }' "$measure")
peak=$(awk '/maximum resident set size/ { printf "%d", $1 / 1048576 }' "$measure")
[ -z "$(ls -A "$ROOT/build/validate/runs")" ] || fail "run files left in build/validate/runs"
[ "$peak" -lt 400 ] || fail "build --mem 256M peaked at $peak MiB"
ok "build --mem 256M: $(head -1 "$measure") in $seconds s, peak memory $peak MiB, the same file again, no run file left"
build/gpstiles info "$PORTO_GPT" | grep -qx 'points=83409386' || fail "info: $(build/gpstiles info "$PORTO_GPT")"

log=$ROOT/build/validate/step-12.log
build/gpstiles serve --port 0 "$PORTO_GPT" > "$log" 2>&1 &
server=$!
trap 'kill $server 2> /dev/null; wait $server 2> /dev/null' EXIT
for _ in $(seq 50); do
    port=$(sed -n 's|^gpstiles serve: http://127.0.0.1:\([0-9]*\)/$|\1|p' "$log")
    [ -n "$port" ] && break
    sleep 0.1
done
[ -n "$port" ] || fail "the server didn't say its port: $(cat "$log")"

python3 -I -B - "http://127.0.0.1:$port" "$PORTO_PTS" "$ROOT/tests" "$ROOT/build/validate" <<'PY' || fail "a Porto check failed (see above)"
import array, csv, io, json, sys, urllib.request
url, pts, tests, out = sys.argv[1:5]
sys.path[:0] = [f"{tests}/oracle", f"{tests}/e2e"]
import box_rules, browser, gpt_rules, osm_tile

# A box around Avenida dos Aliados: the API's count = the slow count over the codes of the smallest tile holding it.
bbox = "-8.6150,41.1470,-8.6080,41.1520"
box = box_rules.parse_bbox(bbox)
z = max(z for z in range(25) if osm_tile.tile(-8.6150, 41.1520, z) == osm_tile.tile(-8.6080, 41.1470, z))
_, tx, ty = map(int, osm_tile.tile(-8.6150, 41.1520, z).split("/"))
prefix, shift, slow = gpt_rules.code_of(tx, ty), 64 - 2 * z, 0
with open(pts, "rb") as f:
    while data := f.read(8 << 20):
        chunk = array.array("Q")
        chunk.frombytes(data)
        if sys.byteorder == "big":
            chunk.byteswap()
        slow += sum(1 for c in chunk if c >> shift == prefix and box_rules.inside(gpt_rules.x_of(c), gpt_rules.y_of(c), box))
with urllib.request.urlopen(f"{url}/api/datasets/porto/count?bbox={bbox}", timeout=60) as r:
    count = json.loads(r.read())["count"]
assert count == slow > 100000, (count, slow)
with urllib.request.urlopen(f"{url}/api/datasets/porto/export.csv?bbox={bbox}&limit=1000000", timeout=120) as r:
    rows = list(csv.reader(io.StringIO(r.read().decode())))
assert len(rows) - 1 == min(count, 1000000), (len(rows), count)
print(f"  ok  bbox={bbox} (Avenida dos Aliados): count {count:,} = Python's slow count · export {len(rows) - 1:,} rows")

LOADED = """(() => { const t = [...document.querySelectorAll("#map .heat-tile img")];
  return t.length > 0 && t.every((i) => i.complete && i.naturalWidth === 256); })()"""
BASE_LOADED = """(() => { const t = [...document.querySelectorAll("#map .base-dark img")];
  return t.length > 0 && t.every((i) => i.complete); })()"""
FADED_IN = """[...document.querySelectorAll("#map .leaflet-tile-loaded")].every((t) => getComputedStyle(t).opacity === "1")"""
with browser.Browser(1400, 860, internet=True) as chrome:
    text = lambda id: chrome.js(f"document.getElementById('{id}').textContent")
    for view, name in [("13/41.1550/-8.6250", "step-12.png"), ("17/41.1496/-8.6110", "step-12-street.png")]:
        chrome.open(f"{url}/#porto/{view}")
        chrome.wait(LOADED, timeout=60)
        chrome.wait(BASE_LOADED, timeout=30)
        chrome.wait(FADED_IN)
        zoom, lat, lon = view.split("/")
        base_tile = f"https://tile.openstreetmap.org/{osm_tile.tile(float(lon), float(lat), int(zoom))}.png"
        assert chrome.js(f"[...document.querySelectorAll('#map .base-dark img')].some((i) => i.src === '{base_tile}' && i.naturalWidth === 256)"), \
            f"the base map didn't load (no internet?): {base_tile}"
        assert text("points") == "83,409,386", text("points")
        chrome.screenshot(f"{out}/{name}")
        print(f"  ok  #porto/{view}: shows 83,409,386 points, {text('in-view')} in view, over the base map · build/validate/{name}")
    chrome.open(f"{url}/#porto")
    chrome.wait(LOADED, timeout=60)
    center = chrome.js("[map.getZoom(), map.getCenter().lat, map.getCenter().lng]")
    assert center[0] >= 12 and abs(center[1] - 41.17) < 0.1 and abs(center[2] + 8.62) < 0.1, center
    print(f"  ok  #porto opens on Porto: zoom {center[0]}, {center[1]:.3f}, {center[2]:.3f} (its GPS glitches out to 37° W are left out)")
    assert not chrome.problems(), chrome.problems()
PY

ok "screenshots for a person to check: build/validate/step-12.png (Porto), step-12-street.png (Avenida dos Aliados)"
