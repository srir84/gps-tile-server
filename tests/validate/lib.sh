# lib.sh: helpers shared by tests/validate/step-N.sh (TESTING.md §12.4). Sourced, not run.
# Deliberate breaks happen only in a scratch copy, never in the real tree.

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
NAME=$(basename "$0" .sh)

# Leftover git variables (e.g. from a hook) would point git at the real repo.
for name in $(env | sed -n 's/^\(GIT_[A-Za-z0-9_]*\)=.*/\1/p'); do
    unset "$name"
done

fail() {
    echo "FAIL $NAME: $*"
    exit 1
}

ok() {
    echo "  ok  $*"
}

# Copies the repo, without build/, data/, dist/, .git and .review, to a temp folder that is
# deleted on exit, and moves there. Logs go to $SCRATCH/log.
scratch_copy() {
    SCRATCH=$(mktemp -d "${TMPDIR:-/tmp}/gpstiles-$NAME.XXXXXX") || exit 1
    trap 'rm -rf "$SCRATCH"' EXIT
    mkdir "$SCRATCH/repo" || exit 1
    # Top-level names only: BSD tar's --exclude ./data would also drop tests/data.
    local item
    for item in "$ROOT"/* "$ROOT"/.[!.]*; do
        case ${item##*/} in build | data | dist | .git | .review | '.[!.]*') continue ;; esac
        cp -R "$item" "$SCRATCH/repo/" || fail "copy failed"
    done
    cd "$SCRATCH/repo" || exit 1
}

# The deliberately failing test: one passing check in tests/unit/test_runner.c made false.
break_unit_test() {
    local file=tests/unit/test_runner.c
    sed 's/CHECK(1 + 1 == 2);/CHECK(1 + 1 == 3);/' "$file" > "$file.new" && mv "$file.new" "$file"
    grep -q 'CHECK(1 + 1 == 3);' "$file" || fail "could not insert the failing test"
}

# Imports and builds T-Drive into build/validate/ with the current gpstiles, once: reused while newer
# than build/gpstiles. Sets TDRIVE_PTS and TDRIVE_GPT. Needs data/raw/tdrive_txt (check before calling).
tdrive_gpt() {
    TDRIVE_PTS=$ROOT/build/validate/tdrive.pts
    TDRIVE_GPT=$ROOT/build/validate/tdrive.gpt
    if [ "$TDRIVE_GPT" -nt "$ROOT/build/gpstiles" ] && [ "$TDRIVE_PTS" -nt "$ROOT/build/gpstiles" ]; then
        return 0
    fi
    mkdir -p "$ROOT/build/validate" || exit 1
    rm -f "$TDRIVE_PTS" "$TDRIVE_GPT"
    # Relative paths: 8,911 absolute ones could pass the argument size limit.
    (cd "$ROOT" && build/gpstiles import --lon-col 3 --lat-col 4 -o "$TDRIVE_PTS" data/raw/tdrive_txt/*.txt > /dev/null) ||
        fail "T-Drive import failed"
    "$ROOT/build/gpstiles" build -o "$TDRIVE_GPT" "$TDRIVE_PTS" > /dev/null || fail "T-Drive build failed"
}

# Imports and builds tdrive-sample, the first 500 T-Drive files in name order, into build/validate/ the same
# way (step 5a: a second, smaller dataset). Sets TDRIVE_SAMPLE_GPT. Needs data/raw/tdrive_txt.
tdrive_sample_gpt() {
    TDRIVE_SAMPLE_GPT=$ROOT/build/validate/tdrive-sample.gpt
    local pts=$ROOT/build/validate/tdrive-sample.pts
    if [ "$TDRIVE_SAMPLE_GPT" -nt "$ROOT/build/gpstiles" ] && [ "$pts" -nt "$ROOT/build/gpstiles" ]; then
        return 0
    fi
    mkdir -p "$ROOT/build/validate" || exit 1
    rm -f "$pts" "$TDRIVE_SAMPLE_GPT"
    # shellcheck disable=SC2046 # the names have no spaces
    (cd "$ROOT" && build/gpstiles import --lon-col 3 --lat-col 4 -o "$pts" $(ls data/raw/tdrive_txt/*.txt | sort | head -500) > /dev/null) ||
        fail "tdrive-sample import failed"
    "$ROOT/build/gpstiles" build -o "$TDRIVE_SAMPLE_GPT" "$pts" > /dev/null || fail "tdrive-sample build failed"
}
