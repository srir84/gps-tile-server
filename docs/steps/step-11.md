# Step 11: Worldwide (USGS earthquakes) + stage 2 report

## Summary

| | |
|---|---|
| **Built** | `tools/fetch-usgs.py`: USGS's earthquake catalog, 1900 to 2026-10-01, each period checked against USGS's own count · the earthquakes (4,770,607 points over the whole world) imported with import options only · their real-data checks in `make check-data` · the opening view drops 5 % of the points at each end (the developer's choice B) · the stage 2 report |
| **Status** | approved (stage 2 go-ahead 2026-11-01) |
| **Date** | 2026-11-01 |
| **Agent(s)** | Claude Opus 5.5 main · Codex reviewer (gpt-6-astra, high effort) · Claude Opus 5.5 skeptic reviewer (separate agent) |

## Stage 2 in numbers (this Mac, warm file cache)

| | T-Drive (stage 1) | GeoLife (step 10) | USGS earthquakes (step 11) |
|---|---|---|---|
| What | 10,357 Beijing taxis, one week | 182 people, mostly Beijing, 5 years | every quake USGS lists, 1900 to 2026-10-01 |
| Files, layout | 8,911 `.txt` · `id,time,lon,lat` | 18,670 `.plt` · 6 header lines, CRLF, latitude first | 58 `.csv` · USGS's 22 columns, a header line, quoted places |
| Import options | `--lon-col 3 --lat-col 4` | `--lat-col 1 --lon-col 2 --skip 6` | `--lat-col 2 --lon-col 3 --skip 1` |
| Rows → points | 10,088,351 → 10,064,891 | 24,876,978 → 24,876,977 | 4,771,181 → 4,770,607 |
| Skipped | 23,357 at (0,0), 103 off the map | 1 off the map (latitude 400) | 9 at (0,0), 565 off the map (all north of 85.05°) |
| Answer sources | `awk`, Python | `awk`, Python, the user guide | `awk`, Python, USGS's count of every period |
| `import` | 1.85 s, 2 MB | 6.7 s, 4.8 MB | 0.9 s, 3 MB |
| `build` | 1.02 s, 80 MB | 2.2 s, 202 MB | 0.56 s, 41 MB |
| `.gpt` | 80,519,384 bytes | 199,016,072 bytes | 38,165,112 bytes |
| Opens at (1400 × 860 window, 5 % rule) | Beijing, zoom 10 | eastern China, zoom 6 (was most of the northern world at zoom 3) | the whole world, zoom 2 |

Drawing one tile (`gpstiles bench`: drawing only, without HTTP; 100 renders a zoom over the tiles under points spread evenly through the file), p50 / p99 in milliseconds:

| Zoom | T-Drive | GeoLife | Earthquakes |
|---|---|---|---|
| 0 (the world) | 20.7 / 38.6 | 49.2 / 49.9 | 11.6 / 12.2 |
| 5 | 21.1 / 21.6 | 43.7 / 44.4 | 6.1 / 9.8 |
| 10 | 9.2 / 11.6 | 14.4 / 24.9 | 1.2 / 4.8 |
| 15 | 1.5 / 3.9 | 2.1 / 9.2 | 0.54 / 0.99 |
| 18 (streets) | 0.59 / 1.2 | 0.72 / 6.8 | 0.53 / 0.57 |
| 24 | 0.53 / 0.55 | 0.53 / 0.55 | 0.53 / 0.56 |

A tile costs about 2 ns per point in it, plus about 0.5 ms however few: GeoLife's zoom-0 tile draws 24.9 million points in 49 ms. At a billion points a zoomed-out tile would take about 2 s by the same measure; stage 4 has to answer that.

## Every stage 2 check (DESIGN §12.4, `PROJECT_IDEAS.md` §8.5)

| Check | GeoLife | Earthquakes |
|---|---|---|
| A new layout with import options only, no code change | yes: `gpstiles` unchanged in step 10 | yes: the only change to `gpstiles` in step 11 is the view rule (B) |
| Points land in the right place | 4 places = Python's rows inside the tile's edges in degrees; the picture matches the user guide's Figure 1 | 6 places around the Pacific, both sides of 180° = Python's rows; the Ring of Fire (`step-11.png`) |
| The file's count = the points imported | 24,876,977 = `awk` = DESIGN §13 | 4,770,607 = `awk` = DESIGN §13 |
| Tile counts add up from one zoom to the next | Beijing's zoom-6 tile = its 4 zoom-7 tiles = slow count | the 4 zoom-1 tiles; the tiles on both sides of 180° = their 4 smaller tiles = slow counts |
| Build time and tile speed recorded | above | above |
| Area count, export and API right | a box's count = slow count, its export = as many rows, all inside | boxes across 180° and around Japan = slow counts; a box drawn across 180° on the page = its two halves = Python |
| A worldwide spread works (poles, 180° line, both hemispheres) | traces in China, the US and France | all 4 quarters; 565 quakes past 85.05° counted and skipped; 12 rows at exactly ±180° |

## Design
- **`tools/fetch-usgs.py`** reads USGS's FDSN event service (`eventtype=earthquake`), one period at a time (1900–1969, then a year each). USGS answers at most 20,000 rows a request, so a period is cut into time windows that USGS counts at most 20,000 quakes in (count, cut in equal parts, count again), each read with one request; a window's rows must equal its count, a quake's id may come only once, and the whole period's rows must equal USGS's count of the period. A file is written under a temporary name and kept only then; `state.json` lets a rerun skip kept periods; `MANIFEST.txt` lists every file with its rows and USGS's count. One request at a time, a pause of 1 s before each, retries on server errors (5, 10, 20, 40 s), a failed certificate check stops at once (Python from python.org has no certificates of its own: the tool adds macOS's `/etc/ssl/cert.pem`, checks stay on).
- **Why windows, not pages:** the first version paged by time (each page starting at the last row's time) and refused a page out of order. On 2018 it stopped: in the Anchorage aftershocks USGS sends a quake at 23:59:50.170 after one at 23:59:51.262, so paging by time could skip a quake. Windows never depend on USGS's order. (1900–2017 were fetched by the first version, every page in order, every period = USGS's count; 2018–2026 by the final one. No id appears twice in the 58 files.)
- **USGS's end time is included:** a period ends 1 ms before the next starts (with `endtime=1970-01-01`, 1900–1969 counts 49,843; it holds 49,841).
- **The opening view drops 5 % of the points at each end** (DESIGN §9.3, the developer's choice B on 2026-11-01). One number in `build.c`, the same in the Python rules (`tests/oracle/gpt_rules.py`) and in the unit test's own count. The view is written by `build`, so a `.gpt` built before keeps the 1 % view until it is built again; `make deploy` doesn't build data, so after this step's deploy the service's `.gpt` files are rebuilt by hand (`PROGRESS.md`).
- **The earthquakes on the map:** 85 % are in the north-west quarter (US networks record many small quakes in California, Alaska, Nevada and Hawaii), so a rule that zooms into the busiest quarter (option D) would have opened them on the US; with B they open on the whole world.

## Files changed

| File | Change | Why |
|---|---|---|
| `tools/fetch-usgs.py` | added | the download, each period checked against USGS's count |
| `tests/e2e/test_fetch_usgs.py` | added | 3 tests against a fake USGS that sends rows newest first |
| `tests/data/check_usgs.py`, `Makefile` | added, changed | the earthquakes' real-data checks in `make check-data` |
| `tests/validate/step-11.sh`, `tests/validate/lib.sh` | added, changed | DESIGN §12.4's check: the 180° line by the API and on the page, the world map, the opening views, bench |
| `src/build.c`, `src/build.h` | changed | the view box drops 5 % at each end |
| `tests/oracle/gpt_rules.py`, `tests/unit/test_build.c` | changed | the same rule in the Python rules and in the unit test's own count |
| `docs/DESIGN.md` | changed | §9.3's rule · §13 the earthquakes' facts |
| `README.md`, `docs/TESTING.md`, `AGENTS.md` | changed | more datasets and how to get them · the test files · where the data is |

## Tests

| Test | Checks | Bug it would catch |
|---|---|---|
| `test_windows_join_without_losing_or_doubling_rows` | a fake USGS (rows newest first): 3 quakes at one time, one at the last moment of 1990, one at midnight on 1 January 1991, an empty year; `--page 5` | a request for more than its limit, rows lost or doubled where windows meet, rows taken in USGS's order |
| `test_server_errors_are_retried_and_a_failed_period_leaves_no_file` | two server errors, then success; 5 errors: exit 1, the period's file not written; a rerun resumes | a passing error ending the download, a half file kept |
| `test_a_cut_answer_is_retried_and_other_dates_need_another_folder` | answers cut inside their last value (twice) are retried · another `--until` in the same folder, and a file of another download, refused (exit 2) · an emptied file and one changed on the same lines fetched again, the rest kept | a cut row kept, overlapping downloads in one folder, a damaged file trusted |
| `test_rows_unequal_to_the_count_and_a_changed_header_are_refused` | counts off by one (every count, or only the year's), a header with two columns swapped, 6 quakes in one millisecond with `--page 5`, bad options | a short window or year kept, the wrong columns imported, an endless cut |
| `check_usgs.py` (`make check-data`) | every file = `MANIFEST.txt` = USGS's count · counts = DESIGN §13 = `awk` · every code = Python · the rows off the map are the quakes past 85.05° · the 4 quarters, the tiles at 180°, 6 places = Python | anything that turns USGS's rows into wrong counts, codes or places |
| `step-11.sh` | DESIGN §12.4's checks through the server and the page, the opening views, bench | as above, through the server and the page |
| `test_build`, `test_info_count`, unit `header_stats_match_slow_counts` (changed) | the header's view box against the Python rules and the unit test's own count, at 5 % | the old 1 % rule, or any other cut |

```text
unit        33 passed   0 failed
e2e        127 passed   0 failed
ALL PASSED (build)                                    make check
unit        33 passed   0 failed
e2e        127 passed   0 failed
ALL PASSED (build/san)                                make sanitize
check-data: T-Drive and GeoLife as before (the T-Drive header = the Python rules, now with the 5 % view)
check-data: USGS: 58 files, 4,771,181 rows, each file = USGS's own count of its period
check-data: USGS import counts = DESIGN §13 = awk: rows=4771181 imported=4770607 skipped_zero=9 skipped_out_of_range=565 skipped_malformed=0 (0.9 s)
check-data: USGS: all 4,770,607 codes = the Python rules · the 565 rows off the map are the quakes nearer the poles than 85.05° (565 north, 0 south)
check-data: USGS info: points=4770607 = 0/0/0 = its 4 zoom-1 tiles [4055058, 162461, 394517, 158571] · tiles 3/0/4, 3/7/4 (both sides of 180°) = their 4 smaller tiles = slow counts · 6 places around the Pacific = Python's rows inside their tiles' edges
--- tests/validate/step-11.sh
  ok  import of the 58 USGS files → rows=4771181 imported=4770607 skipped_zero=9 skipped_out_of_range=565 skipped_malformed=0 (= awk = DESIGN §13)
  ok  the 4 quarters of the world (zoom-1 tiles) all hold quakes and add up to 4770607
  ok  across the 180° line: 9,700 quakes west of it + 46,934 east of it = Python's slow counts · Japan (128,30,146,46): 39,405 = Python
  ok  page: a box drawn across the 180° line is counted as 167.695312500,…,180.000000000,… + -180.000000000,…,-167.695312500,…: 62,206 quakes = Python's slow counts
  ok  #earthquakes/2/15.0000/-170.0000: 4,770,607 quakes, the world map over the base map · build/validate/step-11.png
  ok  #geolife opens at zoom 6, centered on 35.75, 113.22
  ok  #earthquakes opens at zoom 2, centered on 34.64, -17.44
  ok  bench geolife: zoom 0, 5, 10, 15, 18 p50/p99 (ms): 0:49.09/49.73 5:43.49/44.42 10:14.24/24.73 15:2.03/9.11 18:0.71/6.75
  ok  bench earthquakes: zoom 0, 5, 10, 15, 18 p50/p99 (ms): 0:11.62/12.04 5:6.13/9.72 10:1.19/4.76 15:0.53/0.99 18:0.53/0.56
VERIFY PASSED (make verify, 16 min 49 s)
```

## Review (Codex)

Run with `CODEX_BIN=<wrapper> tools/review.sh 11` (gpt-6-astra, high reasoning effort). Files in `.review/step-11/`.

| Round | Finding (severity, file:line) | What happened |
|---|---|---|
| 1 | Medium, `fetch-usgs.py:195`: a rerun with a later `--until` keeps both overlapping 2026 files (quakes counted twice) | Fixed: `state.json` records the dates and the service; another download in the same folder is refused (exit 2). Tested. Caught (U5) |
| 1 | Medium, `check_usgs.py:100`: a valid fresh download fails, since the check wants the 2026-11-01 totals (USGS revises its catalog) | Fixed: DESIGN §13's line is wanted only for that download, known by a SHA-256 of its `MANIFEST.txt` lines (file, rows, USGS's count); any download must equal `awk` and the Python rules. The same in `step-11.sh` |
| 1 | Low, `fetch-usgs.py:171`: a kept file emptied after its fetch is trusted on a rerun | Fixed: a kept file must have the SHA-256 it was written with (stored in `state.json`); else it is fetched again. Tested with an emptied file and with one changed on the same lines. Caught (U6) |
| 2 | Findings 1 and 3 fixed · Medium: finding 2 partly fixed: the 2026-11-01 download was known by its files' names and counts, so a later download with a corrected place but the same counts would be held to DESIGN §13's totals | Fixed after round 2: it is known by its files' contents (`shasum -a 256 usgs-*.csv`, hashed again), in `check_usgs.py` and `step-11.sh` |

Left for the developer to decide: none.

## Review (Claude skeptic, separate agent)

A second Claude Opus 5.5 agent with a fresh context, in its own copy, the real data read-only, USGS never contacted (a fake on 127.0.0.1). It recounted DESIGN §13's USGS facts (all true), fuzzed the window cutting (25 trials: exact) and checked that the TLS change keeps certificate checks (a self-signed server is refused, no retry).

| Round | Finding (severity) | What happened |
|---|---|---|
| 1 | Medium 1: `step-11.sh` flaky: the page asks for the two halves of a box across 180° at once, and they came back in either order | Fixed: compared as a set |
| 1 | Medium 2: changing `--until`/`--since` added overlapping files (as Codex 1) | Fixed (U5) |
| 1 | Low 1: files written in the locale's encoding (all 58 hold non-ASCII place names): under Latin-1 a crash left a `.part` file | Fixed: written as UTF-8 bytes; a failed write removes the `.part` file |
| 1 | Low 2: an answer cut short with no length header, cut inside its last column, was kept | Fixed: a CSV answer must end with a newline, else it is retried. Tested (a fake that closes the connection 4 bytes early, twice). Caught (U4) |
| 1 | Low 3: "every `.gpt` is rebuilt at deploy" was false (`deploy` builds no data): the service's `geolife.gpt` kept the 1 % view | Fixed in this report: the `.gpt` files are rebuilt by hand after the deploy (`PROGRESS.md`) |
| 1 | Low 4: a rerun trusted `state.json` without looking at the files (as Codex 3) | Fixed (U6) |
| 1 | Test gaps: no overlap check in `check_usgs.py`; the earthquakes' opening view not asserted | Fixed: the files must cover 1900-01-01 to 2026-10-01 end to end; the earthquakes must open at zoom 2. Not done: retries on 429 and time-outs are tested only through the 503/500 path they share |
| 2 | Findings 1–6 fixed, each re-run (a Latin-1 locale, a read-only folder, a cut answer, a changed `--until`, a trailing `/` in the URL, the old `state.json` layout) · Low N1: with no `state.json`, a file of another download in the folder was left beside this one's · Low N2: the coverage check wanted 1900-01-01 to 2026-10-01, so another download (other dates) would fail · Test gap: the cut answer lost a whole column (caught by the column count, not the newline) | Fixed after round 2: files that aren't this download's periods are refused (exit 2, tested); the coverage check takes the dates from `MANIFEST.txt`; the cut falls inside the last value (22 columns). Not done: ids unique across files (the coverage check rules out overlapping periods; the real files have none, checked by hand) |

Left for the developer to decide: none.

**After both second rounds** (the 2-round limit, so no reviewer has seen these): the fixes for Codex's round-2 finding and the skeptic's N1, N2 and test gap above. Each is tested (`test_fetch_usgs.py`, `check_usgs.py` and `step-11.sh` on the real files); `make verify` ran after them.

## Proof the tests catch bugs

Each break was made in a scratch copy (deleted afterwards), then the named test was run (`breaks-11.py` in the builder's scratchpad).

| # | Break | Caught by |
|---|---|---|
| V1 | `build`'s view box drops 1 % at each end again | `test_build` (2 tests) and `test_info_count`: the header differs from the Python rules |
| U1 | `fetch-usgs.py` asks for a whole period in one request (no windows) | `test_windows_join_without_losing_or_doubling_rows`: `5 rows, USGS counts 12` |
| U2 | a period ends at the next one's first moment (USGS's end time is included) | the same test: the quake at midnight on 1 January is in two files |
| U3 | a year whose rows differ from USGS's count of the year is kept (only the windows checked) | `test_rows_unequal_to_the_count_and_a_changed_header_are_refused` (a quake that comes in mid-download). Its first run passed: the test then changed only every count, which the windows catch; the year-only case was added |
| U4 | an answer cut short (no final newline) is kept | `test_a_cut_answer_is_retried_and_other_dates_need_another_folder` |
| U5 | a download with other dates is added to the folder | the same test |
| U6 | a kept file is trusted without its SHA-256 | the same test |

The code was restored exactly afterwards: yes (every break was made in a deleted scratch copy).

## Validate it yourself

| Do this | Expected | Actual (agent's run) |
|---|---|---|
| `tests/validate/step-11.sh` | the `ok` lines in Tests | as in Tests (76 s) |
| `open build/validate/step-11.png` | the Ring of Fire, mid-ocean ridges, Hawaii, Alaska and California brightest | yes (looked at by the agent) |
| `cat data/raw/usgs/MANIFEST.txt` | 58 files, each `rows usgs_count` equal, `total 4771181 4771181` | as expected |
| http://127.0.0.1:8090/#earthquakes, then **Draw a box** across the 180° line near Fiji | the box's count, and "across the 180° line" | after the deploy |

## Deploy (after approval)

After this commit: `GPSTILES_PORT=8090 make deploy`, every `.gpt` in `data/build/` rebuilt with the new program (the 5 % view), `earthquakes.gpt` added to `datasets.conf`. The results go in `PROGRESS.md`, which goes in with the next commit.

## Who did what

| Agent | Did |
|---|---|
| Claude Opus 5.5 (main) | the download tool, the checks, the view rule, tests, breaks, validation, this report |
| Codex CLI gpt-6-astra (high effort) | review (read-only) |
| Claude Opus 5.5 skeptic (separate agent, own copy) | adversarial review |

## Decisions
- **The opening view rule B** (the developer, 2026-11-01): 5 % at each end. GeoLife opens on eastern China at zoom 6, the others where they did.
- **USGS's catalog as of 2026-11-01, up to 2026-10-01:** USGS revises its catalog, so a later download may differ slightly; DESIGN §13 holds this download's numbers and `MANIFEST.txt` the counts USGS gave.
- **All earthquakes, every magnitude** (`eventtype=earthquake`), as the plan says ("every recorded earthquake"); not explosions or quarry blasts.

## Not verified
- Retries after a 429 or a time-out: they share the 503/500 path that is tested, but aren't tested on their own.
- The page's hover on the earthquakes near the poles and at 180° (the count API and a drawn box are checked).
- 1900–2017 were fetched by the first version of the tool (pages by time, every page checked in order and every period = USGS's count); 2018–2026 by the final one. Their SHA-256s were added to `state.json` after the fetch, from the files as they were (each file's rows = its recorded rows).
- Cold-cache timings (the numbers above are with the files in the disk cache).

## Next
- Stage 3 (Porto taxis: about 80 million points in a `POLYLINE` column of JSON lists), as the developer set on 2026-11-01.
