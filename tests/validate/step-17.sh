#!/bin/bash
# step-17.sh: validates step 17 (DESIGN §12.7) on OpenSky's public aircraft positions of Monday 2022-06-27: 24 hourly
# tars, each streamed (`tar -xOf | gunzip`) into `gpstiles import`, the counts added up = DESIGN §13's awk total; built
# into one .gpt with the default --mem; the 4 zoom-1 tiles and Frankfurt airport's tile and its 4 smaller tiles add up;
# the page over the base map, the world's flights (build/validate/step-17.png); `gpstiles bench` (warm): p99 under
# 100 ms at every zoom. The build is kept in build/validate/ while nothing changes. SKIPPED without the data; only the
# page needs Chrome.
set -u
. "$(dirname "$0")/lib.sh"
cd "$ROOT" || exit 1

if [ "$(ls "$OPENSKY_DATA"/states_2022-06-27-*.csv.tar 2> /dev/null | wc -l | tr -d ' ')" != 24 ]; then
    echo "SKIPPED: not the 24 hours of 2022-06-27 in data/raw/opensky (tools/fetch-opensky.py)"
    exit 0
fi
make --no-print-directory -s all > /dev/null || fail "build failed"
opensky_gpt
expected="rows=61296085 imported=56869562 skipped_zero=0 skipped_out_of_range=0 skipped_malformed=4426523"
[ "$OPENSKY_COUNTS" = "$expected" ] || fail "the 24 hours imported as '$OPENSKY_COUNTS', expected '$expected' (DESIGN §13)"
ok "import of 24 hours, added up → $OPENSKY_COUNTS (= awk over the whole day, DESIGN §13)"
ok "build: $OPENSKY_BUILD"

points=$(echo "$OPENSKY_COUNTS" | sed 's/.*imported=\([0-9]*\).*/\1/')
sum=0
for x in 0 1; do
    for y in 0 1; do
        sum=$((sum + $(build/gpstiles count "$OPENSKY_GPT" 1 $x $y | sed 's/^points=//')))
    done
done
[ "$sum" = "$points" ] || fail "the 4 zoom-1 tiles hold $sum points, not $points"
tile=$(build/gpstiles where 8.57 50.04 --zoom 9) # Frankfurt airport
z=${tile%%/*}; rest=${tile#*/}; x=${rest%%/*}; y=${rest#*/}
parent=$(build/gpstiles count "$OPENSKY_GPT" "$z" "$x" "$y" | sed 's/^points=//')
kids=0
for dx in 0 1; do
    for dy in 0 1; do
        kids=$((kids + $(build/gpstiles count "$OPENSKY_GPT" $((z + 1)) $((2 * x + dx)) $((2 * y + dy)) | sed 's/^points=//')))
    done
done
[ "$parent" = "$kids" ] && [ "$parent" -gt 10000 ] || fail "tile $tile holds $parent points, its 4 smaller tiles $kids"
ok "the 4 zoom-1 tiles add up to $points · tile $tile (Frankfurt airport) = $parent = its 4 smaller tiles"

log=$ROOT/build/validate/step-17.log
build/gpstiles serve --port 0 "$OPENSKY_GPT" > "$log" 2>&1 &
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
    chrome.open(f"{url}/#opensky-2022-06-27/3/40.0000/-30.0000")
    chrome.wait(LOADED, timeout=120)
    chrome.wait(BASE_LOADED, timeout=30)
    chrome.wait(FADED_IN)
    base_tile = f"https://tile.openstreetmap.org/{osm_tile.tile(-30.0, 40.0, 3)}.png"
    assert chrome.js(f"[...document.querySelectorAll('#map .base-dark img')].some((i) => i.src === '{base_tile}' && i.naturalWidth === 256)"), \
        f"the base map didn't load (no internet?): {base_tile}"
    assert text("points") == f"{points:,}", text("points")
    chrome.screenshot(f"{out}/step-17.png")
    print(f"  ok  #opensky-2022-06-27/3/40.0000/-30.0000: shows {points:,} points, {text('in-view')} in view, over the base map · build/validate/step-17.png")
    assert not chrome.problems(), chrome.problems()
PY
fi

cat "$OPENSKY_GPT" > /dev/null # warm: in the disk cache, as step 15
bench=$ROOT/build/validate/step-17-bench.txt
build/gpstiles bench "$OPENSKY_GPT" > "$bench" || fail "bench failed"
[ "$(awk '$1 ~ /^[0-9]+$/' "$bench" | wc -l | tr -d ' ')" = 25 ] || fail "bench printed no row a zoom"
worst=$(awk '$1 ~ /^[0-9]+$/ { if ($5 > w) w = $5 } END { print w }' "$bench")
awk -v w="$worst" 'BEGIN { exit !(w < 100) }' || fail "the worst p99 is $worst ms"
ok "bench opensky-2022-06-27 ($points points, warm disk cache): zoom 0, 5, 10, 15, 20 p50/p99 (ms): $(awk '$1 ~ /^(0|5|10|15|20)$/ { printf "%s:%s/%s ", $1, $4, $5 }' "$bench")· worst p99 at any zoom: $worst ms"
