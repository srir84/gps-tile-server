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
    (cd "$ROOT" && tar -cf - --exclude ./build --exclude ./data --exclude ./dist \
        --exclude ./.git --exclude ./.review .) | (cd "$SCRATCH/repo" && tar -xf -) || fail "copy failed"
    cd "$SCRATCH/repo" || exit 1
}

# The deliberately failing test: one passing check in tests/unit/test_runner.c made false.
break_unit_test() {
    local file=tests/unit/test_runner.c
    sed 's/CHECK(1 + 1 == 2);/CHECK(1 + 1 == 3);/' "$file" > "$file.new" && mv "$file.new" "$file"
    grep -q 'CHECK(1 + 1 == 3);' "$file" || fail "could not insert the failing test"
}
