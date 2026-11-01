"""make check-data for the NYC taxis 2009–2010 (step 14, DESIGN §12.6): 680 million pickup and dropoff points from
TLC's Parquet files, through tools/nyc-taxi.py (DuckDB writes `lon,lat` rows) into `gpstiles import`. The counts against
DESIGN §13 and against DuckDB's own count (SQL, DESIGN §8's place rules, apart from our code). Then `gpstiles build`
with the default --mem (1 GiB: 5.4 GB of points, so several runs): `info` and the zoom-0 tile hold every point,
Manhattan's zoom-10 tile = its 4 zoom-11 tiles = DuckDB's count of the points inside its edges in degrees, and 3 places
(JFK, LaGuardia, Times Square) hold exactly the points DuckDB finds inside their zoom-14 tiles' edges. Needs DuckDB:
run with data/tools/venv/bin/python (the Makefile does). Prints SKIPPED and exits 0 without the data. Needs
GPSTILES_BIN. Exit 0 = every check passed."""
import importlib.util
import math
import os
import pathlib
import subprocess
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "raw" / "nyc-taxi"
DESIGN_13 = ("rows=679794434 imported=668475278 skipped_zero=11315804 skipped_out_of_range=3242 "
             "skipped_malformed=110")
MAX_LAT = 85.05112877980659
PLACES = [("JFK airport", -73.7781, 40.6413), ("LaGuardia airport", -73.8740, 40.7769),
          ("Times Square", -73.9855, 40.7580)]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tests" / "oracle" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


osm = load("osm_tile")


def fail(message):
    print(f"check-data FAILED (NYC): {message}")
    sys.exit(1)


def gpstiles(*args):
    result = subprocess.run([os.environ["GPSTILES_BIN"], *map(str, args)], capture_output=True, text=True)
    if result.returncode != 0:
        fail(f"gpstiles {' '.join(map(str, args))} exited {result.returncode}: {result.stderr.strip()}")
    return result.stdout.strip()


def count(path, zoom, x, y):
    return int(gpstiles("count", path, zoom, x, y).removeprefix("points="))


def tile_edges(zoom, x, y):
    n = 2 ** zoom
    lat = lambda row: math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * row / n))))
    return x / n * 360 - 180, lat(y + 1), (x + 1) / n * 360 - 180, lat(y)


def points_sql(files):
    """Every pickup and dropoff place of the files, as (lon, lat), in DuckDB: the query and its parameters (the paths,
    never pasted into the SQL)."""
    parts, params = [], []
    for path in files:
        names = {c[0] for c in duckdb.sql("DESCRIBE SELECT * FROM read_parquet(?)", params=[path]).fetchall()}
        cols = ("Start_Lon", "Start_Lat", "End_Lon", "End_Lat") if "Start_Lon" in names else \
            ("pickup_longitude", "pickup_latitude", "dropoff_longitude", "dropoff_latitude")
        for lon, lat in (cols[:2], cols[2:]):
            parts.append(f'SELECT "{lon}" AS lon, "{lat}" AS lat FROM read_parquet(?)')
            params.append(path)
    return " UNION ALL ".join(parts), params


def main():
    global duckdb
    files = sorted(str(p) for p in DATA.glob("yellow_tripdata_20[01][09]-*.parquet"))
    if not files:
        print(f"check-data: SKIPPED (NYC): no Parquet files in {DATA.relative_to(ROOT)}")
        return
    try:
        import duckdb
    except ImportError:  # the data is here: the check must run, not pass
        fail("the NYC files are here but this Python has no DuckDB: run with data/tools/venv/bin/python")
    if len(files) != 24:
        fail(f"expected the 24 files of 2009–2010, found {len(files)}")
    duckdb.sql("SET threads TO 2")
    every, params = points_sql(files)
    valid = f"lon IS NOT NULL AND lat IS NOT NULL AND isfinite(lon) AND isfinite(lat)"
    rows, malformed, zero, off = duckdb.sql(f"""SELECT COUNT(*), COUNT(*) FILTER (WHERE NOT ({valid})),
        COUNT(*) FILTER (WHERE {valid} AND lon = 0 AND lat = 0),
        COUNT(*) FILTER (WHERE {valid} AND NOT (lon = 0 AND lat = 0)
                         AND NOT (lon BETWEEN -180 AND 180 AND lat BETWEEN -{MAX_LAT} AND {MAX_LAT}))
        FROM ({every})""", params=params).fetchall()[0]
    theirs = (f"rows={rows} imported={rows - malformed - zero - off} skipped_zero={zero} skipped_out_of_range={off} "
              f"skipped_malformed={malformed}")

    with tempfile.TemporaryDirectory(dir=ROOT / "build") as tmp:  # 5.4 GB: on this disk, not in /tmp
        tmp = pathlib.Path(tmp)
        pts = tmp / "nyc.pts"
        start = time.monotonic()
        convert = subprocess.Popen([sys.executable, "-I", str(ROOT / "tools" / "nyc-taxi.py"), *files],
                                   stdout=subprocess.PIPE)
        result = subprocess.run([os.environ["GPSTILES_BIN"], "import", "--lon-col", "1", "--lat-col", "2", "--skip", "1",
                                 "-o", str(pts), "/dev/stdin"], stdin=convert.stdout, capture_output=True, text=True)
        convert.stdout.close()
        if convert.wait() != 0 or result.returncode != 0:
            fail(f"nyc-taxi.py exited {convert.returncode}, import {result.returncode}: {result.stderr.strip()}")
        ours = result.stdout.strip()
        for name, answer in [("DESIGN §13", DESIGN_13), ("DuckDB", theirs)]:
            if ours != answer:
                fail(f"counts differ from {name}:\n  gpstiles {ours}\n  {name:10} {answer}")
        print(f"check-data: NYC import counts = DESIGN §13 = DuckDB: {ours} ({time.monotonic() - start:.0f} s)")

        gpt = tmp / "nyc.gpt"
        start = time.monotonic()
        built = gpstiles("build", "--tmp", tmp, "-o", gpt, pts)
        if int(built.split("runs=")[1]) < 2:
            fail(f"build of 5.4 GB with a 1 GiB buffer made one run: {built}")
        pts.unlink()
        print(f"check-data: NYC build: {built} ({time.monotonic() - start:.0f} s)")
        points = rows - malformed - zero - off
        info = dict(line.split("=", 1) for line in gpstiles("info", gpt).splitlines())
        if info["points"] != str(points) or count(gpt, 0, 0, 0) != points:
            fail(f"info points={info['points']}, expected {points:,}")

        def inside(zoom, x, y):
            w, s, e, n = tile_edges(zoom, x, y)
            return duckdb.sql(f"""SELECT COUNT(*) FROM ({every}) WHERE {valid} AND NOT (lon = 0 AND lat = 0)
                AND lon >= {w!r} AND lon < {e!r} AND lat > {s!r} AND lat <= {n!r}""", params=params).fetchall()[0][0]

        x, y = map(int, osm.tile(-73.9855, 40.7580, 10).split("/")[1:])
        got = count(gpt, 10, x, y)
        kids = [count(gpt, 11, 2 * x + dx, 2 * y + dy) for dx in (0, 1) for dy in (0, 1)]
        want = inside(10, x, y)
        if got != want or sum(kids) != got:
            fail(f"count 10/{x}/{y} = {got} (its 4 zoom-11 tiles add up to {sum(kids)}), DuckDB finds {want}")
        print(f"check-data: NYC info points={info['points']} = 0/0/0 · count 10/{x}/{y} (Manhattan) = {got:,} = its 4"
              f" zoom-11 tiles = DuckDB's points inside its edges")
        for place, lon, lat in PLACES:
            z, tx, ty = map(int, osm.tile(lon, lat, 14).split("/"))
            got, want = count(gpt, z, tx, ty), inside(z, tx, ty)
            if got != want or want == 0:
                fail(f"{place}: tile {z}/{tx}/{ty} holds {got} points, DuckDB finds {want} inside its edges")
            print(f"check-data: NYC {place}: tile {z}/{tx}/{ty} holds {got:,} points = DuckDB's points inside its edges")


if __name__ == "__main__":
    main()
