#!/bin/bash
# step-0b.sh: validates step 0b (DESIGN §12.2). In a scratch copy with its own git repo: a
# deliberately failing test is blocked by the Stop hook and refused by the pre-commit hook.
set -u
. "$(dirname "$0")/lib.sh"
scratch_copy

# Isolated from the developer's git config (identity, global hooks, signing).
export GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null
export GIT_AUTHOR_NAME=validate GIT_AUTHOR_EMAIL=validate@localhost
export GIT_COMMITTER_NAME=validate GIT_COMMITTER_EMAIL=validate@localhost

git init -q && git add -A && git commit -q -m base || fail "could not make the scratch repo"
make --no-print-directory hooks > "$SCRATCH/log" 2>&1 || fail "make hooks failed: $(cat "$SCRATCH/log")"
[ -x .git/hooks/pre-commit ] || fail "make hooks did not install .git/hooks/pre-commit"
ok "make hooks installs the pre-commit hook"

# The Stop hook is wired to tools/stop-gate.sh (the file Claude Code reads).
python3 -I -c 'import json, sys
hooks = json.load(open(".claude/settings.json"))["hooks"]["Stop"]
sys.exit(0 if any(h["command"].endswith("/tools/stop-gate.sh") for g in hooks for h in g["hooks"]) else 1)' ||
    fail ".claude/settings.json has no Stop hook running tools/stop-gate.sh"
ok ".claude/settings.json runs tools/stop-gate.sh on Stop"

stop_gate() {
    echo '{"hook_event_name":"Stop","stop_hook_active":false}' | tools/stop-gate.sh 2> "$SCRATCH/gate.err"
}

# 1. The failing test: the Stop hook blocks, the commit is refused.
break_unit_test
stop_gate
status=$?
[ "$status" -eq 2 ] || fail "Stop hook exit $status with a failing test, expected 2 (block)"
grep -q '^FAIL tests/unit/test_runner.c:7' "$SCRATCH/gate.err" || fail "Stop hook did not send the FAIL line back"
ok "Stop hook blocks (exit 2) and sends back the FAIL line"

head_before=$(git rev-parse HEAD)
git add -A
if git commit -q -m broken > "$SCRATCH/log" 2>&1; then
    fail "the commit with a failing test went through"
fi
[ "$(git rev-parse HEAD)" = "$head_before" ] || fail "HEAD moved after a refused commit"
grep -q 'pre-commit: commit refused' "$SCRATCH/log" || fail "no refusal message from the pre-commit hook"
ok "pre-commit hook refuses the commit"

# 2. Fixed: the Stop hook lets the agent stop, and a good change commits.
git checkout -q HEAD -- tests/unit/test_runner.c
echo '/* harmless change */' >> tests/unit/test_runner.c
stop_gate || fail "Stop hook blocked after the fix: $(cat "$SCRATCH/gate.err")"
ok "after the fix the Stop hook lets the agent stop"
git add -A
git commit -q -m fixed > "$SCRATCH/log" 2>&1 || fail "a good commit was refused: $(tail -n 5 "$SCRATCH/log")"
ok "after the fix the commit goes through"

# 3. The hook tests what is staged, not the working tree.
git reset -q
break_unit_test
echo '# notes' >> docs/TESTING.md
git add docs/TESTING.md
git commit -q -m staged-only > "$SCRATCH/log" 2>&1 ||
    fail "a good staged change was refused because of an unstaged break: $(tail -n 5 "$SCRATCH/log")"
ok "pre-commit tests the staged files, not unstaged edits"
