# gpstiles

Turns millions of GPS points into an interactive heat map in your browser, served by one small C program from one file per dataset. First dataset: T-Drive, 10 million Beijing taxi points.

![The map page: T-Drive at zoom 11, a box drawn around Capital Airport with its exact count and Export link, the points under the mouse](docs/images/stage-1-page.jpg)

## What you can do

| You want to | Do |
|---|---|
| See where points are dense | Open the map, pan and zoom from the whole world down to street level |
| Count the points in an area | Click **Draw a box**, drag on the map: the exact count appears |
| Know how many points are under the mouse | Hover: the count for that pixel shows in the panel |
| Get the points out | Draw a box, click **Export CSV**: `lon,lat` rows for Excel, Python or GIS (up to 1,000,000) |
| Use it from a script | Call the same API (below) |

## Quick start: from the release package (macOS, Apple silicon)

The package (`gpstiles-VERSION-macos-arm64.tar.gz`) holds the program (built for macOS 13 or later), this README and Leaflet's license (`LEAFLET-LICENSE`). It needs no other software: the map page is inside the program. The base map under the heat comes from OpenStreetMap, so it needs internet; without it the heat map shows on a plain dark background.

```bash
shasum -a 256 -c gpstiles-0.1.0-macos-arm64.tar.gz.sha256   # in the folder with both files: "OK"
tar -xzf gpstiles-0.1.0-macos-arm64.tar.gz && cd gpstiles-0.1.0-macos-arm64
printf 'lon,lat\n116.39,39.90\n116.40,39.91\n116.41,39.92\n' > points.csv   # or your own file
./gpstiles import --lon-col 1 --lat-col 2 --skip 1 -o points.pts points.csv
./gpstiles build -o points.gpt points.pts
./gpstiles serve points.gpt                                    # then open http://127.0.0.1:8080
```

The program is not signed with a Developer ID or notarized. If macOS refuses to open a copy that came from a browser download, `xattr -d com.apple.quarantine gpstiles` lets it run.

## Quick start: from source, with T-Drive (macOS)

Needs the Xcode command line tools (`xcode-select --install`), which bring `cc`, `make` and `zlib`. The first dataset is T-Drive, Microsoft Research's "T-Drive trajectory data sample": one text file per Beijing taxi, lines `taxi id,date time,longitude,latitude`, unzipped into `data/raw/tdrive_txt/` (8,911 files).

```bash
make                                                     # builds build/gpstiles
mkdir -p data/build
build/gpstiles import --lon-col 3 --lat-col 4 -o data/build/tdrive.pts data/raw/tdrive_txt/*.txt
build/gpstiles build -o data/build/tdrive.gpt data/build/tdrive.pts
build/gpstiles serve data/build/tdrive.gpt               # then open http://127.0.0.1:8080
```

| Step | Prints (T-Drive) | Takes |
|---|---|---|
| `import` | `rows=10088351 imported=10064891 skipped_zero=23357 skipped_out_of_range=103 skipped_malformed=0` | ~2 s (files already in the disk cache) |
| `build` | `points=10064891 runs=1` | ~1 s |
| `serve` | `gpstiles serve: http://127.0.0.1:8080/` | until you press Ctrl-C |

Your own data: any text file with a longitude and a latitude column. `--lon-col` and `--lat-col` count columns from 1, `--delim tab` reads TSV, `--skip 1` skips a header line in each file.

## More datasets (stage 2)

Any CSV-like file works: name the longitude and latitude columns (counted from 1) and the header lines to skip in each file.

| Dataset | Get it | Import (`build` and `serve` as above) |
|---|---|---|
| GeoLife: 182 people's GPS traces, mostly Beijing (24.9 million points) | `Geolife Trajectories 1.3.zip` from Microsoft's download centre (no account), unzipped into `data/raw/geolife/` | from inside `data/raw/geolife/Geolife Trajectories 1.3/Data`: `gpstiles import --lat-col 1 --lon-col 2 --skip 6 -o geolife.pts */Trajectory/*.plt` |
| USGS earthquakes since 1900, worldwide (4.8 million) | `tools/fetch-usgs.py data/raw/usgs` (USGS's own service, no account; about 40 minutes; each year checked against USGS's count) | from inside `data/raw/usgs`: `gpstiles import --lat-col 2 --lon-col 3 --skip 1 -o earthquakes.pts usgs-*.csv` |

With very many files, run the import from inside their folder (shorter names), or import them in batches into several `.pts` files and give them all to `build`.

## Commands

| Command | Does |
|---|---|
| `gpstiles import --lon-col C --lat-col C [--delim D] [--skip N] -o OUT.pts FILE...` | Text rows → `.pts`. Prints what was kept and skipped (rows at 0,0, out of range, malformed) |
| `gpstiles build [--mem 1G] [--tmp DIR] -o OUT.gpt IN.pts...` | Sorts the points into one `.gpt` file. Works with more data than memory (`--mem` sets the sort buffer) |
| `gpstiles serve [--host 127.0.0.1] [--port 8080] [--timeout 10] FILE.gpt...` | The map and the API for up to 32 datasets. `--port 0` picks a free port; `--timeout`: seconds a client has to send its request |
| `gpstiles info FILE.gpt` | Point count, file size, bounds, start view, densest pixel per zoom |
| `gpstiles count FILE.gpt Z X Y` | Points in one map tile |
| `gpstiles render FILE.gpt Z X Y -o tile.png` | Draws one tile to a PNG |
| `gpstiles where LON LAT --zoom Z` | The tile `Z/X/Y` containing a place |
| `gpstiles bench FILE.gpt` | How fast tiles are drawn at each zoom (p50/p99 in ms; drawing only, without HTTP) |

## API

All answers are read-only. A dataset's id is its file name without `.gpt`, and must be 1 to 32 of `a-z 0-9 - _` (`serve` refuses `Beijing.gpt` or `t.2008.gpt`; rename the file). A box is `bbox=west,south,east,north` in degrees, edges included.

| Request | Returns |
|---|---|
| `GET /api/datasets` | JSON: every dataset with id, points, bounds, start view, max zoom and the densest pixel per zoom |
| `GET /api/datasets/{id}` | JSON: one dataset |
| `GET /api/datasets/{id}/count?bbox=w,s,e,n` | JSON: `{"id": ..., "count": N}`, the exact number of points in the box |
| `GET /api/datasets/{id}/export.csv?bbox=w,s,e,n&limit=N` | CSV `lon,lat`, one row per point in the box, in file order, at most `limit` rows (1 to 1,000,000; default 1,000,000). Each row is the middle of the point's stored position with 9 decimals, inside the box. Headers `X-Total-Points` (in the box) and `X-Rows` (in the file) |
| `GET /tiles/{id}/{z}/{x}/{y}.png` | A 256 × 256 heat-map tile. Header `X-Points`: the points in it |

```bash
curl 'http://127.0.0.1:8080/api/datasets/tdrive/count?bbox=116.55,40.03,116.65,40.10'
# {"id":"tdrive","count":239864}
```

## Run it as a background service (this Mac only)

| Command | Does |
|---|---|
| `make deploy` | Builds, tests, installs to `~/.local/gpstiles/`, starts the service (starts again at login), smoke-tests it, and goes back to the previous version if the smoke test fails |
| `make status` | Is it running, which version, does it answer |
| `make rollback` | Back to the previous version |
| `make undeploy` | Stops the service and removes it from login (files stay in `~/.local/gpstiles/`) |

The datasets it serves are listed in `~/.local/gpstiles/datasets.conf`, one absolute `.gpt` path per line (`#` starts a comment). Write it before the first `make deploy`, for example:

```bash
mkdir -p ~/.local/gpstiles && echo "$PWD/data/build/tdrive.gpt" > ~/.local/gpstiles/datasets.conf
```

Logs: `~/.local/gpstiles/logs/serve.log`. It listens on 127.0.0.1 only, so other computers can't reach it.

It uses port 8080. If another program needs that port, move the service: `make undeploy`, then `GPSTILES_PORT=8090 make deploy`, and open http://127.0.0.1:8090. Later `make deploy`, `make status` and `make rollback` need the same `GPSTILES_PORT=8090` in front (without it they look at 8080: `status` says "not answering", and `deploy` and `rollback` refuse to move the service).

## Checks

| Command | Runs |
|---|---|
| `make check` | Unit, random-input, bad-input and end-to-end tests (seconds) |
| `make sanitize` | The same under AddressSanitizer + UndefinedBehaviorSanitizer |
| `make check-data` | T-Drive checked against `awk` and Python (needs `data/`, about a minute) |
| `make verify` | All of the above plus every step's validation script |

How it works, step by step: `docs/DESIGN.md`. How it is tested: `docs/TESTING.md`. What each step built and how it was checked: `docs/steps/`.

## Licenses

The map page uses Leaflet 1.9.4 (BSD 2-Clause: `www/leaflet/LICENSE` in the source, `LEAFLET-LICENSE` in the package), compiled into the program. Base map tiles come from OpenStreetMap (© OpenStreetMap contributors). The license for gpstiles itself is not chosen yet.
