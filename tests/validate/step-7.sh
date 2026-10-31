#!/bin/bash
# step-7.sh: validates step 7 (DESIGN §12.2) on T-Drive: the count API for a box around Capital Airport's
# taxi area, then the page in headless Chrome (tests/e2e/browser.py): hover the busiest zoom-16 pixel and
# an empty one, and draw a box with the mouse. Every number the page shows equals a slow count in Python
# that checks every point near the boxes with the box rule (tests/oracle/box_rules.py). SKIPPED when data/
# or Chrome is missing.
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
log=$ROOT/build/validate/step-7.log
build/gpstiles serve --port 0 "$TDRIVE_GPT" > "$log" 2>&1 &
server=$!
trap 'kill $server 2> /dev/null; wait $server 2> /dev/null' EXIT
for _ in $(seq 50); do
    port=$(sed -n 's|^gpstiles serve: http://127.0.0.1:\([0-9]*\)/$|\1|p' "$log")
    [ -n "$port" ] && break
    sleep 0.1
done
[ -n "$port" ] || fail "the server didn't say its port: $(cat "$log")"

python3 -I -B - "http://127.0.0.1:$port" "$TDRIVE_PTS" "$ROOT/tests" <<'PY' || fail "a count differs (see above)"
import array, collections, json, sys, urllib.parse, urllib.request
url, pts, tests = sys.argv[1], sys.argv[2], sys.argv[3]
sys.path[:0] = [f"{tests}/oracle", f"{tests}/e2e"]
import box_rules, browser, gpt_rules

codes = array.array("Q")
with open(pts, "rb") as f:
    codes.frombytes(f.read())
if sys.byteorder == "big":
    codes.byteswap()
# Every box below lies inside tile 9/421/193 (Beijing's north-east, the airport included), so only the
# points of that tile (the top 18 bits of their code) can be inside; each of those is checked.
prefix = gpt_rules.code_of(421, 193)
near = [(gpt_rules.x_of(c), gpt_rules.y_of(c)) for c in codes if c >> 46 == prefix]

def api_count(bbox):
    with urllib.request.urlopen(f"{url}/api/datasets/tdrive/count?bbox={bbox}", timeout=60) as r:
        return json.loads(r.read())["count"]

def check(name, bbox):
    box = box_rules.parse_bbox(bbox)
    assert box is not None and box[0] >> 23 == 421 and box[2] >> 23 == 421 and box[1] >> 23 == 193 and box[3] >> 23 == 193, (name, box)
    got, slow = api_count(bbox), box_rules.slow_count(near, box)
    assert got == slow, (name, bbox, got, slow)
    print(f"  ok  {name}: bbox={bbox} → {got:,} points = Python's slow count")

check("API: a box around the airport taxi area", "116.55,40.03,116.65,40.10")

# The page, zoom 16, centered on the busiest zoom-16 pixel of the tile (a pixel is 2^8 world units there).
busiest = collections.Counter((x >> 8, y >> 8) for x, y in near).most_common(1)[0][0]
empty = (box_rules.world_x(116.64) >> 8, box_rules.world_y(40.10) >> 8)
LOADED = """(() => { const t = [...document.querySelectorAll("#map .heat-tile img")];
  return t.length > 0 && t.every((i) => i.complete && i.naturalWidth === 256); })()"""
with browser.Browser(1400, 860) as chrome:
    def hover(px, py, name):
        lat, lon = box_rules.lat_of_y((py << 8) + 128), box_rules.lon_of_x((px << 8) + 128)
        chrome.open(f"{url}/#tdrive/16/{lat:.9f}/{lon:.9f}")
        chrome.wait("document.getElementById('zoom').textContent === '16'")
        chrome.wait(LOADED, timeout=60)
        corner = chrome.js(f"(() => {{ const p = map.latLngToContainerPoint([{box_rules.lat_of_y(py << 8)}, "
                           f"{box_rules.lon_of_x(px << 8)}]); return [p.x, p.y]; }})()")
        chrome.mouse("mouseMoved", *corner)  # on the pixel's north-west corner: that pixel is under the mouse
        slow = box_rules.slow_count(near, ((px << 8), (py << 8), (px << 8) + 255, (py << 8) + 255))
        want = f"{slow:,} point{'' if slow == 1 else 's'}"
        chrome.wait(f"document.getElementById('hover').textContent === '{want}'", timeout=30)
        print(f"  ok  page: hovered pixel {name} → '{want}' = Python's slow count of that pixel")
    hover(*empty, "in an empty field (zoom 16)")
    hover(*busiest, "the busiest at zoom 16")

    # Draw a 600 × 400 px box around the middle of the screen (the busiest pixel), with the mouse.
    chrome.click("#box-tool")
    chrome.drag((400, 230), (1000, 630))
    chrome.wait("/^[0-9,]+ points?$/.test(document.getElementById('box-count').textContent)", timeout=60)
    asked = [p for p in chrome.js("performance.getEntriesByType('resource').map((e) => e.name)") if "/count?" in p]
    bbox = urllib.parse.unquote(asked[-1].split("bbox=")[1])
    box = box_rules.parse_bbox(bbox)
    assert box is not None and box[0] >> 23 == 421 and box[2] >> 23 == 421 and box[1] >> 23 == 193 and box[3] >> 23 == 193, (bbox, box)
    shown = int(chrome.js("document.getElementById('box-count').textContent").split()[0].replace(",", ""))
    slow = box_rules.slow_count(near, box)
    assert shown == slow, (bbox, shown, slow)
    print(f"  ok  page: a box drawn with the mouse, bbox={bbox} → {shown:,} points = Python's slow count")
    chrome.screenshot(f"{sys.argv[3]}/../build/validate/step-7.png")
    assert chrome.errors == [] and chrome.violations() == [], (chrome.errors, chrome.violations())
PY
