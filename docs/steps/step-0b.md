# Step 0b: Loop tools (verify, hooks, Codex review)

## Summary

| | |
|---|---|
| **Built** | `make verify`, `make check-data` (placeholder), `make hooks` + `tools/pre-commit`, Stop hook (`.claude/settings.json` + `tools/stop-gate.sh`), `tools/review.sh`, validation scripts for steps 0a and 0b |
| **Status** | approved |
| **Date** | 2026-10-28 |
| **Agent(s)** | Claude Opus 5.5 (builder) · Codex CLI 0.162.1 (reviewer, read-only, via `tools/review.sh`) · Claude Haiku (one headless run to see the Stop hook fire live) |

## Design
- **Three guards, one failing test.** A red `make check` now stops an agent at three points: ending its turn (Stop hook), committing (pre-commit hook), and `make verify`.
- **The Stop hook only runs when code changed.** If `src/`, `tests/` or the `Makefile` differ from the last commit, it runs `make -s check`. Red → exit 2, and the last 40 lines go back to the agent. After 3 blocks in a row it lets the agent stop and tells it to write "Blocked on".
- **The pre-commit hook tests what is being committed.** It exports the staged files to a temp folder and runs `make check` + `make sanitize` there. Unstaged edits can't make a commit pass or fail.
- **The review script is the loop's second opinion.** `tools/review.sh N` gives Codex the step's full diff (new files included, built in a temporary index), the step's DESIGN and TESTING rows, and nothing from the builder. Codex runs read-only. Rounds are kept in `.review/step-N/` and capped at 2.
- **Validation scripts are kept forever.** `tests/validate/step-0a.sh` and `step-0b.sh` break a test in a scratch copy and check that each guard catches it. `make verify` runs every one of them.

```text
deliberately failing test (in a scratch copy)
 ├─ agent tries to end its turn ─► tools/stop-gate.sh ─► exit 2, FAIL line sent back   (block 1, 2, 3, then let go)
 ├─ git commit ─────────────────► tools/pre-commit ───► make check fails on the staged files ─► commit refused
 └─ make verify ────────────────► make check fails ───► "VERIFY FAILED at: make check"

make verify = check → sanitize → check-data → tests/validate/step-*.sh, stops at the first red part
tools/review.sh 0b → .review/step-0b/round-1.{diff,prompt.md,md,log}
```

## Files changed

| File | Change | Why |
|---|---|---|
| `Makefile` | changed | `check-data` (placeholder until step 2), `verify`, `hooks` |
| `.gitignore` | changed | `.review/` (review rounds) |
| `.claude/settings.json` | added | Stop hook → `tools/stop-gate.sh`. JSON can't hold the usual purpose comment |
| `tools/stop-gate.sh` | added | the Stop hook |
| `tools/pre-commit` | added | the pre-commit hook. `make hooks` links `.git/hooks/pre-commit` to it |
| `tools/review.sh` | added | Codex review, read-only, max 2 rounds |
| `tests/validate/lib.sh`, `step-0a.sh`, `step-0b.sh` | added | step validations, run by `make verify` |
| `tests/e2e/test_stop_gate.py` | added | 6 tests: the Stop gate with a fake check |
| `tests/e2e/test_review_script.py` | added | 9 tests: the review script with a fake codex |
| `docs/TESTING.md` §5, §12.2–§12.5 | changed | layout, and what was built (see Decisions) |
| `AGENTS.md`, `docs/DESIGN.md` §10 + §12.2, `docs/steps/TEMPLATE.md` | changed | review files in `.review/`, staged-files pre-commit |
| `PROGRESS.md` | changed | 0a approved (`d29b501`), 0b status |

639 lines in 11 new files, plus 26 Makefile lines. Review the full change: `.review/step-0b/round-2.diff` (the final one).

## Tests

| Test | Checks | Bug it would catch |
|---|---|---|
| `test_red_check_blocks_the_stop_and_shows_the_failure` | red + code changed → exit 2, "block 1 of 3", the FAIL line | the agent ends its turn while tests fail, or is blocked without seeing why |
| `test_green_check_lets_the_agent_stop` | green → exit 0, nothing printed | the agent can never finish |
| `test_new_and_changed_code_files_all_trigger_the_check` | new test file, nested test file, `Makefile`, new `src/` file | a change the gate doesn't see lets a red check slip past |
| `test_no_code_change_skips_the_check` | clean tree or docs-only edits → exit 0 even if red | an unrelated red check blocks every turn |
| `test_three_blocks_in_a_row_then_the_agent_may_stop` | 2, 2, 2 (with "Blocked on"), then 0, then counting starts again | endless loop, or letting go too early |
| `test_a_green_check_resets_the_count` | red, red, green, red → "block 1 of 3" | blocks from a fixed problem count toward the limit |
| `test_diff_has_new_files_but_not_the_builders_notes` | new file + edit in the diff, step file and PROGRESS not | new files missing from the review, or the builder's summary steering it |
| `test_real_index_is_left_alone` | `git status` and the staged list unchanged | the next commit quietly contains more than intended |
| `test_codex_is_read_only_and_told_what_the_step_must_do` | `exec -s read-only`, the step's DESIGN + TESTING rows only, SUMMARY printed | Codex with write access, or reviewing blind |
| `test_round_two_checks_round_one_and_round_three_is_refused` | round 2 prompt names `round-1.md` · 3rd run exit 1 | unlimited rounds, round-1 fixes never checked |
| `test_failed_codex_run_does_not_use_up_a_round` | fake codex exits 1 → no `round-1.md`, next run is round 1 | an offline Codex run counts as a review |
| `test_reply_without_summary_does_not_use_up_a_round` | reply with no `SUMMARY:` line → exit 1, kept as `round-1.invalid.md`, next run is round 1 | a cut-short reply counts as a round (Codex round 1) |
| `test_second_review_of_the_same_step_is_refused_while_one_runs` | a 2nd run while one runs → exit 1 "already running", the 1st run's files intact, lock removed | two reviews overwrite each other's files (Codex round 1) |
| `test_lock_is_released_after_a_failed_run` | lock gone after a failed run | a crashed review blocks every later one |
| `test_bad_or_unknown_step_names_are_refused` | `../x`, empty, `0b; rm -rf /`, `12`, unknown `7` → exit 2, codex not run | writing outside `.review/`, or reviewing with no step rows |
| `tests/validate/step-0a.sh` | scratch copy: green, then a failing test → `make check` red with FAIL + `catches:` | `make check` stops catching failures |
| `tests/validate/step-0b.sh` | scratch repo: `make hooks` installs · settings run the gate · failing test → gate exit 2 + FAIL line, commit refused, HEAD unchanged · fixed → gate lets go, commit OK · unstaged break + good staged change → commit OK | any guard stops working, or the hook tests the wrong files |

```text
make check     unit 1 passed 0 failed · e2e 33 passed 0 failed · ALL PASSED (build)       6.3 s
make sanitize  unit 1 passed 0 failed · e2e 33 passed 0 failed · ALL PASSED (build/san)
make check-data  check-data: no real-data checks yet
make verify (from make clean, after the review fixes): exit 0
--- tests/validate/step-0a.sh
  ok  make check passes on an unchanged copy
  ok  a failing test makes make check exit non-zero and prints FAIL + catches:
--- tests/validate/step-0b.sh
  ok  make hooks installs the pre-commit hook
  ok  .claude/settings.json runs tools/stop-gate.sh on Stop
  ok  Stop hook blocks (exit 2) and sends back the FAIL line
  ok  pre-commit hook refuses the commit
  ok  after the fix the Stop hook lets the agent stop
  ok  after the fix the commit goes through
  ok  pre-commit tests the staged files, not unstaged edits
VERIFY PASSED
```

## Review (Codex)

Run with `tools/review.sh 0b` (its first real use). Files in `.review/step-0b/`.

| Round | Finding (severity, file:line) | What happened |
|---|---|---|
| 1 | Medium, `tools/review.sh:91–98`: a reply without the `SUMMARY:` line was kept and used up a round. Two bad replies would end the reviews | Fixed: the last non-empty line must match `SUMMARY: high=N medium=N low=N`. Otherwise the reply is kept as `round-K.invalid.md`, exit 1, no round used. Test `test_reply_without_summary_…` |
| 1 | Medium, `tools/review.sh:24–36`: two reviews started together both pick round 1 and overwrite each other's diff, prompt and findings | Fixed: per-step lock (`mkdir .review/step-N.lock`, atomic), taken before choosing the round, removed on exit. Tests `test_second_review_…`, `test_lock_is_released_…` |
| 2 | Both round-1 findings: "Fixed", with file:line and the tests that cover them. No new findings | `SUMMARY: high=0 medium=0 low=0` |

Left for the developer to decide: none

## Proof the tests catch bugs

Setup proof (TESTING §8): the same failing test (`CHECK(1 + 1 == 3)` in `tests/unit/test_runner.c`) is caught by all three guards:

| Guard | Where shown | Result |
|---|---|---|
| `make verify` | scratch copy, by hand | exit 2, `FAIL tests/unit/test_runner.c:7 passing_checks_count_as_pass` … `VERIFY FAILED at: make check` |
| Stop hook | `step-0b.sh` + a live headless Claude Code run (below) | exit 2, FAIL line sent back |
| pre-commit hook | `step-0b.sh` | commit refused, HEAD unchanged |

Deliberate breaks of the new tools, each in a fresh scratch copy:

| # | Break | Caught by |
|---|---|---|
| C1 | Stop gate exits 0 on red | `test_red_check_blocks…`, `test_new_and_changed…`, `test_a_green_check…` |
| C2 | Stop gate ignores untracked files | `test_new_and_changed_code_files_all_trigger_the_check` |
| C3 | Stop gate counter never reset by green | `test_a_green_check_resets_the_count` |
| C4 | Loop guard lets go after 2 blocks | `test_three_blocks_in_a_row_then_the_agent_may_stop` |
| C5 | review.sh uses the real index (`--intent-to-add`) | `test_diff_has_new_files…`, `test_codex_is_read_only…`, `test_failed_codex_run…` (and more) |
| C6 | review.sh sends the step file and PROGRESS | `test_diff_has_new_files_but_not_the_builders_notes` |
| C7 | review.sh has no round limit | `test_round_two_checks_round_one_and_round_three_is_refused` |
| C8 | review.sh runs Codex with `workspace-write` | `test_codex_is_read_only_and_told_what_the_step_must_do` |
| C9 | pre-commit tests the working tree | `step-0b.sh`: "a good staged change was refused because of an unstaged break" |
| C10 | pre-commit ignores a red `make check` | `step-0b.sh`: "the commit with a failing test went through" |

| R1 | Undo fix 1: no `SUMMARY:` check | `test_reply_without_summary_does_not_use_up_a_round` |
| R2 | Undo fix 2: no lock | `test_second_review_of_the_same_step_is_refused_while_one_runs` |
| R3 | Lock not removed on exit | `test_lock_is_released_after_a_failed_run` + 4 others |

The concurrency test passed 5 runs in a row (not flaky so far). The real tree was unchanged afterwards: yes (checksums of every file before and after C1–C10 match. R1–R3 ran in copies the same way).

## Validate it yourself

| Do this | Expected | Actual (agent's run) |
|---|---|---|
| `make verify` | `VERIFY PASSED` | `VERIFY PASSED`, exit 0 (29 s from clean before the review fixes) |
| `bash tests/validate/step-0b.sh` | 7 `ok` lines | 7 `ok` lines |
| `ls -l .git/hooks/pre-commit` | link to `tools/pre-commit` | `.git/hooks/pre-commit -> …/gps-tile-server/tools/pre-commit` (installed with `make hooks`) |
| `make hooks` with someone else's hook already there | refuses, leaves it alone | `make hooks: .git/hooks/pre-commit already exists and is not ours. Not replacing it.`, exit 2, hook unchanged |
| Live Stop hook: headless `claude -p` (Haiku, no Edit/Bash) in a scratch repo with the failing test | blocked 3 times with the FAIL line, then allowed to stop | "block 1 of 3" → "block 2 of 3" → "block 3 of 3 … Last block. If you can't fix it, write the problem under "Blocked on"…", then the run ended with `success`, 8 turns, $0.01 |
| `cat .review/step-0b/round-2.md` | Codex findings + `SUMMARY:` line | `SUMMARY: high=0 medium=0 low=0` |

## Deploy (from step 5b, after approval)

none (step 5b)

## Who did what

| Agent | Did |
|---|---|
| Claude Opus 5.5 | built everything, the tests, the deliberate breaks, the docs |
| Codex CLI 0.162.1 | reviewed the diff read-only through `tools/review.sh 0b`, 2 rounds: 2 medium findings, both fixed |
| Claude Haiku | one headless run in a scratch repo, to see the Stop hook fire inside Claude Code |

## Decisions
- **Review files live in `.review/step-N/`, not `build/`.** This applies the proposal from step 0a (my `make clean` deleted round-1 inputs). Git-ignored. DESIGN, TESTING, AGENTS and TEMPLATE updated.
- **Review diff built in a temporary index, not with `git add --intent-to-add`.** Same diff, but the real index is never touched, so a review can't change what the next commit contains. Rejected: intent-to-add (what step 0a did by hand). It leaves entries in the real index.
- **Pre-commit tests the staged files, not the working tree.** Exports the index with `git checkout-index` and runs the tests there. Costs a full rebuild per commit (a few seconds now). Rejected: `git stash --keep-index`, which can lose work if the hook is interrupted.
- **The Stop gate also watches the `Makefile`.** A Makefile edit can break `make check` as surely as code can. TESTING §12.2 updated.
- **Steps are named `0`–`9` with an optional letter (`3a`).** `review.sh` refuses anything else before using the name in a path.
- **`make check` now takes about 6 s** (was under 1 s): 18 temp git repos plus a 1.5 s wait in the lock test. Still under the 10 s limit in TESTING §12.2.
- **Fakes for Codex and `make check` in the tests** (`CODEX_BIN`, `STOP_GATE_CHECK`). Without them `make check` would call Codex (slow, online) or itself (endless).
- **`make hooks` links rather than copies,** so edits to `tools/pre-commit` take effect at once. It refuses to replace a hook it didn't install.
- **Step 0a now has a validation script too** (`tests/validate/step-0a.sh`). The folder didn't exist in 0a.

## Not verified
- **Codex inside the hook-blocked loop:** Codex has no Stop hook. It relies on the AGENTS.md rule (run `make check` before ending a turn), which nothing enforces.
- **The pre-commit hook can be skipped** with `git commit --no-verify`. Only the AGENTS.md "Never" rule stops that.
- **A fresh clone has no pre-commit hook** until someone runs `make hooks`. Git doesn't install hooks by itself.
- **The live Stop hook run used Haiku** with editing turned off, in a scratch repo. In this session the hook only ran on green checks, so it never had reason to block here.
- **A review lock left by a killed `review.sh`** (`kill -9`) must be removed by hand. The error message says which folder.
- **Linux:** `tools/` and `tests/validate/` use bash and BSD `tar` options that GNU tar also accepts, but they were only run on macOS.
- **`make check-data`** is a placeholder until step 2.

## Next
- Step 1: map math (`geo`: lon/lat → tile, Z-order code), after you approve 0b and say "start step 1".
- Open decisions in PROGRESS.md are unchanged (time per point before stage 4, base map at step 6, license at step 9).
