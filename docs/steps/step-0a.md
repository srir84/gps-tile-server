# Step 0a: Project setup (build + tests)

## Summary

| | |
|---|---|
| **Built** | Git repo, Makefile (`all`, `check`, `sanitize`, `clean`), C test runner, Python end-to-end runner, minimal `gpstiles` with `help` |
| **Status** | approved |
| **Date** | 2026-10-28 |
| **Agent(s)** | Claude Opus 5.5 (builder) · Codex CLI 0.162.1 (reviewer, read-only, 2 rounds) |

## Design
- **One command per job.** `make` builds `build/gpstiles`. `make check` runs every test. `make sanitize` runs the same tests with memory checks on (AddressSanitizer + UndefinedBehaviorSanitizer), in `build/san/`.
- **Two test runners, both made to fail loudly.** C: `tests/check.h` + `check.c` (CHECK, CHECK_EQ_U64, `catches:` label, `TEST_SEED`). Python: `tests/e2e/run.py` (requires a `catches:` docstring on every test).
- **The runners are tested too.** `tests/selftest/always_fails.c` fails on purpose, and `test_check_runner.py` checks that the run fails, says where and why, and prints the seed. `test_e2e_runner.py` does the same for the Python runner: `sys.exit(0)`, no tests found, `async`/`yield` tests and missing labels all fail the run.
- **Flag changes rebuild everything.** `build/.build-config` holds the compiler and flags, and every object depends on it, so `make sanitize` can never reuse objects built without sanitizers.
- **CLI errors are one line on stderr, exit code 2.** Control characters in user input are replaced with `?`, and the name is cut to 64 characters.

```text
make check
 ├─ build/gpstiles             src/main.c
 ├─ build/tests/unit           tests/unit/*.c + tests/check.c       → "unit  N passed M failed"
 ├─ build/tests/always_fails   tests/selftest/always_fails.c        (run by the e2e tests)
 └─ python3 -I -B tests/e2e/run.py                                  → "e2e   N passed M failed"
make sanitize = the same, in build/san/, with -fsanitize=address,undefined
```

## Files changed

| File | Change | Why |
|---|---|---|
| `.gitignore` | added | `data/`, `build/`, `dist/`, `__pycache__/`, `.DS_Store` stay out of git |
| `Makefile` | added | build, check, sanitize, clean. GNU Make 3.81 compatible. Rebuilds on flag changes |
| `src/main.c` | added | `gpstiles help`, one-line errors for a missing or unknown command |
| `tests/check.h`, `tests/check.c` | added | C test runner |
| `tests/unit/main.c`, `suites.h`, `test_runner.c` | added | unit test entry point and the first suite |
| `tests/selftest/always_fails.c` | added | proves a failing C test fails the run |
| `tests/e2e/run.py` | added | Python test runner |
| `tests/e2e/test_cli.py`, `test_check_runner.py`, `test_e2e_runner.py` | added | CLI, C-runner and Python-runner tests |
| `docs/TESTING.md` §4, §5 | changed | layout lists the new files · Python runs with `-B` (no bytecode in the repo) |
| `docs/DESIGN.md` §10 | changed | folder layout: `check.c`, `selftest/`, e2e contents |
| `docs/DESIGN.md` §9.2, `docs/TESTING.md`, `AGENTS.md`, `docs/steps/TEMPLATE.md` | changed | fixes from the second planning review (see Decisions) |

559 lines in 13 new code files, most of them tests. Review the full change, new files included: `git add -A --intent-to-add && git diff 4b825dc642cb6eb9a060e54bf8d69288fbee4904 -- .gitignore Makefile src tests` (the hash is git's empty tree, since there is no commit yet).

## Tests

| Test | Checks | Bug it would catch |
|---|---|---|
| unit `passing_checks_count_as_pass` | CHECK and CHECK_EQ_U64 pass on equal values, incl. `UINT64_MAX` | the runner reports a passing check as a failure |
| `test_failing_test_fails_the_run` | the selftest suite exits 1, "1 passed 2 failed" | the runner prints FAIL but exits 0, so `make check` passes broken code |
| `test_failure_names_place_test_and_bug` | `FAIL file:line name` + `catches:` line | a failure nobody can act on |
| `test_failure_shows_expected_and_got` | `expected 3   got 4`, failed condition text | a mismatch reported without the values |
| `test_later_tests_run_after_a_failure` | the 3rd test still runs | the first failure hides every later one |
| `test_seed_is_reported_on_failure` | `seed=1` by default, `seed=7` with `TEST_SEED=7` | a random failure that can't be repeated |
| `test_bad_seed_is_rejected` | `abc`, `-1`, ` 7`, too large, newline + escape → exit 2, one clean line | a mistyped seed silently becomes 1 |
| `test_help_succeeds_on_stdout` | exit 0, usage on stdout, empty stderr | scripts think `help` failed |
| `test_no_command_is_a_one_line_usage_error` | exit 2, one line on stderr | no command looks like success |
| `test_unknown_command_is_one_line_error` | exit 2, one line naming the command | a typo exits 0 |
| `test_unknown_command_name_is_cut_short` | 5,000-character name → under 200 characters of output | the one-line rule breaks |
| `test_control_characters_in_name_stay_on_one_line` | newline + escape code → `?`, one line | a name that splits the error or controls the terminal |
| `test_good_folder_passes` | a folder of passing tests passes | the Python runner fails good tests |
| `test_sys_exit_zero_in_a_test_fails` | `sys.exit(0)` in a test → run fails | a test ends the run early and reports success |
| `test_sys_exit_zero_on_import_fails` | `sys.exit(0)` while loading → run fails | the same, at import time |
| `test_no_test_files_fails` | no `test_*.py` → run fails | renamed test files make the run pass with nothing tested |
| `test_file_without_tests_fails` | file with no `test_*` functions → fails | renamed test functions are skipped silently |
| `test_generator_and_async_tests_fail` | `yield` / `async def` tests → fail | a test counted as passed whose body never ran |
| `test_missing_catches_label_fails` | no `catches:` docstring → fail | tests that don't say what they protect |

From a clean start (`make clean` first):

```text
$ make check          (exit 0, 0.74 s)
unit         1 passed   0 failed
e2e         18 passed   0 failed
ALL PASSED (build)

$ make sanitize       (exit 0, 0.90 s)
unit         1 passed   0 failed
e2e         18 passed   0 failed
ALL PASSED (build/san)
```

Sanitizers really are in the `make sanitize` programs: `nm` finds `__asan_init` and `__ubsan_handle_*` in `build/san/gpstiles`, `build/san/tests/unit` and `build/san/tests/always_fails`.

`make check-data`: not part of 0a (it exists from 0b, with real checks from step 2).

## Review (Codex)

| Round | Finding (severity, file:line) | What happened |
|---|---|---|
| 1 | Medium · `Makefile` · after `make check B=build/san`, `make sanitize` reused objects built without sanitizers, and flag changes never rebuilt | Fixed: `build/.build-config` stamp. Proven: the exact sequence now recompiles 5 objects and the binary has `__asan_init` (was 0) |
| 1 | Medium · `tests/e2e/run.py` · `sys.exit(0)` in a test or on import ended the run with success | Fixed: `SystemExit` caught for both. 2 tests added |
| 1 | Medium · `tests/e2e/run.py` · no tests found → "0 passed 0 failed" and exit 0 | Fixed: no files or a file with no tests fails the run. 2 tests added |
| 1 | Low · `src/main.c` · no command printed 4 lines; a newline in the name split the error | Fixed: one-line "missing command" error, control characters → `?`. 2 tests changed/added |
| 2 | Medium · `tests/e2e/run.py:37` · `async def` or `yield` tests passed without running their body | Fixed: rejected. 1 test added |
| 2 | Low · `tests/check.c:24` · a bad `TEST_SEED` was echoed with its newline and escape codes | Fixed: the value is no longer echoed. Test extended |
| 2 | Round-1 status "cannot assess": the review inputs were deleted mid-review (my `make clean`, see Decisions) | Each round-1 fix was proven instead by breaking it on purpose (B5–B7 below) and by re-running the exact failing sequence (F1) |

Left for the developer to decide: whether to run one more clean review round. Round 2 reviewed the current code, but couldn't compare against round 1.

## Proof the tests catch bugs

Each break was made in a scratch copy of `Makefile`, `src/` and `tests/`. The real tree's file checksums and `git status` were identical before and after.

| Deliberate break | Test that failed | Exit code |
|---|---|---|
| B1 · unit test expects 43, gets 42 | `passing_checks_count_as_pass`: `40 + 2: expected 43   got 42`, with `catches:` and `seed=1` | 2 |
| B2 · `check_report` always returns 0 | `test_failing_test_fails_the_run` | 2 |
| B3 · unknown command returns 0 | `test_unknown_command_is_one_line_error`, `test_unknown_command_name_is_cut_short` | 2 |
| B4 · heap overflow (write 1 past a 4-byte block) inside a passing unit test | `make check` **passes** (exit 0). `make sanitize` fails: `AddressSanitizer: heap-buffer-overflow … test_runner.c:12` | 2 |
| B5 · control characters echoed raw | `test_control_characters_in_name_stay_on_one_line` | 2 |
| B6 · `SystemExit` no longer caught | `test_sys_exit_zero_in_a_test_fails` | 2 |
| B7 · empty discovery allowed | `test_no_test_files_fails` | 2 |
| B8 · generator/async check removed | `test_generator_and_async_tests_fail` | 2 |
| B9 · bad seed echoed raw | `test_bad_seed_is_rejected` | 2 |

B4 shows why `make sanitize` exists: the memory bug is invisible to `make check`.

The code was restored exactly afterwards: yes (scratch copies only, real tree checksums unchanged).

## Validate it yourself

| Do this | Expected | Actual (agent's run) |
|---|---|---|
| `make clean && make check` | `unit 1 passed 0 failed` · `e2e 18 passed 0 failed` · `ALL PASSED (build)` · exit 0 | as expected, exit 0 |
| `make sanitize` | the same with `ALL PASSED (build/san)` · exit 0 | as expected, exit 0 |
| `./build/gpstiles help; echo $?` | usage text, `0` | as expected |
| `./build/gpstiles; echo $?` | `gpstiles: missing command (try 'gpstiles help')`, `2` | as expected |
| Make a test fail: in `tests/unit/test_runner.c` change `CHECK_EQ_U64(42, 40 + 2)` to `43`, run `make check; echo $?`, then undo | `FAIL tests/unit/test_runner.c:8 …`, `catches: …`, `expected 43   got 42`, exit `2` | as expected (B1, in a scratch copy) |
| `git status --short` | only the new files, no `build/`, `data/` or `__pycache__` | as expected |

## Who did what

| Agent | Did |
|---|---|
| Claude Opus 5.5 | Built the step, ran every check, 9 deliberate breaks, fixed all review findings, wrote this file |
| Codex CLI 0.162.1 (read-only) | Round 1: 4 findings. Round 2: 2 new findings. Also 2 rounds on the planning docs before the step (13 + 5 findings, all fixed) |

## Decisions
- **A C file plus a header for the test runner, not header-only.** Test files and the runner share one failure flag, which only works if it lives in one `.c` file. A header-only runner would have a separate copy in every test file and miss failures.
- **The CLI already has end-to-end tests (Python) in 0a.** TESTING §10 says "exit non-zero with a one-line message" from 0a on, and only the real program can show that. TESTING §5 updated.
- **Python runs with `-B`.** Without it, `__pycache__` was written into `tests/e2e/` (found during the step). Also in `.gitignore`.
- **Unknown command / missing command → exit 2** (usage error). Exit 1 stays free for "the command ran and failed", from step 1 on.
- **Planning-review round 2 fixes**, applied while starting 0a (not 0a code):
  - `docs/DESIGN.md` §9.2: new **box rule**. Edges included, and a point on a shared edge counts in both boxes.
  - `docs/TESTING.md` §9 step 1: the round-trip check is now "within 1 world unit per axis", not "1 cm", which a correct program could fail.
  - `check-data` with no `data/` prints SKIPPED and exits 0. A skip is listed under "Not verified".
  - `--mem` described the same way in §9.1 and §5.3.
  - `TEMPLATE.md` diff instructions now include new files.
- **Proposed for 0b (not applied):** `tools/review.sh` should keep its inputs and output outside `build/` (e.g. a git-ignored `.review/` folder), or refuse to run while `make clean` could delete them. My `make clean` during review round 2 deleted the round-1 file and the diff.

## Not verified
- **Review round 2 couldn't confirm the round-1 fixes itself,** because the inputs were deleted. I proved them by deliberate breaks instead. A clean third round would exceed the 2-round limit, so it's your call.
- Only Apple clang 21 and GNU Make 3.81 on this Mac were tried. No Linux and no GNU Make 4.x.
- `make sanitize` on macOS arm64 has no leak checking (LeakSanitizer isn't supported there). Overflows and use-after-free are caught (B4). Memory leaks are not.
- `TEST_SEED` is parsed and printed, but no random test uses it yet (from step 1).
- No Stop hook, pre-commit hook or `make verify` yet: those are step 0b.

## Next
- Step 0b: `make verify`, `make hooks` + `tools/pre-commit`, Stop hook (`.claude/settings.json` + `tools/stop-gate.sh`), `tools/review.sh`.
- After approval of 0a: commit `step 0a: project setup` (the first commit), then start 0b when you say so.
