# Step 17: OpenSky's aircraft positions (stage 5's DS-9)

## Summary

| | |
|---|---|
| **Built** | `tools/fetch-opensky.py`: one day of OpenSky's public aircraft positions, each hourly file kept only when its size and S3 ETag (MD5, or a multipart ETag checked part by part) match the bucket's listing · Monday 2022-06-27 worldwide: 24 hourly tars (3.9 GB) streamed through `tar -xOf \| gunzip` into import and built into one `.gpt` of **56,869,562 points** · its checks · and, prepared for step 18, `tools/fetch-gbif.py` (GBIF's occurrence service was down) |
| **Status** | approved (all-stages go-ahead 2026-11-01; OpenSky route chosen by the developer 2026-11-02) |
| **Blocked on** | Step 18 (GBIF): GBIF's download service answers HTTP 500 (since 2026-11-02 13:56); `tools/fetch-gbif.py data/raw/gbif 2024` is retried, and a rerun never asks GBIF twice |
| **Date** | 2026-11-02 |
| **Agent(s)** | Claude Opus 5.5 main · Codex reviewer (gpt-6-astra, high effort) · Claude Opus 5.5 skeptic reviewer (separate agent) |

## In numbers (this Mac: 16 cores, 128 GB of memory)

| | OpenSky, Monday 2022-06-27 |
|---|---|
| Rows | 61,296,085 state vectors (one an aircraft about every 10 s) |
| Points | **56,869,562**; the other 4,426,523 rows have no position (empty `lat`, `lon`) and are malformed by DESIGN §8 |
| Answer source | `awk` over every hour (`row_counts.awk`, `data/raw/opensky/awk-hours.txt`): the same counts, all five |
| Download | 6 min (24 files, 3,860,377,600 bytes) |
| Import + build | 38 s (one run: 455 MB of points fits the 1 GiB buffer) |
| Tiles, p99 at any zoom (`bench`, warm) | under 18 ms (14.84 ms in `make verify`) |

**What it shows:** the world's flights on one day, as OpenSky's receivers hear them: dense over the US and Europe, thin where there are few receivers (Africa, the oceans). The same program, no new import code: OpenSky's hourly CSVs are plain columns.

## Why the public samples, not OpenSky's full history

The developer registered OpenSky. Its full history is a Trino database; the login works, but a query answered `PERMISSION_DENIED: Cannot execute query`. OpenSky's own Request Data Access page says the full dataset is granted "only to research institutions, aviation authorities, and governments" and that "pre-curated datasets are available for individuals". The developer chose those (2026-11-02): one Monday a week from 2020-05-25 to 2022-06-27, no account needed. Their license allows non-profit research and education and internal testing and evaluation; the data is never committed or published (`data/` is ignored).

## Design
- **`tools/fetch-opensky.py`** (Python, built-in modules only, like `fetch-usgs.py`): reads the bucket's S3 listing (every page), and for each `states_<day>-<HH>.csv.tar` downloads to `.part`, keeps it only when its size and ETag match and it holds exactly one `.csv.gz`; a rerun checks kept hours again and skips them. A stop leaves no `.part`.
- **Multipart ETags:** 4 of the 24 hours (14–17) were uploaded in parts, so their ETag is `<MD5 of the parts' MD5s>-42`, not the file's MD5. The part size isn't listed; only 5 MiB gives 42 parts for these sizes, so each part is hashed and the result compared: the four files are checked as exactly as the others.
- **No CSV on disk:** each hour streams `tar -xOf HOUR.tar '*.csv.gz' | gunzip | gpstiles import --lat-col 3 --lon-col 4 --skip 1 -o HOUR.pts /dev/stdin`; `build` takes the 24 `.pts`.
- **Checks sized for `make verify`:** `check_opensky.py` (30 s) compares hours 00 and 12 with `awk`, and hour 00's every code and 2 airports' tiles with Python; `step-17.sh` imports and builds the whole day (kept in `build/validate/` while nothing changes).
- **GBIF, prepared:** `tools/fetch-gbif.py` and its tests are in this step because they were written while GBIF's occurrence API answered "500 Broken at the moment"; the GBIF data, its checks and report are step 18.

## Files changed

| File | Change | Why |
|---|---|---|
| `tools/fetch-opensky.py` | added | the download, each hour checked whole |
| `tests/e2e/test_fetch_opensky.py` | added | 3 tests against a fake S3 bucket |
| `tests/data/check_opensky.py`, `Makefile` | added, changed | OpenSky's light checks in `make check-data` |
| `tests/validate/step-17.sh`, `tests/validate/lib.sh` | added, changed | the whole day (`opensky_gpt`, kept while unchanged) |
| `tools/fetch-gbif.py`, `tests/e2e/test_fetch_gbif.py` | added | step 18's download, tested against a fake GBIF |
| `tests/data/row_counts.awk` | changed | an optional `DELIM` (GBIF's files are tab-separated) |
| `docs/DESIGN.md`, `docs/TESTING.md`, `README.md`, `AGENTS.md`, `PROGRESS.md` | changed | §12.7 steps 17–18, §13 OpenSky's facts · tests · how to get and import the data · where it is · the developer's decisions |

## Tests

| Test | Checks | Bug it would catch |
|---|---|---|
| `test_whole_hours_are_kept_a_bad_one_leaves_nothing_and_a_rerun_resumes` | a fake bucket: an hour whose bytes differ from its listed MD5 refused, nothing left; a rerun keeps kept hours untouched and fetches the rest; a damaged kept hour fetched again; a day with no files, impossible days refused | a wrong or cut-off hour kept, a `.part` left, kept hours fetched again |
| `test_a_day_must_be_its_24_hours` | a missing hour, a day with no files, an hour's file in another hour's folder | an incomplete day kept, an hour kept under another's name |
| `test_a_file_that_isnt_one_csv_gz_or_of_another_size_is_refused` | tars with two or no CSVs; a listed size 1 byte off with the MD5 right | an hour read twice or not at all, a size mismatch kept |
| `test_a_stopped_download_leaves_no_part_file` | SIGTERM halfway through a slowly sent hour | a `.part` left |
| `test_a_listing_in_pages_is_read_to_its_end_and_multipart_etags_are_checked` | a listing of 2 keys a page; a 12 MiB file with a 3-part ETag: wrong parts refused, right parts kept; an ETag that is neither refused | hours missing from the day, a multipart file kept unchecked or refused |
| `test_the_download_is_requested_once_waited_for_kept_whole_and_a_rerun_doesnt_ask_again` (GBIF) | the query (2024, with coordinates, simple CSV), waiting until SUCCEEDED, the zip kept, the password never printed, no second request, another year refused | hours of GBIF's work asked for again, the wrong data, the password leaked |
| `test_a_request_whose_answer_is_lost_is_not_sent_again` (GBIF) | a request GBIF took but answered 503: one request; the rerun finds and uses it; an earlier download of another year not used | two downloads prepared at GBIF |
| `test_the_newest_good_download_with_the_same_query_is_used` (GBIF) | a FAILED one skipped, the newest of two good ones used, GBIF's stored query shape matched | the wrong download, or a second one asked for |
| `test_a_download_key_from_any_source_must_be_a_key` (GBIF) | `../victim/important` in the list, absolute and dotted keys in `state.json` | a file outside the folder deleted or written |
| `test_the_login_is_never_sent_elsewhere_or_shown` (GBIF) | a redirect to a catcher server (gets nothing), plain http refused, a password with spaces never shown | the password leaked |
| `test_the_request_is_not_sent_on_a_redirect_and_damaged_zips_of_any_kind_are_refused` (GBIF) | the request redirected; a deflated zip damaged inside (new and kept); a Deflate64-labelled zip checked by `unzip` | a crash on every rerun, a damaged zip kept |
| `test_row_counts_awk_reads_tab_separated_files_like_the_python_rules` | `awk` with `DELIM` tab = the Python rules (commas inside fields, empty positions) | the answer source for GBIF splitting wrong |
| `test_a_bad_or_unsafe_login_is_refused_before_anything_is_asked` (GBIF) | a login file others can read, a placeholder, a missing file, a wrong login (not printed) | a password file left readable, a request without a login |
| `test_a_failed_download_or_a_bad_zip_leaves_nothing` (GBIF) | FAILED, a zip of another size, a zip with two files | a broken zip kept |
| `check_opensky.py` (`make check-data`) | hours 00 and 12: import = `awk` on the same stream · hour 00: every code = the Python rules; Frankfurt's and Atlanta's zoom-10 tiles = Python's points inside their edges | an hour read wrong, places in the wrong tile |
| `step-17.sh` | the 24 hours added up = DESIGN §13 (`awk`) · the 4 zoom-1 tiles = every point; Frankfurt airport's tile = its 4 smaller tiles · the page over the base map · bench: p99 under 100 ms | an hour lost or doubled, a merge that loses points, slow tiles |

```text
unit        39 passed   0 failed
e2e        154 passed   0 failed
ALL PASSED (build)                                    make check
unit        39 passed   0 failed
e2e        154 passed   0 failed
ALL PASSED (build/san)                                make sanitize
check-data: T-Drive, GeoLife, USGS, Porto, NYC, AIS, OSM as before
check-data: OpenSky states_2022-06-27-00: rows=2277578 imported=2133292 skipped_zero=0 skipped_out_of_range=0 skipped_malformed=144286 = awk
check-data: OpenSky states_2022-06-27-00, Frankfurt airport: tile 10/536/347 holds 672 points = Python's points inside its edges
check-data: OpenSky states_2022-06-27-00, Atlanta airport: tile 10/271/410 holds 4,932 points = Python's points inside its edges
check-data: OpenSky states_2022-06-27-00: all 2,133,292 codes = the Python rules
check-data: OpenSky states_2022-06-27-12: rows=2858582 imported=2637674 skipped_zero=0 skipped_out_of_range=0 skipped_malformed=220908 = awk
--- tests/validate/step-16.sh
  ok  ... bench osm-gps: worst p99 at any zoom: 98.55 ms   (see Not verified: close to the limit inside make verify)
--- tests/validate/step-17.sh
  ok  import of 24 hours, added up → rows=61296085 imported=56869562 skipped_zero=0 skipped_out_of_range=0 skipped_malformed=4426523 (= awk over the whole day, DESIGN §13)
  ok  build: points=56869562 runs=1
  ok  the 4 zoom-1 tiles add up to 56869562 · tile 9/268/173 (Frankfurt airport) = 165738 = its 4 smaller tiles
  ok  #opensky-2022-06-27/3/40.0000/-30.0000: shows 56,869,562 points, 52,763,542 in view, over the base map · build/validate/step-17.png
  ok  bench opensky-2022-06-27 (56869562 points, warm disk cache): zoom 0, 5, 10, 15, 20 p50/p99 (ms): 0:1.35/1.84 5:10.13/13.22 10:1.14/5.24 15:0.53/1.35 20:0.53/0.54 · worst p99 at any zoom: 14.84 ms
VERIFY PASSED (the second make verify, after the review fixes)
```

## Review (Codex)

Run with `CODEX_BIN=<wrapper> tools/review.sh 17` (gpt-6-astra, high reasoning effort). Files in `.review/step-17/`.

| Round | Finding (severity, file:line) | What happened |
|---|---|---|
| 1 | Medium, `fetch-opensky.py:168`: a day with only some hours succeeded | Fixed: exactly hours 00–23, once each, the folder's hour = the name's; tested (a missing hour, a misfiled one) |
| 1 | Medium, `fetch-gbif.py:67`: the download request was retried, so a lost answer could start a second download at GBIF | Fixed: never retried; before asking, the user's own downloads are searched for one with the same query; tested (taken, then answered 503: one request, the rerun adopts it) |
| 1 | Medium, `fetch-gbif.py:91`: a zip damaged inside at the same size passed (only its list of files was read) | Fixed: `testzip()` checks every CRC, new and kept zips; tested |
| 1 | Low, `test_fetch_opensky.py:61`: no test of a wrong size with a right MD5 | Fixed: tested |
| 2 | 1, 2, 4 fixed · 3 partly: a deflated zip damaged inside raises `zlib.error`, uncaught, so a damaged kept zip crashed every rerun · Medium (new): keys from the list of downloads and from `state.json` were never checked, so `../../victim` could reach a file outside the folder | Fixed after round 2: `zlib.error` caught (tested, new and kept); one `checked_key()` for every key from any source (tested with `../victim/important`, an absolute path, `..`, a `.zip` name, empty) |

Left for the developer to decide: none.

## Review (Claude skeptic, separate agent)

A second Claude Opus 5.5 agent with a fresh context, in its own copy, fake servers only (never the real GBIF, OpenSky or S3, never the credential files). It confirmed the malformed rows are exactly the rows with no position, the day's total = `awk-hours.txt`, and the counts' independence.

| Round | Finding (severity) | What happened |
|---|---|---|
| 1 | Medium M1: `fetch-gbif` retried the download request (two downloads at GBIF) | Fixed (as Codex's) |
| 1 | Medium M2: a redirect sent the GBIF login on to another host (proven: a second server received it) | Fixed: requests carrying the login refuse redirects and plain http (except to this Mac); tested with a catcher server |
| 1 | Medium M3: a listing that never ends was followed forever (33,624 requests in 8 s); guessing a part size could read a file about 5,000 times | Fixed: at most 100 pages, each token new; part sizes only from S3 tools' usual sizes (at most 10 reads) |
| 1 | Low L1: two keys could map to one file name (hour 01 kept as hour 00) | Fixed: the folder's hour must be the name's, each hour once |
| 1 | Low L2: netrc's error message showed part of a password with a space in it | Fixed: not shown; tested |
| 1 | Low L3: a damaged kept GBIF zip was reused | Fixed (as Codex's) |
| 1 | Low L4: a damaged kept hour stayed when its new download failed | Fixed: removed first; tested |
| 1 | Low L5: a non-number size in the listing crashed | Fixed: a clean error |
| 1 | Low L6: Linux (GNU tar needs `--wildcards`, no `ls -lnT`), `state.json` not written atomically, an unknown status looped | `state.json` and the status fixed; Linux: this project's scripts are macOS-only (now said in DESIGN §14) |
| 1 | Test gaps: the stop handler untested, endless listings, misfiled hours, multipart sizes, `awk` with tabs | Fixed: a SIGTERM mid-download leaves no `.part`; the others tested |
| 2 | Round 1 fixed (redirects probed with 301/302/303/307/308 on GET and POST: all refused; `same_query` matches GBIF's real stored shape and rejects other years, `or`, ranges, other formats) · Medium M1: a key adopted from the list of downloads was never checked (`../victim/important` deleted a file outside the folder) · Medium M2: a zip Python can't read (Deflate64) would be called damaged and fetched again every run · Low L1: every rerun decompresses the whole kept zip | Fixed after round 2: `checked_key()` (with Codex's); Python's "can't read" hands the check to macOS's `unzip -tqq`; a zip checked once is trusted while its size and time are the same (`state.json`) |
| 2 | Test gaps: a bad listed key, a FAILED same-query download, the newest wins, GBIF's stored shape, a redirect of the request, Deflate64 | Fixed: all tested (breaks G9–G14) |

Left for the developer to decide: none.

**After both second rounds** (the 2-round limit, so no reviewer has seen these): `checked_key()`, the `zlib.error` catch, the `unzip` fallback, the checked-zip stamp, DESIGN §14's Linux line, and their tests and breaks G9–G14; `make verify` ran after them.

## Proof the tests catch bugs

Each break was made in a scratch copy (deleted afterwards), then the named test was run. The break script now finds each test in its own module and stops if a named test doesn't exist; a control (a comment changed) was "not caught", as it should be.

| # | Break | Caught by |
|---|---|---|
| O1 | the ETag not compared, only the size | `test_whole_hours_are_kept_a_bad_one_leaves_nothing_and_a_rerun_resumes` |
| O2 | only the listing's first page read | `test_a_listing_in_pages_is_read_to_its_end_and_multipart_etags_are_checked` |
| O3 | a multipart ETag taken without checking its parts | the same test |
| O4 | a tar not held to one `.csv.gz` | `test_a_file_that_isnt_one_csv_gz_or_of_another_size_is_refused` |
| G1 | `fetch-gbif` asks GBIF again on a rerun | `test_the_download_is_requested_once_waited_for_kept_whole_and_a_rerun_doesnt_ask_again` |
| G2 | `fetch-gbif` uses a login file others can read | `test_a_bad_or_unsafe_login_is_refused_before_anything_is_asked` |
| G3 | `fetch-gbif` keeps a zip of another size than GBIF's | `test_a_failed_download_or_a_bad_zip_leaves_nothing` |
| O5 | a day with hours missing taken as whole | `test_a_day_must_be_its_24_hours` |
| O6 | a listing token that repeats followed again | `test_a_listing_in_pages_is_read_to_its_end_and_multipart_etags_are_checked` |
| O7 | a damaged kept hour left in place before fetching again | `test_whole_hours_are_kept_a_bad_one_leaves_nothing_and_a_rerun_resumes` |
| O8 | the listing's size not compared | `test_a_file_that_isnt_one_csv_gz_or_of_another_size_is_refused` |
| O9 | the stop handler gone | `test_a_stopped_download_leaves_no_part_file` |
| G4 | the download request retried | `test_a_request_whose_answer_is_lost_is_not_sent_again` |
| G5 | the user's earlier downloads not looked at | the same test |
| G6 | the login sent on a redirect | `test_the_login_is_never_sent_elsewhere_or_shown` |
| G7 | the zip's CRC not checked | `test_a_failed_download_or_a_bad_zip_leaves_nothing` |
| G8 | netrc's error message shown | `test_the_login_is_never_sent_elsewhere_or_shown` |
| G9, G10 | a key from the list of downloads, or from `state.json`, not checked | `test_a_download_key_from_any_source_must_be_a_key` |
| G11, G12 | a `zlib.error` not caught; no `unzip` fallback | `test_the_request_is_not_sent_on_a_redirect_and_damaged_zips_of_any_kind_are_refused` |
| G13, G14 | a FAILED earlier download adopted; `matchCase` not ignored | `test_the_newest_good_download_with_the_same_query_is_used` |
| A1 | `row_counts.awk`'s `DELIM` ignored | `test_row_counts_awk_reads_tab_separated_files_like_the_python_rules` |
| C0 | control: only a comment changed | not caught (as it should be) |

G1 (a rerun ignoring its saved key) is no longer caught, and rightly: the run then finds the same download among the user's own and asks GBIF nothing (G5 covers that search). G3 was rewritten for `whole_zip`'s size check (caught).

The code was restored exactly afterwards: yes.

## Validate it yourself

| Do this | Expected | Actual (agent's run) |
|---|---|---|
| `tests/validate/step-17.sh` | the `ok` lines in Tests | as in Tests |
| http://127.0.0.1:8090/#opensky-2022-06-27 | the US and Europe dense with flight paths | after the deploy |

## Deploy (after approval)

After this commit: `GPSTILES_PORT=8090 make deploy`, `opensky-2022-06-27.gpt` (455 MB) built into `data/build/` and added to `datasets.conf`.

## Who did what

| Agent | Did |
|---|---|
| Claude Opus 5.5 (main) | the fetchers, the download, import, build, checks, this report; opened OpenSky's application page in the developer's Chrome (read only, nothing submitted) |
| Codex CLI gpt-6-astra (high effort) | review (read-only) |
| Claude Opus 5.5 skeptic (separate agent, own copy) | adversarial review |

## Decisions
- **OpenSky's public samples, not Trino** (the developer, 2026-11-02): the full history is for institutions only.
- **The final `fetch-opensky.py` rerun on the real bucket:** all 24 kept hours checked again (size, ETag, one CSV) in 7.6 s, nothing downloaded, no file touched.
- **One day** (2022-06-27, the newest sample): 57 million points; more Mondays would add about that much each.
- **Rows without a position are malformed** (DESIGN §8 as it is): they're counted, not dropped silently.

## Not verified
- **A flaky speed check (seen once):** the first `make verify` after these changes stopped at `step-16.sh`: the worst p99 at 2.7 billion points was 107.95 ms at zoom 1 (limit 100; zoom 0's slowest tile 338 ms), where step 16 measured 52 ms. Run alone right after, `step-16.sh` passed (worst 51.34 ms, zoom 1 at 16 ms). Cause, likely: in `make verify`, step 15's second AIS build (9.7 GB, a 2 GiB buffer) runs just before and can push parts of the 21 GB OSM file out of the disk cache, so the "warm" bench reads from disk. Nothing in step 17 touches the C program. The limit stays; `make verify` was run again and passed, but step 16's worst p99 was 98.55 ms there: inside `make verify` that check is close to its limit and may fail again. A fix for the developer to choose: run `step-16.sh`'s bench before step 15's second build, or give each bench a truly warm file (read it twice).
- A cold-cache `bench` (needs `sudo purge`).
- GBIF (step 18): its service was down; the fetcher is tested only against a fake GBIF.

## Next
- Step 18: GBIF's 2024 occurrences, when GBIF's occurrence API answers again; then the push and the validation steps.
