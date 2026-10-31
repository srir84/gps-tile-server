#!/bin/bash
# step-3a.sh: validates step 3a (DESIGN §12.2): T-Drive built twice, with the default --mem and with
# --mem 1M (~77 runs). The two files are identical, the header counts 10,064,891 points, peak memory
# stays below --mem + 16 MiB, and no temp files are left. Before that, the memory rule at 256 runs and the
# 257-run refusal, which need no data. (Points against Python's sort: make check-data.) The T-Drive part
# is SKIPPED when data/ is missing.
set -u
. "$(dirname "$0")/lib.sh"
cd "$ROOT" || exit 1

make --no-print-directory -s all > /dev/null || fail "build failed"
out=$(mktemp -d "${TMPDIR:-/tmp}/gpstiles-$NAME.XXXXXX") || exit 1
trap 'rm -rf "$out"' EXIT
mkdir "$out/runs" || exit 1

# The memory rule at the run limit (needs no T-Drive): 256 MiB of codes at --mem 1M is exactly 256 runs,
# where the merge reads 256 runs at once. The input is sparse (zeros, no disk space); 257 runs are
# refused at once.
truncate_to() {
    python3 -I -c 'import sys; open(sys.argv[1], "wb").truncate(int(sys.argv[2]))' "$1" "$2"
}
truncate_to "$out/zeros.pts" $((256 * 1024 * 1024))
/usr/bin/time -l build/gpstiles build --mem 1M --tmp "$out/runs" -o "$out/zeros.gpt" "$out/zeros.pts" > "$out/zeros.out" 2> "$out/zeros.time" ||
    fail "the 256-run build exited non-zero: $(head -1 "$out/zeros.time")"
[ "$(cat "$out/zeros.out")" = "points=33554432 runs=256" ] || fail "the 256-run build printed '$(cat "$out/zeros.out")'"
peak=$(awk '/maximum resident set size/ {print $1}' "$out/zeros.time")
[ -n "$peak" ] && [ "$peak" -lt $((17 * 1024 * 1024)) ] || fail "256 runs at --mem 1M: peak memory $peak bytes, limit 17 MiB"
ok "256 runs at --mem 1M → $(cat "$out/zeros.out") · peak memory $((peak / 1024 / 1024)) MiB < --mem + 16 MiB"
rm -f "$out/zeros.gpt"
truncate_to "$out/zeros.pts" $((256 * 1024 * 1024 + 8))
message=$(build/gpstiles build --mem 1M --tmp "$out/runs" -o "$out/zeros.gpt" "$out/zeros.pts" 2>&1)
[ $? -eq 2 ] && [ ! -e "$out/zeros.gpt" ] || fail "257 runs at --mem 1M were not refused: $message"
ok "257 runs refused before any work: $message"
left=$(ls -A "$out/runs"; ls -A "$out" | grep -v -x -E -e 'runs|zeros\.(pts|out|time)')
[ -z "$left" ] || fail "temp files left: $(echo $left)"
rm -f "$out"/zeros.*

if ! ls data/raw/tdrive_txt/*.txt > /dev/null 2>&1; then
    echo "SKIPPED (the T-Drive part): no T-Drive files in data/raw/tdrive_txt"
    exit 0
fi

build/gpstiles import --lon-col 3 --lat-col 4 -o "$out/tdrive.pts" data/raw/tdrive_txt/*.txt > /dev/null ||
    fail "import exited non-zero"

# Runs one build under /usr/bin/time -l and checks its output line and peak memory.
# Arguments: name, --mem in MiB, expected runs, then the build options.
build_one() {
    local name=$1 mem_mib=$2 runs=$3
    shift 3
    /usr/bin/time -l build/gpstiles build "$@" -o "$out/$name.gpt" "$out/tdrive.pts" > "$out/$name.out" 2> "$out/$name.time" ||
        fail "build $name exited non-zero: $(head -1 "$out/$name.time")"
    local got
    got=$(cat "$out/$name.out")
    [ "$got" = "points=10064891 runs=$runs" ] || fail "build $name printed '$got'"
    local peak limit=$(((mem_mib + 16) * 1024 * 1024))
    peak=$(awk '/maximum resident set size/ {print $1}' "$out/$name.time")
    [ -n "$peak" ] && [ "$peak" -lt "$limit" ] || fail "build $name peak memory $peak bytes, limit $limit"
    ok "build $name → $got · peak memory $((peak / 1024 / 1024)) MiB < --mem + 16 MiB"
}

build_one default 1024 1
build_one mem-1M 1 77 --mem 1M --tmp "$out/runs"

cmp -s "$out/default.gpt" "$out/mem-1M.gpt" || fail "the two builds differ"
ok "the default and --mem 1M builds are byte-for-byte identical"

count=$(od -An -t u8 -j 16 -N 8 "$out/default.gpt" | tr -d ' ')
[ "$count" = 10064891 ] || fail "header count $count, expected 10064891"
size=$(wc -c < "$out/default.gpt" | tr -d ' ')
[ "$size" = $((256 + 10064891 * 8)) ] || fail ".gpt is $size bytes"
ok "header count $count · file $size bytes = 256 + 10,064,891 × 8"

# Exact names only: a pattern like 'default\..*' would also hide default.gpt.tmp-XXXXXX.
left=$(ls -A "$out/runs"; ls -A "$out" | grep -v -x -E -e 'runs|tdrive\.pts|(default|mem-1M)\.(gpt|out|time)')
[ -z "$left" ] || fail "temp files left: $(echo $left)"
ok "no temp files left in --tmp or next to the output"
