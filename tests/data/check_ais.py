"""make check-data for NOAA's AIS ship positions (step 15, DESIGN §12.6), January–May 2023, 151 days and 1.2 billion
points. Light, so that it runs on every `make verify`: the first and last day and 7 April (one row off the map, one
malformed), each streamed from its zip into `gpstiles import`, against row_counts.awk on the same stream; the first day's
every code against the Python rules (tests/oracle/import_rules.py) and 3 ports' zoom-12 tiles in that day's .gpt against
the points Python finds inside their edges in degrees; the 3 days built with --mem 64M (several runs) = built in one. The whole 151 days are checked once against awk (DESIGN §13) and built by
tests/validate/step-15.sh. Prints SKIPPED and exits 0 without the data. Needs GPSTILES_BIN. Exit 0 = every check passed."""
import array
import importlib.util
import math
import os
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "raw" / "ais"
LON_COL, LAT_COL, SKIP = 4, 3, 1
PORTS = [("Houston ship channel", -95.0, 29.73), ("New York harbor", -74.03, 40.66), ("Port of Los Angeles", -118.26, 33.73)]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tests" / "oracle" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


rules = load("import_rules")
osm = load("osm_tile")


def fail(message):
    print(f"check-data FAILED (AIS): {message}")
    sys.exit(1)


def gpstiles(*args, stdin=None):
    result = subprocess.run([os.environ["GPSTILES_BIN"], *map(str, args)], capture_output=True, text=True, stdin=stdin)
    if result.returncode != 0:
        fail(f"gpstiles {' '.join(map(str, args))} exited {result.returncode}: {result.stderr.strip()}")
    return result.stdout.strip()


def unzip(path):
    return subprocess.Popen(["unzip", "-p", str(path)], stdout=subprocess.PIPE)


def tile_edges(zoom, x, y):
    n = 2 ** zoom
    lat = lambda row: math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * row / n))))
    return x / n * 360 - 180, lat(y + 1), (x + 1) / n * 360 - 180, lat(y)


def main():
    days = sorted(DATA.glob("AIS_2023_*.zip"))
    if not days:
        print(f"check-data: SKIPPED (AIS): no zips in {DATA.relative_to(ROOT)}")
        return
    if len(days) != 151:
        fail(f"expected the 151 days of January–May 2023, found {len(days)}")
    with tempfile.TemporaryDirectory() as tmp:
        tmp = pathlib.Path(tmp)
        sample = [days[0], DATA / "AIS_2023_04_07.zip", days[-1]]
        for n, day in enumerate(sample):
            pts = tmp / f"{day.stem}.pts"
            source = unzip(day)
            ours = gpstiles("import", "--lat-col", LAT_COL, "--lon-col", LON_COL, "--skip", SKIP, "-o", pts, "/dev/stdin",
                            stdin=source.stdout)
            source.stdout.close()
            source2 = unzip(day)
            awk = subprocess.run(["awk", "-v", f"LON={LON_COL}", "-v", f"LAT={LAT_COL}", "-v", f"SKIP={SKIP}", "-f",
                                  str(ROOT / "tests" / "data" / "row_counts.awk")], stdin=source2.stdout,
                                 capture_output=True, text=True, env={**os.environ, "LC_ALL": "C"})
            source2.stdout.close()
            if source.wait() != 0 or source2.wait() != 0 or awk.returncode != 0:
                fail(f"{day.name}: unzip or awk failed")
            if ours != awk.stdout.strip():
                fail(f"{day.name}: counts differ from awk:\n  gpstiles {ours}\n  awk      {awk.stdout.strip()}")
            print(f"check-data: AIS {day.stem}: {ours} = awk")
            if n == 0:
                check_first_day(tmp, day, pts)
        # The same points sorted in many runs and in one: the same file (the merge loses or moves nothing).
        (tmp / "runs").mkdir()
        pts = [tmp / f"{day.stem}.pts" for day in sample]
        many = gpstiles("build", "--mem", "64M", "--tmp", tmp / "runs", "-o", tmp / "many.gpt", *pts)
        one = gpstiles("build", "-o", tmp / "one.gpt", *pts)
        if int(many.split("runs=")[1]) < 2 or int(one.split("runs=")[1]) != 1:
            fail(f"--mem 64M: {many}, default: {one}")
        if subprocess.run(["cmp", "-s", tmp / "many.gpt", tmp / "one.gpt"]).returncode != 0:
            fail("the 3 days built in many runs differ from the same built in one")
        print(f"check-data: AIS 3 days built with --mem 64M ({many}) = built in one run, byte for byte")


def check_first_day(tmp, day, pts):
    """Every code of the day = the Python rules; 3 ports' tiles = the points inside their edges in degrees."""
    got = array.array("Q")
    got.frombytes(pts.read_bytes())
    if sys.byteorder == "big":
        got.byteswap()
    tiles = [tuple(map(int, osm.tile(lon, lat, 12).split("/")[1:])) for _, lon, lat in PORTS]
    edges = [tile_edges(12, x, y) for x, y in tiles]
    inside, i = [0] * len(PORTS), 0
    source = unzip(day)  # read a line at a time: the day's CSV is 877 MB
    for number, line in enumerate(source.stdout):
        if number < SKIP:
            continue
        line = line.rstrip(b"\n")
        kind, code = rules.classify(line, LON_COL, LAT_COL)
        if kind != "point":
            continue
        if i >= len(got) or got[i] != code:
            fail(f"{day.name}: code {i} differs from the Python rules")
        i += 1
        fields = line.split(b",")
        lon, lat = float(fields[LON_COL - 1]), float(fields[LAT_COL - 1])
        lon = -180.0 if lon == 180.0 else lon
        for p, (w, s, e, n) in enumerate(edges):
            if w <= lon < e and s < lat <= n:
                inside[p] += 1
    if source.wait() != 0:
        fail(f"{day.name}: unzip failed")
    if i != len(got):
        fail(f"{day.name}: the .pts has {len(got)} codes, the Python rules {i}")
    gpt = tmp / "day.gpt"
    gpstiles("build", "-o", gpt, pts)
    for (port, _, _), (x, y), want in zip(PORTS, tiles, inside):
        n = int(gpstiles("count", gpt, 12, x, y).removeprefix("points="))
        if n != want or want == 0:
            fail(f"{port}: tile 12/{x}/{y} holds {n} points of {day.stem}, Python finds {want} inside its edges")
        print(f"check-data: AIS {day.stem}, {port}: tile 12/{x}/{y} holds {n:,} points = Python's points inside its edges")
    print(f"check-data: AIS {day.stem}: all {i:,} codes = the Python rules")


if __name__ == "__main__":
    main()
