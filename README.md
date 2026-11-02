# gpstiles

**Turn millions to billions of GPS points into a fast, zoomable heat map in your browser, on a laptop, with one small C program and one file per dataset.**

![2.7 billion GPS points from OpenStreetMap's public traces, the whole world at zoom 2: Europe brightest, every continent's roads, flight paths across the oceans](docs/images/readme-world-gps.jpg)
<sub>OpenStreetMap's public GPS traces of 2013: **2,675,901,374 points** in one 21 GB file. Every tile on this screen came back in milliseconds.</sub>

## In 30 seconds

| | |
|---|---|
| **What it is** | A tile server for point data. You give it a list of places (longitude, latitude), it gives you an interactive heat map, exact counts for any area, and the points back as CSV |
| **What it isn't** | Not a database, not a GIS, not a cloud service. No PostGIS, no Python stack, no GPU: one 300 KB program (C11 + zlib) that runs on your Mac |
| **How big** | Tested on 9 real datasets, from 4.5 million to **2.7 billion** points. Any map tile at any zoom: tens of milliseconds at most, usually a few |
| **How** | It stores every point as a 64-bit [Z-order code](#the-key-idea-z-order) and sorts them once. Then every map tile, at every zoom, is one contiguous slice of the file, found with two binary searches |
| **Does the repo include data?** | **No.** [Datasets](#datasets-what-the-repo-includes-and-what-you-download) are downloaded by you, when you want them. The tests use tiny files that come with the repo |

<table>
<tr>
<td width="50%"><img src="docs/images/readme-ships.jpg" alt="NOAA AIS ship positions in the Gulf of Mexico: shipping lanes and ports"><br><sub><b>Ships:</b> 1.2 billion AIS positions, Jan–May 2023 (NOAA). Shipping lanes, ports and the busy waters off Louisiana</sub></td>
<td width="50%"><img src="docs/images/readme-flights.jpg" alt="One day of aircraft positions from OpenSky: dense over the US and Europe"><br><sub><b>Flights:</b> 57 million aircraft positions in one day (OpenSky). Dense where OpenSky has receivers: the US and Europe</sub></td>
</tr>
<tr>
<td width="50%"><img src="docs/images/readme-earthquakes.jpg" alt="4.8 million earthquakes since 1900: the Pacific Ring of Fire"><br><sub><b>Earthquakes:</b> 4.8 million since 1900 (USGS). The plate boundaries draw themselves</sub></td>
<td width="50%"><img src="docs/images/readme-nyc-street.jpg" alt="New York taxi pickups and dropoffs at street level around Times Square"><br><sub><b>Taxis:</b> 668 million NYC pickups and dropoffs, at street level near Times Square. No base map: the taxis draw the streets</sub></td>
</tr>
</table>

## What you can use it for

- **See where things happen**: traffic, deliveries, ships, aircraft, people's trips, animal and plant sightings, earthquakes, anything with a longitude and a latitude.
- **Count exactly**: draw a box on the map (or call the API) and get the exact number of points inside, not an estimate.
- **Get the data out**: export the points in any box as CSV, for Excel, Python or a GIS.
- **Build on it**: the same server answers an HTTP API (PNG tiles, JSON counts, CSV), so a web page or a notebook can use it.
- **Check GPS data**: glitches, gaps and outliers stand out on a heat map (a taxi "in the ocean" is one bright dot).
- **Learn how map tiles and spatial indexes work**: [`docs/DESIGN.md`](docs/DESIGN.md) explains each step with pictures.

## Quick start

Needs a Mac and the Xcode command line tools (they bring `cc`, `make` and `zlib`). Nothing else.

### 1. Build and test it: no data, about a minute

```bash
xcode-select --install                     # once, if you haven't
git clone https://github.com/srir84/gps-tile-server.git
cd gps-tile-server
make                                       # builds build/gpstiles
make check                                 # ends with: ALL PASSED (build)
```

### 2. See a real map: 4.5 million Uber pickups in New York, about 2 minutes

The download is 210 MB of plain CSV from FiveThirtyEight's public copy on GitHub (no account).

```bash
mkdir -p data/raw/uber-nyc-2014 data/build
for m in apr may jun jul aug sep; do
  curl -fL -o "data/raw/uber-nyc-2014/uber-raw-data-${m}14.csv" \
    "https://raw.githubusercontent.com/fivethirtyeight/uber-tlc-foil-response/master/uber-trip-data/uber-raw-data-${m}14.csv"
done
build/gpstiles import --lat-col 2 --lon-col 3 --skip 1 -o data/build/uber.pts data/raw/uber-nyc-2014/*.csv
build/gpstiles build -o data/build/uber.gpt data/build/uber.pts
build/gpstiles serve data/build/uber.gpt   # then open http://127.0.0.1:8080
```

`import` prints `rows=4534327 imported=4534327 skipped_zero=0 skipped_out_of_range=0 skipped_malformed=0`, `build` prints `points=4534327 runs=1`. Open the address, zoom into Manhattan, hover for counts, click **Draw a box**.

### 3. Your own data

Any text file with a longitude and a latitude column works. Columns count from 1.

```bash
build/gpstiles import --lon-col 3 --lat-col 4 --skip 1 -o mine.pts my-points.csv   # --delim tab for TSV
build/gpstiles import --gpx -o tracks.pts *.gpx                                     # GPS tracks (GPX)
build/gpstiles build -o mine.gpt mine.pts tracks.pts                                # several .pts into one map
build/gpstiles serve mine.gpt
```

`import` also reads a pipe (`/dev/stdin`), so zipped or compressed data never has to be unpacked to disk: `unzip -p big.zip | build/gpstiles import ... /dev/stdin`. It prints how many rows it kept and why it skipped the rest (at 0,0, off the map, not a number).

## Datasets: what the repo includes and what you download

**The repo contains no datasets.** It holds the program, its tests and its docs (about 8 MB). The test suite (`make check`) runs on tiny files in [`tests/fixtures/`](tests/fixtures) (a few KB each). **Nothing is downloaded automatically**: `make`, `make check` and the other build commands never touch the network.

When you want a real dataset, you download it yourself, into `data/raw/` (git ignores `data/`). For some there is a script in [`tools/`](tools) that downloads and checks it when **you** run it; for the others you download from the publisher's page.

| Dataset | Points | You download | How | Account |
|---|---:|---:|---|---|
| [NYC Uber pickups](https://github.com/fivethirtyeight/uber-tlc-foil-response), Apr–Sep 2014 | 4.5 M | 210 MB | `curl` ([Quick start](#2-see-a-real-map-45-million-uber-pickups-in-new-york-about-2-minutes)) | no |
| [T-Drive](https://www.microsoft.com/en-us/research/publication/t-drive-trajectory-data-sample/), Beijing taxis, one week | 10.1 M | 80 MB | manual: Microsoft Research | no |
| [GeoLife](https://www.microsoft.com/en-us/download/details.aspx?id=52367), 182 people's GPS traces | 24.9 M | 313 MB | manual: Microsoft download centre | no |
| [USGS earthquakes](https://earthquake.usgs.gov/fdsnws/event/1/), 1900–2026, worldwide | 4.8 M | 834 MB | script: `tools/fetch-usgs.py` (about 40 min, checked against USGS's own counts) | no |
| [Porto taxis](https://archive.ics.uci.edu/dataset/339/taxi+service+trajectory+prediction+challenge+ecml+pkdd+2015), one year | 83 M | 534 MB | manual: UCI Machine Learning Repository | no |
| [OpenSky aircraft](https://opensky-network.org/data/scientific), one day (2022-06-27) | 57 M | 3.9 GB | script: `tools/fetch-opensky.py` (6 min, each file checked) | no |
| [NYC yellow taxis](https://www.nyc.gov/site/tlc/about/tlc-trip-record-data.page), 2009–2010 | 668 M | 11 GB | manual: TLC's Parquet files, converted by `tools/nyc-taxi.py` (needs DuckDB) | no |
| [NOAA AIS ships](https://hub.marinecadastre.gov/pages/vesseltraffic), Jan–May 2023 | 1.2 B | 47.6 GB | script: `tools/fetch-ais.sh` (each day checked) | no |
| [OpenStreetMap GPS traces](https://planet.openstreetmap.org/gps/), 2013 | 2.7 B | 22 GB | manual: one `tar.xz` (check its `.md5`) | no |
| [GBIF](https://www.gbif.org/) species sightings, 2024 | – | – | script: `tools/fetch-gbif.py` (GBIF prepares it for you: up to hours) | yes, free |

Each dataset has its own terms: OpenSky's samples are for non-profit research, education and testing; a GBIF download must be cited by the DOI the script prints; OpenStreetMap data is © OpenStreetMap contributors.

<details>
<summary><b>The import command for each dataset</b></summary>

`build` and `serve` are as in the Quick start. Commands run from the repo root; `gpstiles` is `build/gpstiles`. In zsh, use `setopt pipefail` where a line says `set -o pipefail`: if the source of a pipe stops early, only both succeeding keeps the file.

| Dataset | Import |
|---|---|
| T-Drive | unzip into `data/raw/tdrive_txt/`, then `gpstiles import --lon-col 3 --lat-col 4 -o tdrive.pts data/raw/tdrive_txt/*.txt` |
| GeoLife | unzip into `data/raw/geolife/`; from inside `Geolife Trajectories 1.3/Data`: `gpstiles import --lat-col 1 --lon-col 2 --skip 6 -o geolife.pts */Trajectory/*.plt` |
| USGS | `tools/fetch-usgs.py data/raw/usgs`; from inside `data/raw/usgs`: `gpstiles import --lat-col 2 --lon-col 3 --skip 1 -o earthquakes.pts usgs-*.csv` |
| Porto | `train.csv` in `data/raw/porto/`: `gpstiles import --polyline 9 --skip 1 -o porto.pts data/raw/porto/train.csv` (column 9 holds each trip's `[[lon,lat],...]`) |
| OpenSky | `tools/fetch-opensky.py data/raw/opensky 2022-06-27`; for each hour HH: `set -o pipefail; tar -xOf data/raw/opensky/states_2022-06-27-HH.csv.tar '*.csv.gz' \| gunzip \| gpstiles import --lat-col 3 --lon-col 4 --skip 1 -o HH.pts /dev/stdin`; then `build` all 24 `.pts` |
| NYC taxis | Parquet files in `data/raw/nyc-taxi/`; `python3 -m venv data/tools/venv && data/tools/venv/bin/pip install duckdb==2.0.0`; then `set -o pipefail; data/tools/venv/bin/python tools/nyc-taxi.py data/raw/nyc-taxi/*.parquet \| gpstiles import --lon-col 1 --lat-col 2 --skip 1 -o nyc.pts.new /dev/stdin && mv nyc.pts.new nyc.pts` |
| NOAA AIS | `tools/fetch-ais.sh data/raw/ais 2023-01-01 2023-05-31`; per day: `set -o pipefail; unzip -p data/raw/ais/AIS_2023_01_01.zip \| gpstiles import --lat-col 3 --lon-col 4 --skip 1 -o AIS_2023_01_01.pts.new /dev/stdin && mv AIS_2023_01_01.pts.new AIS_2023_01_01.pts`; then `gpstiles build -o ais-2023.gpt AIS_2023_*.pts` |
| OSM traces | `gpx-planet-2013-04-09.tar.xz` in `data/raw/osm-gps/`: `set -o pipefail; xz -dc data/raw/osm-gps/gpx-planet-2013-04-09.tar.xz \| tar -xOf - \| gpstiles import --gpx -o osm-gps.pts.new /dev/stdin && mv osm-gps.pts.new osm-gps.pts` (about 30 min) |
| GBIF | a free login at gbif.org, saved in `~/.config/gpstiles/gbif.netrc` as `machine api.gbif.org login USER password PASS` (`chmod 600`); `tools/fetch-gbif.py data/raw/gbif 2024`; then `set -o pipefail; unzip -p data/raw/gbif/KEY.zip \| gpstiles import --delim tab --lat-col LAT --lon-col LON --skip 1 -o gbif.pts /dev/stdin` (LAT, LON: the columns `decimalLatitude`, `decimalLongitude`) |

With very many files, run the import from inside their folder (shorter names), or import them in batches into several `.pts` files and give them all to `build`.
</details>

## How it works

![How gpstiles works: import turns each point into a code, build sorts the codes into one file, serve reads tiles from it](docs/images/how-it-works.svg)

1. **`import`** reads each row's longitude and latitude and turns the place into one 64-bit number, its Z-order code (below). Rows at (0,0), off the map or not numbers are counted and skipped, never guessed.
2. **`build`** sorts all the codes into one `.gpt` file: a 256-byte header, then the codes in order. It uses an external merge sort, so the data can be far bigger than memory: sort a memory-sized chunk, write it out, repeat, then merge the sorted chunks.
3. **`serve`** maps the `.gpt` file into memory, so the operating system reads only the parts a request touches. For a tile it finds the tile's slice of the file with two binary searches, counts the points in each pixel and paints a PNG. Dense areas are counted by cutting the tile into quarters, not by walking every point, so a tile holding a billion points still takes milliseconds.
4. **The browser** shows the tiles with Leaflet (built into the program) over an OpenStreetMap base map, and asks the server for exact counts and CSV export.

### The key idea: Z-order

Number the squares of the map by walking them in a "Z" pattern, at every zoom level. Each square's number, written in binary, is the path to it: two bits per zoom level, picking one of four quarters. So **all the squares inside any tile share the same first bits, and sit next to each other once the codes are sorted.**

![The Z-order trick: number squares in Z order; every tile's squares share their leading bits, so in the sorted file each tile is one contiguous slice at every zoom](docs/images/zorder-trick.png)

That one sort gives every zoom level for free: the whole world is the whole file, each zoom-1 quarter is one quarter's slice, and so on down to street level.

## Why it's technically interesting

| Idea | What it buys | Measured |
|---|---|---|
| One sorted file per dataset, memory-mapped | No database, no import into a server, nothing to load at start; the OS cache does the caching | ready to serve in 5 ms with 31 GB of files open (3.9 billion points) |
| Z-order codes | Any tile at any zoom = one contiguous slice, found by two binary searches | no per-zoom index or tile cache |
| External merge sort | Data far bigger than the sort buffer | 2.7 billion points (21 GB) sorted with 1 GiB in 20 runs, 4 min 43 s, peak memory 1.08 GB |
| Counting dense squares by quarters | Zoomed-out tiles don't walk every point | Porto's world tile: 164 ms point by point → 0.6 ms |
| Streaming import | Archives are read through pipes, never unpacked | 848,059 GPX files inside a 22 GB `tar.xz`, imported in 27 min |
| Exact answers | Counts and exports are exact, not sampled | box counts match independent tools |
| Small and strict | C11, one dependency (zlib), `-Wall -Wextra -Wconversion -Werror`, tested under AddressSanitizer and UBSan | about 3,100 lines of C; the binary is 300 KB |

**Tested against independent answers, not its own output.** Every dataset's counts were checked against a separate tool: `awk` over the raw files, DuckDB's SQL, Python's XML parser, or the publisher's own count (USGS, OpenStreetMap). Every step also has to prove its tests work: a bug is planted on purpose in a throwaway copy, and a test must catch it. Each step was then reviewed by two independent AI reviewers looking for flaws. [`docs/TESTING.md`](docs/TESTING.md) has the details.

### Speed and size on real data

On an Apple-silicon MacBook (16 cores, 128 GB), with the file in the disk cache. "Worst p99" is the slowest zoom's 99th-percentile time to draw one tile (`gpstiles bench`).

| Dataset | Points | `.gpt` file | Build (1 GiB buffer) | Worst p99, any zoom |
|---|---:|---:|---|---:|
| Porto taxis | 83 M | 0.7 GB | 1 run | 19 ms |
| OpenSky, one day | 57 M | 0.5 GB | 1 run, 38 s with import | 15 ms |
| NYC taxis 2009–2010 | 668 M | 5.3 GB | 5 runs, 97 s | 50 ms |
| NOAA AIS ships | 1.2 B | 9.7 GB | 10 runs, 149 s | 20 ms |
| OpenStreetMap traces | 2.7 B | 21.4 GB | 20 runs, 283 s | 52 ms |

The first read of a file straight from disk is slower: up to about 0.5 s a tile until the parts in use are cached.

## Reference

### Commands

| Command | Does |
|---|---|
| `gpstiles import (--lon-col C --lat-col C \| --polyline C \| --gpx) [--delim D] [--skip N] -o OUT.pts FILE...` | Text rows → `.pts`; prints what was kept and skipped. `--polyline C`: column C holds a list of `[lon,lat]` pairs; `--gpx`: GPX track points |
| `gpstiles build [--mem 1G] [--tmp DIR] -o OUT.gpt IN.pts...` | Sorts the points into one `.gpt` file; `--mem` sets the sort buffer |
| `gpstiles serve [--host 127.0.0.1] [--port 8080] [--timeout 10] FILE.gpt...` | The map and the API for up to 32 datasets; `--port 0` picks a free port |
| `gpstiles info FILE.gpt` | Point count, file size, bounds, start view, densest pixel per zoom |
| `gpstiles count FILE.gpt Z X Y` | Points in one map tile |
| `gpstiles render FILE.gpt Z X Y -o tile.png` | Draws one tile to a PNG |
| `gpstiles where LON LAT --zoom Z` | The tile `Z/X/Y` containing a place |
| `gpstiles bench FILE.gpt` | Tile drawing speed at each zoom (p50/p99 in ms) |

### HTTP API

Read-only. A dataset's id is its file name without `.gpt` (1 to 32 of `a-z 0-9 - _`). A box is `bbox=west,south,east,north` in degrees, edges included.

| Request | Returns |
|---|---|
| `GET /api/datasets` | JSON: every dataset's id, points, bounds, start view, densest pixel per zoom |
| `GET /api/datasets/{id}` | JSON: one dataset |
| `GET /api/datasets/{id}/count?bbox=w,s,e,n` | JSON `{"id": ..., "count": N}`: the exact points in the box |
| `GET /api/datasets/{id}/export.csv?bbox=w,s,e,n&limit=N` | CSV `lon,lat` of the points in the box, at most `limit` rows (1 to 1,000,000); headers `X-Total-Points`, `X-Rows` |
| `GET /tiles/{id}/{z}/{x}/{y}.png` | A 256 × 256 heat-map tile; header `X-Points` |

```bash
curl 'http://127.0.0.1:8080/api/datasets/uber/count?bbox=-73.83,40.62,-73.74,40.67'   # points around JFK
```

<details>
<summary><b>Run it as a background service on your Mac</b></summary>

| Command | Does |
|---|---|
| `make deploy` | Builds, tests, installs to `~/.local/gpstiles/`, starts the service (again at login), smoke-tests it, and goes back to the previous version if that fails |
| `make status` | Is it running, which version, does it answer |
| `make rollback` | Back to the previous version |
| `make undeploy` | Stops the service (files stay in `~/.local/gpstiles/`) |

The datasets it serves are listed in `~/.local/gpstiles/datasets.conf`, one absolute `.gpt` path per line. Write it before the first `make deploy`:

```bash
mkdir -p ~/.local/gpstiles && echo "$PWD/data/build/uber.gpt" > ~/.local/gpstiles/datasets.conf
```

It listens on 127.0.0.1 only (other computers can't reach it), port 8080. For another port: `make undeploy`, then `GPSTILES_PORT=8090 make deploy`, and give later `make` commands the same `GPSTILES_PORT=8090`. Logs: `~/.local/gpstiles/logs/serve.log`.
</details>

<details>
<summary><b>Checks</b></summary>

| Command | Runs | Needs data |
|---|---|---|
| `make check` | Unit, random-input, bad-input and end-to-end tests (seconds) | no |
| `make sanitize` | The same under AddressSanitizer and UndefinedBehaviorSanitizer | no |
| `make check-data` | Each downloaded dataset against `awk`, Python or DuckDB (minutes; a dataset you don't have is SKIPPED) | yes |
| `make verify` | All of the above plus every step's validation script, with screenshots in `build/validate/` (about 40 minutes with every dataset) | yes |
</details>

## Project layout

```text
src/        the program: import, build (external sort), tilefile (reading .gpt), render, area (counts, export), server
www/        the map page (HTML, CSS, JS) and Leaflet 1.9.4, compiled into the program
tools/      download scripts (fetch-usgs.py, fetch-ais.sh, fetch-opensky.py, fetch-gbif.py), nyc-taxi.py, deploy and review scripts
tests/      unit (C), end-to-end (Python), fixtures (tiny data), data checks, per-step validation scripts
docs/       DESIGN.md (how and why, with pictures), TESTING.md, steps/ (what each step built and how it was checked)
```

It was built in 17 small steps over five stages, from 10 million Beijing taxi points to 2.7 billion worldwide. [`PROGRESS.md`](PROGRESS.md) lists every step, and [`docs/steps/`](docs/steps) reports what each one built, how it was tested and what the reviewers found.

## Limits

- **macOS.** The program is portable C, but the build, deploy and data scripts use macOS tools.
- **Places only, no time.** A point is stored as a place; there's no time filter or animation (a deliberate choice: it would change the file format).
- **Local only.** It serves 127.0.0.1, read-only, with no logins. Don't expose it to the internet as is.
- **Base map needs internet.** The OpenStreetMap tiles under the heat map come from the internet; without it the heat map shows on a dark background.

## Licenses

The map page uses [Leaflet](https://leafletjs.com) 1.9.4 (BSD 2-Clause, `www/leaflet/LICENSE`), compiled into the program. Base map tiles: © OpenStreetMap contributors. Datasets keep their publishers' terms (see [Datasets](#datasets-what-the-repo-includes-and-what-you-download)). The license for gpstiles itself is not chosen yet.
