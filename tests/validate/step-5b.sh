#!/bin/bash
# step-5b.sh: validates step 5b (DESIGN §12.2, TESTING.md §12.6) before approval: `make deploy-test`, the
# whole deploy cycle with a test label of its own in build/deploy-test/ on a free port: bad releases refused
# or rolled back, a killed server restarted by launchd, `rollback` and `status`, and nothing left
# afterwards (see tools/deploy-test.sh). Never touches the real service.
# SKIPPED on a system without launchd.
set -u
. "$(dirname "$0")/lib.sh"
cd "$ROOT" || exit 1

if ! command -v launchctl > /dev/null; then
    echo "SKIPPED: no launchctl (the local service is for macOS)"
    exit 0
fi
make --no-print-directory -s all > /dev/null || fail "build failed"
output=$(make --no-print-directory -s deploy-test 2>&1) || fail "make deploy-test failed: $(echo "$output" | tail -5)"
echo "$output" | grep '^  ok ' || fail "make deploy-test printed no ok lines"
echo "$output" | grep -q '^DEPLOY-TEST PASSED$' || fail "make deploy-test didn't pass"
label=local.gpstiles.test-$(printf '%s' "$ROOT" | cksum | cut -d' ' -f1) # as tools/deploy-test.sh names it
if launchctl print "gui/$(id -u)/$label" > /dev/null 2>&1; then
    fail "the test service is still loaded"
fi
[ ! -e build/deploy-test ] || fail "build/deploy-test is still there"
ok "make deploy-test passed and left nothing behind"
