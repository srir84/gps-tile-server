#!/bin/bash
# step-15.sh: validates step 15 (DESIGN §12.6) on NOAA's AIS ship positions, January–May 2023: over a billion points.
# Each day streamed from its zip into `gpstiles import` (the counts added up = DESIGN §13's awk total), then all 151 .pts
# built into one .gpt with the default --mem (1 GiB, for 9.7 GB of points: several runs). `info`, the 4 zoom-1 tiles and
# a tile at the Port of Houston and its 4 smaller tiles add up; served: the page over the base map at the Gulf of Mexico
# (build/validate/step-15.png); `gpstiles bench`: p99 at every zoom under 100 ms at 1.2 billion points. The build is kept
# in build/validate/ while the zips and the program are the same (it takes about 20 minutes); a second build with a 2 GiB
# buffer must be the same file. SKIPPED without the data; only the page needs Chrome.
set -u
. "$(dirname "$0")/lib.sh"
cd "$ROOT" || exit 1

if ! ls "$AIS_DATA"/AIS_2023_*.zip > /dev/null 2>&1; then
    echo "SKIPPED: no AIS zips in data/raw/ais (tools/fetch-ais.sh)"
    exit 0
fi
make --no-print-directory -s all > /dev/null || fail "build failed"
ais_gpt
expected="rows=1216355904 imported=1216355854 skipped_zero=0 skipped_out_of_range=39 skipped_malformed=11"
[ "$AIS_COUNTS" = "$expected" ] || fail "the 151 days imported as '$AIS_COUNTS', expected '$expected' (DESIGN §13)"
ok "import of 151 days, added up → $AIS_COUNTS (DESIGN §13)"
runs=${AIS_BUILD##*runs=}
[ "$runs" -gt 1 ] || fail "9.7 GB of points sorted with a 1 GiB buffer in one run: $AIS_BUILD"
ok "build: $AIS_BUILD (out of core: 9.7 GB of points, a 1 GiB sort buffer)"
# The same 1.2 billion points sorted in other runs (a 2 GiB buffer): the same file. (One run would need 10 GB of memory;
# one run = many runs is checked on 25 million AIS points in make check-data.)
again=$ROOT/build/validate/ais-2023-2g.gpt
build/gpstiles build --mem 2G --tmp "$ROOT/build/validate" -o "$again" "$AIS_PTS_DIR"/AIS_2023_*.pts > "$again.txt" ||
    { rm -f "$again" "$again.txt"; fail "the 2 GiB build failed"; }
cmp -s "$again" "$AIS_GPT" || { rm -f "$again" "$again.txt"; fail "the 2 GiB build differs from the 1 GiB one"; }
ok "the same points with a 2 GiB buffer ($(cat "$again.txt")) = the 1 GiB build ($runs runs), byte for byte"
rm -f "$again" "$again.txt"

sum=0
for x in 0 1; do
    for y in 0 1; do
        sum=$((sum + $(build/gpstiles count "$AIS_GPT" 1 $x $y | sed 's/^points=//')))
    done
done
[ "$sum" = 1216355854 ] || fail "the 4 zoom-1 tiles hold $sum points"
tile=$(build/gpstiles where -95.0 29.73 --zoom 9)
z=${tile%%/*}; rest=${tile#*/}; x=${rest%%/*}; y=${rest#*/}
parent=$(build/gpstiles count "$AIS_GPT" "$z" "$x" "$y" | sed 's/^points=//')
kids=0
for dx in 0 1; do
    for dy in 0 1; do
        kids=$((kids + $(build/gpstiles count "$AIS_GPT" $((z + 1)) $((2 * x + dx)) $((2 * y + dy)) | sed 's/^points=//')))
    done
done
[ "$parent" = "$kids" ] && [ "$parent" -gt 1000000 ] || fail "tile $tile holds $parent points, its 4 smaller tiles $kids"
ok "the 4 zoom-1 tiles add up to 1,216,355,854 · tile $tile (Houston) = $parent = its 4 smaller tiles"

log=$ROOT/build/validate/step-15.log
build/gpstiles serve --port 0 "$AIS_GPT" > "$log" 2>&1 &
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
python3 -I -B - "http://127.0.0.1:$port" "$ROOT/tests" "$ROOT/build/validate" <<'PY' || fail "a page check failed (see above)"
import sys
url, tests, out = sys.argv[1:4]
sys.path[:0] = [f"{tests}/oracle", f"{tests}/e2e"]
import browser, osm_tile
LOADED = """(() => { const t = [...document.querySelectorAll("#map .heat-tile img")];
  return t.length > 0 && t.every((i) => i.complete && i.naturalWidth === 256); })()"""
BASE_LOADED = """(() => { const t = [...document.querySelectorAll("#map .base-dark img")];
  return t.length > 0 && t.every((i) => i.complete); })()"""
FADED_IN = """[...document.querySelectorAll("#map .leaflet-tile-loaded")].every((t) => getComputedStyle(t).opacity === "1")"""
with browser.Browser(1400, 860, internet=True) as chrome:
    text = lambda id: chrome.js(f"document.getElementById('{id}').textContent")
    chrome.open(f"{url}/#ais-2023/6/27.0000/-88.0000")
    chrome.wait(LOADED, timeout=120)
    chrome.wait(BASE_LOADED, timeout=30)
    chrome.wait(FADED_IN)
    base_tile = f"https://tile.openstreetmap.org/{osm_tile.tile(-88.0, 27.0, 6)}.png"
    assert chrome.js(f"[...document.querySelectorAll('#map .base-dark img')].some((i) => i.src === '{base_tile}' && i.naturalWidth === 256)"), \
        f"the base map didn't load (no internet?): {base_tile}"
    assert text("points") == "1,216,355,854", text("points")
    chrome.screenshot(f"{out}/step-15.png")
    print(f"  ok  #ais-2023/6/27.0000/-88.0000: shows 1,216,355,854 points, {text('in-view')} in view, over the base map · build/validate/step-15.png")
    assert not chrome.problems(), chrome.problems()
PY
fi

# Warm: the file read once into the disk cache first. A cold first bench (the file only on disk) is far slower:
# the step 15 skeptic measured p99 of 0.4–0.5 s at zooms 2–10 (docs/steps/step-15.md).
cat "$AIS_GPT" > /dev/null
bench=$ROOT/build/validate/step-15-bench.txt
build/gpstiles bench "$AIS_GPT" > "$bench" || fail "bench failed"
[ "$(awk '$1 ~ /^[0-9]+$/' "$bench" | wc -l | tr -d ' ')" = 25 ] || fail "bench printed no row a zoom"
worst=$(awk '$1 ~ /^[0-9]+$/ { if ($5 > w) w = $5 } END { print w }' "$bench")
awk -v w="$worst" 'BEGIN { exit !(w < 100) }' || fail "the worst p99 at 1.2 billion points is $worst ms"
ok "bench ais-2023 (1,216,355,854 points, warm disk cache): zoom 0, 5, 10, 15, 20 p50/p99 (ms): $(awk '$1 ~ /^(0|5|10|15|20)$/ { printf "%s:%s/%s ", $1, $4, $5 }' "$bench")· worst p99 at any zoom: $worst ms"
