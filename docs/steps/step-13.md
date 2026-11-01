# Step 13: Fast tiles

## Summary

| | |
|---|---|
| **Built** | `render_count` without visiting every point: a dense part of a tile is cut into its 4 quarters (each one slice of the sorted file, found by binary search), down to single pixels, whose count is their slice's length. Same pictures; zoomed-out tiles of Porto in 0.6 ms instead of 164 ms |
| **Status** | approved (all-stages go-ahead 2026-11-01) |
| **Date** | 2026-11-01 |
| **Agent(s)** | Claude Opus 5.5 main · Codex reviewer (gpt-6-astra, high effort) · Claude Opus 5.5 skeptic reviewer (separate agent) |

## Design
- **The Z order again:** a tile is one slice of the sorted file, and so are its 4 quarters, their quarters, and so on down to one pixel (the codes of a square share their top bits). `count_cell` takes a square's slice: one pixel → its count is the slice's length; more than 4 points a pixel → 3 binary searches cut it into its quarters, in Z order (0,0), (1,0), (0,1), (1,1), and each is counted the same way; fewer → walked point by point, as before. Empty quarters cost nothing.
- **Cost:** at most about 87,000 squares a tile (65,536 pixels and the squares above them), each with 3 binary searches over its own slice, against 2 ns per point before. It grows with the pixels a tile's points fill, not with the points: a billion points in one tile cost about what 83 million do.
- **The same pictures:** every count is the same number as before (a pixel's slice holds exactly its points), checked byte for byte on 693 tiles of 5 datasets.
- **Nothing else changes:** the file format, `build`, the server and the API.

| Zoom (Porto, 83 million points) | 0 | 5 | 10 | 11 | 13 | 15 | 18 | 24 |
|---|---|---|---|---|---|---|---|---|
| step 12, p50 / p99 (ms) | 163 / 164 | 163 / 164 | 164 / 166 | 87 / 88 | 60 / 65 | 8.4 / 23 | 1.7 / 3.4 | 0.53 / 0.56 |
| step 13, p50 / p99 (ms) | 0.54 / 0.56 | 0.67 / 0.73 | 6.4 / 10.3 | 5.5 / 11.1 | 11.0 / 18.5 | 6.3 / 10.6 | 1.7 / 3.2 | 0.53 / 0.55 |

## Files changed

| File | Change | Why |
|---|---|---|
| `src/render.c` | changed | `count_cell` and `first_at_least`; `render_count` uses them |
| `tests/unit/test_render.c` | changed | 1 test: 300 random dense tiles = counting point by point |
| `tests/validate/step-13.sh` | added | the tiles of every dataset here (built when missing) = step 12's drawing, byte for byte; Porto's bench |
| `docs/DESIGN.md`, `docs/TESTING.md` | changed | §5.5 how a tile is counted · §12.6 stage 4's steps and the time decision · §13 NYC's facts · §14 · step 13's row |

## Tests

| Test | Checks | Bug it would catch |
|---|---|---|
| `dense_tiles_count_the_same_as_walking_every_point` (unit) | 600,000 points in clusters of every size (one spot to the whole world, up to 300,000 points each), 300 tiles at random zooms 0–24 under random points: every pixel = counting point by point · an empty tile: all 0 · all 600,000 points in one spot: one pixel holds them all at every zoom | a quarter cut at the wrong code (points in the wrong pixel), quarters swapped, a pixel counted twice or lost |
| the old render tests (unit, `test_render.py`, `check_tdrive.py`) | pixel counts and colors against Python's own counts | anything that changes a picture |
| `step-13.sh` | 2,757 tiles (zoom 0–24) of 11 files: T-Drive, its sample, GeoLife, the earthquakes, Porto (built in `build/validate/` when missing) and `data/build/`'s, with NYC Uber = step 12's drawing, byte for byte · Porto's p99 under 5 ms at zooms 0–5, under 50 ms at 0–13 | a changed picture on real data; drawing point by point again; a slow tile |

```text
unit        38 passed   0 failed
e2e        131 passed   0 failed
ALL PASSED (build)                                    make check
unit        38 passed   0 failed
e2e        131 passed   0 failed
ALL PASSED (build/san)                                make sanitize
check-data: T-Drive (render 11/1686/776: every pixel = Python's counts), GeoLife, USGS, Porto as before
--- tests/validate/step-13.sh
  ok  build/earthquakes.gpt: 333 tiles (zoom 0–24) = step 12's point-by-point drawing, byte for byte
  ok  build/geolife.gpt: 250 tiles … · build/porto.gpt: 205 · build/tdrive-sample.gpt: 242 · build/tdrive.gpt: 243
  ok  data/earthquakes.gpt: 333 · data/geolife.gpt: 250 · data/porto.gpt: 205 · data/tdrive-sample.gpt: 242 · data/tdrive.gpt: 243
  ok  data/uber-nyc-2014.gpt: 211 tiles (zoom 0–24) = step 12's point-by-point drawing, byte for byte
  ok  bench porto (83 million points): zoom 0, 5, 10, 13 p50/p99 (ms): 0:0.54/0.57 5:0.66/0.71 10:7.08/7.48 13:12.29/19.19 · worst p99 at zooms 0–13: 19.19 ms (step 12: 164 ms)
VERIFY PASSED (make verify, 19 min 8 s)
```

## Review (Codex)

Run with `CODEX_BIN=<wrapper> tools/review.sh 13` (gpt-6-astra, high reasoning effort). Files in `.review/step-13/`.

| Round | Finding (severity, file:line) | What happened |
|---|---|---|
| 1 | Medium, `step-13.sh:11`: the datasets compared were only the ones already built in `build/validate/`; from an empty folder only Porto was compared, and without Porto nothing | Fixed: every dataset whose raw files are here is built (and kept when unchanged), a missing one is named, and only Porto's timing needs Porto. Run from an empty `build/validate/`: all 5 built and compared, with `data/build/`'s 6 |
| 1 | Low, `test_render.c:218`: the empty tile's check read `counts` in the same expression as the call that clears it (the order isn't fixed in C) | Fixed: two statements; all 65,536 pixels checked |
| 2 | Both fixed · Medium: the new one-spot unit case shifted a 32-bit value by 32 at zoom 0 (undefined; UBSan stopped `make sanitize`, which the builder's `make verify` also hit) | Fixed: the shift is done in 64 bits. `make sanitize`: all passed |

Left for the developer to decide: none.

## Review (Claude skeptic, separate agent)

A second Claude Opus 5.5 agent with a fresh context, in its own copy. It found no pixel-count difference: 4,650 tiles built to break it under the sanitizers (codes at 0 and at `UINT64_MAX`, points on quarter edges, zoom + depth = 31, 4–5 points a code, single points, the world's edges), 25,830 tiles of 5 real datasets in memory, and 813 PNGs against step 12's program, byte for byte. `start + k * quarter` can't wrap; the recursion is at most 9 deep.

| Round | Finding (severity) | What happened |
|---|---|---|
| 1 | Medium: the builder decided "time per point: not stored", which the plan leaves to the developer, and DESIGN said "nothing in stages 4–5 needs one" though the plan names NYC as where it matters most | Kept as the builder's decision (to keep going under "proceed with all stages"), the wording made true: why the plan wanted it, and what reversing it costs, estimated from one month (NYC should import in about 4 minutes and build in about 1; the raw files are kept). **The developer should confirm or reverse it** (`PROGRESS.md`, DESIGN §12.6) |
| 1 | Low: the speed claim is Porto's best case | Fixed: DESIGN §5.5 gives the worst case too (every pixel dense: about 20 ms; the skeptic measured 22 ms for 40 million even points against 81 ms) |
| 1 | Low: `step-13.sh` compared 8 points a file and only `build/validate/`; DESIGN said "every zoom's tiles of every dataset" | Fixed: 16 points a file, `data/build/`'s files too, and DESIGN's row says what is compared |
| 1 | Low: the stages diagram still said NYC 2B+ and billions in stage 5 | Fixed: redrawn (stage 4: fast tiles, NYC 2009–2010, NOAA AIS over a billion) |
| 1 | Low: a stale "Next action" in `PROGRESS.md` | It was already updated in the tree (the skeptic read an older copy) |
| 1 | Test gaps: no splitting at all passes `make check`; a loose speed gate; the edge cases only by chance | Fixed: Porto's p99 at zooms 0–5 must be under 5 ms (walking every point: 164 ms); a unit case with every point in one spot (one pixel holds them all at every zoom). Not done: a unit test that splitting happens (the pictures are the same either way; only time shows it) |
| 2 | L1–L3 fixed; M1 partly · High H1: the same undefined shift as Codex's round 2 (fixed) · Low: DESIGN quoted the plan as "6 pm" (it says "only 8–9 am") and called NYC's import time measured (it was estimated from one month) · Low: the diagram said "Decided" while the text asks the developer · Low: `PROGRESS.md` still said "Then stage 3" · a note: the January 2009 test file seemed 32 points short of DuckDB | Fixed after round 2: the plan's words, "estimated from one month", the diagram redrawn ("builder; developer to confirm"), `PROGRESS.md`'s next action. The note was a misreading: the file holds 27,761,844 points = DuckDB's count |

Left for the developer to decide: **time per point** (above).

**After both second rounds** (the 2-round limit, so no reviewer has seen these): the 64-bit shift (found by both reviewers in round 2, checked by `make sanitize`), DESIGN's wording, the redrawn diagram and `PROGRESS.md`. `make verify` ran after them.

## Proof the tests catch bugs

| # | Break | Caught by |
|---|---|---|
| R1 | each quarter's slice cut one code late (`+ 1`) | unit `dense_tiles_count_the_same_as_walking_every_point` · its first version (200,000 points, never more than a tile's 262,144 before a cut) never cut a tile, so it would have passed: the points were raised to 600,000 and then it failed |
| R2 | the quarters' x and y swapped | the same test |
| R3 | the wrong quarter size (a sixteenth) | the same test |

The code was restored exactly afterwards: yes (every break was made in a deleted scratch copy).

## Validate it yourself

| Do this | Expected | Actual (agent's run) |
|---|---|---|
| `tests/validate/step-13.sh` | 5 `ok` lines (byte for byte), then Porto's bench | as in Tests (37 s) |
| `build/gpstiles bench build/validate/porto.gpt` | zoom 0–5 under 1 ms, 10–13 under 20 ms | the table above |
| http://127.0.0.1:8090/#porto/3/40.0000/-8.0000, zoom out and in | the heat tiles appear at once | after the deploy |

## Deploy (after approval)

After this commit: `GPSTILES_PORT=8090 make deploy` (the `.gpt` files don't change). The results go in `PROGRESS.md`, which goes in with the next commit.

## Who did what

| Agent | Did |
|---|---|
| Claude Opus 5.5 (main) | the drawing, tests, breaks, validation, this report |
| Codex CLI gpt-6-astra (high effort) | review (read-only) |
| Claude Opus 5.5 skeptic (separate agent, own copy) | adversarial review |

## Decisions
- **No precomputed zoom levels** (a pyramid of pixel counts in the file): cutting by binary search gives milliseconds with no format change and no build cost; a pyramid would be needed only if cold disk reads (a file bigger than memory) made the binary searches slow. Stage 4's billion points will show.
- **The threshold, 4 points a pixel:** below it walking is cheaper than 3 binary searches. Not tuned further (any value gives the same pictures).
- **Time per point: not stored** (DESIGN §12.6, §14), decided by the builder to keep going under the developer's "proceed with all stages"; the developer may reverse it.

## Not verified
- Tiles of a file bigger than memory (cold reads from disk): step 15.
- Every tile of every dataset (693 tiles across all zooms were compared, not all of them).

## Next
- Step 14: the NYC taxis 2009–2010 (680 million points).
