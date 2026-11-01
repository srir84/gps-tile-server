#!/bin/bash
# step-6.sh: validates step 6 (DESIGN §12.2): the map page in headless Chrome (tests/e2e/browser.py), served
# with T-Drive and tdrive-sample. The page shows T-Drive's point count (DESIGN §13) and asks for exactly the
# tiles on the map; a click on the dataset switch shows tdrive-sample's count (awk) and only its tiles.
# Screenshots for a person to look at, in build/validate/ (with the real base map, from the internet):
# step-6.png (Beijing, zoom 11: ring roads, the airport), step-6-sample.png (after the switch) and
# step-6-street.png (zoom 17 near Tiananmen: single points on streets). SKIPPED without data/ or Chrome.
set -u
. "$(dirname "$0")/lib.sh"
cd "$ROOT" || exit 1

if ! ls data/raw/tdrive_txt/*.txt > /dev/null 2>&1; then
    echo "SKIPPED: no T-Drive files in data/raw/tdrive_txt"
    exit 0
fi
if [ ! -x "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" ]; then
    echo "SKIPPED: no Google Chrome"
    exit 0
fi
make --no-print-directory -s all > /dev/null || fail "build failed"
tdrive_gpt
tdrive_sample_gpt

# The sample's point count from awk (step 2's independent row rules), not from our own files.
# shellcheck disable=SC2046 # the names have no spaces
sample_awk=$(LC_ALL=C awk -v LON=3 -v LAT=4 -f tests/data/row_counts.awk $(ls data/raw/tdrive_txt/*.txt | sort | head -500) |
    sed -n 's/.*imported=\([0-9]*\).*/\1/p')
[ -n "$sample_awk" ] || fail "awk gave no count for the sample"

out=$ROOT/build/validate
log=$out/step-6.log
build/gpstiles serve --port 0 "$TDRIVE_GPT" "$TDRIVE_SAMPLE_GPT" > "$log" 2>&1 &
server=$!
trap 'kill $server 2> /dev/null; wait $server 2> /dev/null' EXIT
for _ in $(seq 50); do
    port=$(sed -n 's|^gpstiles serve: http://127.0.0.1:\([0-9]*\)/$|\1|p' "$log")
    [ -n "$port" ] && break
    sleep 0.1
done
[ -n "$port" ] || fail "the server didn't say its port: $(cat "$log")"

python3 -I -B - "http://127.0.0.1:$port" "$sample_awk" "$out" "$ROOT/tests/e2e" <<'PY' || fail "a page check failed (see above)"
import math, sys
url, sample_awk, out = sys.argv[1], int(sys.argv[2]), sys.argv[3]
sys.path.insert(0, sys.argv[4])
import browser

LOADED = """(() => { const t = [...document.querySelectorAll("#map .heat-tile img")];
  return t.length > 0 && t.every((i) => i.complete && i.naturalWidth === 256); })()"""
REQUESTED = """performance.getEntriesByType("resource").map((e) => new URL(e.name).pathname)
  .filter((p) => p.startsWith("/tiles/")).map((p) => p.slice(7, -4))"""
ON_MAP = """[...document.querySelectorAll("#map .heat-tile")].map((t) => t.dataset.tile)"""
# The base map has finished loading (from the internet, or failed when offline), and every tile has faded
# in: then the screenshot.
BASE_LOADED = """(() => { const t = [...document.querySelectorAll("#map .base-dark img")];
  return t.length > 0 && t.every((i) => i.complete); })()"""
BASE_SHOWN = """[...document.querySelectorAll("#map .base-dark img")].filter((i) => i.naturalWidth > 0).length"""
FADED_IN = """[...document.querySelectorAll("#map .leaflet-tile-loaded")].every((t) => getComputedStyle(t).opacity === "1")"""

def ready():
    """The heat and base tiles have loaded and faded in. Without internet no base tile loads: the other
    checks still run, the base map's look is SKIPPED (a CSP block would still fail, in problems())."""
    chrome.wait(LOADED, timeout=60)
    chrome.wait(BASE_LOADED, timeout=30)
    if chrome.js(BASE_SHOWN) == 0:
        print("  SKIPPED (the base map's look): no base tile loaded (no internet?); the checks still run")
    chrome.wait(FADED_IN)

with browser.Browser(1400, 860, internet=True) as chrome:
    text = lambda id: chrome.js(f"document.getElementById('{id}').textContent")
    chrome.open(f"{url}/#tdrive/11/39.9500/116.4300")
    ready()
    # The base tile under the center, by the OpenStreetMap formula: 11/1686/776.
    x = int((116.43 + 180) / 360 * 2**11)
    y = int((1 - math.asinh(math.tan(math.radians(39.95))) / math.pi) / 2 * 2**11)
    base_tile = f"https://tile.openstreetmap.org/11/{x}/{y}.png"
    assert chrome.js(f"[...document.querySelectorAll('#map .base-dark img')].some((i) => i.src === '{base_tile}' && i.naturalWidth === 256)"), base_tile
    requested, on_map = chrome.js(REQUESTED), chrome.js(ON_MAP)
    assert text("points") == "10,064,891", text("points")  # DESIGN §13
    assert sorted(requested) == sorted(f"tdrive/{t}" for t in on_map) and all(t.startswith("11/") for t in on_map), (requested, on_map)
    print(f"  ok  #tdrive at zoom 11: shows 10,064,891 points (DESIGN §13), asked for exactly the {len(on_map)} tiles on the map,"
          f" points in them: {text('in-view')}; base map {chrome.js(BASE_SHOWN)} tiles, {base_tile} among them")
    chrome.screenshot(f"{out}/step-6.png")

    before = len(requested)
    chrome.click('#switch button[data-id="tdrive-sample"]')
    chrome.wait("location.hash.startsWith('#tdrive-sample/')")
    ready()
    after, on_map = chrome.js(REQUESTED)[before:], chrome.js(ON_MAP)
    assert text("points") == f"{sample_awk:,}", (text("points"), sample_awk)
    assert after and all(r.startswith("tdrive-sample/") for r in after), after
    assert {r.split("/", 1)[1] for r in after} <= set(on_map), (after, on_map)
    print(f"  ok  clicked tdrive-sample: shows {sample_awk:,} points (= awk over its 500 files), its {len(after)} tile"
          f" requests all /tiles/tdrive-sample/, each for a tile on the map, points in them: {text('in-view')}")
    chrome.screenshot(f"{out}/step-6-sample.png")

    chrome.open(f"{url}/#tdrive/17/39.9050/116.3975")
    chrome.wait("document.getElementById('zoom').textContent === '17'")
    ready()
    chrome.screenshot(f"{out}/step-6-street.png")
    assert not chrome.problems(), chrome.problems()
    print(f"  ok  zoom 17 near Tiananmen loaded ({text('in-view')} points in its tiles, base map {chrome.js(BASE_SHOWN)} tiles);"
          " no script errors or blocked loads")
PY
ok "screenshots for a person to check: build/validate/step-6.png, step-6-sample.png, step-6-street.png"
