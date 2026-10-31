# Step 5b: Local deploy (service, smoke test, rollback)

## Summary

| | |
|---|---|
| **Built** | `tools/deploy.sh` and `make deploy` / `rollback` / `undeploy` / `status` / `deploy-test`: the server as a macOS background service (launchd user agent `local.gpstiles.serve`, starts at login, restarts if it crashes) on 127.0.0.1:8080, with a smoke test after every deploy and automatic rollback |
| **Status** | approved (developer's go-ahead 2026-10-31) |
| **Date** | 2026-10-31 |
| **Agent(s)** | Claude Opus 5.5 main · Codex reviewer (gpt-6-astra, high effort) · Claude Opus 5.5 skeptic reviewer (separate agent) |

## Design
- **Check first, switch second.** `make deploy` runs `make check`, then checks `datasets.conf` (absolute, readable paths) and runs the new program on those datasets on a free port and smoke-tests it (**pre-flight**). Only then does it copy `build/gpstiles` to `~/.local/gpstiles/releases/<commit>[-dirty]-<time>/` (a release is never overwritten), point `previous` at the old release and `current` at the new one, and reload the service.
- **Smoke test after every switch** (TESTING §12.6): within 15 s the service's own process (launchd's pid) must be the one listening on the port, `/api/datasets` must list every file in `datasets.conf`, tile 0/0/0 of each dataset must be a real PNG, and a bad URL must give 404. Every request has a 2 s connect and 10 s total limit, and ignores proxies.
- **Red smoke test, an error or Ctrl-C → automatic rollback:** until the smoke test is green, any exit puts `current` and `previous` back as they were and reloads the old release (smoke-tested again); the deploy exits 1 and prints the end of the service log. On a first install there is nothing to go back to, so the service is stopped and removed.
- **The datasets are a list, not baked in:** `~/.local/gpstiles/datasets.conf`, one `.gpt` path per line (`#` comments allowed). The launchd file runs `serve.sh`, which reads the list at every start, so changing datasets needs only a restart.
- **Tested before approval, never on the real service:** `make deploy-test` runs the whole cycle with a label of its own (`local.gpstiles.test-<checksum of the checkout>`), in `build/deploy-test/`, on a free port, then removes everything (below).

| Command | Does |
|---|---|
| `make deploy` | check → datasets.conf + pre-flight → copy → switch → reload → smoke test (→ rollback if red) |
| `make rollback` | `current` ↔ `previous`, restart, smoke test |
| `make undeploy` | stop the service and remove its launchd file (releases and logs stay) |
| `make status` | loaded or not, its pid, which release, does it answer |
| `make deploy-test` | the pre-approval check above |

| On this Mac | Path |
|---|---|
| Program and releases | `~/.local/gpstiles/releases/<commit>/gpstiles`, `current` and `previous` links |
| Datasets | `~/.local/gpstiles/datasets.conf` |
| Start script | `~/.local/gpstiles/serve.sh` |
| launchd file | `~/Library/LaunchAgents/local.gpstiles.serve.plist` |
| Log | `~/.local/gpstiles/logs/serve.log` (only startup and errors: the server doesn't log every request, so it doesn't grow) · `preflight.log` (the last pre-flight) |

## Files changed

| File | Change | Why |
|---|---|---|
| `tools/deploy.sh` | added | deploy, rollback, undeploy, status, smoke |
| `tools/deploy-test.sh` | added | the pre-approval check, 16 scenarios with stand-in programs |
| `tests/validate/step-5b.sh` | added | runs `make deploy-test` and checks nothing is left |
| `Makefile` | changed | `deploy-test`, `deploy`, `rollback`, `undeploy`, `status` |

## Tests

`make deploy-test` (run by `tests/validate/step-5b.sh`, so by every `make verify`). The bad programs are small stand-ins written by the test.

| Scenario | Checks | Bug it would catch |
|---|---|---|
| 1. A first install that fails as the service | nothing left: no `current`, no launchd file, not loaded | a broken service starting at every login |
| 2. A good release | live, smoke test green, the service's pid is the listener | — |
| 3. The same release name again (another program) | refused ("already exists"), the running release byte-identical | the running or rollback release overwritten (Claude F3) |
| 4. A release that works alone but fails under launchd (in `/`) | rolled back to the good one, `previous` as before, answering | a release left live after a red smoke test; `previous == current` after a rollback (F10) |
| 5–7. Seven bad programs: exits at once, text tiles, a PNG whose data doesn't inflate, no dataset listed, 200 for a bad URL, hangs, hangs and ignores SIGTERM | each refused by the pre-flight, none left running, the service untouched, all in under 90 s | a hang forever (F1), each smoke check never going red, a broken PNG passing on its header (N1, Codex) |
| 7b. A deploy killed (SIGTERM) after the switch, during its smoke test | the old release back, the lock gone, answering | an interruption leaving an untested release live (F11) |
| 8. A relative path in `datasets.conf` | refused with a clear message, the service untouched | a crash loop under launchd (F4) |
| 8b. Port 65536 | refused up front ("bad port"), the service untouched | a setting that breaks the new release and the rollback (Codex) |
| 8c. Another port for the installed service | refused ("undeploy first") | a rollback smoke-testing the wrong port (Codex round 2) |
| 9. Another program on the port | refused ("used by another program") | the smoke test passing against the wrong server (F2) |
| 10–11. Two good releases, then `rollback` | `current` and `previous` swap, answering | a broken `make rollback` |
| 11b. `rollback` to a release that fails under launchd | swapped back, answering | a failed rollback leaving the broken release live (Codex round 2, F11) |
| 12. `kill -9` the server | launchd starts a new pid, which answers | KeepAlive missing: a crashed server stays down |
| 12b. `launchctl kickstart -k` | a new pid, which answers | (DESIGN §12.2's restart check) |
| 13. `status` | "answering on" within 15 s (the exact line, not "not answering") | `status` hanging or lying (F1, Codex) |
| 14. `undeploy` | nothing loaded, `status` says "not answering", nothing left in `build/deploy-test` | a test service left on the Mac |

```text
make check       unit 31 passed 0 failed · e2e 91 passed 0 failed · ALL PASSED (build)
make sanitize    unit 31 passed 0 failed · e2e 91 passed 0 failed · ALL PASSED (build/san)
make check-data  as in step 4
make verify      VERIFY PASSED, 6 min 4 s (step-0a … 5a as before · 5b 17 ok)
--- tests/validate/step-5b.sh
  ok  a failed first install leaves nothing installed
  ok  good release live on 127.0.0.1:53503: smoke test green: 1 dataset(s) listed and drawn, bad URL → 404, pid 43950 (http://127.0.0.1:53503/)
  ok  a reused release name is refused, the running release untouched
  ok  a release failing as the service is rolled back to test-good-1, which answers
  ok  7 bad programs refused in the pre-flight (27 s), none left running, the service untouched
  ok  a deploy killed after the switch puts test-good-1 back, unlocked and answering
  ok  a relative path in datasets.conf is refused, the service untouched
  ok  a bad port setting is refused, the service untouched
  ok  moving the installed service to another port is refused (undeploy first)
  ok  another program on the port is refused
  ok  rollback swaps test-good-2 and test-good-1, and the service answers
  ok  a rollback to a broken release swaps back to test-good-1, which answers
  ok  a killed server is restarted by launchd (pid 49089 → 49193)
  ok  back up after launchctl kickstart -k (pid 49193 → 49252)
  ok  status: answering on http://127.0.0.1:53503/ (listener pid 49252)
  ok  test service removed, nothing left in build/deploy-test
  ok  make deploy-test passed and left nothing behind
```

## Review (Codex)

Run with `CODEX_BIN=<wrapper> tools/review.sh 5b` (gpt-6-astra, high reasoning effort). Files in `.review/step-5b/`. Round 1 reviewed the scripts after the Claude skeptic's round-1 fixes.

| Round | Finding (severity, file:line) | What happened |
|---|---|---|
| 1 | Medium, `deploy.sh:214`: port 65536 passed the digits check and the pre-flight (port 0), then broke the new release and the rollback | Fixed: port 1–65535 and throttle 1–3600 checked up front; a rollback restores the old start script and launchd file. Scenario 8b. Caught (P9) |
| 1 | Medium, `deploy.sh:101`: only the PNG's first 8 bytes were checked, curl's status ignored | Fixed: the whole tile is downloaded (curl must succeed) and decoded (below) |
| 1 | Medium, `deploy.sh:247`: two deploys at once could race | Fixed: one lock per installation for deploy, rollback and undeploy; a release folder is created exclusively |
| 1 | Medium, `deploy.sh:133`: an interrupted pre-flight left its server running; a server ignoring SIGTERM hung the deploy | Fixed: the exit trap is set before the pre-flight and stops it; TERM, then KILL after 5 s. Scenarios 5–7 (`hangs-ignoring-term`) |
| 1 | Medium, `deploy.sh:296`: `undeploy` reported success when stopping failed | Fixed: it checks the job is unloaded, else exits 1 and keeps the launchd file |
| 1 | Low, `deploy-test.sh:169`: the status check also matched "not answering" | Fixed: the exact line, and "not answering" checked after `undeploy`. Caught (P10) |
| 1 | Low, `deploy-test.sh:160`: `launchctl kickstart -k` (DESIGN §12.2) no longer tested | Fixed: scenario 12b |
| 2 | Items 3–7: fixed; 1 and 2 partly (it reviewed a snapshot taken during the next edit) | — |
| 2 | Low: after restoring the old configuration, the recovery smoke test used the new port | Fixed: the port of an installed service can't change (undeploy first). Scenario 8c. Caught (P15) |
| 2 | Medium: image size doesn't prove a valid PNG (a JPEG, or a PNG with corrupt data, passes `sips`) | Fixed: a small Python check verifies the signature, every chunk's CRC, IHDR first and IEND last, and inflates the image data to 256 rows. Scenario 5–7 `corrupt-png`. Caught (P13) |
| 2 | Medium: a failed `rollback` left the broken release live | Fixed: `rollback` pre-flights its target and runs in the same undo transaction as `deploy`. Scenario 11b. Caught (P14) |
| 2 | Medium: a failed backup copy (disk full) was ignored | Fixed: backups are published only when complete, and the deploy stops before switching if one can't be written |

Left for the developer to decide: none. The last round of fixes was not reviewed by Codex again (2-round limit); each is guarded by a scenario that a deliberate break showed failing.

## Review (Claude skeptic, separate agent)

A second Claude Opus 5.5 agent with a fresh context, in its own copy, using only a test label of its own and paths inside its copy (never the real service, `~/Library/LaunchAgents` or `~/.local/gpstiles`).

| Round | Finding (severity) | What happened |
|---|---|---|
| 1 | High F1: no curl had a timeout, so a release that hangs made `make deploy` (and `status`) hang forever with the broken release live; no trap on Ctrl-C | Fixed: every request bounded (2 s connect, 10 s total), a pre-flight before the switch, and a trap that undoes the switch on any exit before a green smoke test. Scenarios 5–7, 13. Caught (P2) |
| 1 | Medium F2: the smoke test checked whatever answered on the port (a hand-started `serve` passed for the service) | Fixed: refused when another program holds the port; the service passes only when launchd's pid is the listener. Scenario 9. Caught (P4) |
| 1 | Medium F3: re-deploying a release name overwrote the running binary and broke the rollback | Fixed: names carry the time (`<commit>[-dirty]-<time>`) and a release is never overwritten. Scenario 3. Caught (P3) |
| 1 | Medium F4: a mistake in `datasets.conf` turned a working service into a crash loop | Fixed: the list is checked and the new program pre-flighted on it before anything changes. Scenario 8. Caught (P5) |
| 1 | Medium F5: the fixed test label made two runs at once break each other | Fixed: the label carries a checksum of the checkout, and a lock stops two runs in one checkout |
| 1 | Medium F6: `ProcessType Background` made the server about 6× slower | Fixed: removed (launchd's standard priority) |
| 1 | Low F7: a changed launchd file never reached a loaded service (`kickstart` reuses the old one) | Fixed: every restart is `bootout` + `bootstrap` |
| 1 | Low F8: an `http_proxy` in the shell sent the smoke test to the proxy | Fixed: `--noproxy '*'` |
| 1 | Low F9: install paths were pasted unescaped into the start script and the launchd file | Fixed: paths with characters other than letters, digits, space and `. _ - /` are refused, and the start script quotes with `%q` |
| 1 | Low F10: after an automatic rollback `previous == current` | Fixed: `previous` is put back too. Scenario 4. Caught (P7) |
| 1 | Low F11: an exit between the switch and a green smoke test left the release live | Fixed by the trap (F1) |
| 1 | Test gaps: KeepAlive, a release that answers with bad tiles, the first-install cleanup, `rollback`, a hang, another program on the port, a reused name, a bad `datasets.conf`, `status`; the failure log deleted by the cleanup | All covered by scenarios 1–14; on failure the service log is kept in `build/deploy-test-failed.log`. Caught (P1, P6, P8) |
| 2 | F1–F10: fixed, each re-run with its round-1 reproduction (e.g. the hang refused in 11 s, or 15 s when it ignores SIGTERM; tiles through the service as fast as a plain `serve`: 0.021 s) | — |
| 2 | F11 partly: `rollback` had no undo | Fixed: the same transaction as `deploy` (with Codex round 2). Caught (P14) |
| 2 | Low N1: `sips` read only the PNG's size from its header; a cut PNG body passed | Fixed: the PNG is decoded (Codex round 2's medium). Caught (P13) |
| 2 | Test gaps: the "dataset listed" and "bad URL → 404" checks never went red; no scenario interrupted a deploy or ran a release ignoring SIGTERM | Fixed: `missing-id`, `no-404`, `hangs-ignoring-term`, and scenario 7b. Caught (P11, P12, P16) |

Left for the developer to decide: none.

## Proof the tests catch bugs

Each break in a fresh copy of the repo, then `tests/validate/step-5b.sh` (about a minute each):

| # | Deliberate break | What failed |
|---|---|---|
| P1 | a red smoke test doesn't roll back | scenario 4: "not rolled back cleanly" |
| P2 | no pre-flight | scenarios 5–7: "the exits program wasn't caught by the pre-flight" |
| P3 | a release may be overwritten | scenario 3: "a release name was reused" |
| P4 | another program on the port not noticed | scenario 9 |
| P5 | `datasets.conf` not checked | scenario 8 |
| P6 | no KeepAlive | scenario 12: "no answer after the server was killed" |
| P7 | a rollback doesn't restore `previous` | scenario 4 |
| P8 | the smoke test doesn't decode tiles | scenarios 5–7: "the bad-tiles program was accepted" |
| P9 | the port's range not checked | scenario 8b: "port 65536 wasn't refused up front" |
| P10 | `status` says "answering" when it doesn't | scenario 13/14 |
| P11 | the smoke test doesn't check the dataset list | scenarios 5–7: "the missing-id program wasn't caught" |
| P12 | the smoke test doesn't check the 404 | scenarios 5–7: "the no-404 program wasn't caught" |
| P13 | the smoke test checks only the PNG's header | scenarios 5–7: "the corrupt-png program wasn't caught" |
| P14 | a failed rollback isn't swapped back | scenario 11b |
| P15 | the port of an installed service may change | scenario 8c |
| P16 | an interrupted deploy isn't undone | scenario 1 (a failed first install left the service) |

The code was restored exactly afterwards: yes (every break was in a deleted copy, each with its own test label).

## Validate it yourself

| Do this | Expected | Actual (agent's run) |
|---|---|---|
| `make deploy-test` | 16 `ok` lines and `DEPLOY-TEST PASSED`, about 2 minutes | as above |
| `make status` | the service, its pid, `current`, "answering on http://127.0.0.1:8080/" | see Deploy |
| open http://127.0.0.1:8080/api/datasets | both datasets with their points | see Deploy |
| `launchctl print gui/$(id -u)/local.gpstiles.serve \| grep -E 'state|pid'` | `state = running`, a pid | see Deploy |

## Deploy (after approval)

Done after the commit (the details are in step 6's file, which is committed next):

| Command | Smoke test | Rolled back? |
|---|---|---|
| `make deploy` (datasets: `data/build/tdrive.gpt`, `data/build/tdrive-sample.gpt`) | see step 6 | — |

## Who did what

| Agent | Did |
|---|---|
| Claude Opus 5.5 (main) | scripts, the deploy test, breaks, validation, the real deploy, this file |
| Codex CLI gpt-6-astra (high effort) | review (read-only) |
| Claude Opus 5.5 skeptic (separate agent, own copy and test label) | adversarial review |

## Decisions
- **Pre-flight before the switch:** most broken releases (exit at once, bad tiles, a hang, unreadable datasets) are refused while the old service keeps running. Only problems that show up under launchd (another working directory, the login environment) reach the live switch, where the trap rolls them back.
- **`bootout` + `bootstrap` instead of `kickstart -k`:** a changed launchd file always takes effect. `ThrottleInterval` stays at launchd's 10 s for the real service (a crashing server can't spin the CPU) and is 1 s in the test.
- **Release names with the time,** so a re-deploy of the same commit never overwrites the running or rollback release. Old releases are kept (about 250 KB each).
- **The test label carries a checksum of the checkout,** so two checkouts never share a test service.
- **Standard process priority:** `ProcessType Background` made tiles about 6× slower.

## Not verified
- A Mac restart (the service is set to start at login: `RunAtLoad`, in the user's launch agents).
- A failure of `launchctl` itself (the trap covers it; it wasn't produced).
- Two different checkouts deploying the real service at once.

## Next
- Step 6: the map page at http://127.0.0.1:8080/.
