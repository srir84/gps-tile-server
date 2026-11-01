#!/bin/bash
# step-13.sh: validates step 13 (DESIGN §12.6): tiles drawn by cutting dense cells are the tiles drawn point by point.
# The program as it was before this step (the last commit's src/render.c, built apart) and the current one render the
# same tiles of every .gpt in build/validate/ and data/build/ (at each zoom, the tiles under 16 points spread through
# the file): every PNG must be the same, byte for byte. Then `gpstiles bench` on Porto (83 million points): p99 under
# 5 ms at zooms 0–5 (walking every point: 164 ms) and under 50 ms at zooms 0–13. Each dataset is built when its raw
# files are here, and named when they aren't; SKIPPED without any.
set -u
. "$(dirname "$0")/lib.sh"
cd "$ROOT" || exit 1

make --no-print-directory -s all > /dev/null || fail "build failed"
# Every dataset whose raw files are here is built into build/validate/ (kept when unchanged); a missing one is named.
if ls data/raw/tdrive_txt/*.txt > /dev/null 2>&1; then tdrive_gpt; tdrive_sample_gpt; else echo "  SKIPPED: T-Drive (no data/raw/tdrive_txt)"; fi
if [ -d "$GEOLIFE_DATA" ]; then geolife_gpt; else echo "  SKIPPED: GeoLife (no data)"; fi
if [ -f "$USGS_DATA/MANIFEST.txt" ]; then usgs_gpt; else echo "  SKIPPED: USGS (no data)"; fi
if [ -f "$PORTO_DATA" ]; then porto_gpt; else echo "  SKIPPED: Porto (no data): no tile timing either"; fi
gpts=$(ls "$ROOT"/build/validate/*.gpt "$ROOT"/data/build/*.gpt 2> /dev/null)
if [ -z "$gpts" ]; then
    echo "SKIPPED: no dataset"
    exit 0
fi

# The point-by-point drawing: this tree with render.c's render_count as it was in step 12 (commit 1e22d25).
old=$(mktemp -d "${TMPDIR:-/tmp}/gpstiles-step13.XXXXXX") || exit 1
trap 'rm -rf "$old"' EXIT
git archive HEAD | tar -x -C "$old" || fail "can't export HEAD"
git show 1e22d25:src/render.c > "$old/src/render.c" || fail "can't read step 12's render.c"
env -u MAKEFLAGS -u MFLAGS make -C "$old" -s all B="$old/build" > /dev/null 2>&1 || fail "the step-12 drawing doesn't build"

python3 -I -B - "$old/build/gpstiles" "$ROOT/build/gpstiles" $gpts <<'PY' || fail "a tile differs (see above)"
import mmap, os, struct, subprocess, sys, tempfile
before, now, gpts = sys.argv[1], sys.argv[2], sys.argv[3:]
compared = 0
with tempfile.TemporaryDirectory() as tmp:
    for path in gpts:
        with open(path, "rb") as f, mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as m:
            n = (len(m) - 256) // 8
            codes = [struct.unpack_from("<Q", m, 256 + 8 * (i * n // 16))[0] for i in range(16)] if n else []
        tiles = set()
        for code in codes:
            for zoom in range(25):
                x = y = 0
                for bit in range(zoom):  # the tile is the code's top 2 × zoom bits: x in the even bits, y in the odd
                    pair = code >> (62 - 2 * bit) & 3
                    x, y = x << 1 | pair & 1, y << 1 | pair >> 1
                tiles.add((zoom, x, y))
        for zoom, x, y in sorted(tiles):
            pngs = []
            for program in (before, now):
                out = os.path.join(tmp, "tile.png")
                r = subprocess.run([program, "render", path, str(zoom), str(x), str(y), "-o", out], capture_output=True)
                assert r.returncode == 0, (program, r.stderr)
                pngs.append(open(out, "rb").read())
            assert pngs[0] == pngs[1], f"{os.path.basename(path)} tile {zoom}/{x}/{y} differs"
            compared += 1
        print(f"  ok  {path.split('/')[-3]}/{os.path.basename(path)}: {len(tiles)} tiles (zoom 0–24) = step 12's point-by-point drawing, byte for byte")
assert compared > 0
PY

[ -f "$PORTO_DATA" ] || exit 0
bench=$ROOT/build/validate/step-13-bench.txt
build/gpstiles bench "$PORTO_GPT" > "$bench" || fail "bench failed"
[ "$(awk '$1 ~ /^[0-9]+$/' "$bench" | wc -l | tr -d ' ')" = 25 ] || fail "bench printed $(wc -l < "$bench") lines, not a row a zoom"
worst=$(awk '$1 ~ /^[0-9]+$/ && $1 <= 13 { if ($5 > w) w = $5 } END { print w }' "$bench")
low=$(awk '$1 ~ /^[0-9]+$/ && $1 <= 5 { if ($5 > w) w = $5 } END { print w }' "$bench")
# Zooms 0–5 hold nearly all 83 million points in a few pixels: walking them takes 164 ms, cutting under 1 ms.
awk -v w="$worst" -v l="$low" 'BEGIN { exit !(w < 50 && l < 5) }' || fail "Porto's p99: $low ms at zooms 0–5, $worst ms at 0–13"
ok "bench porto (83 million points): zoom 0, 5, 10, 13 p50/p99 (ms): $(awk '$1 ~ /^(0|5|10|13)$/ { printf "%s:%s/%s ", $1, $4, $5 }' "$bench")· worst p99 at zooms 0–13: $worst ms (step 12: 164 ms)"
