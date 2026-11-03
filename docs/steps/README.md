# Step reports

gpstiles was built in 22 small steps over five stages. Each report has the real command output, the bugs planted to prove the tests, and what the reviewers (Codex; from step 3a also a separate Claude agent) found.

| Stage | Step | Built |
|---|---|---|
| 1 · T-Drive, 10 M points | [0a](step-0a.md) | Makefile, C and Python test runners (themselves tested) |
| | [0b](step-0b.md) | `make verify`, pre-commit and Stop hooks, the Codex review script |
| | [1](step-1.md) | Map math: place → Z-order code → tile |
| | [2](step-2.md) | Importer, checked against `awk` on real T-Drive |
| | [3a](step-3a.md) | External merge sort → `.gpt` file |
| | [3b](step-3b.md) | Reading `.gpt`: memory map, binary search, `info` and `count` |
| | [4](step-4.md) | Tile drawing: per-pixel counts, log color scale, PNG |
| | [5a](step-5a.md) | HTTP server: JSON and PNG tiles |
| | [5b](step-5b.md) | macOS background service, smoke test, automatic rollback |
| | [6](step-6.md) | The map page (Leaflet 1.9.4) |
| | [7](step-7.md) | Exact count in any box, and its API |
| | [8](step-8.md) | Streamed CSV export |
| | [9](step-9.md) | Benchmarks, release package, stage 1 report |
| 2 · new formats, worldwide | [10](step-10.md) | GeoLife, 24,876,977 points, with import options only |
| | [11](step-11.md) | USGS earthquakes worldwide, 4,770,607 points, against USGS's own counts |
| 3 · polylines | [12](step-12.md) | Porto taxi trips, 83,409,386 points, against Python's `csv` and `json` |
| 4 · over a billion | [13](step-13.md) | Fast tiles: a world tile in 0.6 ms instead of 164 ms |
| | [14](step-14.md) | NYC taxis 2009–2010, 668,475,278 points, against DuckDB |
| | [15](step-15.md) | NOAA AIS ships, **1,216,355,854 points**, stage 4 report |
| 5 · GPX, world datasets | [16](step-16.md) | GPX reader; OpenStreetMap GPS traces, **2,675,901,374 points**, stage 5 report |
| | [17](step-17.md) | OpenSky aircraft, 56,869,562 points |
| | [18](step-18.md) | GBIF species sightings of 2024, 287,450,825 points, against GBIF's own record count |

## Where the evidence is

- **Bugs planted to prove the tests:** every report's "Proof the tests catch bugs" section. Step 13 shows a planted bug that first slipped through, and the test that was strengthened to catch it.
- **Independent answer sources** (never gpstiles's own output): [TESTING.md §6](../TESTING.md#6-where-expected-answers-come-from).
- **Memory safety and fuzzing:** every step runs its tests under AddressSanitizer and UBSan; step 12's reviewer also fuzzed the importer with 3,000 random files against the Python rules.
- **Billions of points, checked end to end:** steps [15](step-15.md) and [16](step-16.md).

Reports cite `PROGRESS.md` and `PROJECT_IDEAS.md`: the builder's working notes, kept outside the repo.
