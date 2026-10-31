#!/bin/bash
# step-8.sh: validates step 8 (DESIGN §12.2) on T-Drive: the CSV export of the box around Capital Airport's
# taxi area. It reads as CSV (header lon,lat), has as many rows as the box count, and every row is a point
# Python finds in the box itself, in file order. A row limit is kept. Then in the page (headless Chrome,
# tests/e2e/browser.py): a box drawn with the mouse, its Export link clicked, and the downloaded file checked
# the same way. The CSVs are saved in build/validate/ to open in Numbers or Excel. SKIPPED without data/ or
# Chrome.
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
log=$ROOT/build/validate/step-8.log
build/gpstiles serve --port 0 "$TDRIVE_GPT" > "$log" 2>&1 &
server=$!
trap 'kill $server 2> /dev/null; wait $server 2> /dev/null' EXIT
for _ in $(seq 50); do
    port=$(sed -n 's|^gpstiles serve: http://127.0.0.1:\([0-9]*\)/$|\1|p' "$log")
    [ -n "$port" ] && break
    sleep 0.1
done
[ -n "$port" ] || fail "the server didn't say its port: $(cat "$log")"

python3 -I -B - "http://127.0.0.1:$port" "$TDRIVE_PTS" "$ROOT/tests" "$ROOT/build/validate/step-8.csv" <<'PY' ||
import array, csv, io, json, pathlib, sys, tempfile, urllib.parse, urllib.request
url, pts, tests, saved = sys.argv[1:5]
sys.path[:0] = [f"{tests}/oracle", f"{tests}/e2e"]
import box_rules, browser, gpt_rules

bbox = "116.55,40.03,116.65,40.10"
with urllib.request.urlopen(f"{url}/api/datasets/tdrive/count?bbox={bbox}", timeout=60) as r:
    count = json.loads(r.read())["count"]
with urllib.request.urlopen(f"{url}/api/datasets/tdrive/export.csv?bbox={bbox}&limit={min(count, 1000000)}", timeout=120) as r:
    disposition, data = r.headers["Content-Disposition"], r.read()
open(saved, "wb").write(data)
text = data.decode("utf-8")
rows = list(csv.reader(io.StringIO(text)))
assert rows[0] == ["lon", "lat"] and all(len(row) == 2 for row in rows[1:]), rows[:2]
assert len(rows) - 1 == count, (len(rows) - 1, count)
assert disposition == 'attachment; filename="tdrive-export.csv"', disposition
print(f"  ok  export.csv of bbox={bbox}: {count:,} rows = the box count · header lon,lat · saved as build/validate/step-8.csv")

# Python's own answer: every point of the .pts in the box, in file (code) order, written the same way.
codes = array.array("Q")
with open(pts, "rb") as f:
    codes.frombytes(f.read())
if sys.byteorder == "big":
    codes.byteswap()
box = box_rules.parse_bbox(bbox)
prefix = gpt_rules.code_of(421, 193)  # the zoom-9 tile holding the whole box
want = []
for c in sorted(c for c in codes if c >> 46 == prefix):
    x, y = gpt_rules.x_of(c), gpt_rules.y_of(c)
    if box_rules.inside(x, y, box):  # the middle of its unit, kept inside the box's degrees
        lon, lat = min(max(box_rules.lon_of_x(x + 0.5), 116.55), 116.65), min(max(box_rules.lat_of_y(y + 0.5), 40.03), 40.10)
        want.append(f"{lon:.9f},{lat:.9f}")
assert text.splitlines()[1:] == want, (len(want), [r for r in text.splitlines()[1:6]], want[:5])
# Read back with the box rule's formulas, every row is a unit inside the box; read as plain numbers (as a
# spreadsheet filter would), every row is inside the box's degrees, with no slack.
outside = [r for r in rows[1:] if not box_rules.inside(box_rules.world_x(float(r[0])), box_rules.world_y(float(r[1])), box)]
assert not outside, outside[:3]
w, s, e, n = map(float, bbox.split(","))
outside = [r for r in rows[1:] if not (w <= float(r[0]) <= e and s <= float(r[1]) <= n)]
assert not outside, (len(outside), outside[:3])
print(f"  ok  every row is inside the box, and the rows are exactly Python's points of the box in file order")

with urllib.request.urlopen(f"{url}/api/datasets/tdrive/export.csv?bbox={bbox}&limit=1000", timeout=60) as r:
    limited = r.read().decode().splitlines()
assert len(limited) == 1001 and limited[1:] == want[:1000], len(limited)
print(f"  ok  limit=1000 → 1,000 rows, the first 1,000 of the full export")

# The page: a box drawn with the mouse near the airport at zoom 14, its Export link clicked.
near = sorted(c for c in codes if c >> 46 == prefix)
LOADED = """(() => { const t = [...document.querySelectorAll("#map .heat-tile img")];
  return t.length > 0 && t.every((i) => i.complete && i.naturalWidth === 256); })()"""
with tempfile.TemporaryDirectory() as downloads, browser.Browser(1400, 860) as chrome:
    chrome.save_downloads_in(downloads)
    chrome.open(f"{url}/#tdrive/14/40.0650/116.6000")
    chrome.wait(LOADED, timeout=60)
    chrome.click("#box-tool")
    chrome.drag((450, 250), (950, 600))
    chrome.wait("!document.getElementById('export').hidden", timeout=60)
    shown = int(chrome.js("document.getElementById('box-count').textContent").split()[0].replace(",", ""))
    href = chrome.js("document.getElementById('export').getAttribute('href')")
    page_box = box_rules.parse_bbox(urllib.parse.parse_qs(urllib.parse.urlsplit(href).query)["bbox"][0])
    # inside tile 9/421/193, whose points are all in `near`
    assert page_box is not None and page_box[0] >> 23 == page_box[2] >> 23 == 421 and page_box[1] >> 23 == page_box[3] >> 23 == 193, page_box
    pw, ps, pe, pn = map(float, urllib.parse.parse_qs(urllib.parse.urlsplit(href).query)["bbox"][0].split(","))
    page_want = [f"{min(max(box_rules.lon_of_x(gpt_rules.x_of(c) + 0.5), pw), pe):.9f},{min(max(box_rules.lat_of_y(gpt_rules.y_of(c) + 0.5), ps), pn):.9f}"
                 for c in near if box_rules.inside(gpt_rules.x_of(c), gpt_rules.y_of(c), page_box)]
    assert shown == len(page_want), (shown, len(page_want))
    chrome.click("#export")
    data = chrome.wait_for_download(pathlib.Path(downloads) / "tdrive-export.csv", timeout=120)
    assert data.decode().splitlines() == ["lon,lat"] + page_want, (len(data.decode().splitlines()) - 1, len(page_want))
    pathlib.Path(saved).with_name("step-8-page.csv").write_bytes(data)
    assert not chrome.problems(), chrome.problems()
print(f"  ok  page: a box drawn with the mouse, its Export link clicked: {shown:,} rows downloaded = the box count = Python's points of the box · saved as build/validate/step-8-page.csv")
PY
    fail "an export check failed (see above)"

# A slow reader, against a second server with --timeout 1 (an export's client may then pause 3 s): one that
# reads steadily (about 400 KB/s) gets the whole export, 64,000 rows (about 1.9 MB: more than the socket
# buffers hold, so the server must wait for it), in about 5 s, longer than the 3 s.
log1=$ROOT/build/validate/step-8-timeout1.log
build/gpstiles serve --port 0 --timeout 1 "$TDRIVE_GPT" > "$log1" 2>&1 &
server1=$!
trap 'kill $server $server1 2> /dev/null; wait $server $server1 2> /dev/null' EXIT
for _ in $(seq 50); do
    port1=$(sed -n 's|^gpstiles serve: http://127.0.0.1:\([0-9]*\)/$|\1|p' "$log1")
    [ -n "$port1" ] && break
    sleep 0.1
done
[ -n "$port1" ] || fail "the second server didn't say its port: $(cat "$log1")"
python3 -I -B - "$port1" <<'PY' || fail "a slow-reader check failed (see above)"
import socket, sys, time
port, box = int(sys.argv[1]), "/api/datasets/tdrive/export.csv?bbox=116.55,40.03,116.65,40.10"

def read(path, piece, pause, slow_for):
    """Reads the export `piece` bytes at a time with a pause after each for `slow_for` seconds, then the rest
    at full speed until the server closes (what the server had already written is still delivered)."""
    s = socket.create_connection(("127.0.0.1", port))
    s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)  # the file can't wait in socket buffers
    s.sendall(f"GET {path} HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n".encode())
    data, start = bytearray(), time.monotonic()
    while (chunk := s.recv(piece if time.monotonic() - start < slow_for else 1 << 20)):
        data += chunk
        if time.monotonic() - start < slow_for:
            time.sleep(pause)
    s.close()
    return bytes(data), time.monotonic() - start

data, seconds = read(box + "&limit=64000", 16384, 0.04, 120)
rows = data.count(b"\n") - data.count(b"\r\n") - 1  # rows end with \n; chunk lines with \r\n
assert data.endswith(b"\r\n0\r\n\r\n") and rows == 64000 and seconds > 3, (seconds, len(data), rows, data[-40:])
print(f"  ok  a steady slow reader (about 400 KB/s, --timeout 1) got the whole export: 64,000 rows in {seconds:.1f} s")
PY

