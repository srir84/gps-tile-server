#!/bin/bash
# step-18.sh: validates step 18 (DESIGN §12.7) on GBIF's occurrences of 2024 with coordinates: one zip from
# tools/fetch-gbif.py (35 GB, 161 GB of tab-separated CSV) streamed through `unzip -p` into `gpstiles import`. Its rows =
# GBIF's own totalRecords (download.json) and = awk over the whole file (awk-counts.txt); for the developer's download
# also = DESIGN §13; built with the default
# --mem (several runs); the 4 zoom-1 tiles, and Amsterdam's tile and its 4 smaller tiles, add up; the page over the base
# map (build/validate/step-18.png); `gpstiles bench` (warm): p99 under 100 ms at every zoom. The build is kept in
# build/validate/ while nothing changes (about 15 minutes when it must be redone). SKIPPED without the data.
set -u
. "$(dirname "$0")/lib.sh"
cd "$ROOT" || exit 1

if ! ls "$GBIF_DATA"/*.zip > /dev/null 2>&1 || [ ! -f "$GBIF_DATA/download.json" ]; then
    echo "SKIPPED: no GBIF zip and download.json in data/raw/gbif (tools/fetch-gbif.py)"
    exit 0
fi
make --no-print-directory -s all > /dev/null || fail "build failed"
gbif_gpt
total=$(python3 -I -c 'import json, sys; print(json.load(open(sys.argv[1]))["totalRecords"])' "$GBIF_DATA/download.json") ||
    fail "can't read download.json"
rows=$(echo "$GBIF_COUNTS" | sed 's/^rows=\([0-9]*\).*/\1/')
[ "$rows" = "$total" ] || fail "the zip holds $rows rows, GBIF's totalRecords is $total"
# The independent count: awk over the whole file, made once by hand (an hour), into data/raw/gbif/awk-counts.txt:
zip=$(ls "$GBIF_DATA"/*.zip)
awk_command="set -o pipefail; unzip -p $zip | LC_ALL=C awk -v LON=23 -v LAT=22 -v SKIP=1 -v DELIM='\\t' -f tests/data/row_counts.awk > $GBIF_DATA/awk-counts.txt"
awk_counts=$(cat "$GBIF_DATA/awk-counts.txt" 2> /dev/null)
# The developer's download (DESIGN §13) has known counts; another download (GBIF changes daily) has its own.
download=$(python3 -I -c 'import json, sys; d = json.load(open(sys.argv[1])); print(d["key"], d["size"])' "$GBIF_DATA/download.json")
if [ "$download" = "0023351-261023074918325 34921376760" ]; then
    expected="rows=287451215 imported=287450825 skipped_zero=381 skipped_out_of_range=4 skipped_malformed=5"
    [ "$GBIF_COUNTS" = "$expected" ] || fail "import printed '$GBIF_COUNTS', expected '$expected' (DESIGN §13)"
    [ -n "$awk_counts" ] || fail "no awk-counts.txt for the known download; make it with: $awk_command"
    known=" = DESIGN §13"
else
    known=" · another download than DESIGN §13's"
fi
if [ -n "$awk_counts" ]; then
    # Its rows = totalRecords too, so the unzip that fed it ran to the end.
    [ "$awk_counts" = "$GBIF_COUNTS" ] || fail "awk over the whole file gave '$awk_counts', gpstiles '$GBIF_COUNTS'"
    ok "import of the zip → $GBIF_COUNTS (rows = GBIF's totalRecords $total · = awk over the whole file$known)"
else
    ok "import of the zip → $GBIF_COUNTS (rows = GBIF's totalRecords $total$known)"
    echo "  SKIPPED (= awk over the whole file): no awk-counts.txt; make it (an hour) with: $awk_command"
fi
runs=${GBIF_BUILD##*runs=}
[ "$runs" -gt 1 ] || fail "the build made one run: $GBIF_BUILD"
ok "build: $GBIF_BUILD"

points=$(echo "$GBIF_COUNTS" | sed 's/.*imported=\([0-9]*\).*/\1/')
sum=0
for x in 0 1; do
    for y in 0 1; do
        sum=$((sum + $(build/gpstiles count "$GBIF_GPT" 1 $x $y | sed 's/^points=//')))
    done
done
[ "$sum" = "$points" ] || fail "the 4 zoom-1 tiles hold $sum points, not $points"
tile=$(build/gpstiles where 4.90 52.37 --zoom 9) # Amsterdam
z=${tile%%/*}; rest=${tile#*/}; x=${rest%%/*}; y=${rest#*/}
parent=$(build/gpstiles count "$GBIF_GPT" "$z" "$x" "$y" | sed 's/^points=//')
kids=0
for dx in 0 1; do
    for dy in 0 1; do
        kids=$((kids + $(build/gpstiles count "$GBIF_GPT" $((z + 1)) $((2 * x + dx)) $((2 * y + dy)) | sed 's/^points=//')))
    done
done
[ "$parent" = "$kids" ] && [ "$parent" -gt 100000 ] || fail "tile $tile holds $parent points, its 4 smaller tiles $kids"
ok "the 4 zoom-1 tiles add up to $points · tile $tile (Amsterdam) = $parent = its 4 smaller tiles"

log=$ROOT/build/validate/step-18.log
build/gpstiles serve --port 0 "$GBIF_GPT" > "$log" 2>&1 &
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
    chrome.open(f"{url}/#gbif-2024/2/30.0000/10.0000")
    chrome.wait(LOADED, timeout=120)
    chrome.wait(BASE_LOADED, timeout=30)
    chrome.wait(FADED_IN)
    base_tile = f"https://tile.openstreetmap.org/{osm_tile.tile(10.0, 30.0, 2)}.png"
    assert chrome.js(f"[...document.querySelectorAll('#map .base-dark img')].some((i) => i.src === '{base_tile}' && i.naturalWidth === 256)"), \
        f"the base map didn't load (no internet?): {base_tile}"
    assert text("points") == f"{points:,}", text("points")
    chrome.screenshot(f"{out}/step-18.png")
    print(f"  ok  #gbif-2024/2/30.0000/10.0000: shows {points:,} points, {text('in-view')} in view, over the base map · build/validate/step-18.png")
    assert not chrome.problems(), chrome.problems()
PY
fi

cat "$GBIF_GPT" > /dev/null # warm: in the disk cache, as step 15
bench=$ROOT/build/validate/step-18-bench.txt
build/gpstiles bench "$GBIF_GPT" > "$bench" || fail "bench failed"
[ "$(awk '$1 ~ /^[0-9]+$/' "$bench" | wc -l | tr -d ' ')" = 25 ] || fail "bench printed no row a zoom"
worst=$(awk '$1 ~ /^[0-9]+$/ { if ($5 > w) w = $5 } END { print w }' "$bench")
awk -v w="$worst" 'BEGIN { exit !(w < 100) }' || fail "the worst p99 is $worst ms"
ok "bench gbif-2024 ($points points, warm disk cache): zoom 0, 5, 10, 15, 20 p50/p99 (ms): $(awk '$1 ~ /^(0|5|10|15|20)$/ { printf "%s:%s/%s ", $1, $4, $5 }' "$bench")· worst p99 at any zoom: $worst ms"
