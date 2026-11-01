#!/bin/bash
# step-14.sh: validates step 14 (DESIGN §12.6) on the NYC taxis 2009–2010: tools/nyc-taxi.py | `gpstiles import` of the
# 24 Parquet files prints DESIGN §13's counts (679,794,434 pickup and dropoff places). Served: the count API for a box
# at JFK = DuckDB's count of the points inside it (its edges half a millionth of a degree off the data's 6 decimals, so
# no point is on an edge); the page in headless Chrome over the base map at Manhattan, zoom 12 and 16
# (build/validate/step-14.png, step-14-street.png) and its opening view on New York; `gpstiles bench`: 680 million
# points drawn in milliseconds at every zoom. Needs DuckDB in data/tools/venv. SKIPPED without the data, DuckDB or
# Chrome.
set -u
. "$(dirname "$0")/lib.sh"
cd "$ROOT" || exit 1

if ! ls "$NYC_DATA"/yellow_tripdata_20*.parquet > /dev/null 2>&1; then
    echo "SKIPPED: no NYC Parquet files in data/raw/nyc-taxi"
    exit 0
fi
[ -x "$NYC_PYTHON" ] || fail "the NYC files are here but DuckDB isn't (data/tools/venv: see the README)"
if [ ! -x "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" ]; then
    echo "SKIPPED: no Google Chrome"
    exit 0
fi
make --no-print-directory -s all > /dev/null || fail "build failed"
nyc_gpt
expected="rows=679794434 imported=668475278 skipped_zero=11315804 skipped_out_of_range=3242 skipped_malformed=110"
[ "$NYC_COUNTS" = "$expected" ] || fail "import printed '$NYC_COUNTS', expected '$expected' (DESIGN §13)"
ok "nyc-taxi.py | import of 24 months → $NYC_COUNTS (DESIGN §13)"

log=$ROOT/build/validate/step-14.log
build/gpstiles serve --port 0 "$NYC_GPT" > "$log" 2>&1 &
server=$!
trap 'kill $server 2> /dev/null; wait $server 2> /dev/null' EXIT
for _ in $(seq 50); do
    port=$(sed -n 's|^gpstiles serve: http://127.0.0.1:\([0-9]*\)/$|\1|p' "$log")
    [ -n "$port" ] && break
    sleep 0.1
done
[ -n "$port" ] || fail "the server didn't say its port: $(cat "$log")"

"$NYC_PYTHON" -I -B - "http://127.0.0.1:$port" "$NYC_DATA" "$ROOT/tests" "$ROOT/build/validate" <<'PY' || fail "an NYC check failed (see above)"
import glob, json, sys, urllib.request
url, data, tests, out = sys.argv[1:5]
sys.path[:0] = [f"{tests}/oracle", f"{tests}/e2e"]
import browser, duckdb, osm_tile
duckdb.sql("SET threads TO 2")

parts, params = [], []  # the paths go in as parameters, never pasted into the SQL
for path in sorted(glob.glob(f"{data}/yellow_tripdata_20*.parquet")):
    names = {c[0] for c in duckdb.sql("DESCRIBE SELECT * FROM read_parquet(?)", params=[path]).fetchall()}
    cols = ("Start_Lon", "Start_Lat", "End_Lon", "End_Lat") if "Start_Lon" in names else \
        ("pickup_longitude", "pickup_latitude", "dropoff_longitude", "dropoff_latitude")
    parts += [f'SELECT "{a}" AS lon, "{b}" AS lat FROM read_parquet(?)' for a, b in (cols[:2], cols[2:])]
    params += [path, path]
w, s, e, n = -73.8200005, 40.6300005, -73.7500005, 40.6600005  # around JFK
want = duckdb.sql(f"SELECT COUNT(*) FROM ({' UNION ALL '.join(parts)}) WHERE lon BETWEEN {w} AND {e} AND lat BETWEEN {s} AND {n}",
                  params=params).fetchall()[0][0]
with urllib.request.urlopen(f"{url}/api/datasets/nyc-taxi/count?bbox={w},{s},{e},{n}", timeout=60) as r:
    got = json.loads(r.read())["count"]
assert got == want > 100000, (got, want)
print(f"  ok  bbox={w},{s},{e},{n} (JFK): count {got:,} = DuckDB's count of the places inside it")

LOADED = """(() => { const t = [...document.querySelectorAll("#map .heat-tile img")];
  return t.length > 0 && t.every((i) => i.complete && i.naturalWidth === 256); })()"""
BASE_LOADED = """(() => { const t = [...document.querySelectorAll("#map .base-dark img")];
  return t.length > 0 && t.every((i) => i.complete); })()"""
FADED_IN = """[...document.querySelectorAll("#map .leaflet-tile-loaded")].every((t) => getComputedStyle(t).opacity === "1")"""
with browser.Browser(1400, 860, internet=True) as chrome:
    text = lambda id: chrome.js(f"document.getElementById('{id}').textContent")
    for view, name in [("12/40.7400/-73.9500", "step-14.png"), ("16/40.7580/-73.9855", "step-14-street.png")]:
        chrome.open(f"{url}/#nyc-taxi/{view}")
        chrome.wait(LOADED, timeout=120)
        chrome.wait(BASE_LOADED, timeout=30)
        chrome.wait(FADED_IN)
        zoom, lat, lon = view.split("/")
        base_tile = f"https://tile.openstreetmap.org/{osm_tile.tile(float(lon), float(lat), int(zoom))}.png"
        assert chrome.js(f"[...document.querySelectorAll('#map .base-dark img')].some((i) => i.src === '{base_tile}' && i.naturalWidth === 256)"), \
            f"the base map didn't load (no internet?): {base_tile}"
        assert text("points") == "668,475,278", text("points")
        chrome.screenshot(f"{out}/{name}")
        print(f"  ok  #nyc-taxi/{view}: shows 668,475,278 points, {text('in-view')} in view, over the base map · build/validate/{name}")
    chrome.open(f"{url}/#nyc-taxi")
    chrome.wait(LOADED, timeout=120)
    z, lat, lon = chrome.js("[map.getZoom(), map.getCenter().lat, map.getCenter().lng]")
    assert z >= 10 and abs(lat - 40.75) < 0.2 and abs(lon + 73.95) < 0.2, (z, lat, lon)
    print(f"  ok  #nyc-taxi opens on New York: zoom {z}, {lat:.3f}, {lon:.3f}")
    assert not chrome.problems(), chrome.problems()
PY

bench=$ROOT/build/validate/step-14-bench.txt
build/gpstiles bench "$NYC_GPT" > "$bench" || fail "bench failed"
[ "$(awk '$1 ~ /^[0-9]+$/' "$bench" | wc -l | tr -d ' ')" = 25 ] || fail "bench printed $(wc -l < "$bench") lines, not a row a zoom"
worst=$(awk '$1 ~ /^[0-9]+$/ { if ($5 > w) w = $5 } END { print w }' "$bench")
awk -v w="$worst" 'BEGIN { exit !(w < 100) }' || fail "NYC's worst p99 is $worst ms"
ok "bench nyc-taxi (668 million points): zoom 0, 5, 10, 13, 16 p50/p99 (ms): $(awk '$1 ~ /^(0|5|10|13|16)$/ { printf "%s:%s/%s ", $1, $4, $5 }' "$bench")· worst p99 at any zoom: $worst ms"
ok "screenshots for a person to check: build/validate/step-14.png (Manhattan), step-14-street.png (Times Square)"
