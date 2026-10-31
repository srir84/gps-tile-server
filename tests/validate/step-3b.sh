#!/bin/bash
# step-3b.sh: validates step 3b (DESIGN §12.2): `gpstiles info` on T-Drive prints 10,064,891 points, the
# bounds and the view box, and `count` on the Beijing tile 10/843/388 equals the sum of its 4 smaller
# tiles and a slow count in Python over every point of the .pts. SKIPPED when data/ is missing.
set -u
. "$(dirname "$0")/lib.sh"
cd "$ROOT" || exit 1

if ! ls data/raw/tdrive_txt/*.txt > /dev/null 2>&1; then
    echo "SKIPPED: no T-Drive files in data/raw/tdrive_txt"
    exit 0
fi
make --no-print-directory -s all > /dev/null || fail "build failed"
tdrive_gpt

info=$(build/gpstiles info "$TDRIVE_GPT") || fail "info exited non-zero"
echo "$info" | sed 's/^/      /'
[ "$(echo "$info" | sed -n 's/^points=//p')" = 10064891 ] || fail "info doesn't say points=10064891"
for name in bounds view; do
    echo "$info" | grep -Eq "^$name=-?[0-9]+\.[0-9]{6}(,-?[0-9]+\.[0-9]{6}){3}$" || fail "info has no $name in degrees"
done
ok "info: points=10064891 (DESIGN §13), bounds and view box printed"

count() {
    build/gpstiles count "$TDRIVE_GPT" "$@" | sed -n 's/^points=//p'
}
parent=$(count 10 843 388)
children=$(($(count 11 1686 776) + $(count 11 1687 776) + $(count 11 1686 777) + $(count 11 1687 777)))
[ -n "$parent" ] && [ "$parent" = "$children" ] || fail "10/843/388 = '$parent', its 4 zoom-11 tiles add up to $children"
ok "count 10/843/388 = $parent = the sum of its 4 zoom-11 tiles"

slow=$(python3 -I -B - "$TDRIVE_PTS" <<'PY'
import array, sys
codes = array.array("Q")
with open(sys.argv[1], "rb") as f:
    codes.frombytes(f.read())
if sys.byteorder == "big":
    codes.byteswap()
x, y, prefix = 843, 388, 0  # the tile's top 20 bits: x in the even bits, y in the odd bits
for i in range(10):
    prefix |= ((x >> i) & 1) << (2 * i) | ((y >> i) & 1) << (2 * i + 1)
print(sum(1 for c in codes if c >> 44 == prefix))
PY
)
[ "$slow" = "$parent" ] || fail "Python's slow count of 10/843/388 is $slow, gpstiles says $parent"
ok "Python's slow count over every point of the .pts agrees: $slow"
