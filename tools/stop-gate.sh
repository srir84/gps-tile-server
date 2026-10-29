#!/bin/bash
# stop-gate.sh: Claude Code Stop hook (TESTING.md §12.2). While src/, tests/ or the Makefile differ
# from the last commit, the agent can't end its turn until `make check` passes. Exit 2 = blocked.
set -u
cd "$(dirname "$0")/.." || exit 0
cat > /dev/null # Claude Code sends JSON on stdin. Not needed: the block counter is kept here.

CHECK_CMD=${STOP_GATE_CHECK:-make -s --no-print-directory check} # -s: no compiler lines; the tests use a fake
MAX_BLOCKS=3
COUNTER=build/stop-gate.count

if ! changed=$(git status --porcelain --untracked-files=all -- src tests Makefile 2>/dev/null); then
    changed="git status failed" # can't tell what changed, so check
fi
if [ -z "$changed" ]; then
    rm -f "$COUNTER"
    exit 0
fi

if output=$(/bin/sh -c "$CHECK_CMD" 2>&1); then
    rm -f "$COUNTER"
    exit 0
fi

blocks=$(cat "$COUNTER" 2>/dev/null)
case $blocks in '' | *[!0-9]*) blocks=0 ;; esac
if [ "$blocks" -ge "$MAX_BLOCKS" ]; then
    rm -f "$COUNTER"
    echo "stop-gate: make check still fails after $MAX_BLOCKS blocks in a row. Letting the agent stop." >&2
    exit 0
fi

blocks=$((blocks + 1))
mkdir -p build && echo "$blocks" > "$COUNTER"
{
    echo "stop-gate: make check fails (block $blocks of $MAX_BLOCKS). Fix it before ending the turn."
    if [ "$blocks" -eq "$MAX_BLOCKS" ]; then
        echo "Last block. If you can't fix it, write the problem under \"Blocked on\" in PROGRESS.md, then stop."
    fi
    echo "--- last 40 lines of: $CHECK_CMD"
    printf '%s\n' "$output" | tail -n 40
} >&2
exit 2
