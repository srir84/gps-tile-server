# Step 10: GeoLife, a second file layout

## Summary

| | |
|---|---|
| **Built** | GeoLife (Microsoft: 182 people, 18,670 `.plt` files, 24,876,977 points) imported with import options only, no change to `gpstiles` · its real-data checks in `make check-data` · `row_counts.awk` for any columns · a `.plt` fixture · `tools/review.sh` takes two-digit steps · stage 2's plan (DESIGN §12.4) |
| **Status** | approved (stage 2 go-ahead 2026-11-01) |
| **Date** | 2026-11-01 |
| **Agent(s)** | Claude Opus 5.5 main · Codex reviewer (gpt-6-astra, high effort) · Claude Opus 5.5 skeptic reviewer (separate agent) |

## GeoLife in numbers (this Mac)

| What | Result |
|---|---|
| Download | `Geolife Trajectories 1.3.zip` from download.microsoft.com: 313,164,406 bytes (the size the server sent), SHA-256 `1107c5ac…86bdb6` (DESIGN §13) · unzipped 1.6 GB in 11 s |
| Files | 18,670 `.plt` in 182 user folders (= the user guide's Figure 7) |
| `import --lat-col 1 --lon-col 2 --skip 6` | `rows=24876978 imported=24876977 skipped_zero=0 skipped_out_of_range=1 skipped_malformed=0` in 6.7 s, peak memory 4.8 MB · `awk` gives the same line in 64 s · the user guide: 24,876,978 points |
| The one row off the map | `020/Trajectory/20110911000506.plt` line 6782: latitude 400.166666666667 (a GPS glitch) |
| `build` | 1 run, 2.2 s, peak memory 202 MB · `geolife.gpt` 199,016,072 bytes |
| Where the points are | 20,876,966 (84 %) in Beijing's zoom-6 tile `6/52/24` · 9,799,511 in one zoom-11 tile at Zhongguancun (Microsoft Research Asia) · 321,610 (1.3 %) in North America · traces near Redmond, San Diego and Nice too |
| `info` | `bounds=-179.969593,1.044024,179.996942,64.751993` · `view=-115.169678,22.593726,121.635132,46.604167` (see Decisions) |

## Design
- **Stage 2's rule held for GeoLife: no code change.** `gpstiles import --lat-col 1 --lon-col 2 --skip 6` reads its layout (6 header lines, CRLF, latitude first, altitude -777 for "none"). The C program is the same as step 9's.
- **The answers come from three places that don't share code with `gpstiles`:** `awk` (all 24.9 million rows), the Python rules (every code of every 10th file), and GeoLife's own user guide (24,876,978 points). Where the points land is checked in degrees: for 4 places GeoLife's people went to, the rows Python finds inside a zoom-11 tile's edges (OpenStreetMap's formula) are exactly the points `gpstiles count` finds in that tile.
- **`tdrive_counts.awk` became `row_counts.awk`**, with the columns and header lines as settings (`-v LON=… -v LAT=… -v SKIP=…`), so one copy of DESIGN §8's rules in `awk` serves every dataset. It still gives T-Drive's DESIGN §13 line exactly, and it is now itself tested against the Python rules on every fixture.
- **Many files:** 18,670 full paths are longer than macOS allows on one command line (1 MB); the checks run from inside GeoLife's `Data` folder, where the names take 634,780 bytes. A bigger set can be imported in batches into several `.pts` files, which `build` takes together.
- **Stage 2's plan** is in DESIGN §12.4 (steps 10 and 11), TESTING §9 has their rows, and `tools/review.sh` accepts steps 10–99 (step 1 still gets only its own rows).

## Files changed

| File | Change | Why |
|---|---|---|
| `tests/data/check_geolife.py` | added | GeoLife's real-data checks, run by `make check-data` |
| `tests/data/row_counts.awk` | renamed from `tdrive_counts.awk`, changed | any columns and header lines (`LON`, `LAT`, `SKIP`) |
| `tests/data/check_tdrive.py`, `tests/validate/step-5a.sh`, `step-6.sh` | changed | call `row_counts.awk` with T-Drive's columns |
| `tests/fixtures/geolife_small.plt` | added | GeoLife's layout with made-up places near Beijing |
| `tests/e2e/test_import.py` | changed | 2 tests: the `.plt` layout; `row_counts.awk` = the Python rules |
| `tools/review.sh`, `tests/e2e/test_review_script.py` | changed | steps 10–99; rows only from DESIGN §12 and TESTING §9; 2 tests |
| `tests/validate/step-10.sh`, `tests/validate/lib.sh` | added, changed | DESIGN §12.4's check; `geolife_gpt` builds GeoLife into `build/validate/`, kept while the options and files are the same |
| `Makefile` | changed | `check-data` runs one script per dataset · `verify` runs the steps' scripts in step order |
| `docs/DESIGN.md` | changed | §12.4 stage 2's steps · §13 GeoLife's facts · the status line ("Design only" was stale) |
| `docs/TESTING.md`, `AGENTS.md` | changed | files, answer sources, fixture, step rows; where GeoLife is |

## Tests

| Test | Checks | Bug it would catch |
|---|---|---|
| `test_geolife_plt_layout_gives_its_known_counts_and_codes` | the fixture twice with `--skip 6`: 24 rows, 22 kept, 2 off the map, codes = Python · `--skip 5`: the header's `0` line is a malformed row · columns swapped: nothing kept | header lines counted as rows (or skipped in the first file only), latitude and longitude mixed up, the latitude-400 glitch kept |
| `test_row_counts_awk_gives_the_python_rules_counts` | `row_counts.awk` against the Python rules on every fixture (2 copies each), the GeoLife fixture with 3 settings, the map's edges with and without a header line, numbers that overflow or underflow, lines of exactly 65,536 and 65,537 bytes | the `awk` answer drifting from DESIGN §8: a row rule, an edge, an overflowed number compared as text, the columns, the header lines |
| `test_two_digit_steps_get_their_own_rows` | `review.sh 10` runs with its own DESIGN and TESTING rows only, `review.sh 1` doesn't get step 10's rows, `100`, `05`, `1x0` and `12` (rows only outside the step tables) are refused | stage 2's steps refused, or rows matched by prefix |
| `test_the_real_docs_give_each_step_only_its_step_table_rows` | on the real DESIGN and TESTING: steps 12, 16, 21, 24 refused, steps 8 and 10 get exactly their 2 rows | a review told to build a `.gpt` header row (`\| 12 \| header_size \|`) |
| `check_geolife.py` (`make check-data`) | all files: counts = DESIGN §13 = `awk` · every 10th file: counts and every code = Python · `info` and `0/0/0` = every point · Beijing's zoom-6 tile = its 4 zoom-7 tiles = a slow count · 4 places: tile count = Python's rows inside the tile's edges | anything that turns GeoLife's rows into wrong counts, codes or places |
| `step-10.sh` | DESIGN §12.4's command and expected line · `info` · the tile at Zhongguancun = Python's count of its slice · a box's count = slow count, its export = as many rows, each inside the box · the page shows 24,876,977 points over a base map that loaded | as above, through the server and the page |

```text
unit        33 passed   0 failed
e2e        123 passed   0 failed
ALL PASSED (build)                                    make check
unit        33 passed   0 failed
e2e        123 passed   0 failed
ALL PASSED (build/san)                                make sanitize
check-data: import counts = DESIGN §13 = awk: rows=10088351 imported=10064891 … (T-Drive, as before)
check-data: GeoLife import counts = DESIGN §13 = awk: rows=24876978 imported=24876977 skipped_zero=0 skipped_out_of_range=1 skipped_malformed=0 (6.0 s)
check-data: GeoLife sample (every 10th file, 1,867 files): rows=2579683 imported=2579683 … = the Python rules, every code too
check-data: Zhongguancun, Beijing (Microsoft Research Asia): tile 11/1685/775 holds 984,970 sample points = Python's rows inside its edges
check-data: Bellevue, near Microsoft in Redmond: tile 11/329/715 holds 1,682 sample points = Python's rows inside its edges
check-data: San Diego: tile 11/357/826 holds 1,668 sample points = Python's rows inside its edges
check-data: Nice, France: tile 11/1065/747 holds 3,190 sample points = Python's rows inside its edges
check-data: GeoLife info: points=24876977 = 0/0/0 · count 6/52/24 (Beijing) = 20,876,966 = slow count = sum of its 4 zoom-7 tiles
--- tests/validate/step-10.sh
  ok  import of the 18,670 .plt files → rows=24876978 imported=24876977 skipped_zero=0 skipped_out_of_range=1 skipped_malformed=0 (DESIGN §13)
  ok  info: points=24876977 · count 6/52/24 (Beijing) = 20876966 = its 4 zoom-7 tiles added up
  ok  tile 11/1685/775 (Microsoft Research Asia) holds 9,799,511 points = Python's count of its slice of the .pts
  ok  bbox=116.3060,39.9790,116.3100,39.9820: count 52,544 = Python's slow count · export.csv: 52,544 rows, each inside the box
  ok  #geolife/11/39.9100/116.3800: shows 24,876,977 points (DESIGN §13), 19,025,110 in view, over 24 base map tiles
  ok  #geolife/16/39.9800/116.3100: shows 24,876,977 points (DESIGN §13), 1,299,422 in view, over 28 base map tiles
VERIFY PASSED (make verify, 13 min 55 s; every step's script, 0a to 10, in step order)
```

## Review (Codex)

Run with `CODEX_BIN=<wrapper> tools/review.sh 10` (gpt-6-astra, high reasoning effort). Files in `.review/step-10/`.

| Round | Finding (severity, file:line) | What happened |
|---|---|---|
| 1 | Medium, `step-10.sh:98`: a failed base-map image is also "complete", and `browser.py` ignores OpenStreetMap's errors, so with no internet the check passed and saved screenshots without streets | Fixed: the base tile under each view's center must have decoded (256 px wide), else FAIL. Shown with Chrome's internet blocked: `FAIL step-10 … the base map didn't load (no internet?): https://tile.openstreetmap.org/11/1686/775.png, 0 base tiles shown` (B6) |
| 2 | Round-1 finding fixed · no new findings | — |

Left for the developer to decide: none.

## Review (Claude skeptic, separate agent)

A second Claude Opus 5.5 agent with a fresh context, in its own copy, the real data read-only. It recounted DESIGN §13's GeoLife facts with its own Python (all true), ran `check_geolife.py`, `step-10.sh` and a sanitized import of all of GeoLife (clean, byte-identical `.pts`).

| Round | Finding (severity) | What happened |
|---|---|---|
| 1 | Medium F1: `row_counts.awk` compared fields as text after an overflow (`1e999`, `1e-400`: macOS's awk then turns the number back into a string), and macOS's awk ends a line at a NUL byte; 428 of 200,000 random rows disagreed with the Python rules | Fixed: it compares the numbers (`lon = $LON + 0`); the NUL limit is stated in the file and in DESIGN §12.4 (none of our data has one). Caught (B7) |
| 1 | Medium F2: `review.sh` took rows from every DESIGN table: step 12 would have been reviewed against `\| 12 \| header_size \|`, step 8 already got `\| 8 \| version \|` | Fixed: rows only from DESIGN §12 and TESTING §9; a new test runs on the real docs (12, 16, 21, 24 refused; 8 and 10 get their 2 rows). Caught (B8) |
| 1 | Low F3: no base map passed (as Codex's finding) | Fixed (B6) |
| 1 | Low F4: the awk test missed `bytes >= 65536`, `$LAT >= MAX_LAT`, `$LON >= 180` | Fixed: the edges read with no header skip, an LF-only file with lines of exactly 65,536 and 65,537 bytes, overflow and underflow in both columns. Caught (B9); the skeptic's 8 awk mutants all fail now |
| 1 | Low F5: the GeoLife cache in `lib.sh` was reused for other files or other options | Fixed: kept only under a SHA-256 of the options and `ls -lnT` of every file |
| 1 | Low F6: `make verify` ran `step-10.sh` between steps 1 and 2 | Fixed: step order (`sort -t- -k2n`) |
| 1 | Low F7: `GPSTILES_BIN=$(CURDIR)/…` unquoted (a path with a space failed) | Fixed: quoted |
| 1 | Low F8: DESIGN said zoom 12 and wrote the `.pts` into the data folder; AGENTS.md still said T-Drive only and §12.2 | Fixed |
| 2 | F1–F8 fixed, each re-run (a 3-file data folder now re-imports: `rows=1897`; a path with a space exits 0) · no new findings | — |

Left for the developer to decide: none.

## Proof the tests catch bugs

Each break was made in a scratch copy (deleted afterwards), then the named test was run (`breaks-10.py` in the builder's scratchpad).

| # | Break | Caught by |
|---|---|---|
| B1 | `review.sh` refuses two-digit steps | `test_two_digit_steps_get_their_own_rows`: `usage: tools/review.sh N …` |
| B2 | `review.sh` matches a step's rows by prefix | the same test: `step 10's rows leaked into step 1's review` |
| B3 | `row_counts.awk` skips the header lines in the first file only (`NR` for `FNR`) | `test_row_counts_awk_gives_the_python_rules_counts` (`geolife_small.plt`, SKIP=6) |
| B4 | `import` skips the header lines in the first file only (`static` line counter) | `test_geolife_plt_layout_gives_its_known_counts_and_codes`: `rows=30 … skipped_malformed=5` · and `check_geolife.py` on the real data: `counts differ from DESIGN §13: rows=24988992 imported=24895646 … skipped_malformed=93345` |
| B5 | `row_counts.awk` checks the map's edges on the wrong columns | `test_row_counts_awk_gives_the_python_rules_counts` (`tdrive_small.txt`) |
| B6 | `step-10.sh` with Chrome's internet blocked | `FAIL step-10: … the base map didn't load (no internet?) … 0 base tiles shown` |
| B7 | `row_counts.awk` compares the fields as they are (the round-1 code) | `test_row_counts_awk_gives_the_python_rules_counts` (`edges.txt`) |
| B8 | `review.sh` takes rows from every table of the docs (the round-1 code) | `test_the_real_docs_give_each_step_only_its_step_table_rows`: step 8 got `\| 8 \| version \| uint32 …` |
| B9 | `row_counts.awk` calls a line of exactly 65,536 bytes malformed | `test_row_counts_awk_gives_the_python_rules_counts` (`long.txt`) |

The code was restored exactly afterwards: yes (every break was made in a deleted scratch copy).

## Validate it yourself

| Do this | Expected | Actual (agent's run) |
|---|---|---|
| `cd 'data/raw/geolife/Geolife Trajectories 1.3/Data'` then `../../../../../build/gpstiles import --lat-col 1 --lon-col 2 --skip 6 -o /tmp/geolife.pts */Trajectory/*.plt` | `rows=24876978 imported=24876977 skipped_zero=0 skipped_out_of_range=1 skipped_malformed=0` | the same, 6.7 s |
| `LC_ALL=C awk -v LON=2 -v LAT=1 -v SKIP=6 -f ../../../../../tests/data/row_counts.awk */Trajectory/*.plt` (same folder) | the same line | the same, 64 s |
| `tests/validate/step-10.sh` | the `ok` lines in Tests | as in Tests |
| `open build/validate/step-10.png` beside page 1 of `User Guide-1.3.pdf` (Figure 1) | the same picture: Beijing's ring roads, brightest in the north-west | yes (looked at by the agent) |

## Deploy (after approval)

After this commit: `GPSTILES_PORT=8090 make deploy` (the program is the same as step 9's), and `geolife.gpt` added to `~/.local/gpstiles/datasets.conf`. The results go in `PROGRESS.md`, which goes in with the next commit.

## Who did what

| Agent | Did |
|---|---|
| Claude Opus 5.5 (main) | stage 2's plan, the download, the checks, the tests, breaks, validation, this report |
| Codex CLI gpt-6-astra (high effort) | review (read-only) |
| Claude Opus 5.5 skeptic (separate agent, own copy) | adversarial review |

## Decisions
- **Stage 2's steps were planned here** (DESIGN §12.4): §12.3 had one line for the whole stage. The developer started stage 2 on 2026-11-01 ("continue with stage implementation make sure everything works all tests pass").
- **The opening view for spread-out data: the developer chose B (2026-11-01), applied in step 11.** GeoLife opens on most of the northern world (`view=-115.17,22.59,121.64,46.60`, zoom 3 on a 1400 × 860 window): 1.3 % of its points are in North America, more than the 1 % DESIGN §9.3 drops at each end, although 84 % are in one zoom-6 tile around Beijing. Measured on the real files, the options were: A keep it; **B drop 5 % at each end** (GeoLife opens on eastern China at zoom 6; T-Drive and NYC Uber at zoom 10 and 12 as now); C the narrowest band with 90 % of the points (about the same as B); D zoom into the busiest quarter while it holds over half (Beijing itself, but untried on worldwide data). It changes what `build` writes (DESIGN §9.3), so it was asked, not applied here. Until step 11 the link `#geolife/11/39.9100/116.3800` opens on Beijing.
- **Codes are checked file by file on every 10th file** (2,579,683 rows), not on all 24.9 million: the Python rules take about 3 µs a row (more than a minute for all); the counts of every row come from `awk`, and every file has the same layout. T-Drive's check still checks every code.
- **GeoLife's `labels.txt` files** (transport modes, 73 users) are not GPS points and are not imported.

## Not verified
- The page's box tool and hover on GeoLife in Chrome: checked through the API here (count and export), in the page on T-Drive in steps 7–8.
- The codes of the 9 in 10 files outside the sample: their counts are checked (all rows, `awk`), their codes only through the format, which every file shares.
- The opening view rule for GeoLife (`view=` in `info`) is printed, not compared with a Python computation of DESIGN §9.3's rule; that rule changes in step 11 (B).
- Data with NUL bytes has no independent count (macOS's `awk` stops at a NUL); none of our datasets has one.

## Next
- Step 11: USGS earthquakes worldwide (`tools/fetch-usgs.py`, the 180° line, the poles) and the stage 2 report.
