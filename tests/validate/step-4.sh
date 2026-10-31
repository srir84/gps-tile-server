#!/bin/bash
# step-4.sh: validates step 4 (DESIGN §12.2): T-Drive tiles drawn by `gpstiles render` beside the same
# OpenStreetMap tiles. Checks: the central Beijing tiles aren't empty, the airport tile has bright pixels
# at the terminals (taxis queue there), and a tile far from Beijing is fully transparent. Then headless
# Chrome saves build/validate/step-4.png: each tile beside the OpenStreetMap tile and on top of it, for
# a person to look at (the roads must line up). SKIPPED when data/ is missing.
set -u
. "$(dirname "$0")/lib.sh"
cd "$ROOT" || exit 1

if ! ls data/raw/tdrive_txt/*.txt > /dev/null 2>&1; then
    echo "SKIPPED: no T-Drive files in data/raw/tdrive_txt"
    exit 0
fi
make --no-print-directory -s all > /dev/null || fail "build failed"
tdrive_gpt
out=$ROOT/build/validate/step-4
rm -rf "$out" && mkdir -p "$out" || exit 1

# Central Beijing at zooms 11-13, the airport taxi lot at zooms 13 and 15, and the sea east of Beijing at 11.
tiles="11/1686/776 12/3372/1552 13/6744/3104 13/6748/3099 15/26994/12396 11/1709/786"
for tile in $tiles; do
    IFS=/ read -r z x y <<< "$tile"
    build/gpstiles render "$TDRIVE_GPT" "$z" "$x" "$y" -o "$out/$z-$x-$y.png" > "$out/$z-$x-$y.txt" ||
        fail "render $tile failed"
done
ok "rendered: $(for t in $tiles; do printf '%s (%s) ' "$t" "$(cut -d' ' -f1 "$out/${t//\//-}.txt")"; done)"

python3 -I -B - "$ROOT/tests/oracle" "$out" <<'PY' || fail "a tile check failed (see above)"
import sys
sys.path.insert(0, sys.argv[1])
import tile_rules
out = sys.argv[2]

def pixels(name):
    return tile_rules.decode_png(open(f"{out}/{name}.png", "rb").read())[2]

for name in ("11-1686-776", "12-3372-1552", "13-6744-3104"):
    lit = sum(p[3] > 0 for row in pixels(name) for p in row)
    assert lit > 2000, f"{name}: only {lit} pixels lit in central Beijing"
    print(f"  ok  {name}: {lit:,} of 65,536 pixels lit")
# Capital Airport (zoom 13): taxis queue at the terminals, so some pixels must reach the upper half of
# the log scale: at least sqrt(densest pixel) points. The green channel is >= 0x49 exactly there.
rows = pixels("13-6748-3099")
bright = sum(p[3] > 0 and p[1] >= 0x49 for row in rows for p in row)
assert bright > 0, "no bright pixels at the airport"
print(f"  ok  airport tile 13/6748/3099: {bright} pixels in the upper half of the color scale")
assert all(p == (0, 0, 0, 0) for row in pixels("11-1709-786") for p in row), "a tile with no points isn't transparent"
print("  ok  11/1709/786 (the sea east of Beijing): fully transparent")
PY

# Side by side and overlaid on OpenStreetMap, for a person to look at. The reference tiles are downloaded
# first (6 tiles, a light use OpenStreetMap allows) and checked, so the picture shows exactly them.
loaded=0
for tile in $tiles; do
    name=${tile//\//-}
    if curl -sf -m 20 -A "gpstiles-validation/1.0 (local test of a heat-map tile server)" \
        -o "$out/osm-$name.png" "https://tile.openstreetmap.org/$tile.png" &&
        [ "$(head -c 8 "$out/osm-$name.png" | od -An -tx1 | tr -d ' \n')" = 89504e470d0a1a0a ]; then
        loaded=$((loaded + 1))
    fi
done
{
    echo '<!doctype html><meta charset="utf-8"><body style="margin:0;background:#111;color:#ddd;font:12px sans-serif">'
    for tile in $tiles; do
        name=${tile//\//-}
        echo "<div style=\"display:inline-block;margin:6px\"><div>$tile</div>"
        echo "<img src=\"osm-$name.png\" width=256 height=256><img src=\"$name.png\" width=256 height=256 style=\"background:#000\">"
        echo "<span style=\"position:relative;display:inline-block;width:256px;height:256px\"><img src=\"osm-$name.png\" style=\"position:absolute;filter:grayscale(1) brightness(.6)\"><img src=\"$name.png\" style=\"position:absolute\"></span></div>"
    done
} > "$out/compare.html"
chrome="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
if [ ! -x "$chrome" ]; then
    echo "  --  no Chrome: open build/validate/step-4/compare.html yourself"
    exit 0
fi
rm -f "$ROOT/build/validate/step-4.png" # an old picture must never pass for a new one
"$chrome" --headless=new --disable-gpu --hide-scrollbars --no-first-run --no-default-browser-check \
    --user-data-dir="$out/chrome" --window-size=1600,1700 --virtual-time-budget=10000 \
    --screenshot="$ROOT/build/validate/step-4.png" "file://$out/compare.html" > /dev/null 2>&1 ||
    fail "headless Chrome failed"
rm -rf "$out/chrome"
[ -s "$ROOT/build/validate/step-4.png" ] || fail "headless Chrome saved no screenshot"
count=$(echo $tiles | wc -w | tr -d ' ')
if [ "$loaded" = "$count" ]; then
    ok "screenshot for a person to check: build/validate/step-4.png (all $count OpenStreetMap tiles downloaded and checked)"
else
    echo "  --  SKIPPED (the picture): only $loaded of $count OpenStreetMap tiles downloaded (no internet?); the tile checks above still ran"
fi
