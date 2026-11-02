# AGENTS.md

Rules for any agent (Claude, Codex, others) working in this repo. Humans: this is also the quickest way in.

## What this is
- **gps-tile-server**: turns millions to billions of GPS points into an interactive web map, served by one small C program (`gpstiles`) from one file per dataset.
- Built in small, reviewed steps. A human approves every step before the next one starts.

## Read first, in this order
1. `PROGRESS.md`: where the project is right now, and the exact next action.
2. `docs/DESIGN.md`: what we are building (architecture, formats, endpoints, step plan in section 12, known answers in section 13).
3. `docs/TESTING.md`: how to test each step (levels, answer sources, tests per step).
4. The latest `docs/steps/step-N.md`: what the previous step did.

## Commands
Use only these to build, test, review and deploy. Build and test commands exist from step 0a, loop tools from 0b, later ones as marked.

| Command | Does |
|---|---|
| `make` | Build `build/gpstiles` |
| `make check` | Build + unit, random-input, bad-input and end-to-end tests (seconds, no `data/` needed) |
| `make sanitize` | Same tests under AddressSanitizer + UndefinedBehaviorSanitizer |
| `make check-data` | Real-data checks (T-Drive, GeoLife, …) against `awk` / Python answers (minutes, needs `data/`; each dataset SKIPPED without its files) |
| `make verify` (0b) | check + sanitize + check-data (if `data/` exists) + every step's `tests/validate/step-N.sh` |
| `tools/review.sh N` (0b) | Codex reviews step N, read-only, fresh context → `.review/step-N/round-K.md` (max 2 rounds) |
| `make hooks` (0b) | Install the pre-commit hook (check + sanitize on the staged files) |
| `make deploy-test` | Pre-approval check: temporary install in `build/`, test label, free port, removed afterwards (from step 5b) |
| `make deploy` / `rollback` / `undeploy` / `status` | Local service on this Mac, with smoke test and automatic rollback. After approval only (from step 5b) |
| `make release-test` | Pre-approval check: package + smoke test in `build/`, no tag (from step 9) |
| `make release VERSION=x.y.z` | Package + `.sha256` in `dist/` + local tag, after a smoke test. After approval only (from step 9) |
| `make clean` | Remove `build/` |

## Workflow (every step)
1. Read `PROGRESS.md`. Work only on the step it names.
2. Set the step to `in progress` in `PROGRESS.md`.
3. Build the step as `docs/DESIGN.md` section 12.2 (stage 1) or 12.4 (stage 2) describes. Nothing from later steps.
4. Verify: `make verify` green (step 0a: `make check` + `make sanitize`), plus the bug-catching proof (see "Definition of done").
5. Review: `tools/review.sh N` (in step 0a, before the script exists: `codex exec -s read-only` by hand). Fix each finding or write why not. At most 2 rounds.
6. Validate: run the step's validation for real (CLI output, headless Chrome screenshot for steps 4 and 6) and look at the result.
7. Write `docs/steps/step-N.md` from `docs/steps/TEMPLATE.md`.
8. Update `PROGRESS.md`: status `waiting for review`, last verified results, the next action.
9. **Stop.** Do not commit, deploy or start the next step.
10. After the developer approves: commit (message `step N: <name>`). From step 5b on, `make deploy`. Set the status to `approved` with the commit hash, and set the next action.

Loop limits (TESTING.md §12.8): 3 fix tries per problem, 2 review rounds, then stop and write the problem under "Blocked on" in `PROGRESS.md`. If you and the reviewer disagree, the developer decides.
Codex as builder: there is no Stop hook for you, so run `make check` before ending every turn.

Picking up mid-step: trust the files and `git status`, not memory. Re-run `make check` before building on someone else's work.

## Definition of done (one step)
- `make check`, `make sanitize` and `make check-data` (real checks from step 2) pass. Paste the summary lines into the step file. A `SKIPPED` because `data/` is missing is not a pass: list it under "Not verified".
- Tests follow `docs/TESTING.md`: a `catches:` line on every test, tests added as section 9 lists for the step.
- Every new test names the real bug it would catch.
- Proof the tests catch bugs: at least 2 deliberate breaks per step from step 1 on (TESTING.md section 8), in a scratch copy, each with the test that failed. Steps 0a/0b use the setup proof in TESTING.md section 8. The real tree is left unchanged.
- The step's validation command from DESIGN 12.2 has been run, and its real output is pasted next to the expected output. `tests/validate/step-N.sh` automates it.
- Codex review done. Every finding is fixed or answered in the step file.
- Answers are checked against independent sources (DESIGN section 13), never against the code's own output.
- "Not verified" lists every gap. An empty list must be true.

## Code rules
- The Makefile must work with GNU Make 3.81 (the version on macOS). No newer features such as `.ONESHELL`, `$(file ...)` or grouped targets `&:`.
- C11, `cc` with `-Wall -Wextra -Wpedantic -Wshadow -Wconversion -Werror`.
- Only one dependency, zlib. The map page uses Leaflet 1.9.4, pinned with an integrity hash.
- Follow the module plan in DESIGN section 6. Every new file starts with a 1–3 line comment saying what it is for.
- Validate all external input: files, HTTP requests, command-line arguments. Bad data is counted and skipped, never a crash.
- The server listens on 127.0.0.1 by default and is read-only, with limits on request size, connections and export rows.
- Small, readable diffs. No speculative features.

## Data
- `data/` is never committed. Raw downloads go in `data/raw/`; generated `.pts` / `.gpt` files go in `data/build/`.
- T-Drive is already downloaded to `data/raw/tdrive/` (zips) and `data/raw/tdrive_txt/` (8,911 text files).
- GeoLife (step 10) is in `data/raw/geolife/`: the zip from download.microsoft.com and its `Geolife Trajectories 1.3/Data/` (18,670 `.plt` files, DESIGN §13).
- The USGS earthquakes (step 11) are in `data/raw/usgs/`, fetched by `tools/fetch-usgs.py` (58 files, `MANIFEST.txt`).
- The Porto taxis (step 12) are in `data/raw/porto/` (UCI's zip and `train.csv`, DESIGN §13).
- The NYC taxis 2009–2010 (step 14) are in `data/raw/nyc-taxi/` (24 Parquet files); DuckDB, for them only, in `data/tools/venv/` (not part of the program or `make check`).
- NOAA's AIS ship positions, January–May 2023 (step 15), are in `data/raw/ais/` (151 zips from `tools/fetch-ais.sh`).
- OpenStreetMap's GPS traces of 2013 (step 16) are in `data/raw/osm-gps/` (the `tar.xz`, its `.md5`, and `metadata.xml` taken out of it).
- OpenSky's public aircraft positions of Monday 2022-06-27 (step 17) are in `data/raw/opensky/` (24 hourly tars from `tools/fetch-opensky.py`). OpenSky's full history (Trino) is only for institutions, so it isn't used.
- GBIF's 2024 occurrences (step 18) are in `data/raw/gbif/` (the zip, `download.json` with its DOI, `state.json`), fetched with the developer's GBIF login from `~/.config/gpstiles/gbif.netrc` (outside the repo; never print, copy or commit it).
- Datasets that need an account (Kaggle, GBIF, OpenSky): never create accounts yourself. Ask the developer, who registers with [email removed].

## Docs
- Keep docs minimal: this file, `PROGRESS.md`, `docs/DESIGN.md`, `docs/TESTING.md`, `docs/steps/`. Create a new doc only if the developer asks.
- Prefer diagrams and tables to prose.
- Any `.md` with a ```mermaid diagram must be baked before you hand it over: `python3 ~/.agents/templates/bake_mermaid.py <file.md>`.
- If the design needs to change, propose it in the step file under "Decisions". Do not edit DESIGN decisions silently.

## Never
- Start the next step without the developer's approval.
- Commit without approval, or commit `data/`.
- Claim something works without the command output that shows it.
- Weaken or delete a test to make it pass.
- Turn off or bypass a hook (`--no-verify`, editing `.claude/settings.json` or `tools/stop-gate.sh`) to get past a red check.
- Deploy before approval, or publish a release anywhere (push, upload) without the developer saying so.
- Let the reviewer edit code. Codex runs read-only.
- Push anywhere but `origin` (github.com/srir84/gps-tile-server, private), or commit or push as anyone but `srir84`. This repo's own git config sets both (`user.email` 179548959+srir84@users.noreply.github.com; pushes use gh's `srir84` login whatever account gh has active). Don't change that config.
