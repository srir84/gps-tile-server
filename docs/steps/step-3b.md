# Step 3b: Read `.gpt`: tilefile, info, count

## Summary

| | |
|---|---|
| **Built** | `tilefile` (open a `.gpt` read-only by memory mapping, check its header, find a tile's points with two binary searches) and the commands `gpstiles info` and `gpstiles count` |
| **Status** | approved (developer's go-ahead 2026-10-31) |
| **Date** | 2026-10-31 |
| **Agent(s)** | Claude Opus 5.5 main · Codex reviewer (gpt-6-astra) · Claude Opus 5.5 skeptic reviewer (separate agent) |

## Design
- **Open = map, check, done.** `tilefile_open` maps the whole file read-only. Nothing is read up front, so a 16 GB file opens as fast as an 80 MB one. Then it checks the 256-byte header: the label `GPSTILE`, version 1, header size 256, and file size = 256 + 8 × count.
- **A tile is one slice.** The points of tile z/x/y all share the top 2z bits of their code (DESIGN §5.2). The slice runs from the first code ≥ the tile's smallest code to the first code > its largest one. That takes two binary searches, about 24 reads each for T-Drive.
- **`info`** prints the header as `key=value` lines. Boxes are in degrees, ordered west,south,east,north like the API's `bbox`. **`count`** prints `points=N` for one tile.
- **Trusted, never trusting too much:** the points are trusted to be sorted, because `build` writes them so, and checking 10 million (or a billion) codes on every open would cost a full read. An unsorted file gives wrong counts, never a read outside the file. Every index stays within 0…count.

| Tile | Its codes | Slice in the file |
|---|---|---|
| 0/0/0 | every code | all points |
| 10/843/388 | top 20 bits = `interleave(843, 388)` | `first code ≥ prefix << 44` … `last code ≤ prefix << 44 \| (2^44 − 1)` |
| a tile with no points | none | an empty slice (first = end) |

## Files changed

| File | Change | Why |
|---|---|---|
| `src/tilefile.h`, `src/tilefile.c` | added | check the header (pure, on bytes), open + map, code at index i, slice of a code range, slice of a tile |
| `src/main.c` | changed | `info` and `count` commands, `open_gpt` (one message per kind of broken file), usage text · `finish_output`: every command fails if its result can't be written (Claude review) |
| `tests/unit/test_tilefile.c` | added | 3 tests |
| `tests/e2e/test_info_count.py` | added | 7 tests |
| `tests/oracle/gpt_rules.py` | changed | `code_of`, `tile_of`, `lon_of_x`, `lat_of_y`: tiles and degrees, written apart from `src/geo.c` |
| `tests/data/check_tdrive.py` | changed | `info` and `count` on the real `.gpt` |
| `tests/validate/step-3b.sh`, `lib.sh` | added / changed | the DESIGN §12.2 check · `tdrive_gpt`: T-Drive imported and built once into `build/validate/`, reused by later steps |
| `tests/unit/main.c`, `suites.h` | changed | run the tilefile suite |
| `docs/DESIGN.md` | changed | decisions applied (see Decisions) |
| `docs/TESTING.md` | changed | test list |

## Tests

| Test | Checks | Bug it would catch |
|---|---|---|
| `a_tile_count_is_the_slow_count_and_the_sum_of_its_4_children` | 3,000 clustered points (repeats, both world corners): 400 tiles at random zooms, the points' own tiles and random (mostly empty) ones, against a slow count of every point · each tile = the sum of its 4 smaller tiles | a slice off by one at either end, x/y swapped in the tile code, the world's first or last tile lost |
| `a_code_range_includes_both_ends_and_every_equal_code` | 10 copies each of 100 codes: ranges on, between and past them, up to `UINT64_MAX`, and `low > high` | the binary search stopping inside a run of equal codes, dropping the last code, or wrapping at the top |
| `broken_files_are_refused_and_a_good_header_reads_back` | every header field reads back where it was written · 0, 7, 8 and 255 bytes · a wrong label, version 2, version 0 (unfinished), header size 257 or 512 · one point cut, one junk byte or one point too many · a count whose × 8 wraps to the right size · impossible stats (min > max, a densest pixel of 0, above the count, or growing), and stats on a file with no points | a broken file accepted, so reads go past its end or step 4 divides by 0 · fields read from the wrong offset |
| `test_info_prints_the_header_the_oracle_expects` | `info` on a 400-point `.gpt` made by `build`: points, bytes, bounds and view in degrees, densest pixel per zoom = `gpt_rules.py` (degrees from its own inverse formulas) | a field from the wrong offset, south/north or x/y swapped |
| `test_count_is_the_slow_count_and_the_sum_of_its_4_children` | `count` on 32 tiles (corners, random, empty) = a slow count in Python, and = its 4 smaller tiles | the same bugs through the real command |
| `test_info_at_the_edges_of_the_world` | the world's two corner units → `bounds=-180.000000,-85.051129,180.000000,85.051129` | an overflow at the last unit (east shown as −180) |
| `test_an_empty_gpt_has_no_bounds` | 0 points → `bounds=none`, `view=none`, max pixels all 0 | made-up bounds at the world's corner |
| `test_broken_gpt_files_are_refused_with_a_clear_message` | 12 broken files (`broken_*.gpt`, made from a good one, incl. junk after the points and impossible stats), a missing file, a folder and a named pipe → exit 1, one line naming the file and the reason, for `info` and `count` | a broken file read past its end, a `.pts` taken for a `.gpt`, a hang on a pipe |
| `test_bad_arguments_are_a_usage_error` | 19 bad commands: zoom 25 or −1, x or y = 2^zoom, `+1`, a space, extra or missing arguments, a mistyped option before or after the file (the error must name it) → exit 2 · the largest tile number accepted | a tile outside the world counted anyway, or the error blaming the wrong argument |
| `test_a_result_that_cannot_be_written_is_an_error` | `info`, `count`, `where`, `help`, `import` and `build` with stdout closed → exit 1, "can't write the result" | a lost result reported as success |
| `make check-data` | `info` on the real `.gpt` = DESIGN §13 and the Python header · `count` 0/0/0 = every point · 10/843/388 = a slow count over all 10,064,891 codes = its 4 zoom-11 tiles | anything the small tests miss on real data |

```text
make check       unit 28 passed 0 failed · e2e 78 passed 0 failed · ALL PASSED (build)
make sanitize    unit 28 passed 0 failed · e2e 78 passed 0 failed · ALL PASSED (build/san)
make check-data  (import and build lines as in step 3a), then:
                 check-data: info: points=10064891 bounds=-180.000000,0.000000,179.633330,84.550030 view=115.966187,39.597223,117.169189,40.476203
                 check-data: count 10/843/388 = 2,229,964 = slow count = sum of its 4 zoom-11 tiles; 0/0/0 = every point
make verify      VERIFY PASSED, after both review rounds (step-0a 2 ok · 0b 7 ok · 1 2 ok · 2 3 ok · 3a 7 ok · 3b 3 ok)
--- tests/validate/step-3b.sh
      points=10064891
      bytes=80519384
      bounds=-180.000000,0.000000,179.633330,84.550030
      view=115.966187,39.597223,117.169189,40.476203
      max_pixel=5096856,5016273,3157022,2429731,1157176,379767,145787,54232,53278,37900,21535,8145,8140,8140,8140,8140,8140,8140,8140,8140,8140,8140,8140,8140,8140
  ok  info: points=10064891 (DESIGN §13), bounds and view box printed
  ok  count 10/843/388 = 2229964 = the sum of its 4 zoom-11 tiles
  ok  Python's slow count over every point of the .pts agrees: 2229964
```

The bounds are the whole world (−180 to 179.6, 0 to 84.6) because T-Drive has a few junk points far from Beijing (one at lon 180, which is stored as −180). The view box ignores them: 115.97–117.17° E, 39.60–40.48° N is Beijing.

## Review (Codex)

Run with `CODEX_BIN=<wrapper> tools/review.sh 3b`: the same script, with Codex pinned to gpt-6-astra at high reasoning effort (the log confirms `model: gpt-6-astra`, `reasoning effort: high`). Files in `.review/step-3b/`.

| Round | Finding (severity, file:line) | What happened |
|---|---|---|
| 1 | none: "No actionable findings … Reviewed file validation, tile searches, CLI handling, and tests against DESIGN and TESTING" · `SUMMARY: high=0 medium=0 low=0` | — |
| 2 (after the Claude review's fixes) | Low, `tests/unit/test_tilefile.c:174`: the "growing densest pixel" case also exceeds the point count, so it would still be refused if the growing check were removed | Fixed: a case where zoom 11 grows from 2 to 3, within the count. Caught (T17) |

## Review (Claude skeptic, separate agent)

A second Claude Opus 5.5 agent with a fresh context, working only in its own copy. It found "no high or medium problems: tile slices, `count` and the `info` numbers match independent answers on random data and on all of T-Drive", including 200,000 random tile queries under the sanitizers and a 1 TB sparse file opened with under 3 MB of memory.

| Round | Finding (severity, file:line) | What happened |
|---|---|---|
| 1 | Low F1, `src/main.c` (`info`, `count`): with a mistyped option and too many arguments, the error names the extra argument, not the option | Fixed: the leading dash is checked first. The test now asserts the quoted argument. Caught (T11) |
| 1 | Low F2, `src/main.c`: a result that can't be written (stdout closed, disk full) still exits 0, in every command | Fixed: `finish_output` checks stdout after every command (one command table in `main`). Test `test_a_result_that_cannot_be_written_is_an_error`. Caught (T12) |
| 1 | Low F3, `src/tilefile.c`: header stats never checked (a crafted file showed west > east and a densest pixel of 0, which step 4 divides by) | Fixed: impossible stats are refused (`stats_possible`): all 0 with no points; else min ≤ max and 1 ≤ densest pixel ≤ count, never growing with the zoom. Tests in the unit suite and `broken_stats.gpt`. Caught (T13, T17) |
| 1 | Low F4, `docs/DESIGN.md` §8: the long-line rule didn't say a trailing `\r` counts | Fixed (wording) |
| 1 | Low F5 (Linux only, unproven): a `.gpt` rewritten in place while mapped can crash a reader there (SIGBUS); on this Mac the mapping kept the old contents | Documented in `tilefile.h` and DESIGN §9.3: replace an open `.gpt` only by renaming a new file over it, as `build` does. Listed under "Not verified" |
| 1 | Test gap TG1: x and y swapped in `info`'s bounds passed (every test file spanned the whole world) | Fixed: the `info` test uses points away from the world's corners. Caught (T16) |
| 1 | Test gap TG2: 1–7 junk bytes after the last point were never tested | Fixed: a unit case one byte over and `broken_tail.gpt`. Caught (T14) |
| 1 | Test gap TG3: the `low > high` guard was never exercised | Fixed: the test now uses a range whose two searches land 20 codes apart. Caught (T15) |
| 1 | Notes: `make check` takes ~10 s, the TESTING §12.2 budget · PROGRESS's open-decisions table still listed the applied wording | PROGRESS fixed. The time budget is raised in step 9's report |
| 2 | F1 partly fixed: an option typed after the file (`count good.gpt --zoom 10 843 388`) still named `388` | Fixed: the first argument that looks like an option is named, wherever it is (`first_option`). Caught (T18) |
| 2 | Low N1: the "never grows with the zoom" rule had no test of its own | Already fixed by Codex round 2's case (T17) |
| 2 | Low N2: after the TG1 change, no `info` test at the world's edge (an overflow there would print east as −180) | Fixed: `test_info_at_the_edges_of_the_world` expects `-180.000000,-85.051129,180.000000,85.051129`. Caught (T19) |
| 2 | Checked fine: `finish_output` (also under a 0-byte file limit), the command table, `stats_possible` ("can't refuse a file `build` really writes"), the DESIGN wording | — |

Left for the developer to decide: none.

## Proof the tests catch bugs

Each break in a fresh scratch copy, `make check`:

| # | Deliberate break | Tests that failed |
|---|---|---|
| T1 | binary search `<` → `<=` (stops after equal codes) | `a_code_range_includes…`, `a_tile_count_is_the_slow_count…` |
| T2 | a slice drops its last code | `a_code_range_includes_both_ends…` |
| T3 | x and y swapped in the tile's code | `a_tile_count_is_the_slow_count…` |
| T4 | the count × 8 overflow guard removed | `broken_files_are_refused…` (2^61 + 3 points accepted) |
| T5 | version not checked | `broken_files_are_refused…` |
| T6 | min y read from max x's offset | `broken_files_are_refused…` (header read-back) |
| T7 | named pipe opened without `O_NONBLOCK` | e2e `test_broken_gpt_files…` (hangs, then times out) |
| T8 | `info` prints south and north swapped | e2e `test_info_prints_the_header…` |
| T9 | `count` accepts x = 2^zoom | e2e `test_bad_arguments_are_a_usage_error` |
| T10 | an unfinished `.gpt` reported as a wrong version | `broken_files_are_refused…` |
| T11 | a usage error names the extra argument, not the mistyped option (F1 undone) | e2e `test_bad_arguments_are_a_usage_error` |
| T12 | a lost result still exits 0 (F2 undone) | e2e `test_a_result_that_cannot_be_written_is_an_error` |
| T13 | header stats not checked (F3 undone) | `broken_files_are_refused…` |
| T14 | size check "simplified" to `count != (size − 256) / 8` | `broken_files_are_refused…` (one junk byte accepted) |
| T15 | the `low > high` guard removed | `a_code_range_includes_both_ends…` |
| T16 | `info` prints the bounds with x and y swapped | e2e `test_info_prints_the_header…` |
| T17 | densest pixels allowed to grow with the zoom | `broken_files_are_refused…` |
| T18 | only the first argument checked for a mistyped option | e2e `test_bad_arguments_are_a_usage_error` |
| T19 | `info` prints east from max x + 1 (wraps to −180 at the edge) | e2e `test_info_at_the_edges_of_the_world` |

The code was restored exactly afterwards: yes (every break was in a deleted scratch copy).

## Validate it yourself

| Do this | Expected | Actual (agent's run) |
|---|---|---|
| `build/gpstiles info data/build/tdrive.gpt` | `points=10064891`, bytes, bounds, view, `max_pixel` | as in the output above |
| `build/gpstiles count data/build/tdrive.gpt 10 843 388` | `points=2229964` | `points=2229964` |
| `build/gpstiles count data/build/tdrive.gpt 11 1686 776`, then the same with `11 1687 776`, `11 1686 777`, `11 1687 777` | 4 counts adding up to 2,229,964 | 1,849,140 + 176,409 + 134,194 + 70,221 = 2,229,964 |
| `build/gpstiles count data/build/tdrive.gpt 0 0 0` | `points=10064891` | `points=10064891` |
| `build/gpstiles info data/build/tdrive.pts` (a `.pts`, not a `.gpt`) | refused, exit 1 | `gpstiles info: data/build/tdrive.pts: not a .gpt file (it doesn't start with the GPSTILE label)`, exit 1 |
| `bash tests/validate/step-3b.sh` | 3 `ok` lines | 3 `ok` |

## Deploy (from step 5b, after approval)

| Command | Smoke test | Rolled back? |
|---|---|---|
| none (deploy starts at step 5b) | | |

## Who did what

| Agent | Did |
|---|---|
| Claude Opus 5.5 (main) | code, tests, Python answers, breaks, validation, DESIGN wording, this file |
| Codex CLI gpt-6-astra (high effort) | review (read-only) |
| Claude Opus 5.5 skeptic (separate agent, own scratch copy) | adversarial review |

## Decisions
- **DESIGN wording applied** (the developer's go-ahead of 2026-10-31 to complete every step; until now these were proposals waiting in step files):
  - §9.3: the `.gpt` header's byte offsets, the pixel rule (top 2(z + 8) bits), the view box rule, "0 points → all stats 0", and which broken files are refused (step 3a proposal).
  - §9.4: World x without "then mod 2^32", which read literally was step 1's round-1 bug (step 1 proposal).
  - §8: the import rules the code and tests already follow: columns from 1, blank lines, the 65,536-byte limit, plain decimals, `--skip` per file, `--delim` (step 2 proposal).
  - TESTING §7: the 1 MB line is made by the test, not stored in `bad_rows.txt` (step 2 proposal).
- **Memory-mapped, not read.** Opening costs no RAM up front, and the OS keeps busy parts in memory for all server threads. Rejected: `pread` per lookup (a system call per binary-search step).
- **Points are trusted to be sorted,** not checked at open: checking costs a full read of the file (16 GB at NYC scale) on every start. An unsorted file gives wrong counts, never a crash.
- **`info` output:** `key=value` lines like `import` and `build`. Degrees to 6 decimals (about 10 cm), boxes as west,south,east,north (the order of the API's `bbox`), `none` for an empty dataset. **`count` prints `points=N`.**
- **Odd files:** a folder, pipe or device → "not a regular file" (pipes opened non-blocking, so a pipe can't hang the command). A `.gpt` left by a killed build (version 0, step 3a) → "an unfinished .gpt … build it again".
- **`tdrive_gpt` in `tests/validate/lib.sh`:** later steps' validation scripts share one T-Drive build in `build/validate/`, made with the current program and remade when the program changes.

## Not verified
- A `.gpt` changed or cut by another program while it is mapped. On this Mac the skeptic found no crash (the mapping kept the old contents); on Linux, reading a page past a new end would crash (SIGBUS). `build` never does this (it writes a new file and renames it); DESIGN §9.3 now says to replace an open `.gpt` only that way.
- Files over 2 GB: only T-Drive (80 MB) and test files were opened. The sizes are 64-bit throughout.
- Big-endian machines (the reads convert explicitly, but only arm64 macOS was run).

## Next
- Step 4: draw a tile. `render` counts each pixel's points in the tile's slice and colors them on a log scale against the header's densest pixel for the zoom.
