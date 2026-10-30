#!/bin/bash
# step-2.sh: validates step 2 (DESIGN §12.2): `gpstiles import` on all of T-Drive prints the
# DESIGN §13 counts and writes 8 bytes per kept point. SKIPPED when data/ is missing.
set -u
. "$(dirname "$0")/lib.sh"
cd "$ROOT" || exit 1
expected="rows=10088351 imported=10064891 skipped_zero=23357 skipped_out_of_range=103 skipped_malformed=0"

# Project files must never be git-ignored (Codex step 2 round 1: "data/" also hid tests/data/).
ignored=$(git ls-files --others --ignored --exclude-standard -- src tests tools docs Makefile |
    grep -v -e '\.DS_Store$' -e '__pycache__/')
[ -z "$ignored" ] || fail "git ignores project files: $(echo $ignored)"
ok "no file in src/, tests/, tools/ or docs/ is git-ignored"

if ! ls data/raw/tdrive_txt/*.txt > /dev/null 2>&1; then
    echo "SKIPPED: no T-Drive files in data/raw/tdrive_txt"
    exit 0
fi
make --no-print-directory -s all > /dev/null || fail "build failed"
out=$(mktemp -d "${TMPDIR:-/tmp}/gpstiles-$NAME.XXXXXX") || exit 1
trap 'rm -rf "$out"' EXIT

got=$(build/gpstiles import --lon-col 3 --lat-col 4 -o "$out/tdrive.pts" data/raw/tdrive_txt/*.txt) ||
    fail "import exited non-zero"
[ "$got" = "$expected" ] || fail "import printed '$got', expected '$expected'"
ok "import → $got"

size=$(wc -c < "$out/tdrive.pts" | tr -d ' ')
[ "$size" = $((10064891 * 8)) ] || fail ".pts is $size bytes, expected $((10064891 * 8))"
ok "tdrive.pts is $size bytes = 10,064,891 points × 8"
