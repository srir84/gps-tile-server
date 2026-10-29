#!/bin/bash
# step-0a.sh: validates step 0a (DESIGN §12.2). In a scratch copy: make check passes, then a
# deliberately failing test makes it exit non-zero and print the test's catches: line.
set -u
. "$(dirname "$0")/lib.sh"
scratch_copy

make --no-print-directory check > "$SCRATCH/log" 2>&1 || fail "make check fails on an unchanged copy"
ok "make check passes on an unchanged copy"

break_unit_test
if make --no-print-directory check > "$SCRATCH/log" 2>&1; then
    fail "make check passed with a failing test"
fi
grep -q '^FAIL tests/unit/test_runner.c:7 passing_checks_count_as_pass$' "$SCRATCH/log" ||
    fail "no FAIL line with file:line and test name"
grep -q '^  catches: the runner reports a passing check as a failure' "$SCRATCH/log" ||
    fail "no catches: line"
ok "a failing test makes make check exit non-zero and prints FAIL + catches:"
