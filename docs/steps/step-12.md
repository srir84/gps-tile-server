# Step 12: Porto taxis, polylines + stage 3 report

## Summary

| | |
|---|---|
| **Built** | `gpstiles import --polyline C`: a row is a trip, its places one CSV column holding `[[lon,lat],...]` (quoted or not), each pair a point, rows up to 1,000,000 bytes · the Porto taxis (1,710,670 trips, 83,409,386 points) imported and checked against Python's own `csv` and `json` · a many-runs build of 83 million points · the stage 3 report |
| **Status** | approved (all-stages go-ahead 2026-11-01) |
| **Date** | 2026-11-01 |
| **Agent(s)** | Claude Opus 5.5 main · Codex reviewer (gpt-6-astra, high effort) · Claude Opus 5.5 skeptic reviewer (separate agent) |

## Stage 3 in numbers (this Mac, warm file cache)

| What | Result |
|---|---|
| Download | UCI's `taxi+service+trajectory+prediction+challenge+ecml+pkdd+2015.zip`, 534,065,916 bytes, SHA-256 `a33e2a5e…f8c76` (no account; the plan named Kaggle, which needs one) → `train.csv`, 1,942,848,724 bytes |
| `import --polyline 9 --skip 1` | `rows=1710670 points=83409386 imported=83409386 skipped_zero=0 skipped_out_of_range=0 skipped_malformed=0` in 12 s, peak memory 3 MB · Python's `csv` + `json`: the same, in 44 s |
| `build` (default `--mem`, 1 GiB) | 1 run, 7.8 s, peak memory 670 MB |
| `build --mem 256M` | 3 runs merged, 8.1 s, peak memory 258 MB, byte-identical to the 1-run file, no run file left |
| `porto.gpt` | 667,275,344 bytes |
| Opens at (5 % view) | Porto, zoom 13 (its GPS glitches reach 37° W and 53° E) |

Drawing one tile (`gpstiles bench build/validate/porto.gpt`: drawing only, 100 renders a zoom), p50 / p99 in milliseconds:

| Zoom | 0–10 (all of Porto in 1–3 tiles) | 11 | 13 (the city) | 15 | 17 | 18 (streets) | 24 |
|---|---|---|---|---|---|---|---|
| p50 / p99 | 162–164 / 164–203 | 87 / 88 | 60 / 65 | 8.4 / 23 | 3.5 / 8.8 | 1.7 / 3.4 | 0.53 / 0.56 |

**What stage 3 shows:** the polyline reader works and 83 million points build in 8 s in a quarter of a gigabyte, with several runs. But a zoomed-out tile of Porto takes 164 ms: drawing costs about 2 ns per point in the tile, and at zoom 0–10 nearly all 83 million are in one tile. A city view at zoom 13 is 60 ms a tile. That is fine for one person's map, not for "milliseconds". At a billion points (stage 4) the same tile would take about 2 s, so stage 4 has to stop drawing zoomed-out tiles point by point.

## Every stage 3 check (DESIGN §12.5)

| Check | Result |
|---|---|
| The polyline reader works | 1,710,670 trips → 83,409,386 points = Python's `csv` + `json` (and DESIGN §13); every point of every 50th trip = two Python readers; 2,000 random rows = the Python rules |
| ~80 million points build | 8 s; with `--mem 256M` in 3 runs, the same file, 258 MB |
| ~80 million points serve | yes; zoomed-out tiles 164 ms (above) |
| Points land in the right place | 3 places in Porto (Avenida dos Aliados, the airport, Campanhã station) = Python's points inside the tiles' edges in degrees; the trips lie on Porto's streets (`step-12-street.png`) |
| The file's count = the points imported | 83,409,386 |
| Tile counts add up | Porto's zoom-10 tile = its 4 zoom-11 tiles = slow count |
| Area count, export and API | a box at Avenida dos Aliados: 3,366,938 = Python's slow count; its export the first 1,000,000 rows (the limit) |

## Design
- **One option, `--polyline C`**, instead of `--lon-col`/`--lat-col` (both together are refused). The column is found with CSV quotes (`"..."`, `""` inside), because the list's own commas would split it; plain rows still split at every delimiter, as before.
- **A row is all or nothing:** the whole list is read (into a buffer for up to 200,001 pairs) before any pair is counted, so a broken list contributes no point. Each pair then follows the plain rows' rules (DESIGN §8: (0,0), off the map, kept).
- **Counts:** `rows=` trips and `points=` pairs; `skipped_zero` and `skipped_out_of_range` count pairs, `skipped_malformed` rows. Plain rows print what they did before.
- **Longer rows for trips:** 1,000,000 bytes (Porto's longest is 84,640; a plain row stays at 65,536). The reader's buffer is 1 MiB, so memory stays bounded.
- **Found while building:** moving the CRLF handling into the reading loop stripped a trailing `\r` twice for plain rows, so a line ending `\r\r` was counted as a row but nothing else; the random-rows test caught it (137 of 59,600 rows) before any commit. Plain rows are again stripped once, by `import_row`.

## Files changed

| File | Change | Why |
|---|---|---|
| `src/import.c`, `src/import.h` | changed | the CSV column with quotes, the pair list, polyline rows, the line limit per mode, the place rules shared by both modes |
| `src/main.c` | changed | `--polyline`, its checks, `points=` in the counts |
| `tests/unit/test_import.c` | changed | 4 tests |
| `tests/e2e/test_import.py`, `tests/oracle/import_rules.py` | changed | 4 tests; the Python rules for polyline rows (their own CSV and list reader) |
| `tests/fixtures/porto_small.csv` | added | Porto's layout with made-up trips |
| `tests/data/check_porto.py`, `Makefile` | added, changed | Porto's real-data checks in `make check-data` |
| `tests/validate/step-12.sh`, `tests/validate/lib.sh` | added, changed | DESIGN §12.5's check |
| `tests/e2e/test_review_script.py` | changed | step 12 has rows now: the refused numbers are the `.gpt` header's |
| `docs/DESIGN.md`, `docs/TESTING.md`, `README.md`, `AGENTS.md` | changed | §8's polyline rules, §9.1, §12.5, §13 · tests · the dataset · where it is |

## Tests

| Test | Checks | Bug it would catch |
|---|---|---|
| `quoted_csv_columns_keep_their_commas` (unit) | quoted and plain fields, `""` inside, empty fields; refused: too few columns, an unclosed quote, text after a closing quote | a polyline split at its commas, a `""` taken as the end, a broken quote read as text |
| `pair_lists_parse_whole_or_not_at_all` (unit) | good lists with spaces, `[]`, `1e999`; 20 broken ones; too many pairs | half a broken list imported, a trailing comma or a missing number accepted, pairs written past the buffer |
| `polyline_rows_count_each_pair_as_a_point` (unit) | a header, a trip, an empty trip, (0,0) and off-the-map pairs, a broken list, a blank line, a short line, CRLF: every count and code | a pair miscounted, a broken list's first pair kept |
| `polyline_rows_may_be_long_up_to_their_limit` (unit) | rows of exactly 1,000,000 and 1,000,001 bytes, then a short one | long trips refused at 64 KB, a too-long row kept, the next row lost |
| `test_porto_small_polylines_give_their_known_counts_and_codes` | the fixture twice: known counts, codes = the Python rules | Porto's layout read wrong |
| `test_random_polylines_match_the_python_rules` | 2,000 random rows (quotes, spaces, broken lists, the map's edges), column 1 and 2 | any disagreement with DESIGN §8's polyline rules |
| `test_polylines_with_other_delimiters_quoted_or_not` | `;`, tab and `|`, quoted and unquoted lists, an empty one, (0,0), a trailing comma: = the Python rules | a polyline that works only with commas |
| `test_polyline_arguments_are_checked` | with `--lon-col`/`--lat-col`, `--delim '"'` or `[`, column 0 or `x`: exit 2, no file | a mixed-up option taken |
| `check_porto.py` (`make check-data`) | counts = DESIGN §13 = `csv` + `json` · every 50th trip's codes = two Python readers · two builds identical, no run file · Porto's tile = its 4 children = slow count · 3 places = Python | anything that turns Porto's trips into wrong counts, codes or places |
| `step-12.sh` | DESIGN §12.5's command and line, the many-runs build measured, a box's count and export, the page at zoom 13 and 17, the opening view | as above, through the server and the page |

```text
unit        37 passed   0 failed
e2e        130 passed   0 failed
ALL PASSED (build)                                    make check (131 with the other-delimiters test, run by the pre-commit hook)
unit        37 passed   0 failed
e2e        130 passed   0 failed
ALL PASSED (build/san)                                make sanitize
check-data: T-Drive, GeoLife, USGS as before
check-data: Porto import counts = DESIGN §13 = csv + json: rows=1710670 points=83409386 imported=83409386 skipped_zero=0 skipped_out_of_range=0 skipped_malformed=0 (12.7 s)
check-data: Porto sample (every 50th trip): rows=34213 points=1659002 imported=1659002 … = the Python rules = csv + json, every code
check-data: Avenida dos Aliados: tile 14/7800/6133 holds 304,175 sample points = Python's points inside its edges (and the airport, Campanhã)
check-data: Porto build --mem default: points=83409386 runs=1 (8.3 s)
check-data: Porto build --mem 256M: points=83409386 runs=3 (8.6 s)
check-data: Porto: the two builds are identical, no run file left · info points=83409386 = 0/0/0 · count 10/487/383 (Porto) = 81,877,195 = slow count = its 4 zoom-11 tiles
--- tests/validate/step-12.sh
  ok  import --polyline 9 of Porto's 1,710,670 trips → rows=1710670 points=83409386 imported=83409386 skipped_zero=0 skipped_out_of_range=0 skipped_malformed=0 (DESIGN §13)
  ok  build --mem 256M: points=83409386 runs=3 in 8.29 s, peak memory 258 MiB, the same file again, no run file left
  ok  bbox=-8.6150,41.1470,-8.6080,41.1520 (Avenida dos Aliados): count 3,366,938 = Python's slow count · export 1,000,000 rows
  ok  #porto/13/41.1550/-8.6250: shows 83,409,386 points, 78,955,747 in view, over the base map · build/validate/step-12.png
  ok  #porto/17/41.1496/-8.6110: shows 83,409,386 points, 6,974,479 in view, over the base map · build/validate/step-12-street.png
  ok  #porto opens on Porto: zoom 13, 41.170, -8.622 (its GPS glitches out to 37° W are left out)
VERIFY PASSED (make verify, 19 min 56 s)
```

## Review (Codex)

Run with `CODEX_BIN=<wrapper> tools/review.sh 12` (gpt-6-astra, high reasoning effort). Files in `.review/step-12/`.

| Round | Finding (severity, file:line) | What happened |
|---|---|---|
| 1 | **High**, `import.c:275`: `take(import_point(…, &code), code, …)`: C doesn't fix the order arguments are worked out in, so a compiler may pass `code` before `import_point` sets it, and every pair would be written as code 0 | Fixed: two statements, the result first (as the plain rows already did). This compiler happened to give the right order: the tests passed before, and no test can force the other order |
| 1 | Medium, `import.c:87`: the column finder stopped at the polyline column, so a broken quote later in the row was let through (DESIGN §8 says such a row is malformed); the Python rules did the same | Fixed in both: every field's quoting is checked. Unit cases and the random test's rows have broken quotes after the list. Caught (P6) |
| 2 | Findings 1 and 2 fixed · Low: no test imported a polyline with a delimiter other than `,` (quoted or not), so a reader that ignored `--delim` would pass | Fixed after round 2: `test_polylines_with_other_delimiters_quoted_or_not` (`;`, tab, `|`; quoted and unquoted lists; = the Python rules). Caught (P9) |

Left for the developer to decide: none.

## Review (Claude skeptic, separate agent)

A second Claude Opus 5.5 agent with a fresh context, in its own copy, the real data read-only. It ran `make sanitize` (clean), fuzzed 3,000 random files (about 450,000 rows: quotes, `""`, unclosed quotes, other delimiters and columns, spaces, broken lists, numbers of 62–65 characters, NUL, `\r`, `\r\r`) through the sanitizer build against the Python rules (0 differences), checked rows of 999,998 to 1,000,002 bytes and at the reader's buffer edges, and compared plain rows of 400 random files with the program before this step (byte-identical). `check_porto.py` and `step-12.sh` passed on the real data; DESIGN §13's Porto facts are true.

| Round | Finding (severity) | What happened |
|---|---|---|
| 1 | Medium G1: nothing tested numbers of 63 and 64 characters, so an off-by-one copying into the 64-byte buffer passed every test (UBSan saw it only with a 64-character number) | Fixed: 63 characters read and 64 refused, in both places of a pair, in the unit test and in the random test's numbers. Caught (P7) |
| 1 | Low F1: the README said 442 taxis; the data has 448 | Fixed |
| 1 | Low F2: the Python rules' number pattern took time growing with the square of a number's length (31.7 s for 40,000 digits) | Fixed: a pattern without overlapping parts (a million digits: 0.06 s) |
| 1 | Low F3: DESIGN §8's long-row rule didn't say a trailing `\r` counts | Fixed |
| 1 | Low F4: `check_porto.py` printed `runs=3` but never checked it | Fixed: the 256M build must make several runs, the default one |
| 1 | Low G2: no polyline test had `\r\r` | Fixed: in the random test. Caught (P8) |
| 1 | Low G3: nothing tied the row limits to the read buffer at compile time | Fixed: a `_Static_assert` |
| 2 | All 7 fixed, each re-run (mutants: the off-by-one stopped by UBSan, a 62-character limit and a `while` strip both fail); a new fuzz of 3,000 files with broken quotes after the column: 0 differences; `csv_field` = Python's `csv.reader(strict=True)` on 32,131 lines; `check_porto.py` again on the real data (78 s) · no new findings | — |

Left for the developer to decide: none.

**After both second rounds** (the 2-round limit, so no reviewer has seen it): the other-delimiters test for Codex's round-2 finding, tested by break P9. `make check` and `make sanitize` ran after it (the pre-commit hook); the last `make verify` ran just before it (the change adds a test only).

## Proof the tests catch bugs

Each break was made in a scratch copy (deleted afterwards), built, then the unit tests and the named tests were run (`breaks-12.py` in the builder's scratchpad).

| # | Break | Caught by |
|---|---|---|
| P1 | quotes ignored: the quoted list split at its own commas | unit `quoted_csv_columns_keep_their_commas`, `polyline_rows_count_each_pair_as_a_point`, `polyline_rows_may_be_long_up_to_their_limit` |
| P2 | a list with a trailing comma taken | unit `pair_lists_parse_whole_or_not_at_all` · `test_porto_small_polylines…`: `points=36 imported=32 … skipped_malformed=0` |
| P3 | a broken list's first good pair kept | unit `polyline_rows_count_each_pair_as_a_point` · `test_porto_small_polylines…`: `imported=30` |
| P4 | polyline rows held to the plain rows' 64 KB | unit `polyline_rows_may_be_long_up_to_their_limit` |
| P5 | a trailing `\r` stripped twice for plain rows (the regression found while building) | `test_random_rows_match_the_python_rules`: `rows=59463 …` against 59,600 |
| P6 | the column finder stops at the polyline column (Codex's finding) | unit `quoted_csv_columns_keep_their_commas` · `test_random_polylines_match_the_python_rules` |
| P7 | a 64-character number copied into the 64-byte buffer (the skeptic's G1) | unit `pair_lists_parse_whole_or_not_at_all` · the random test |
| P8 | a polyline row strips every trailing `\r` (the skeptic's G2) | `test_random_polylines_match_the_python_rules` |
| P9 | polyline rows split at `,` whatever `--delim` says (Codex round 2) | `test_polylines_with_other_delimiters_quoted_or_not`: `points=0 … skipped_malformed=5` |

Not caught, by design: the argument order Codex found (this compiler gives the right order; no test can force the other).

The code was restored exactly afterwards: yes (every break was made in a deleted scratch copy).

## Validate it yourself

| Do this | Expected | Actual (agent's run) |
|---|---|---|
| `build/gpstiles import --polyline 9 --skip 1 -o "$TMPDIR/porto.pts" data/raw/porto/train.csv` | `rows=1710670 points=83409386 imported=83409386 skipped_zero=0 skipped_out_of_range=0 skipped_malformed=0` | the same, 12 s |
| `tests/validate/step-12.sh` | the `ok` lines in Tests | as in Tests |
| `gpstiles bench build/validate/porto.gpt` (about 3 minutes) | the table above | as above |
| `open build/validate/step-12-street.png` | trips on the streets around Avenida dos Aliados | yes (looked at by the agent) |

## Deploy (after approval)

After this commit: `GPSTILES_PORT=8090 make deploy`, `porto.gpt` built in `data/build/` and added to `datasets.conf`. The results go in `PROGRESS.md`, which goes in with the next commit.

## Who did what

| Agent | Did |
|---|---|
| Claude Opus 5.5 (main) | the polyline reader, the checks, tests, breaks, validation, this report |
| Codex CLI gpt-6-astra (high effort) | review (read-only) |
| Claude Opus 5.5 skeptic (separate agent, own copy) | adversarial review |

## Decisions
- **The data from UCI, not Kaggle:** the plan named Kaggle, which needs an account; UCI hosts the same competition files with none.
- **`--polyline` reads `[lon,lat]` pairs** (Porto's order, and GeoJSON's). A list in the other order would need a new option; none of the planned datasets has one.
- **Polyline rows only get CSV quotes.** Plain rows keep splitting at every delimiter (no dataset of ours quotes its numbers), so their behaviour and speed don't change.
- **Not done here: faster zoomed-out tiles.** They are 164 ms at 83 million points (Stage 3 in numbers); the fix belongs to stage 4, where it is needed for a billion points.

## Not verified
- Another C compiler's argument order (Codex's high finding): fixed by writing two statements, not testable here.
- `--polyline` with a delimiter other than `,` on real data (tested on random rows only).
- The page's box tool and hover on Porto in Chrome (the count API and export are checked; the page tool on T-Drive in steps 7–8).
- Cold-cache timings.

## Next
- Stage 4 (the NYC taxis, over a billion points, bigger than memory) as the developer set on 2026-11-01. First: DESIGN §14's "store time per point?" decision, and fast zoomed-out tiles.
