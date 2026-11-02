#!/bin/bash
# step-16.sh: validates step 16 (DESIGN §12.7) on OpenStreetMap's public GPS traces of 2013: the whole 22 GB dump
# streamed through xz and tar into `gpstiles import --gpx`. Its track points (rows) = tests/data/osm_count.py's count of
# the dump (Python, file by file: DESIGN §13), which is metadata.xml's sum of `points` (OpenStreetMap's own count) plus
# 99 files that hold more track points than it lists; the counts = DESIGN §13. Built with the default --mem (several
# runs); `info`, the 4 zoom-1 tiles and a tile and its 4 smaller tiles add up; the page over the base map, the world
# (build/validate/step-16.png); `gpstiles bench` (warm): p99 under 100 ms at every zoom. The import and build are kept in
# build/validate/ while nothing changes (about an hour when they must be redone). SKIPPED without the dump.
set -u
. "$(dirname "$0")/lib.sh"
cd "$ROOT" || exit 1

if [ ! -f "$OSM_DUMP" ] || [ ! -f "$ROOT/data/raw/osm-gps/metadata.xml" ]; then
    echo "SKIPPED: no data/raw/osm-gps/gpx-planet-2013-04-09.tar.xz or its metadata.xml"
    exit 0
fi
make --no-print-directory -s all > /dev/null || fail "build failed"
osm_gpt
listed=$(python3 -I -c '
import re, sys
print(sum(int(m) for m in re.findall(rb"<gpxFile [^>]*?points=\"(\d+)\"", open(sys.argv[1], "rb").read())))' \
    "$ROOT/data/raw/osm-gps/metadata.xml") || fail "can't read metadata.xml"
[ "$listed" = 2674972244 ] || fail "metadata.xml lists $listed points, not DESIGN §13's 2,674,972,244"
expected="rows=2676451044 imported=2675901374 skipped_zero=546151 skipped_out_of_range=3519 skipped_malformed=0"
[ "$OSM_COUNTS" = "$expected" ] || fail "import printed '$OSM_COUNTS', expected '$expected' (DESIGN §13)"
ok "import --gpx of the whole dump → $OSM_COUNTS (rows = tests/data/osm_count.py's 2,676,451,044 = metadata.xml's $listed + 1,478,800 in 99 files that hold more than it lists, DESIGN §13)"
runs=${OSM_BUILD##*runs=}
[ "$runs" -gt 1 ] || fail "the build made one run: $OSM_BUILD"
ok "build: $OSM_BUILD"

points=$(echo "$OSM_COUNTS" | sed 's/.*imported=\([0-9]*\).*/\1/')
sum=0
for x in 0 1; do
    for y in 0 1; do
        sum=$((sum + $(build/gpstiles count "$OSM_GPT" 1 $x $y | sed 's/^points=//')))
    done
done
[ "$sum" = "$points" ] && [ "$(build/gpstiles count "$OSM_GPT" 0 0 0 | sed 's/^points=//')" = "$points" ] ||
    fail "the 4 zoom-1 tiles hold $sum points, not $points"
tile=$(build/gpstiles where 13.40 52.52 --zoom 8) # Berlin
z=${tile%%/*}; rest=${tile#*/}; x=${rest%%/*}; y=${rest#*/}
parent=$(build/gpstiles count "$OSM_GPT" "$z" "$x" "$y" | sed 's/^points=//')
kids=0
for dx in 0 1; do
    for dy in 0 1; do
        kids=$((kids + $(build/gpstiles count "$OSM_GPT" $((z + 1)) $((2 * x + dx)) $((2 * y + dy)) | sed 's/^points=//')))
    done
done
[ "$parent" = "$kids" ] && [ "$parent" -gt 1000000 ] || fail "tile $tile holds $parent points, its 4 smaller tiles $kids"
ok "the 4 zoom-1 tiles add up to $points · tile $tile (Berlin) = $parent = its 4 smaller tiles"

log=$ROOT/build/validate/step-16.log
build/gpstiles serve --port 0 "$OSM_GPT" > "$log" 2>&1 &
server=$!
trap 'kill $server 2> /dev/null; wait $server 2> /dev/null' EXIT
for _ in $(seq 50); do
    port=$(sed -n 's|^gpstiles serve: http://127.0.0.1:\([0-9]*\)/$|\1|p' "$log")
    [ -n "$port" ] && break
    sleep 0.1
done
[ -n "$port" ] || fail "the server didn't say its port: $(cat "$log")"
if [ ! -x "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" ]; then
    echo "  SKIPPED (the page): no Google Chrome"
else
python3 -I -B - "http://127.0.0.1:$port" "$ROOT/tests" "$ROOT/build/validate" "$points" <<'PY' || fail "a page check failed (see above)"
import sys
url, tests, out, points = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])
sys.path[:0] = [f"{tests}/oracle", f"{tests}/e2e"]
import browser, osm_tile
LOADED = """(() => { const t = [...document.querySelectorAll("#map .heat-tile img")];
  return t.length > 0 && t.every((i) => i.complete && i.naturalWidth === 256); })()"""
BASE_LOADED = """(() => { const t = [...document.querySelectorAll("#map .base-dark img")];
  return t.length > 0 && t.every((i) => i.complete); })()"""
FADED_IN = """[...document.querySelectorAll("#map .leaflet-tile-loaded")].every((t) => getComputedStyle(t).opacity === "1")"""
with browser.Browser(1400, 860, internet=True) as chrome:
    text = lambda id: chrome.js(f"document.getElementById('{id}').textContent")
    chrome.open(f"{url}/#osm-gps/2/30.0000/10.0000")
    chrome.wait(LOADED, timeout=120)
    chrome.wait(BASE_LOADED, timeout=30)
    chrome.wait(FADED_IN)
    base_tile = f"https://tile.openstreetmap.org/{osm_tile.tile(10.0, 30.0, 2)}.png"
    assert chrome.js(f"[...document.querySelectorAll('#map .base-dark img')].some((i) => i.src === '{base_tile}' && i.naturalWidth === 256)"), \
        f"the base map didn't load (no internet?): {base_tile}"
    assert text("points") == f"{points:,}", text("points")
    chrome.screenshot(f"{out}/step-16.png")
    print(f"  ok  #osm-gps/2/30.0000/10.0000: shows {points:,} points, {text('in-view')} in view, over the base map · build/validate/step-16.png")
    assert not chrome.problems(), chrome.problems()
PY
fi

cat "$OSM_GPT" > /dev/null # warm: in the disk cache, as step 15
bench=$ROOT/build/validate/step-16-bench.txt
build/gpstiles bench "$OSM_GPT" > "$bench" || fail "bench failed"
[ "$(awk '$1 ~ /^[0-9]+$/' "$bench" | wc -l | tr -d ' ')" = 25 ] || fail "bench printed no row a zoom"
worst=$(awk '$1 ~ /^[0-9]+$/ { if ($5 > w) w = $5 } END { print w }' "$bench")
awk -v w="$worst" 'BEGIN { exit !(w < 100) }' || fail "the worst p99 is $worst ms"
ok "bench osm-gps ($points points, warm disk cache): zoom 0, 5, 10, 15, 20 p50/p99 (ms): $(awk '$1 ~ /^(0|5|10|15|20)$/ { printf "%s:%s/%s ", $1, $4, $5 }' "$bench")· worst p99 at any zoom: $worst ms"
