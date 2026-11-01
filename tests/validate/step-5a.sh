#!/bin/bash
# step-5a.sh: validates step 5a (DESIGN §12.2): `gpstiles serve` on all of T-Drive and on tdrive-sample
# (the first 500 T-Drive files). /api/datasets lists both with their own counts (DESIGN §13, awk), a tile of
# each equals Python's from that dataset's own points (count and every pixel), and bad URLs and an unknown
# id get errors while the server keeps answering. SKIPPED when data/ is missing.
set -u
. "$(dirname "$0")/lib.sh"
cd "$ROOT" || exit 1

if ! ls data/raw/tdrive_txt/*.txt > /dev/null 2>&1; then
    echo "SKIPPED: no T-Drive files in data/raw/tdrive_txt"
    exit 0
fi
make --no-print-directory -s all > /dev/null || fail "build failed"
tdrive_gpt
tdrive_sample_gpt
sample=$TDRIVE_SAMPLE_GPT

# The sample's point count from awk (step 2's independent row rules), not from our own files.
# shellcheck disable=SC2046 # the names have no spaces
sample_awk=$(LC_ALL=C awk -v LON=3 -v LAT=4 -f tests/data/row_counts.awk $(ls data/raw/tdrive_txt/*.txt | sort | head -500) |
    sed -n 's/.*imported=\([0-9]*\).*/\1/p')
[ -n "$sample_awk" ] || fail "awk gave no count for the sample"

log=$ROOT/build/validate/step-5a.log
build/gpstiles serve --port 0 "$TDRIVE_GPT" "$sample" > "$log" 2>&1 &
server=$!
trap 'kill $server 2> /dev/null' EXIT
for _ in $(seq 50); do
    port=$(sed -n 's|^gpstiles serve: http://127.0.0.1:\([0-9]*\)/$|\1|p' "$log")
    [ -n "$port" ] && break
    sleep 0.1
done
[ -n "$port" ] || fail "the server didn't say its port: $(cat "$log")"
url=http://127.0.0.1:$port
ok "serving both datasets on $url"

python3 -I -B - "$url" "$TDRIVE_GPT" "$sample" "$sample_awk" "$ROOT/tests/oracle" <<'PY' || fail "a server check failed (see above)"
import array, json, sys, urllib.error, urllib.request
url, files = sys.argv[1], {"tdrive": sys.argv[2], "tdrive-sample": sys.argv[3]}
awk_counts = {"tdrive": 10064891, "tdrive-sample": int(sys.argv[4])}  # DESIGN §13 and awk
sys.path.insert(0, sys.argv[5])
import gpt_rules, tile_rules

def get(path):
    try:
        with urllib.request.urlopen(url + path, timeout=30) as r:
            return r.status, r.headers, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read()

status, _, body = get("/api/datasets")
listed = {d["id"]: d["points"] for d in json.loads(body)["datasets"]}
assert status == 200 and listed == awk_counts, (listed, awk_counts)
print(f"  ok  /api/datasets: tdrive {listed['tdrive']:,} points (DESIGN §13) · tdrive-sample {listed['tdrive-sample']:,} points (= awk over the same 500 files)")
# Each dataset's tile against Python's own answer from that dataset's points (the .pts next to its .gpt):
# the point count and every pixel's color, so a tile drawn from the other dataset can't pass.
pixels = {}
for name, path in files.items():
    status, headers, body = get(f"/tiles/{name}/11/1686/776.png")
    assert status == 200 and headers["Content-Type"] == "image/png" and body[:8] == b"\x89PNG\r\n\x1a\n", (name, status)
    codes = array.array("Q")
    with open(path[:-4] + ".pts", "rb") as f:
        codes.frombytes(f.read())
    if sys.byteorder == "big":
        codes.byteswap()
    prefix = gpt_rules.code_of(1686, 776)
    counts = {}
    for c in codes:
        if c >> 42 == prefix:
            px = ((gpt_rules.x_of(c) >> 13) & 255, (gpt_rules.y_of(c) >> 13) & 255)
            counts[px] = counts.get(px, 0) + 1
    max_count = gpt_rules.parse_header(open(path, "rb").read(256))["max_pixel"][11]
    rows = tile_rules.decode_png(body)[2]
    wrong = sum(rows[py][px] != tile_rules.color(counts.get((px, py), 0), max_count) for py in range(256) for px in range(256))
    assert int(headers["X-Points"]) == sum(counts.values()) and wrong == 0, (name, headers["X-Points"], sum(counts.values()), wrong)
    pixels[name] = rows
    print(f"  ok  /tiles/{name}/11/1686/776.png: {int(headers['X-Points']):,} points and all 65,536 pixels = Python's from {name}'s own points")
assert pixels["tdrive"] != pixels["tdrive-sample"], "both datasets drew the same tile"
for path, want in [("/tiles/nope/11/1686/776.png", 404), ("/api/datasets/nope", 404), ("/tiles/tdrive/25/0/0.png", 404),
                   ("/tiles/tdrive/x/1/2.png", 400), ("/no/such/page", 404), ("/tiles/tdrive/11/1686", 404)]:
    status, _, body = get(path)
    assert status == want, (path, status)
    assert get("/api/datasets")[0] == 200, f"no answer after {path}"
    print(f"  ok  {path} → {status} {body.decode().strip()} · the next request still works")
PY
kill $server
wait $server 2> /dev/null
ok "server stopped"
