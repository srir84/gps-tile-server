# Step 18: GBIF species sightings (stage 5's DS-8)

## Summary

| | |
|---|---|
| **Built** | GBIF's occurrences of 2024 with coordinates, fetched with `tools/fetch-gbif.py` (step 17) and the developer's GBIF login: one 35 GB zip of tab-separated CSV (161 GB unzipped), streamed through `unzip -p` into `gpstiles import --delim tab` and built into one `.gpt` of **287,450,825 points** · rows = GBIF's own record count · its checks |
| **Status** | approved (all-stages go-ahead 2026-11-01; GBIF scope chosen by the developer 2026-11-02: one recent year) |
| **Blocked on** | nothing |
| **Date** | 2026-11-02 |
| **Agent(s)** | Claude Opus 5.5 main · Codex reviewer (gpt-6-astra, high effort) · Claude Opus 5.5 skeptic reviewer (separate agent) |

## In numbers (this Mac: 16 cores, 128 GB of memory)

| | GBIF, 2024, with coordinates |
|---|---|
| Records | 287,451,215 (GBIF's `totalRecords`) = the file's rows |
| Points | **287,450,825**; skipped: 381 at (0,0), 4 nearer a pole than the map reaches, 5 malformed |
| Answer sources | GBIF's own record count (`download.json`) · `awk` over the whole file (`data/raw/gbif/awk-counts.txt`) |
| Download | GBIF prepared it in about 25 minutes (4,617 datasets); the zip was fetched and every CRC checked by `fetch-gbif.py` |
| Import + build | 14 min 26 s (`unzip` is the slow part: 161 GB inflated on one core) · 3 runs with the 1 GiB buffer |
| `.gpt` | 2.3 GB |
| Tiles, p99 at any zoom (`bench`, warm) | 22 ms |

**What it shows:** where people recorded wildlife in 2024, as GBIF publishes it: brightest where many observers are (the US, Europe), and lines across the oceans from surveys at sea. The same program, no new code: GBIF's simple CSV is plain tab-separated columns.

## Design
- **One download, made once:** `fetch-gbif.py` asks GBIF for every 2024 occurrence with coordinates, as "simple CSV". GBIF's download service failed (HTTP 500) for about three hours on 2026-11-02; the script was rerun every 20 minutes, each time first looking among the developer's downloads for one already made, so GBIF was asked once.
- **No CSV on disk:** `unzip -p KEY.zip | gpstiles import --delim tab --lat-col 22 --lon-col 23 --skip 1 -o … /dev/stdin`; the 161 GB CSV never touches the disk.
- **Rows = records:** GBIF's `totalRecords` counts records, and the file's rows equal it exactly, so no record was split by a newline inside a field (that could only add rows) and none was lost.
- **Checks sized for `make verify`:** `check_gbif.py` (11 s) checks that the zip is the one `download.json` describes, the header's columns, and the first 500,000 rows against `awk` and the Python rules, code by code; `step-18.sh` imports and builds the whole file, kept in `build/validate/`.

## Files changed

| File | Change | Why |
|---|---|---|
| `tests/data/check_gbif.py`, `Makefile` | added, changed | GBIF's light checks in `make check-data` |
| `tests/validate/step-18.sh`, `tests/validate/lib.sh` | added, changed | the whole file (`gbif_gpt`, kept while unchanged) |
| `tests/e2e/test_check_gbif.py` | added | `check_gbif.py`'s download rule, in `make check` |
| `tests/e2e/browser.py`, `tests/validate/step-13.sh` | changed | the helper on Python 3.9, cleaned up when Chrome can't start · step 12's commit found by message, not hash |
| `docs/DESIGN.md`, `docs/TESTING.md`, `docs/steps/README.md`, `README.md`, `AGENTS.md` | changed | §13 GBIF's facts · its check · the step index · the dataset and speed tables · where the data is |

## Tests

| Test | Checks | Bug it would catch |
|---|---|---|
| `check_gbif.py` (`make check-data`) | the zip = `download.json` (key, size, SIMPLE_CSV, exactly `HAS_COORDINATE = true AND YEAR = 2024`, SUCCEEDED) · an unreadable zip refused · columns 22 and 23 are `decimalLatitude`, `decimalLongitude` · the first 500,000 rows: import = `awk` = the Python rules, every code | the wrong download, swapped or moved columns, the wrong delimiter, a row read wrong |
| `step-18.sh` | rows = GBIF's `totalRecords` · = `awk` over the whole file (`awk-counts.txt`) · for the developer's download also = DESIGN §13 (another download: its own counts; without `awk-counts.txt` that check is SKIPPED and the command printed) · `build` in several runs · the 4 zoom-1 tiles = every point; Amsterdam's tile = its 4 smaller tiles · the page over the base map · bench: p99 under 100 ms | a record lost or doubled, a merge that loses points, slow tiles |

```text
unit        39 passed   0 failed
e2e        155 passed   0 failed
ALL PASSED (build)                                    make check
unit        39 passed   0 failed
e2e        155 passed   0 failed
ALL PASSED (build/san)                                make sanitize
check-data: T-Drive, GeoLife, USGS, Porto, NYC, AIS, OSM, OpenSky as before
check-data: GBIF 0023351-261023074918325.zip = download.json (key, 34,921,376,760 bytes, the 2024 query, 287,451,215 records, DOI 10.15468/dl.rb4bz5) · header: columns 22, 23 = decimalLatitude, decimalLongitude
check-data: GBIF first 500,000 rows: rows=500000 imported=500000 skipped_zero=0 skipped_out_of_range=0 skipped_malformed=0 = awk = the Python rules, every code
--- tests/validate/step-0a.sh … step-17.sh: ok as before (step 13 now finds step 12's commit by its message)
--- tests/validate/step-18.sh
  ok  import of the zip → rows=287451215 imported=287450825 skipped_zero=381 skipped_out_of_range=4 skipped_malformed=5 (rows = GBIF's totalRecords 287451215 · = awk over the whole file = DESIGN §13)
  ok  build: points=287450825 runs=3
  ok  the 4 zoom-1 tiles add up to 287450825 · tile 9/262/168 (Amsterdam) = 1070637 = its 4 smaller tiles
  ok  #gbif-2024/2/30.0000/10.0000: shows 287,450,825 points, 287,450,192 in view, over the base map · build/validate/step-18.png
  ok  bench gbif-2024 (287450825 points, warm disk cache): zoom 0, 5, 10, 15, 20 p50/p99 (ms): 0:3.98/6.46 5:7.02/15.95 10:1.03/5.21 15:0.55/1.23 20:0.53/0.68 · worst p99 at any zoom: 16.50 ms
VERIFY PASSED (after every review fix)
```

## Review (Codex)

Run with `CODEX_BIN=<wrapper> tools/review.sh 18` (gpt-6-astra, high reasoning effort). Files in `.review/step-18/`.

| Round | Finding (severity, file:line) | What happened |
|---|---|---|
| 1 | Medium, `step-18.sh:22`: "counts = awk" printed while the whole-file `awk` pass hadn't finished and the script never read it | Fixed: the pass finished (3,811 s, exit 0, rows = `totalRecords`) and equals gpstiles; `step-18.sh` now reads `awk-counts.txt` and fails unless it is the same |
| 1 | Medium, `docs/steps/README.md:28`: this report was missing | Fixed: this file |
| 1 | Low, `check_gbif.py:47`: the query check flattened predicates, so `OR` or `YEAR >= 2024` passed | Fixed: exactly `and` of two `equals`, and `SIMPLE_CSV` |
| 2 | 1 fixed · 2 partly (this report's results were still to be filled in) · 3 partly: no permanent test of the query rule | Fixed after round 2: the results below; the rule is a function, `is_the_2024_download`, with `tests/e2e/test_check_gbif.py` (an `or`, `>=`, a third condition, YEAR twice, another year, no coordinates, DWCA, unfinished, no query) |

Left for the developer to decide: none.

## Review (Claude skeptic, separate agent)

A second Claude Opus 5.5 agent with a fresh context, in its own copy (no full re-import, no real GBIF, never the login file). It ran `check_gbif.py` and `step-18.sh` (cached), and scanned the first 100 million lines of the file with its own program: 81 rows at (0,0), no malformed row, and 2 of the 4 out-of-range rows (gbifIDs 6231333167 and 6231269095: latitude 89.0, rightly skipped).

| Round | Finding (severity) | What happened |
|---|---|---|
| 1 | Medium M1: "= awk" claimed, not proven (the same as Codex's); the `awk` pipe's `unzip` status not checked | Fixed (as Codex's); the `awk` rows = `totalRecords`, so its `unzip` ran to the end |
| 1 | Low L1: this report missing; three different timings | Fixed: about 15 minutes everywhere |
| 1 | Low L2: `browser.py` (the Python 3.9 fix) left a temp folder and 4 pipes when Chrome couldn't start | Fixed: cleaned up on that path; tested with Chrome missing |
| 1 | Low L3: a second zip would delete the cached build before failing | Fixed: exactly one zip, checked first |
| 1 | Low L4: TESTING's dataset count, the CC BY-NC 4.0 license, GBIF among the publishers' counts | Fixed |
| 1 | Test gaps: the format not checked; the 5 malformed rows not found one by one | Format: fixed (`SIMPLE_CSV`). The 5 rows: their count = `awk` (the skeptic agreed in round 2 that this is enough) |
| 2 | Round 1 fixed (re-checked: the query refusals, the leak, two zips) · Medium M1: `step-18.sh` could pass only for this developer's download (another `fetch-gbif.py` run gets its own key and counts, and no `awk-counts.txt`) · Low: `check_gbif.py` failed with a traceback on an unreadable zip · Low: text slips | Fixed after round 2: the DESIGN §13 counts are required only for this download (by key and size); any download must have rows = `totalRecords` and = `awk-counts.txt` when it exists, else that one check is SKIPPED with the exact command printed; a clean failure for an unreadable zip (B7); the text |

Left for the developer to decide: none.

**After both second rounds** (the 2-round limit, so no reviewer has seen these): the per-download pinning in `step-18.sh`, `check_gbif.py`'s unreadable-zip check and `is_the_2024_download` with its test, and `step-13.sh` finding step 12's commit by its message (the history rewrite that removed the developer's email changed every commit id, and its old hard-coded id `1e22d25` was gone). `make verify` ran after them.

## Proof the tests catch bugs

Each break was made in a scratch copy (deleted afterwards), then `check_gbif.py` was run on the real file. The program itself didn't change in this step (its import rules were proven in steps 2, 10 and 17).

| # | Break | Caught by |
|---|---|---|
| B1 | latitude and longitude columns swapped (23, 22) | `check_gbif.py`: "columns 23 and 22 are b'decimalLongitude' and b'decimalLatitude'" |
| B2 | the import told the file is comma-separated | `check_gbif.py`: gpstiles "imported=0 … skipped_malformed=500000" ≠ `awk` |
| B3 | `download.json`'s size 1 byte off the zip's | `check_gbif.py`: "isn't the download download.json describes" |
| B4–B6 | the query in `download.json` an `or`, a `>=` on YEAR, or with a third condition | `check_gbif.py`: "isn't the download download.json describes", each |
| B8 | the query rule flattened again (`or` and `>=` accepted) | `test_only_the_exact_2024_query_is_the_known_download` ("or") |
| B7 | the zip replaced by a file of the right size that isn't a zip | `check_gbif.py`: "unzip gave 0 lines … (not a readable zip?)" |
| B9 | `awk-counts.txt` doctored (`skipped_zero=380`) | `step-18.sh` exit 1: "awk over the whole file gave '… skipped_zero=380 …', gpstiles '… skipped_zero=381 …'" |
| B10 | `awk-counts.txt` missing, the developer's download | `step-18.sh` exit 1: "no awk-counts.txt for the known download; make it with: …" (the command) |
| B11 | `awk-counts.txt` missing and another key in `download.json` | `step-18.sh` passes on rows = `totalRecords` and prints "SKIPPED (= awk over the whole file) … make it (an hour) with: …" |

B9–B11 changed the real data files' copies in place; both were restored and compared (`cmp`) afterwards. The code was restored exactly afterwards: yes.

## Validate it yourself

| Do this | Expected | Actual (agent's run) |
|---|---|---|
| `tests/validate/step-18.sh` | the `ok` lines in Tests | as in Tests |
| http://127.0.0.1:8090/#gbif-2024 | species sightings worldwide | 287,450,825 points; bright over the US and Europe, survey lines at sea |

## Deploy (after approval)

Done after commit 30322b7: `gbif-2024.gpt` (2.3 GB) copied to `data/build/` (`cmp` = the validated build), added to `datasets.conf`, `GPSTILES_PORT=8090 make deploy`: "smoke test green: the map page, 11 dataset(s) listed and drawn, bad URL → 404".

## Who did what

| Agent | Did |
|---|---|
| Claude Opus 5.5 (main) | the download (with the developer's login), import, build, checks, this report |
| Codex CLI gpt-6-astra (high effort) | review (read-only) |
| Claude Opus 5.5 skeptic (separate agent, own copy) | adversarial review |

## Decisions
- **One year, 2024** (the developer, 2026-11-02): 287 million points, a 35 GB download; every year with coordinates would be about 2.5 billion and 260 GB.
- **GBIF's records are kept as published:** no filter on GBIF's quality flags (the map shows what GBIF serves for the query).

## Not verified
- A cold-cache `bench` (needs `sudo purge`).

## Next
- All planned steps are built. Open for the developer: nothing blocking.
