# PROGRESS.md

The handoff file. Read it first. Update it at the start and end of every step.

## Now

| | |
|---|---|
| **Current step** | 12: Porto taxis (stage 3, DESIGN §12.5) |
| **Status** | approved |
| **Next action** | Deploy step 12 and add `porto.gpt`. Then stage 4: step 13 (fast zoomed-out tiles), step 14 (NYC taxis 2009–2010), step 15 (a billion points: NOAA AIS) + report. Then stage 3 (Porto taxis), as the developer set on 2026-11-01: "proceed with all stages do not stop until all stages are complete". |
| **Blocked on** | nothing |

Stage 2 approval: on 2026-11-01 the developer said "continue with stage implementation make sure everything works all tests pass", so stage 2 runs the same way as stage 1.

Approval: on 2026-10-31 the developer set the goal "complete each step … do not stop until the full project is completed", with Codex (gpt-6-astra) and a Claude Opus skeptic reviewing every step. Each step is committed after both reviews and a green `make verify`. Deploy is local only (this Mac); nothing is published.

Status values: `not started` → `in progress` → `waiting for review` → `approved`

## Step log (stage 1: T-Drive)

| Step | Name | Status | Date | Commit | Review |
|---|---|---|---|---|---|
| 0a | Project setup: build + tests | approved | 2026-10-28 | `0e0e3fb` | `docs/steps/step-0a.md` |
| 0b | Loop tools: verify, hooks, Codex review | approved | 2026-10-28 | `36419af` | `docs/steps/step-0b.md` |
| 1 | Map math | approved | 2026-10-29 | `c587160` | `docs/steps/step-1.md` |
| 2 | Importer | approved | 2026-10-29 | `0777186` | `docs/steps/step-2.md` |
| 3a | Build: external sort + write `.gpt` | approved | 2026-10-31 | `c974041` | `docs/steps/step-3a.md` |
| 3b | Read `.gpt`: tilefile, info, count | approved | 2026-10-31 | `98e0f88` | `docs/steps/step-3b.md` |
| 4 | Tile drawing | approved | 2026-10-31 | `1114779` | `docs/steps/step-4.md` |
| 5a | Web server | approved | 2026-10-31 | `4fba06c` | `docs/steps/step-5a.md` |
| 5b | Local deploy (service, smoke test, rollback) | approved | 2026-10-31 | `e46af4d` | `docs/steps/step-5b.md` |
| 6 | Map page | approved | 2026-10-31 | `e68e36f` | `docs/steps/step-6.md` |
| 7 | Area count + API | approved | 2026-10-31 | `da206fe` | `docs/steps/step-7.md` |
| 8 | Export | approved | 2026-10-31 | `820f438` | `docs/steps/step-8.md` |
| 9 | Stage 1 report + release | approved | 2026-10-31 | `7f21698` | `docs/steps/step-9.md` |

## Step log (stage 2: GeoLife + USGS, DESIGN §12.4)

| Step | Name | Status | Date | Commit | Review |
|---|---|---|---|---|---|
| 10 | GeoLife: a second file layout | approved | 2026-11-01 | `fd60a87` | `docs/steps/step-10.md` |
| 11 | Worldwide: USGS earthquakes + stage 2 report | approved | 2026-11-01 | `f73eb0f` | `docs/steps/step-11.md` |

## Step log (stage 3: Porto taxis, DESIGN §12.5)

| Step | Name | Status | Date | Commit | Review |
|---|---|---|---|---|---|
| 12 | Porto taxis: polylines + stage 3 report | approved | 2026-11-01 | | `docs/steps/step-12.md` |

## Done before step 0 (planning)

| Item | Where |
|---|---|
| Design doc with diagrams | `docs/DESIGN.md` |
| Agent rules | `AGENTS.md`, `CLAUDE.md` |
| Step review template | `docs/steps/TEMPLATE.md` |
| T-Drive data downloaded | `data/raw/tdrive/`, `data/raw/tdrive_txt/` |
| Project plan and datasets | `../PROJECT_IDEAS.md` sections 8–10 |
| Mockup of the finished page | https://claude.ai/artifact/6eS7M1H57qtoZ7oYseCbST |

## Last verified

| Date | What | Command | Result |
|---|---|---|---|
| 2026-11-01 | Step 12 after both review rounds (Codex: 1 high + 1 medium, then 1 low; Claude skeptic: 1 medium + 6 low, then clean; all fixed): `make verify` | `make verify` | unit 37/0 · e2e 130/0 under check and sanitize · check-data: Porto counts = DESIGN §13 = csv + json, sample codes = two Python readers, 3 places, 1-run = 3-run build · step-12 7 ok · VERIFY PASSED (19 min 56 s) |
| 2026-11-01 | NYC taxis 2009–2010 downloaded for stage 4 (TLC, no account) and counted by DuckDB | `curl` (24 files, each size = the server's), DuckDB 2.0.0 in `data/tools/venv` | 24 Parquet files, 11 GB · TLC's files from 2011 on hold zone numbers, not places · 339,897,217 trips → 679,794,434 pickup and dropoff points: 668,475,278 on the map, 11,315,804 at (0,0), 3,242 off the map, 110 without a place |
| 2026-11-01 | Deploy of step 11 (`f73eb0f`); every `.gpt` rebuilt (the 5 % view); the earthquakes added | `GPSTILES_PORT=8090 make deploy`, `gpstiles build` ×5, `datasets.conf`, `launchctl kickstart -k`, `tools/deploy.sh smoke` | smoke test green, no rollback · 5 datasets listed and drawn (pid 97046) · views: tdrive 116.17,39.73–116.96,40.21 · geolife 108.47,30.85–117.97,40.37 · earthquakes -162.09,-8.04–127.21,63.11 |
| 2026-11-01 | Step 11 after both review rounds (Codex: 2 medium + 1 low, then 1 medium; Claude skeptic: 2 medium + 4 low, then 2 low; all fixed): `make verify` | `make verify` | unit 33/0 · e2e 127/0 under check and sanitize · check-data: T-Drive, GeoLife, USGS (counts = DESIGN §13 = awk, codes = Python, the 180° tiles, 6 places) · step-11 10 ok · VERIFY PASSED (16 min 49 s) |
| 2026-11-01 | Porto taxis downloaded for stage 3 (UCI, no account) | `curl`, `unzip`; Python's `csv` and `json` over `train.csv` | `porto.zip` 534,065,916 bytes (SHA-256 `a33e2a5e…f8c76`) · `train.csv` 1,942,848,724 bytes · 1,710,670 trips, 83,409,386 points, all on the map, none at (0,0), 0 malformed rows, 5,901 empty trips · longest line 84,640 bytes |
| 2026-11-01 | Deploy of step 10 (`fd60a87`), GeoLife added to the service | `GPSTILES_PORT=8090 make deploy`, `datasets.conf`, `launchctl kickstart -k`, `tools/deploy.sh smoke` | smoke test green, no rollback · then 4 datasets listed and drawn (pid 23760): tdrive 10,064,891 · tdrive-sample 543,401 · uber-nyc-2014 4,534,327 · geolife 24,876,977 |
| 2026-11-01 | Step 10 after both review rounds (Codex: 1 medium, then clean; Claude skeptic: 2 medium + 6 low, all fixed, then clean): `make verify` | `make verify` | unit 33/0 · e2e 123/0 under check and sanitize · check-data: T-Drive as before, GeoLife counts = DESIGN §13 = awk, sample codes = Python, 4 places = Python · step-10 7 ok · VERIFY PASSED (13 min 55 s) |
| 2026-11-01 | USGS earthquakes downloaded for step 11 | `fetch-usgs.py data/raw/usgs` (the step-11 tool, from the builder's scratchpad) | 58 files, 4,771,181 rows, each period = USGS's own count (`MANIFEST.txt`), no id twice, 834 MB · `awk` and `gpstiles import`: imported=4770607 skipped_zero=9 skipped_out_of_range=565 (all north of 85.05°) |
| 2026-10-31 | Third local dataset, for English map labels (developer's choice): NYC Uber pickups, April–September 2014, FiveThirtyEight's public copy (`github.com/fivethirtyeight/uber-tlc-foil-response`, `uber-trip-data/uber-raw-data-{apr..sep}14.csv`, 6 files, 209,715,627 bytes) in `data/raw/uber-nyc-2014/` | `gpstiles import --lon-col 3 --lat-col 2 --skip 1`, `build`, `info`; `awk` over the CSVs; the live count API | rows 4,534,327 = awk, all kept (0 at 0,0, 0 out of range, 0 malformed) · `uber-nyc-2014.gpt` 36,274,872 bytes, bounds = awk's min/max · JFK box `-73.83005,40.62005,-73.74005,40.67005`: 107,680 = awk · added to `datasets.conf`, service restarted: smoke test green, 3 datasets · the page in Chrome: English street names, 30/30 base tiles |
| 2026-10-31 | Deploy fix: `make undeploy` now also removes the start script `serve.sh` (it kept the old port, so the deploy's port guard refused every move, even after undeploy) | `make deploy-test` | new scenario 15 (undeploy, then a deploy on another port answers there) · DEPLOY-TEST PASSED · break P1 (the old undeploy) caught: `a deploy on another port after undeploy: … installed on another port` |
| 2026-10-31 | Service moved to port 8090 (developer's choice: a chat app of theirs uses 8080, and Chrome kept that app's page for 127.0.0.1:8080) | `make undeploy`, the old `serve.sh` removed by hand, `GPSTILES_PORT=8090 make deploy` | smoke test green on http://127.0.0.1:8090/ (pid 95803) · nothing listening on 8080 |
| 2026-10-31 | Release v0.1.0, local only | `make release VERSION=0.1.0`, `shasum -a 256 -c`, `git tag -n` | smoke test green on the unpacked package · `dist/gpstiles-0.1.0-macos-arm64.tar.gz` (90,618 bytes: `gpstiles`, `README.md`, `LEAFLET-LICENSE`, owned by root; links only libSystem and libz; built for macOS 13.0) + `.sha256`: OK · annotated tag `v0.1.0` on `7f21698` · no git remote: nothing pushed or uploaded |
| 2026-10-31 | Deploy of step 9 (`7f21698`) | `make deploy`, `make status` | smoke test green, no rollback (58 s, pid 89721) · current `releases/7f21698-20261031195723`, previous `releases/820f438-20261031184524` |
| 2026-10-31 | Step 9 after both review rounds (Codex, Claude skeptic) and the fixes after them: `make verify` | `make verify` | unit 33/0 · e2e 119/0 under check and sanitize · step-9 15 ok (`make release-test`'s package on its own; a real `make release` in a throwaway repo; import 1.83 s, build 0.96 s, bench) · VERIFY PASSED (12 min 29 s) |
| 2026-10-31 | Deploy of step 8 (`820f438`) | `make deploy`, `make status` | smoke test green, no rollback (pid 83707) · the live export: `X-Total-Points: 239864` for the airport box |
| 2026-10-31 | Step 8 after both review rounds (Codex, Claude skeptic): `make verify` | `make verify` | unit 33/0 · e2e 117/0 under check and sanitize · step-8 5 ok (real T-Drive: rows = Python's points, the page's Export, a steady slow reader) · VERIFY PASSED (11 min 7 s) |
| 2026-10-31 | Deploy of step 7 (`da206fe`) | `make deploy`, `make status` | smoke test green on the first try (pid 84451) · the live count API: 239,864 for the airport box |
| 2026-10-31 | Step 7 after both review rounds (Codex, Claude skeptic): `make verify` | `make verify` | unit 33/0 · e2e 103/0 under check and sanitize · step-7 4 ok (real T-Drive, the page's hover and box = Python) · step-5b 21 deploy scenarios · VERIFY PASSED (8 min 5 s) |
| 2026-10-31 | Deploy of step 6 (`e68e36f`) | `make deploy` ×2, then traced | 2 tries: launchd error 5 on restart, rolled back to 5b automatically · 3rd: smoke test green with the map page, pid 80452 · footprint 3 MB |
| 2026-10-31 | Step 6 after both review rounds (Codex, Claude skeptic): `make verify` | `make verify` | unit 31/0 · e2e 96/0 under check and sanitize · step-6 4 ok (headless Chrome, real T-Drive, real base map) · VERIFY PASSED (6 min 57 s) |
| 2026-10-31 | Deploy of step 5b (`e46af4d`) | `make deploy`, `make status` | smoke test green (2 datasets, pid 55018 on 127.0.0.1:8080) · footprint 3 MB |
| 2026-10-31 | Step 5b after both review rounds (Codex, Claude skeptic): `make verify` | `make verify` | unit 31/0 · e2e 91/0 under check and sanitize · step-5b 17 ok (`make deploy-test`: 16 scenarios, nothing left) · VERIFY PASSED (6 min 4 s) |
| 2026-10-31 | Step 5a after both review rounds (Codex, Claude skeptic): `make verify` | `make verify` | unit 31/0 · e2e 91/0 under check and sanitize · check-data as step 4 · step-5a 11 ok (each dataset's tile = Python's from its own points) · VERIFY PASSED (4 min 15 s) |
| 2026-10-31 | Step 4 after both review rounds (Codex, Claude skeptic): `make verify` | `make verify` | unit 31/0 · e2e 83/0 under check and sanitize · check-data: render 11/1686/776 = Python for all 65,536 pixels · step-4 7 ok (screenshot beside OpenStreetMap) · VERIFY PASSED (3 min 18 s) |
| 2026-10-31 | Step 3b after both review rounds (Codex, Claude skeptic): `make verify` | `make verify` | unit 28/0 · e2e 78/0 under check and sanitize · check-data: info = DESIGN §13 and the Python header, count 10/843/388 = 2,229,964 = slow count = its 4 children · step-0a 2 ok · 0b 7 ok · 1 2 ok · 2 3 ok · 3a 7 ok · 3b 3 ok · VERIFY PASSED (3 min 5 s) |
| 2026-10-31 | Step 3a after both Claude skeptic rounds: `make verify` | `make verify` | unit 25/0 · e2e 71/0 under check and sanitize · check-data as before · step-0a 2 ok · 0b 7 ok · 1 2 ok · 2 3 ok · 3a 7 ok (256 runs at `--mem 1M`: 3 MiB peak) · VERIFY PASSED (2 min 57 s) |
| 2026-10-30 | Step 3a: `make verify` from clean | `make clean && make verify` | unit 23/0 · e2e 65/0 under check and sanitize · check-data: import as step 2, build 1 run and 77 runs identical, `.gpt` = Python byte for byte · step-0a 2 ok · 0b 7 ok · 1 2 ok · 2 3 ok · 3a 5 ok · VERIFY PASSED (2 min 31 s) |
| 2026-10-29 | Step 2: `make verify` from clean | `make clean && make verify` | unit 17/0 · e2e 58/0 under check and sanitize · check-data: counts = DESIGN §13 = awk, all 10,064,891 codes = Python · step-0a 2 ok · 0b 7 ok · 1 2 ok · 2 3 ok · VERIFY PASSED (1 min 38 s) |
| 2026-10-28 | Step 1: `make verify` from clean | `make clean && make verify` | unit 10/0 · e2e 43/0 under check and sanitize · step-0a 2 ok · step-0b 7 ok · step-1 2 ok · VERIFY PASSED · Codex round 2: high=0 medium=0 low=0 |
| 2026-10-28 | Step 0b: `make verify` from clean | `make clean && make verify` | unit 1/0 · e2e 33/0 under check and sanitize · step-0a.sh 2 ok · step-0b.sh 7 ok · VERIFY PASSED · Codex round 2: high=0 medium=0 low=0 |
| 2026-10-28 | Step 0a: `make check` + `make sanitize` from clean | `make clean && make check && make sanitize` | unit 1/0 · e2e 18/0 · both exit 0 · sanitizers present (`nm`) |
| 2026-10-28 | T-Drive row counts (independent of our code) | `awk` over `data/raw/tdrive_txt/*.txt` | 10,088,351 rows · 23,357 at (0,0) · 103 out of range · 0 malformed |
| 2026-10-28 | Design diagrams render | `bake_mermaid.py docs/DESIGN.md` | 9 mermaid baked, 0 failed · 8 images in `docs/images/`, all linked files exist |

## Open decisions

| Decision | Needed by | Notes |
|---|---|---|
| ~~DESIGN §9.4, §9.3, §8 and TESTING §7 wording~~ | — | Applied in step 3b (see `docs/steps/step-3b.md` Decisions) |
| Store time per point? | Before stage 4 | Changes the `.gpt` format. DESIGN section 14 |
| ~~Opening view for spread-out data (DESIGN §9.3)~~ | — | Developer chose B on 2026-11-01: drop 5 % of the points at each end instead of 1 % (GeoLife opened on most of the northern world). Applied in step 11 (`docs/steps/step-11.md`) |
| Base map provider for the page | Developer to confirm | Step 6 uses OpenStreetMap's standard tiles, darkened by CSS (CARTO's dark tiles need an account). A one-line change in `www/app.js` plus the CSP |
| Box rule wording (DESIGN §9.2) | Developer to confirm | Longitude 180 as a box edge = the world's last unit; bbox at most 127 characters, each number at most 63. See `docs/steps/step-7.md` Decisions |
| A total time limit on exports | Developer to confirm | None in step 8, on purpose: a client that keeps reading is served; one that pauses 3 × timeout is let go. See `docs/steps/step-8.md` Decisions |
| Test time budgets (TESTING §2) | Developer to confirm | Proposed: `make check` under 90 s, `make sanitize` under 120 s, `make verify` under 15 minutes (now 57 s, 64 s and 12 min 29 s: the headless Chrome page tests and the export reader tests). See `docs/steps/step-9.md` Decisions |
| License | Developer to choose | v0.1.0 is packaged without one, so others can't legally use it. E.g. MIT, Apache-2.0 or GPL-3.0. Once a `LICENSE` is committed, `make release` packs it |

## Known issues
- A fresh clone has no pre-commit hook until `make hooks` is run (installed in this checkout).
- Leak checks are not available in `make sanitize` on macOS arm64 (no LeakSanitizer). Overflows and use-after-free are caught.
- A step's commit hash is written into this file after the commit, so it goes in with the next step's commit.
- **On this Mac the service runs on port 8090**, not 8080: `GPSTILES_PORT=8090 make deploy` / `make status` / `make rollback`. Without it they look at 8080 (`status`: "not answering"; `deploy`, `rollback`: refused, "installed on another port").
- The release package is not signed with a Developer ID or notarized: on another Mac, Gatekeeper blocks it until its quarantine flag is removed (`README.md` says how).
- If `tests/validate/step-9.sh` fails during its unwritable-`dist/` test, its temp folder (`$TMPDIR/gpstiles-step9.*`) is left behind: `rm -rf` can't empty the read-only folder. Passing runs clean up. Fix: `chmod -R u+w` before the `rm -rf` in its exit trap (found after the step 9 commit, when a deliberate break failed there).
