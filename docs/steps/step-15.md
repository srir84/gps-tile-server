# Step 15: A billion points (NOAA AIS) + stage 4 report

## Summary

| | |
|---|---|
| **Built** | `tools/fetch-ais.sh`: NOAA's AIS ship positions, one zip a day, each kept only whole · January–May 2023 (151 days, 45 GB) imported day by day from the zips and built into one `.gpt` of **1,216,355,854 points** with a 1 GiB sort buffer (10 runs) · its checks · the stage 4 report |
| **Status** | approved (all-stages go-ahead 2026-11-01) |
| **Date** | 2026-11-01 |
| **Agent(s)** | Claude Opus 5.5 main · Codex reviewer (gpt-6-astra, high effort) · Claude Opus 5.5 skeptic reviewer (separate agent) |

## Stage 4 in numbers (this Mac: 16 cores, 128 GB of memory)

| | NYC taxis 2009–2010 (step 14) | NOAA AIS Jan–May 2023 (step 15) |
|---|---|---|
| Points | 668,475,278 (of 679,794,434 places) | **1,216,355,854** (of 1,216,355,904 rows) |
| Answer source | DuckDB's SQL | `awk` over every day, streamed from the zips |
| Import | 3 min 36 s (Parquet → DuckDB → pipe) | 16 min 23 s (151 days, `unzip -p` → pipe) |
| Build (default `--mem`, 1 GiB) | 5 runs, 97 s, peak 1.08 GB | 10 runs, 149 s, peak 1.08 GB |
| `.gpt` | 5.3 GB | 9.7 GB |
| Tiles, p99 at any zoom (`bench`, warm disk cache) | under 52 ms | about 20 ms (21.5 ms in `step-15.sh`, 22 ms in the skeptic's run; cold, the first time the file is read: up to 0.5 s) |

Drawing one tile at 1.2 billion points (`gpstiles bench`, drawing only), p50 / p99 in milliseconds:

| Zoom | 0 | 2 | 5 | 8 | 10 | 13 | 15 | 18 | 20 | 24 |
|---|---|---|---|---|---|---|---|---|---|---|
| p50 / p99 | 1.1 / 1.4 | 3.2 / 10.9 | 9.2 / 20.7 | 5.5 / 16.1 | 4.3 / 11.8 | 2.3 / 8.6 | 1.8 / 7.2 | 1.0 / 2.7 | 0.6 / 1.0 | 0.55 / 0.61 |

**What stage 4 shows** (`PROJECT_IDEAS.md` §8.5: "over 1 billion points; build must work out-of-core; tile latency stays in milliseconds"):
- **Over a billion points:** 1,216,355,854, from one file, served by the same small program.
- **Out of core:** 9.7 GB of points sorted with a 1 GiB buffer, in 10 runs, peak memory 1.08 GB. This Mac's memory (128 GB) is bigger than the data, so the files sat in its disk cache; the sort itself never held more than a ninth of the points.
- **Milliseconds:** every zoom's p99 is about 20 ms at 1.2 billion points once the file is in the disk cache (the first read from disk is slower: the skeptic measured p99 of 0.4–0.5 s at zooms 2–10 cold), because a tile is counted by cutting it into slices (step 13), not point by point (that would be about 2.4 s for the world tile).

## Every stage 4 check (DESIGN §12.6)

| Check | Result |
|---|---|
| Over a billion points | 1,216,355,854 |
| The counts = an independent count | AIS: the 151 days' import counts added up = `awk` over every day (DESIGN §13); NYC: = DuckDB's SQL |
| Points land in the right place | AIS: 3 ports (Houston ship channel, New York harbor, the Port of Los Angeles) on 1 January = Python's points inside the tiles' edges; NYC: Manhattan, JFK, LaGuardia, Times Square = DuckDB; the pictures (`step-14.png`, `step-15.png`) |
| Tile counts add up | the 4 zoom-1 tiles = every point; Houston's zoom-9 tile = its 4 zoom-10 tiles |
| A build out of core | 10 runs with 1 GiB for 9.7 GB (and NYC: 5 runs for 5.3 GB) |
| Tile latency in milliseconds | p99 under 21 ms at every zoom |
| Area count, export, API | NYC: a box at JFK = DuckDB; AIS: served and drawn (`step-15.sh`) |

## Design
- **The dataset:** the plan's NYC taxis 2009–2016 would have been 2+ billion points, but TLC's files hold places for 2009–2010 only (step 14: 668 million). NOAA's AIS positions (planned for stage 5) are plain CSV with no account and about 8 million rows a day, so 151 days pass a billion.
- **No CSV on disk:** each day's zip streams through `unzip -p` into `gpstiles import /dev/stdin`, one `.pts` a day (65 MB), and `build` takes all 151 at once (DESIGN §9.1: `IN.pts...`). The raw zips stay (45 GB) for the checks.
- **`tools/fetch-ais.sh`:** one day at a time with a pause, written under a temporary name and kept only when its size is the server's `Content-Length` and `unzip -t` finds it whole; a rerun skips kept days. `AIS_URL` points it at a fake server for its test.
- **Checks sized for `make verify`:** `awk` over all 151 days takes over an hour, so `make check-data` checks 3 days (the first, middle and last) against `awk` and one day's every code and 3 ports against Python (2 minutes); the whole set was counted by `awk` once (DESIGN §13), and `step-15.sh` builds and checks it all, kept in `build/validate/` while nothing changes (about 20 minutes when it must rebuild).

## Files changed

| File | Change | Why |
|---|---|---|
| `tools/fetch-ais.sh` | added | the download, each day checked whole (and every kept day again) |
| `tests/e2e/test_fetch_ais.py` | added | 3 tests against a fake server |
| `tests/data/check_ais.py`, `Makefile` | added, changed | AIS's light checks in `make check-data` |
| `tests/validate/step-15.sh`, `tests/validate/lib.sh` | added, changed | DESIGN §12.6's check on all 1.2 billion points (`ais_gpt`, kept while unchanged) |
| `docs/DESIGN.md`, `docs/TESTING.md`, `README.md`, `AGENTS.md` | changed | §13 AIS's facts · tests · how to get and import the data · where it is |

## Tests

| Test | Checks | Bug it would catch |
|---|---|---|
| `test_whole_days_are_kept_a_bad_one_leaves_nothing_and_a_rerun_resumes` | a fake server: a good day kept; a corrupt one of the right size refused, no `.part` left; a rerun fetches the rest and leaves kept days alone; a missing day and a bad date refused | a broken zip kept as a day, a half file left, kept days fetched again |
| `check_ais.py` (`make check-data`) | 3 days: import = `awk` on the same stream · 1 January: every code = Python, 3 ports' tiles = Python's points inside their edges | a day read wrong, places in the wrong tile |
| `step-15.sh` | the 151 days' counts added up = DESIGN §13 · `build` in several runs · the 4 zoom-1 tiles = every point, Houston's tile = its 4 smaller tiles · the page over the base map · bench: 25 rows, p99 under 100 ms at every zoom | a day lost or doubled, an in-memory build, a merge that loses points, slow tiles at a billion points |

```text
unit        38 passed   0 failed
e2e        136 passed   0 failed
ALL PASSED (build)                                    make check
unit        38 passed   0 failed
e2e        136 passed   0 failed
ALL PASSED (build/san)                                make sanitize
check-data: T-Drive, GeoLife, USGS, Porto, NYC as before
check-data: AIS AIS_2023_01_01: rows=8156509 imported=8156509 skipped_zero=0 skipped_out_of_range=0 skipped_malformed=0 = awk
check-data: AIS AIS_2023_01_01, Houston ship channel: tile 12/967/1693 holds 2,909 points = Python's points inside its edges (New York harbor 48,848 · Port of Los Angeles 53,724)
check-data: AIS AIS_2023_01_01: all 8,156,509 codes = the Python rules
check-data: AIS AIS_2023_04_07: rows=8596916 imported=8596914 skipped_zero=0 skipped_out_of_range=1 skipped_malformed=1 = awk
check-data: AIS AIS_2023_05_31: rows=8675457 imported=8675457 skipped_zero=0 skipped_out_of_range=0 skipped_malformed=0 = awk
check-data: AIS 3 days built with --mem 64M (points=25428880 runs=4) = built in one run, byte for byte
--- tests/validate/step-15.sh
  ok  import of 151 days, added up → rows=1216355904 imported=1216355854 skipped_zero=0 skipped_out_of_range=39 skipped_malformed=11 (DESIGN §13)
  ok  build: points=1216355854 runs=10 (out of core: 9.7 GB of points, a 1 GiB sort buffer)
  ok  the same points with a 2 GiB buffer (points=1216355854 runs=5) = the 1 GiB build (10 runs), byte for byte
  ok  the 4 zoom-1 tiles add up to 1,216,355,854 · tile 9/120/211 (Houston) = 46047980 = its 4 smaller tiles
  ok  #ais-2023/6/27.0000/-88.0000: shows 1,216,355,854 points, 616,080,144 in view, over the base map · build/validate/step-15.png
  ok  bench ais-2023 (1,216,355,854 points, warm disk cache): zoom 0, 5, 10, 15, 20 p50/p99 (ms): 0:1.04/1.19 5:7.95/20.36 10:4.13/11.50 15:1.70/6.89 20:0.60/0.96 · worst p99 at any zoom: 20.36 ms
VERIFY PASSED (make verify, 34 min 39 s)
Once, by hand: all 151 days' awk counts = their import lines (data/raw/ais/awk-days.txt) · build --mem 12G: runs=1, the same file as the 10-run one
```

## Review (Codex)

Run with `CODEX_BIN=<wrapper> tools/review.sh 15` (gpt-6-astra, high reasoning effort). Files in `.review/step-15/`.

| Round | Finding (severity, file:line) | What happened |
|---|---|---|
| 1 | Medium, `README.md:61`: the AIS line hides a broken zip (import sees the rows end and keeps a short `.pts`) | Fixed: `pipefail`, a `.new` file renamed only when both succeed |
| 1 | Medium, `lib.sh:224`: no many-run = one-run comparison on AIS | Fixed: `step-15.sh` builds the full 1.2 billion again with a 2 GiB buffer (5 runs) and the file must be the 1 GiB one (10 runs), byte for byte; one run = many runs on 25 million AIS points in `check_ais.py` (one run of all 9.7 GB would need 10 GB of memory) |
| 1 | Medium, `step-15.sh:17`: no Chrome skipped every billion-point check | Fixed: only the page needs Chrome |
| 1 | Low, `fetch-ais.sh:12`: impossible dates and backwards ranges taken | Fixed (with the skeptic's L2): a day must read back the same from `date`, the first not after the last; tested |
| 2 | 1, 3, 4 fixed · Medium: 2 partly: the full set is compared between two many-run builds (10 and 5 runs), one run only on 3 days · Medium: a kept zip damaged inside (its list of files intact) was trusted on a rerun · Low: a failed rename reported success and kept nothing | Fixed after round 2: a one-run build of all 1.2 billion points (`--mem 12G`, once, by hand: 10 GB of memory) = the 10-run file, byte for byte (below); kept days must pass `unzip -t` (tested with a damaged zip; about 7 minutes on a full rerun); a failed rename fails the run and the trap removes `.part` |

Left for the developer to decide: none.

## Review (Claude skeptic, separate agent)

A second Claude Opus 5.5 agent with a fresh context, in its own copy (the full build off limits by the brief; `check_ais.py` once, `bench`/`info`/`count` read-only on the real file, `fetch-ais.sh` against its own server only). PIPESTATUS, the sums past 2^31, the cleanup, 1,216,355,854 points and 10 runs all checked out.

| Round | Finding (severity) | What happened |
|---|---|---|
| 1 | Medium M1: the first `bench` on a cold disk cache gave p99 of 407–538 ms at zooms 2–10; the report's 21 ms is warm, and a rerun of `step-15.sh` (the build kept) would time a cold file | Fixed: `step-15.sh` reads the file once before `bench`; the report says warm and gives the cold numbers |
| 1 | Medium M2: no many-run = one-run check for AIS | Fixed (as Codex 2) |
| 1 | Medium M3: DESIGN §13 said "= awk over every day" before that `awk` run had finished (135 of 151 days then) | Fixed: the run finished; all 151 days compared one by one (below); the counts kept in `data/raw/ais/awk-days.txt` |
| 1 | Low L1: a stopped download left `.part` | Fixed: a trap removes it |
| 1 | Low L2: impossible dates (macOS's `date` turns 02-29 into 03-01), backwards ranges and a failing `date` | Fixed and tested |
| 1 | Low L3: the size request didn't follow redirects or retry | Fixed: `-L --retry 3`, the last answer's status and size |
| 1 | Low L4: any file in the folder was a kept day (an empty one too) | Fixed: a kept day must list exactly one CSV; tested with an empty file |
| 1 | Low L5: `check_ais.py` read an 877 MB CSV into memory (3.6 GB) | Fixed: line by line (206 MB) |
| 1 | Low L6: the README's AIS line had no `pipefail` and the wrong folder | Fixed |
| 1 | Low L7: DESIGN said `--mem 2G`, "45 GB", and "out of core" without saying against what | Fixed: the default 1 GiB, 47.6 GB, and the wording above (against the sort buffer, not this Mac's memory) |
| 1 | Test gaps: a size check that could go unnoticed, dates, sample days with no skipped rows, the cache key | Fixed: a server that states another size (refused, no `.part`); dates; 7 April (one row off the map, one malformed) in the sample; the key holds `lib.sh`'s hash. Not done: a cold-cache bench in the scripts (it needs `sudo purge`) |
| 2 | M1–M3 and L1, L2, L3, L5, L6 fixed (re-run: interrupts, month and year ends, a 2024 leap day, a redirect); L4, L7 partly · Low N1: a new download holding 2 CSVs was kept · Low N2: SIGTERM to the script left curl running · Low N3: the cache looked only for the last day's `.pts`, and hashed all of `lib.sh` | Fixed after round 2: a new download must hold exactly one CSV (tested); curl runs as a child the trap stops; the cache wants all 151 `.pts` and hashes only `ais_gpt`'s own code; "about 20 ms"; TESTING's row. The damaged-inside kept zip (L4): fixed with Codex's round-2 finding |

Left for the developer to decide: none.

**After both second rounds** (the 2-round limit, so no reviewer has seen these): the fixes above, each tested (A1–A3 below; the damaged and 2-CSV zips); `make verify` ran after them. And the one-run comparison Codex asked for, run once by hand: `gpstiles build --mem 12G` of all 151 days → `points=1216355854 runs=1` in 140 s, peak memory 9.7 GB; `cmp` with the 10-run file: the same, byte for byte.

## Proof the tests catch bugs

Each break was made in a scratch copy (deleted afterwards), then the named test was run.

| # | Break | Caught by |
|---|---|---|
| A1 | `fetch-ais.sh` without the size check | `test_a_download_of_another_size_than_the_server_said_is_refused` |
| A2 | `fetch-ais.sh` trusts a kept day without `unzip -t` | `test_whole_days_are_kept_a_bad_one_leaves_nothing_and_a_rerun_resumes` (the damaged kept zip) |
| A3 | a new download not held to one CSV | `test_a_day_that_isnt_one_csv_is_refused` |

The import and build code didn't change in this step (step 14's and 13's breaks stand); the many-run = one-run and 2 GiB = 1 GiB comparisons check the merge on AIS's own points.

The code was restored exactly afterwards: yes.

## Validate it yourself

| Do this | Expected | Actual (agent's run) |
|---|---|---|
| `tests/validate/step-15.sh` | the `ok` lines in Tests | as in Tests |
| `gpstiles bench data/build/ais-2023.gpt` | p99 under about 20 ms at every zoom | the table above |
| http://127.0.0.1:8090/#ais-2023 | the US coasts, shipping lanes and ports | after the deploy |

## Deploy (after approval)

After this commit: `GPSTILES_PORT=8090 make deploy`, `ais-2023.gpt` (9.7 GB, in `data/build/`) added to `datasets.conf`. The results go in `PROGRESS.md`, which goes in with the next commit.

## Who did what

| Agent | Did |
|---|---|
| Claude Opus 5.5 (main) | the download, import, build, checks, this report |
| Codex CLI gpt-6-astra (high effort) | review (read-only) |
| Claude Opus 5.5 skeptic (separate agent, own copy) | adversarial review |

## Decisions
- **AIS for the billion points** (planned for stage 5): NYC's public files can't reach a billion any more (step 14).
- **January–May 2023:** 151 days, enough to pass a billion with a margin (8 million a day).
- **The full `awk` count runs once**, not in every `make verify` (over an hour); `make verify` checks 3 days, and `step-15.sh` the whole build.

## Not verified
- A cold-cache `bench` in the scripts (it needs `sudo purge`); the skeptic measured p99 of 0.4–0.5 s at zooms 2–10 on the first read of the file from disk.
- A file bigger than this Mac's memory (128 GB): the 9.7 GB file sat in the disk cache; only the sort's buffer was smaller than the data.
- The page's box tool on AIS (the API and tiles are checked).
- `fetch-ais.sh` against MarineCadastre after the fixes (the real data was fetched by its first version, from the scratchpad; every day = `awk` = import).

## Next
- Stage 5: a GPX reader (OpenStreetMap's public GPS traces) and the world datasets that need accounts (GBIF, OpenSky: the developer registers).
