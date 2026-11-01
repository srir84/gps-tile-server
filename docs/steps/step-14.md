# Step 14: NYC taxis 2009–2010

## Summary

| | |
|---|---|
| **Built** | `tools/nyc-taxi.py`: TLC's yellow-taxi Parquet files → `lon,lat` rows (DuckDB, in `data/tools/venv/`, not part of the program) · the NYC taxis 2009–2010 (339,897,217 trips: 679,794,434 pickup and dropoff places, 668,475,278 on the map) imported, built out of core in 5 runs, served · their checks against DuckDB's own SQL count |
| **Status** | approved (all-stages go-ahead 2026-11-01) |
| **Date** | 2026-11-01 |
| **Agent(s)** | Claude Opus 5.5 main · Codex reviewer (gpt-6-astra, high effort) · Claude Opus 5.5 skeptic reviewer (separate agent) |

## NYC in numbers (this Mac)

| What | Result |
|---|---|
| Data | TLC's `yellow_tripdata_2009-01` … `2010-12.parquet`: 24 files, 11 GB (each size = the server's). From 2011 on TLC's files hold zone numbers (`PULocationID`), not places: checked on 2011-01 and 2013-06 |
| `nyc-taxi.py \| import --lon-col 1 --lat-col 2 --skip 1 /dev/stdin` | `rows=679794434 imported=668475278 skipped_zero=11315804 skipped_out_of_range=3242 skipped_malformed=110` in 3 min 36 s = DuckDB's SQL count (DESIGN §13) |
| `build` (default `--mem`, 1 GiB) | 5 runs, 97 s, peak memory 1.08 GB · `nyc-taxi.gpt` 5,347,802,480 bytes: the sort works with 5 times less memory than the data |
| Skipped | 11.3 million places at exactly (0,0) (a meter with no GPS fix), 3,242 off the map, 110 with no place |


| | |
|---|---|
| Places = DuckDB | Manhattan's zoom-10 tile 620,923,153 · JFK's zoom-14 tile 2,433,772 · LaGuardia 3,917,936 · Times Square 87,424,110 · a box at JFK through the API 6,654,591 |
| Tiles (`bench`, 668 million points) | p99 under 52 ms at every zoom: zoom 0 1.1 ms, 10: 18 ms, 13: 51 ms, 16: 21 ms |

## Design
- **No Parquet reader in the program:** `PROJECT_IDEAS.md` §8.4 says to convert Parquet with an existing tool. DuckDB (one Python package, 63 MB, in a private `venv` under `data/`, which is never committed) writes each file's pickups and then its dropoffs as `lon,lat` rows, its shortest exact text for each number, an empty field for a missing place. `gpstiles import` reads them from `/dev/stdin`; no CSV touches the disk.
- **The answers come from DuckDB's SQL**, written apart from our code: DESIGN §8's place rules over the same Parquet columns. The importer reads DuckDB's text, so the counts agreeing means the text and the rules agree.
- **Pickups and dropoffs are both points** (2 per trip), as the plan says ("2B+ points" for the full NYC set).
- **`make check-data` runs `check_nyc.py` with the `venv`'s Python** (it needs DuckDB); without it, or without the data, it prints SKIPPED.

## Files changed

| File | Change | Why |
|---|---|---|
| `tools/nyc-taxi.py` | added | Parquet → `lon,lat` rows (into a pipe only) |
| `tests/e2e/test_nyc_taxi.py` | added | 2 tests on tiny Parquet files (SKIPPED without DuckDB) |
| `tests/data/check_nyc.py`, `Makefile` | added, changed | NYC's real-data checks in `make check-data` (with DuckDB's Python) |
| `tests/validate/step-14.sh`, `tests/validate/lib.sh` | added, changed | DESIGN §12.6's check: the counts, the API at JFK = DuckDB, the page, bench |
| `docs/DESIGN.md`, `docs/TESTING.md`, `README.md`, `AGENTS.md` | changed | §13 NYC's facts · tests · how to get and import the data · where it is |

## Tests

| Test | Checks | Bug it would catch |
|---|---|---|
| `test_the_converter_keeps_every_place_of_both_years` | 2009's and 2010's column names, 8 trips each: NULL, NaN, infinity, (0,0), the map's edges, 1e308 → `rows=32 imported=20 skipped_zero=2 skipped_out_of_range=4 skipped_malformed=6` | a column dropped or swapped, a year's names not found, a bad place imported |
| `test_the_converter_refuses_a_file_and_a_year_without_places` | output to a file → exit 1; a file with zone numbers only → exit 1, "zone numbers" | half the rows lost into a file; a 2011-on file converted to nothing |
| `check_nyc.py` (`make check-data`) | counts = DESIGN §13 = DuckDB's SQL · `build` makes several runs · `info` = 0/0/0 = every point · Manhattan's zoom-10 tile = its 4 zoom-11 tiles = DuckDB's points inside its edges · JFK, LaGuardia, Times Square: their zoom-14 tiles = DuckDB's points inside their edges | the converter dropping or doubling places, a pickup and a dropoff column swapped, NULL or NaN places kept, places landing in the wrong tile |
| `step-14.sh` | the import line · the count API for a box at JFK = DuckDB's count · the page at Manhattan (zoom 12 and 16) over the base map and its opening view · bench: worst p99 at any zoom under 100 ms | the same, through the server and the page; slow tiles at 668 million points |

```text
unit        38 passed   0 failed
e2e        133 passed   0 failed
ALL PASSED (build)                                    make check (test_nyc_taxi.py's 2 tests ran: DuckDB is here)
unit        38 passed   0 failed
e2e        133 passed   0 failed
ALL PASSED (build/san)                                make sanitize
check-data: T-Drive, GeoLife, USGS, Porto as before
check-data: NYC import counts = DESIGN §13 = DuckDB: rows=679794434 imported=668475278 skipped_zero=11315804 skipped_out_of_range=3242 skipped_malformed=110 (118 s)
check-data: NYC build: points=668475278 runs=5 (100 s)
check-data: NYC info points=668475278 = 0/0/0 · count 10/301/384 (Manhattan) = 620,923,153 = its 4 zoom-11 tiles = DuckDB's points inside its edges
check-data: NYC JFK airport: tile 14/4834/6164 holds 2,433,772 points = DuckDB's points inside its edges (LaGuardia 3,917,936 · Times Square 87,424,110)
--- tests/validate/step-14.sh
  ok  nyc-taxi.py | import of 24 months → rows=679794434 imported=668475278 skipped_zero=11315804 skipped_out_of_range=3242 skipped_malformed=110 (DESIGN §13)
  ok  bbox=-73.8200005,40.6300005,-73.7500005,40.6600005 (JFK): count 6,654,591 = DuckDB's count of the places inside it
  ok  #nyc-taxi/12/40.7400/-73.9500: shows 668,475,278 points, 664,061,854 in view, over the base map · build/validate/step-14.png
  ok  #nyc-taxi/16/40.7580/-73.9855: shows 668,475,278 points, 127,957,705 in view, over the base map · build/validate/step-14-street.png
  ok  #nyc-taxi opens on New York: zoom 13, 40.749, -73.968
  ok  bench nyc-taxi (668 million points): zoom 0, 5, 10, 13, 16 p50/p99 (ms): 0:0.94/1.12 5:2.61/2.79 10:14.57/18.02 13:24.65/51.42 16:14.08/20.71 · worst p99 at any zoom: 51.42 ms
VERIFY PASSED (make verify, 30 min 26 s)
```

## Review (Codex)

Run with `CODEX_BIN=<wrapper> tools/review.sh 14` (gpt-6-astra, high reasoning effort). Files in `.review/step-14/`.

| Round | Finding (severity, file:line) | What happened |
|---|---|---|
| 1 | Medium, `README.md:60`: the documented pipeline hides a converter that fails (import sees the end of the rows and writes a short `.pts`, without `pipefail` the pipeline succeeds) | Fixed: the README's command uses `pipefail` and keeps the file only when both succeed; the converter's docstring says so. The checks already looked at both exit codes |
| 1 | Medium, `lib.sh:168`: the NYC cache ignored `tools/nyc-taxi.py` (as the skeptic's) | Fixed: the key holds the converter's SHA-256, DuckDB's version and import's options |
| 1 | Low: Parquet paths pasted into SQL (a folder named `O'Brien` breaks the checks) | Fixed: every `read_parquet` takes its path as a parameter, in `check_nyc.py` and `step-14.sh` (the converter already did) |
| 2 | All 3 fixed · Low: the new test's fixture maker pasted its output path into SQL (a temp folder named `O'Brien` breaks it) | Fixed after round 2: the quote doubled; the tests pass with `TMPDIR` in a folder named `O'Brien` |

Left for the developer to decide: none.

## Review (Claude skeptic, separate agent)

A second Claude Opus 5.5 agent with a fresh context, in its own copy, the real data read-only (one and two months only, by the brief). It confirmed DESIGN §13 with its own DuckDB query (all 24 files), the converter through a pipe for 1 and 2 months (= DuckDB), the SQL rules on a Parquet file of edge values (NULL, NaN, ±inf, -0.0, 1e308, 5e-324, ±180, ±85.0511… and just past), 202 tiles around Times Square and the 3 places, that no point lies near the JFK box's edges, and that a failing converter is reported by `nyc_gpt` and `check_nyc.py`.

| Round | Finding (severity) | What happened |
|---|---|---|
| 1 | Medium: the converter's output into a file loses half the rows (DuckDB writes each COPY to `/dev/stdout` from its start), exit 0 | Fixed: it refuses (exit 1) unless its output is a pipe. Tested. Caught (N3) |
| 1 | Low: the NYC cache ignored the converter | Fixed (as Codex 2) |
| 1 | Low: a failed run left a 5 GB `.pts` and counts that look whole | Fixed: `nyc_gpt` checks both exit codes and removes both files on failure |
| 1 | Low: the converter used about 1.5 GB of memory a month | Fixed: `preserve_insertion_order = false` (the rows' order doesn't matter to import): 467 MB, the same counts |
| 1 | Low: DuckDB not pinned | Fixed: the README installs `duckdb==2.0.0` |
| 1 | Test gaps: no small test of the converter; a missing DuckDB passes; an empty bench passes | Fixed: `test_nyc_taxi.py` (tiny Parquet files: both years' columns, the edge values; a file output and a zone-number file refused); `check_nyc.py` fails when the data is here but DuckDB isn't; `step-13.sh` and `step-14.sh` want one bench row a zoom |
| 2 | The medium and 3 lows fixed (re-run: a broken converter now rebuilds the cache; 755 MB for two months) · Low N1: the fast test's dropoffs were valid either way round, so swapped dropoff columns passed · Low N2: with the data but no `venv`, `make check-data` and `step-14.sh` still said SKIPPED · Low N3: a failed build left the 5 GB `.pts` | Fixed after round 2: a dropoff at (120, 10) (swapped: latitude 120, off the map), caught (N4); both fail when the files are here without DuckDB; a failed build removes `.pts` and `.counts` |

Left for the developer to decide: none.

**After both second rounds** (the 2-round limit, so no reviewer has seen these): the fixes for Codex's and the skeptic's round-2 findings above. Each is tested (N4; the `O'Brien` run); `make verify` ran after them.

## Proof the tests catch bugs

Each break was made in a scratch copy (deleted afterwards), then the named test was run.

| # | Break | Caught by |
|---|---|---|
| N1 | the converter writes the pickups only | `test_the_converter_keeps_every_place_of_both_years`: `rows=16 imported=4 …` |
| N2 | the converter writes `lat,lon` | the same test: `imported=18 … skipped_out_of_range=6` |
| N3 | the converter writes into a file (the pipe check gone) | `test_the_converter_refuses_a_file_and_a_year_without_places` |
| N4 | the dropoff columns swapped (the skeptic's round-2 N1) | `test_the_converter_keeps_every_place_of_both_years`: `imported=18 … skipped_out_of_range=6` |

The code was restored exactly afterwards: yes.

## Validate it yourself

| Do this | Expected | Actual (agent's run) |
|---|---|---|
| `tests/validate/step-14.sh` | the `ok` lines in Tests | as in Tests |
| http://127.0.0.1:8090/#nyc-taxi | New York, Manhattan brightest, both airports | after the deploy |

## Deploy (after approval)

After this commit: `GPSTILES_PORT=8090 make deploy`, `nyc-taxi.gpt` (built in `data/build/`) added to `datasets.conf`. The results go in `PROGRESS.md`, which goes in with the next commit.

## Who did what

| Agent | Did |
|---|---|
| Claude Opus 5.5 (main) | the converter, the checks, validation, this report |
| Codex CLI gpt-6-astra (high effort) | review (read-only) |
| Claude Opus 5.5 skeptic (separate agent, own copy) | adversarial review |

## Decisions
- **NYC is 2009–2010 only**, the years TLC's files still have places for (DESIGN §12.6). The billion points come in step 15.
- **DuckDB for Parquet, outside the program and `make check`**: a converter per the plan (§8.4); the program keeps zlib as its only dependency, and the tests that need DuckDB say SKIPPED without it.

## Not verified
- TLC's files from 2011 on: checked on 2011-01 and 2013-06 (zone numbers only), not every month.
- `nyc-taxi.py` with another DuckDB version than 2.0.0 (the number text and COPY to stdout are this version's).
- The page's box tool on NYC in Chrome (the count API is checked against DuckDB).

## Next
- Step 15: a billion points (NOAA AIS, January–May 2023) and the stage 4 report.
