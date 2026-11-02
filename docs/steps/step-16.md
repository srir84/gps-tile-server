# Step 16: GPX (OpenStreetMap's GPS traces) + stage 5 report

## Summary

| | |
|---|---|
| **Built** | `gpstiles import --gpx`: every `<trkpt>` start tag of a GPX (XML) stream is a row, its `lat` and `lon` the place, read in 1 MiB chunks (tags may span lines) · OpenStreetMap's public GPS traces of 2013 (22 GB `tar.xz`, 848,059 GPX files) streamed through `xz -dc \| tar -xOf -` into one `.gpt` of **2,675,901,374 points** (20 runs with the 1 GiB buffer) · its checks · the stage 5 report |
| **Status** | approved (all-stages go-ahead 2026-11-01) |
| **Date** | 2026-11-01 |
| **Agent(s)** | Claude Opus 5.5 main · Codex reviewer (gpt-6-astra, high effort) · Claude Opus 5.5 skeptic reviewer (separate agent) |

## Stage 5 in numbers (this Mac: 16 cores, 128 GB of memory)

| | OpenStreetMap GPS traces 2013 (step 16) |
|---|---|
| Points | **2,675,901,374** (of 2,676,451,044 track points: 546,151 at (0,0), 3,519 off the map, none malformed) |
| Answer source | `tests/data/osm_count.py` (Python's `tarfile` + a regular expression, file by file) for the track points; Python's XML parser for sample files' places |
| Import | 27 min 12 s (`xz -dc` → `tar -xOf -` → `import --gpx`; `xz` is the slow part, about 100% of one core) |
| Build (default `--mem`, 1 GiB) | 20 runs, 4 min 43 s, peak 1.08 GB |
| `.gpt` | 21.4 GB |
| Tiles, p99 at any zoom (`bench`, warm disk cache) | under 53 ms (52.3 ms at zoom 5 in `step-16.sh`; 60 ms in an earlier run while `xz` was busy on the same Mac) |

Drawing one tile at 2.7 billion points (`gpstiles bench`, drawing only), p50 / p99 in milliseconds:

| Zoom | 0 | 2 | 5 | 8 | 10 | 13 | 15 | 18 | 20 | 24 |
|---|---|---|---|---|---|---|---|---|---|---|
| p50 / p99 | 5.1 / 7.6 | 18.1 / 25.8 | 11.7 / 52.3 | 4.2 / 22.4 | 2.5 / 11.8 | 1.2 / 5.4 | 0.9 / 3.1 | 0.6 / 1.9 | 0.5 / 1.1 | 0.5 / 0.6 |

**What stage 5 shows** (`PROJECT_IDEAS.md` §8.5: "GPX reader; multi-billion-point worldwide datasets"):
- **A GPX reader:** `import --gpx` reads OpenStreetMap's 848,059 files in one stream with no XML library (DESIGN §8's GPX rules), and agrees with Python's XML parser on every sample file.
- **Multi-billion, worldwide:** 2.68 billion points on every continent, from one 21.4 GB file, served by the same small program; the build stays out of core (1 GiB buffer, 20 runs).
- **DS-7 (AIS)** was done in stage 4 (step 15). **DS-8 (GBIF) and DS-9 (OpenSky) need accounts**, which the builder never makes: they wait for the developer. Their import needs no new code (CSV/TSV columns, or Parquet through a converter as in step 14).

## Every stage 5 check (DESIGN §12.7)

| Check | Result |
|---|---|
| GPX read right | sample files: counts and every place = Python's XML parser (`check_osm.py`, `small.gpx`); random GPX = the Python rules (`import_rules.py`); 4 + 4 more dump files by the skeptic |
| The dump's track points = an independent count | 2,676,451,044 = `osm_count.py` (planned: = `metadata.xml`'s 2,674,972,244; it undercounts 99 files: Decisions) |
| Multi-billion points | 2,675,901,374 on the map |
| Tile counts add up | the 4 zoom-1 tiles = every point; Berlin's zoom-8 tile = its 4 zoom-9 tiles |
| Out of core | 20 runs with 1 GiB for 21.4 GB |
| Tiles in milliseconds | p99 under 53 ms at every zoom (warm) |
| Served and drawn | the page over the base map (`build/validate/step-16.png`), the service on port 8090 |

## Design
- **GPX without an XML library** (DESIGN §8): the program has one dependency, zlib. A track point is `<trkpt` followed by a space, tab, CR, LF, `/` or `>`, up to its first `>` outside a quoted value; its `lat` and `lon` attributes are the place, in any order and quote. A tag with no `>` within 4,096 bytes, or with a `<` or NUL before it (XML allows neither, even quoted), is one malformed row and the scan goes on right after its `<trkpt`, so one broken tag never hides the next.
- **Read in chunks, not lines:** a tag may span lines, and a line may hold many tags. The 1 MiB buffer keeps a tag still waiting for its `>` (or the last 6 bytes, which may start one) when it refills.
- **No GPX on disk:** the 22 GB `tar.xz` holds 848,059 files; `xz -dc | tar -xOf -` streams them all, one after another, into `import --gpx /dev/stdin`. Only the `.pts` (21.4 GB) and the `.gpt` are written.
- **The answer source:** `metadata.xml` lists each file's `points`, but for 99 early uploads it lists fewer than the file holds (their points repeat). So the count to match is Python's own, file by file (`osm_count.py`, run once by hand: 27 minutes), which also shows every other file = `metadata.xml`.
- **Checks sized for `make verify`:** `check_osm.py` (2 s) takes 3 files from the start of the dump and checks them three ways; `step-16.sh` imports and builds the whole dump, kept in `build/validate/` while nothing changes (about 35 minutes when it must redo it).

## Files changed

| File | Change | Why |
|---|---|---|
| `src/import.c`, `src/import.h` | changed | `import_gpx_point`, `tag_attribute`, `tag_end`, `next_trkpt`, the chunked `gpx_stream`; `struct import_options` gets `gpx` |
| `src/main.c` | changed | `--gpx`, refused with column options, `--delim` or `--skip` |
| `tests/unit/test_import.c` | changed | `gpx_tags_need_one_good_lat_and_lon` |
| `tests/oracle/import_rules.py` | changed | the GPX rules in Python (`gpx_files`) |
| `tests/fixtures/small.gpx` | added | OpenStreetMap's layout and its odd cases |
| `tests/e2e/test_import.py`, `tests/e2e/test_review_script.py` | changed | 4 GPX tests; 16 is a step now |
| `tests/data/check_osm.py`, `tests/data/osm_count.py`, `Makefile` | added, changed | the light check in `make check-data`; the hand-run count of the whole dump |
| `tests/validate/step-16.sh`, `tests/validate/lib.sh` | added, changed | DESIGN §12.7's check on all 2.7 billion points (`osm_gpt`, kept while unchanged) |
| `docs/DESIGN.md`, `docs/TESTING.md`, `README.md`, `AGENTS.md`, `PROGRESS.md` | changed | §8 GPX rules, §9.1 usage, §12.7, §13 facts · tests · how to get and import the data · where it is |

## Tests

| Test | Checks | Bug it would catch |
|---|---|---|
| `gpx_tags_need_one_good_lat_and_lon` (unit) | either order and quote, spaces and newlines around `=`, a self-closing tag, other attributes; (0,0), off the map; 15 broken tags (no lat, two lats, unquoted, unclosed, `plat`, hex, spaces in the number, a NUL) | a place from the wrong attribute, a doubled or missing lat kept, a broken tag taken |
| `test_gpx_track_points_give_their_known_counts_and_codes` | `small.gpx` twice: known counts, every code = the Python rules, the kept places = Python's XML parser | GPX read wrong, a waypoint or `<trkptx>` taken |
| `test_random_gpx_matches_the_python_rules` | 60,000 random pieces in 2 files over 3 MiB (past the 1 MiB buffer), some tags over 4 KiB, one file ending mid-tag | any disagreement with DESIGN §8's GPX rules |
| `test_gpx_tags_at_the_read_buffer_edge_and_the_tag_limit` | a tag starting at each of 40 places before the 1 MiB edge; files ending inside `<trkpt`; tags of exactly 4,096 (kept) and 4,097 bytes; `>` inside either quote; a stray quote, an unclosed quote, an unclosed tag before a good one; NUL bytes | a tag lost or doubled at a refill, the limit off by one, a broken tag hiding the next |
| `test_gpx_arguments_are_checked` | `--gpx` with column options, `--delim`, `--skip`: exit 2 | options silently ignored |
| `check_osm.py` (`make check-data`) | 3 dump files: counts and every code = the Python rules; every track point and place = Python's XML parser; count = `metadata.xml` | the real files read wrong |
| `step-16.sh` | the whole dump: counts = DESIGN §13 (rows = `osm_count.py`), `metadata.xml` = its known sum · `build` in several runs · the 4 zoom-1 tiles = every point, Berlin's tile = its 4 smaller tiles · the page over the base map · bench: p99 under 100 ms at every zoom | a file lost or doubled in the stream, an in-memory build, slow tiles at 2.7 billion points |

```text
unit        39 passed   0 failed
e2e        140 passed   0 failed
ALL PASSED (build)                                    make check
unit        39 passed   0 failed
e2e        140 passed   0 failed
ALL PASSED (build/san)                                make sanitize
check-data: T-Drive, GeoLife, USGS, Porto, NYC, AIS as before
check-data: OSM 001005252.gpx: rows=8098 imported=8098 skipped_zero=0 skipped_out_of_range=0 skipped_malformed=0 = the Python rules, every code · 8,098 track points and places = Python's XML parser = metadata.xml
check-data: OSM 001005107.gpx: rows=108 imported=108 skipped_zero=0 skipped_out_of_range=0 skipped_malformed=0 = the Python rules, every code · 108 track points and places = Python's XML parser = metadata.xml
check-data: OSM 001005876.gpx: rows=8790 imported=8790 skipped_zero=0 skipped_out_of_range=0 skipped_malformed=0 = the Python rules, every code · 8,790 track points and places = Python's XML parser = metadata.xml
--- tests/validate/step-16.sh
  ok  import --gpx of the whole dump → rows=2676451044 imported=2675901374 skipped_zero=546151 skipped_out_of_range=3519 skipped_malformed=0 (rows = tests/data/osm_count.py's 2,676,451,044 = metadata.xml's 2674972244 + 1,478,800 in 99 files that hold more than it lists, DESIGN §13)
  ok  build: points=2675901374 runs=20
  ok  the 4 zoom-1 tiles add up to 2675901374 · tile 8/137/83 (Berlin) = 7200297 = its 4 smaller tiles
  ok  #osm-gps/2/30.0000/10.0000: shows 2,675,901,374 points, 2,675,900,881 in view, over the base map · build/validate/step-16.png
  ok  bench osm-gps (2675901374 points, warm disk cache): zoom 0, 5, 10, 15, 20 p50/p99 (ms): 0:5.13/7.63 5:11.74/52.31 10:2.52/11.83 15:0.87/3.13 20:0.54/1.09 · worst p99 at any zoom: 52.31 ms
VERIFY PASSED (make verify, about 1 h 30 min: step 16 imported the whole dump again with the final program)
Once, by hand: tests/data/osm_count.py over the whole dump → track points 2676451044, 848059 .gpx files; 99 differ from metadata.xml, by 1478800
```

## Review (Codex)

Run with `CODEX_BIN=<wrapper> tools/review.sh 16` (gpt-6-astra, high reasoning effort). Files in `.review/step-16/`.

| Round | Finding (severity, file:line) | What happened |
|---|---|---|
| 1 | Medium, `step-16.sh:24`: `EXPECTED_COUNTS` is a placeholder, so the full check always fails | Fixed after the full import: the counts and their source in DESIGN §13 (`osm_count.py`); `metadata.xml`'s sum checked too |
| 1 | Medium, `import.c:380`: a `>` inside a quoted value ended the tag (valid XML counted as malformed) | Fixed: `tag_end()` follows quotes, in the C and the Python rules; tested end to end |
| 1 | Low, `import.c:184`: `strchr` takes a NUL as a space | Fixed: `xml_space()` (space, tab, CR, LF only); tested |
| 2 | 1 open (filled after the import), 2 fixed · Low: a NUL in another attribute's value was still kept · Medium (new): an unclosed tag took the next tag's `>`, losing that track point | Fixed after round 2: a `<` or NUL before the `>` breaks the tag and the scan goes on after its `<trkpt` (the same fix as the skeptic's round-2 finding 1); Codex's own example tested (2 rows, 1 kept) |

Left for the developer to decide: none.

## Review (Claude skeptic, separate agent)

A second Claude Opus 5.5 agent with a fresh context, in its own copy (the full import off limits by the brief; `check_osm.py` and a few dump files). Round 1: no crash, hang or out-of-bounds read in 82 edge cases and 300 random files under ASan and UBSan; 108 MB of real GPX imported in 0.29 s.

| Round | Finding (severity) | What happened |
|---|---|---|
| 1 | Low 1: a NUL counted as a space (`strchr`) | Fixed (as Codex's low) |
| 1 | Medium 2: losing a tag at a refill (keeping 5 bytes, not 6) passed every test | Fixed: the 40-offset sweep at the 1 MiB edge; the mutant is break K1 |
| 1 | Low 3: the 4,096-byte limit never tested at its edge | Fixed: 4,096 kept, 4,097 malformed; break K2 |
| 1 | Low 4: `>` inside a quoted value passed the unit test but not a real import | Fixed with Codex's round-1 medium |
| 1 | Test gap: `check_osm.py` compared places only with the Python rules | Fixed: also with Python's XML parser |
| 2 | Round-1 fixes right (120 edge cases at the refill and the limit, 300 random files, no differences) · Low 1: a stray quote (`it's>`) made the tag run on and hid the track points after it · Low 2: the quote scan made a worst case 24× slower (10 MB of `<trkpt `: 4.3 s) | Fixed after round 2: a `<` ends a tag as malformed (XML forbids it in a value); the skeptic's example now 3 rows; the worst case 0.01 s |
| 2 | Test gaps: single quotes untested, an unclosed quote before good tags, `check_osm.py` crashing on a point without lat | Fixed: `'a>b'`, `stray.gpx`, a clean failure; breaks L3, L4 |

Left for the developer to decide: none.

**After both second rounds** (the 2-round limit, so no reviewer has seen these): the `<`/NUL rule, its tests and breaks L1–L4; the counts in `step-16.sh` and DESIGN §13; `osm_count.py`. `make verify` ran after them.

## Proof the tests catch bugs

Each break was made in a scratch copy (deleted afterwards), then the named test was run.

| # | Break | Caught by |
|---|---|---|
| X1 | an attribute matched by its end (`plat` taken as `lat`) | `gpx_tags_need_one_good_lat_and_lon` |
| X2 | the refill keeps nothing of a tag the buffer cut | `test_random_gpx_matches_the_python_rules` |
| X3 | no 4,096-byte limit | `test_random_gpx_matches_the_python_rules` |
| X4 | a doubled `lat` taken | `gpx_tags_need_one_good_lat_and_lon`, `test_gpx_track_points_give_their_known_counts_and_codes` |
| K1 | the refill keeps 5 bytes, not 6 | `test_gpx_tags_at_the_read_buffer_edge_and_the_tag_limit` (2 of 80 lost) |
| K2 | a 4,097-byte tag kept | the same test |
| K3 | a NUL taken as a space (`strchr`) | `gpx_tags_need_one_good_lat_and_lon`, the same e2e test |
| Q1 | quotes not followed (`>` in a value ends the tag) | the same e2e test |
| L1 | a `<` doesn't end a tag (a stray quote hides the next track points) | the same e2e test (11 rows, not 13) |
| L2 | a NUL in a value kept | the same e2e test |
| L3 | single quotes not followed | the same e2e test |
| L4 | a broken tag skips to its `<` instead of going on after `<trkpt` | the same e2e test (10 rows, not 13) |

The code was restored exactly afterwards: yes.

## Validate it yourself

| Do this | Expected | Actual (agent's run) |
|---|---|---|
| `tests/validate/step-16.sh` | the `ok` lines in Tests | as in Tests |
| `gpstiles bench data/build/osm-gps.gpt` | p99 in tens of milliseconds at every zoom | the table above |
| http://127.0.0.1:8090/#osm-gps | the world's GPS traces: Europe brightest, roads and cities | after the deploy |

## Deploy (after approval)

After this commit: `GPSTILES_PORT=8090 make deploy`, `osm-gps.gpt` (21.4 GB, in `data/build/`) added to `datasets.conf`. The results go in `PROGRESS.md`, which goes in with the next commit.

## Who did what

| Agent | Did |
|---|---|
| Claude Opus 5.5 (main) | the GPX reader, the import, build, checks, this report |
| Codex CLI gpt-6-astra (high effort) | review (read-only) |
| Claude Opus 5.5 skeptic (separate agent, own copy) | adversarial review |

## Decisions
- **The count to match is Python's, not `metadata.xml`'s** (a change to DESIGN §12.7's plan, for the developer to confirm): `metadata.xml` lists 1,478,800 fewer points than the dump holds, all in 99 early uploads (ids 105,565–123,773) whose files repeat their points; Python's XML parser counts what gpstiles counts on the 15 biggest of them. The other 847,960 files = `metadata.xml` exactly.
- **Repeated points are kept**: the heat map counts what the files hold (as for every dataset); 99 files of 848,059 are too few to change the picture.
- **Comments, CDATA and entities aren't read** (DESIGN §8): OpenStreetMap's files have none in track points (malformed = 0 over the whole dump).

## Not verified
- The (0,0) and off-the-map counts of the whole dump (546,151 and 3,519) come from gpstiles only; the places were checked independently on sample files (Python's XML parser), not on all 2.7 billion.
- A cold-cache `bench` (it needs `sudo purge`); the numbers are warm, as in step 15.
- GBIF and OpenSky (DS-8, DS-9): they need accounts, which wait for the developer.

## Next
- All five stages are built. Open for the developer: GBIF and OpenSky accounts, the time per point decision, the license.
