#!/bin/bash
# review.sh: Codex reviews step N, read-only, in a fresh context (TESTING.md §12.3).
# Usage: tools/review.sh N → .review/step-N/round-K.md (K = 1, then 2; at most 2 rounds).
set -u
cd "$(dirname "$0")/.." || exit 1
CODEX=${CODEX_BIN:-codex} # the tests swap in a fake codex

step=${1:-}
case $step in
    [0-9] | [0-9][a-z] | [1-9][0-9]) ;;
    *)
        echo "usage: tools/review.sh N   (a step from DESIGN §12.2 or §12.4, e.g. 1, 3a or 10)" >&2
        exit 2
        ;;
esac

# Only the step tables: DESIGN §12 (build plan) and TESTING §9. Other tables have rows like "| 12 | header_size |".
design_rows=$(sed -n '/^## 12\. /,/^## 13\. /p' docs/DESIGN.md | grep -E "^\| $step[ |]")
testing_row=$(sed -n '/^## 9\. /,/^## 10\. /p' docs/TESTING.md | grep -E "^\| $step \|")
if [ -z "$design_rows" ] || [ -z "$testing_row" ]; then
    echo "review.sh: step $step has no rows in DESIGN §12.2/§12.4 or TESTING §9" >&2
    exit 2
fi

dir=.review/step-$step
lock=.review/step-$step.lock
mkdir -p .review || exit 1
# One review per step at a time. mkdir is atomic, so a second run is refused here.
if ! mkdir "$lock" 2>/dev/null; then
    echo "review.sh: a review of step $step is already running (if it crashed, remove $lock)" >&2
    exit 1
fi
tmp_index=
trap 'rmdir "$lock"; if [ -n "$tmp_index" ]; then rm -f "$tmp_index"; fi' EXIT

if [ -e "$dir/round-2.md" ]; then
    echo "review.sh: step $step already had 2 review rounds (TESTING.md §12.8). The developer decides on what is left." >&2
    exit 1
fi
round=1
if [ -e "$dir/round-1.md" ]; then
    round=2
fi
mkdir -p "$dir" || exit 1
diff_file=$dir/round-$round.diff
prompt_file=$dir/round-$round.prompt.md
out_file=$dir/round-$round.md

# Base: the last commit (the last approved step), or the empty tree before the first commit.
if ! base=$(git rev-parse -q --verify 'HEAD^{commit}'); then
    base=$(git hash-object -t tree /dev/null)
fi

# The full change, new files included, built in a temporary index so the real one (and so the
# next commit) is untouched. The builder's own notes (step file, PROGRESS.md) are left out, and so is
# Leaflet (www/leaflet/): the release as published, minified, pinned by its official hash and tested.
tmp_index=$(mktemp "${TMPDIR:-/tmp}/gpstiles-review-index.XXXXXX") || exit 1
cp "$(git rev-parse --git-path index)" "$tmp_index" 2>/dev/null || rm -f "$tmp_index"
GIT_INDEX_FILE=$tmp_index git add -A || exit 1
GIT_INDEX_FILE=$tmp_index git diff --cached "$base" -- . \
    ':(exclude,glob)docs/steps/step-*.md' ':(exclude)PROGRESS.md' ':(exclude)www/leaflet' > "$diff_file" || exit 1
if [ ! -s "$diff_file" ]; then
    echo "review.sh: no changes since $base to review" >&2
    rm -f "$diff_file"
    exit 1
fi

{
    cat <<EOF
You are reviewing step $step of gps-tile-server. You are read-only: never edit, create or delete files.
Don't run make (the sandbox can't write build/). Reading files and git commands are fine.

The rules are in AGENTS.md. The design is docs/DESIGN.md, the test plan docs/TESTING.md.
The full change for this step, new files included, is in $diff_file (base $base).

What this step must build (DESIGN §12.2, or §12.4 for stage 2):
$design_rows

Tests this step must add (TESTING §9):
$testing_row

Look for: bugs, missing or weak tests, security problems where outside input enters
(files, HTTP, command line, environment), and drift from DESIGN, TESTING or AGENTS.
Skip style preferences.
For each finding give: severity (high, medium or low), file:line, what goes wrong and
how to trigger it, and a suggested fix.
EOF
    if [ "$round" -eq 2 ]; then
        cat <<EOF

This is round 2. Your round-1 findings are in $dir/round-1.md. For each one, say
fixed, partly fixed or not fixed, with file:line. Then list any new findings.
EOF
    fi
    cat <<EOF

End with exactly one line: SUMMARY: high=N medium=N low=N
EOF
} > "$prompt_file"

echo "review.sh: step $step, round $round. Codex is reviewing (this takes minutes)..."
if ! "$CODEX" exec -s read-only -C "$(pwd)" -o "$out_file" - < "$prompt_file" > "$dir/round-$round.log" 2>&1 ||
    [ ! -s "$out_file" ]; then
    rm -f "$out_file" # a failed run doesn't use up a round
    echo "review.sh: codex failed. Its output is in $dir/round-$round.log" >&2
    exit 1
fi
# A reply that doesn't end with the SUMMARY line was cut short or ignored the format. It is kept
# for reading but doesn't use up a round.
summary=$(grep -v '^[[:space:]]*$' "$out_file" | tail -n 1)
if ! printf '%s\n' "$summary" | grep -Eq '^SUMMARY: high=[0-9]+ medium=[0-9]+ low=[0-9]+[[:space:]]*$'; then
    mv "$out_file" "$dir/round-$round.invalid.md"
    echo "review.sh: Codex's reply doesn't end with a SUMMARY line. Kept as $dir/round-$round.invalid.md. Run again." >&2
    exit 1
fi
echo "review.sh: wrote $out_file"
echo "$summary"
