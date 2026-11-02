"""make check-data for OpenSky's public state vectors of Monday 2022-06-27 (step 17, DESIGN §12.7): 24 hourly tars of
aircraft positions (LAT 3rd, LON 4th; a row without a position has empty fields and is malformed by DESIGN §8). Light,
so that it runs on every `make verify`: hours 00 and 12 streamed from their tars (`tar -xOf | gunzip`) into `gpstiles
import`, against row_counts.awk on the same stream; hour 00's every code against the Python rules
(tests/oracle/import_rules.py) and the zoom-10 tiles of 2 airports (Frankfurt, Atlanta) in that hour's .gpt against the
points Python finds inside their edges in degrees. The whole day is checked once against awk (DESIGN §13) and built by
tests/validate/step-17.sh. Prints SKIPPED and exits 0 without the data. Needs GPSTILES_BIN. Exit 0 = every check passed."""
import array
import importlib.util
import math
import os
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "raw" / "opensky"
DAY = "2022-06-27"
LON_COL, LAT_COL, SKIP = 4, 3, 1
AIRPORTS = [("Frankfurt airport", 8.57, 50.04), ("Atlanta airport", -84.43, 33.64)]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tests" / "oracle" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


rules = load("import_rules")
osm = load("osm_tile")


def fail(message):
    print(f"check-data FAILED (OpenSky): {message}")
    sys.exit(1)


def gpstiles(*args, stdin=None):
    result = subprocess.run([os.environ["GPSTILES_BIN"], *map(str, args)], capture_output=True, text=True, stdin=stdin)
    if result.returncode != 0:
        fail(f"gpstiles {' '.join(map(str, args))} exited {result.returncode}: {result.stderr.strip()}")
    return result.stdout.strip()


def csv_stream(tar):
    """The hour's CSV, as `tar -xOf TAR '*.csv.gz' | gunzip` sends it: (the gunzip process, the tar process)."""
    untar = subprocess.Popen(["tar", "-xOf", str(tar), "*.csv.gz"], stdout=subprocess.PIPE)
    gunzip = subprocess.Popen(["gunzip"], stdin=untar.stdout, stdout=subprocess.PIPE)
    untar.stdout.close()
    return gunzip, untar


def finished(*processes):
    return all(p.wait() == 0 for p in processes)


def tile_edges(zoom, x, y):
    n = 2 ** zoom
    lat = lambda row: math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * row / n))))
    return x / n * 360 - 180, lat(y + 1), (x + 1) / n * 360 - 180, lat(y)


def main():
    hours = sorted(DATA.glob(f"states_{DAY}-*.csv.tar"))
    if not hours:
        print(f"check-data: SKIPPED (OpenSky): no states_{DAY}-*.csv.tar in {DATA.relative_to(ROOT)}")
        return
    if len(hours) != 24:
        fail(f"expected the 24 hours of {DAY}, found {len(hours)}")
    with tempfile.TemporaryDirectory() as tmp:
        tmp = pathlib.Path(tmp)
        for hour in (hours[0], hours[12]):
            name = hour.name.removesuffix(".csv.tar")
            pts = tmp / f"{name}.pts"
            gunzip, untar = csv_stream(hour)
            ours = gpstiles("import", "--lat-col", LAT_COL, "--lon-col", LON_COL, "--skip", SKIP, "-o", pts, "/dev/stdin",
                            stdin=gunzip.stdout)
            gunzip.stdout.close()
            gunzip2, untar2 = csv_stream(hour)
            awk = subprocess.run(["awk", "-v", f"LON={LON_COL}", "-v", f"LAT={LAT_COL}", "-v", f"SKIP={SKIP}", "-f",
                                  str(ROOT / "tests" / "data" / "row_counts.awk")], stdin=gunzip2.stdout,
                                 capture_output=True, text=True, env={**os.environ, "LC_ALL": "C"})
            gunzip2.stdout.close()
            if not finished(gunzip, untar, gunzip2, untar2) or awk.returncode != 0:
                fail(f"{hour.name}: tar, gunzip or awk failed")
            if ours != awk.stdout.strip():
                fail(f"{hour.name}: counts differ from awk:\n  gpstiles {ours}\n  awk      {awk.stdout.strip()}")
            if "imported=0 " in ours:
                fail(f"{hour.name}: no point imported: {ours}")
            print(f"check-data: OpenSky {name}: {ours} = awk")
            if hour == hours[0]:
                check_first_hour(tmp, hour, name, pts)


def check_first_hour(tmp, hour, name, pts):
    """Every code of the hour = the Python rules; 2 airports' tiles = the points inside their edges in degrees."""
    got = array.array("Q")
    got.frombytes(pts.read_bytes())
    if sys.byteorder == "big":
        got.byteswap()
    tiles = [tuple(map(int, osm.tile(lon, lat, 10).split("/")[1:])) for _, lon, lat in AIRPORTS]
    edges = [tile_edges(10, x, y) for x, y in tiles]
    inside, i = [0] * len(AIRPORTS), 0
    gunzip, untar = csv_stream(hour)  # a line at a time: the hour's CSV is over 300 MB
    for number, line in enumerate(gunzip.stdout):
        if number < SKIP:
            continue
        line = line.rstrip(b"\n")
        kind, code = rules.classify(line, LON_COL, LAT_COL)
        if kind != "point":
            continue
        if i >= len(got) or got[i] != code:
            fail(f"{hour.name}: code {i} differs from the Python rules")
        i += 1
        fields = line.split(b",")
        lon, lat = float(fields[LON_COL - 1]), float(fields[LAT_COL - 1])
        lon = -180.0 if lon == 180.0 else lon
        for p, (w, s, e, n) in enumerate(edges):
            if w <= lon < e and s < lat <= n:
                inside[p] += 1
    if not finished(gunzip, untar):
        fail(f"{hour.name}: tar or gunzip failed")
    if i != len(got):
        fail(f"{hour.name}: the .pts has {len(got)} codes, the Python rules {i}")
    gpt = tmp / "hour.gpt"
    gpstiles("build", "-o", gpt, pts)
    for (airport, _, _), (x, y), want in zip(AIRPORTS, tiles, inside):
        n = int(gpstiles("count", gpt, 10, x, y).removeprefix("points="))
        if n != want or want == 0:
            fail(f"{airport}: tile 10/{x}/{y} holds {n} points of {name}, Python finds {want} inside its edges")
        print(f"check-data: OpenSky {name}, {airport}: tile 10/{x}/{y} holds {n:,} points = Python's points inside its edges")
    print(f"check-data: OpenSky {name}: all {i:,} codes = the Python rules")


if __name__ == "__main__":
    main()
