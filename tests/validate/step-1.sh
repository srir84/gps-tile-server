#!/bin/bash
# step-1.sh: validates step 1 (DESIGN §12.2): `gpstiles where` prints the known tiles of DESIGN §13.
# Opening the tile on openstreetmap.org is done by hand once and shown in docs/steps/step-1.md.
set -u
. "$(dirname "$0")/lib.sh"
cd "$ROOT" || exit 1
make --no-print-directory -s all > /dev/null || fail "build failed"

expect_tile() {
    local got
    got=$(build/gpstiles where "$1" "$2" --zoom "$3" 2>&1) || fail "where $1 $2 --zoom $3 exited non-zero: $got"
    [ "$got" = "$4" ] || fail "where $1 $2 --zoom $3 printed '$got', expected '$4'"
    ok "where $1 $2 --zoom $3 → $got"
}

expect_tile 116.391 39.907 10 10/843/388
expect_tile -74.006 40.7128 12 12/1205/1540
