"""make check-data for the Porto taxis (step 12, DESIGN §12.5): 1.7 million trips, each a CSV row with its points in a
quoted POLYLINE column. `gpstiles import --polyline 9` of the whole file: its counts against DESIGN §13 and against
Python's own csv and json modules. Every 50th trip again: every code against two readers, tests/oracle/import_rules.py
and csv + json. Then `gpstiles build` with the default --mem and with --mem 256M (several runs): the same file, no run
file left; `info` and the zoom-0 tile hold every point; Porto's zoom-10 tile = its 4 zoom-11 tiles = a slow count; and
3 places in Porto hold exactly the sample's points Python finds inside their zoom-14 tile's edges in degrees. Prints
SKIPPED and exits 0 without the data. Needs GPSTILES_BIN. Exit 0 = every check passed."""
import array
import csv
import importlib.util
import json
import math
import os
import pathlib
import subprocess
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "raw" / "porto" / "train.csv"
DESIGN_13 = ("rows=1710670 points=83409386 imported=83409386 skipped_zero=0 skipped_out_of_range=0 "
             "skipped_malformed=0")
POINTS = 83409386
PLACES = [("Avenida dos Aliados", -8.6110, 41.1496), ("Porto airport", -8.6814, 41.2481),
          ("Campanhã station", -8.5855, 41.1486)]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tests" / "oracle" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


rules = load("import_rules")
gpt = load("gpt_rules")
osm = load("osm_tile")


def fail(message):
    print(f"check-data FAILED (Porto): {message}")
    sys.exit(1)


def gpstiles(*args):
    result = subprocess.run([os.environ["GPSTILES_BIN"], *map(str, args)], capture_output=True, text=True)
    if result.returncode != 0:
        fail(f"gpstiles {' '.join(map(str, args))} exited {result.returncode}: {result.stderr.strip()}")
    return result.stdout.strip()


def count(path, zoom, x, y):
    return int(gpstiles("count", path, zoom, x, y).removeprefix("points="))


def read_codes(path):
    codes = array.array("Q")
    codes.frombytes(pathlib.Path(path).read_bytes())
    if sys.byteorder == "big":
        codes.byteswap()
    return codes


def stream_codes(path, chunk=1 << 20):
    with open(path, "rb") as f:
        while data := f.read(8 * chunk):
            codes = array.array("Q")
            codes.frombytes(data)
            if sys.byteorder == "big":
                codes.byteswap()
            yield from codes


def tile_edges(zoom, x, y):
    n = 2 ** zoom
    lat = lambda row: math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * row / n))))
    return x / n * 360 - 180, lat(y + 1), (x + 1) / n * 360 - 180, lat(y)


def python_counts(path):
    """Python's own reading: the csv module for the quotes, json for the list, DESIGN §8's place rules per pair."""
    counts = dict(rows=0, points=0, imported=0, skipped_zero=0, skipped_out_of_range=0, skipped_malformed=0)
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        column = next(reader).index("POLYLINE")
        for row in reader:
            counts["rows"] += 1
            try:
                pairs = json.loads(row[column])
                assert all(len(p) == 2 for p in pairs)
            except (ValueError, AssertionError, IndexError, TypeError):
                counts["skipped_malformed"] += 1
                continue
            for lon, lat in pairs:
                counts["points"] += 1
                if lon == 0 and lat == 0:
                    counts["skipped_zero"] += 1
                elif not (-180 <= lon <= 180 and -rules.MAX_LAT <= lat <= rules.MAX_LAT):
                    counts["skipped_out_of_range"] += 1
                else:
                    counts["imported"] += 1
    return rules.polyline_counts_line(counts)


def check_sample(tmp):
    """Every 50th trip: codes = both Python readers; the places' tiles = the rows inside their edges."""
    sample = tmp / "sample.csv"
    with open(DATA, "rb") as src, open(sample, "wb") as dst:
        for i, line in enumerate(src):
            if i == 0 or i % 50 == 0:
                dst.write(line)
    pts = tmp / "sample.pts"
    ours = gpstiles("import", "--polyline", 9, "--skip", 1, "-o", pts, sample)
    counts, want = rules.polyline_files([sample], 9, skip=1)
    got = read_codes(pts)
    if ours != rules.polyline_counts_line(counts) or list(got) != want:
        fail(f"the sample differs from the Python rules:\n  gpstiles {ours}\n  Python   {rules.polyline_counts_line(counts)}")
    tiles = [tuple(map(int, osm.tile(lon, lat, 14).split("/")[1:])) for _, lon, lat in PLACES]
    edges = [tile_edges(14, x, y) for x, y in tiles]
    inside, json_codes = [0] * len(PLACES), []
    with open(sample, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        next(reader)
        for row in reader:
            for lon, lat in json.loads(row[8]):
                json_codes.append(rules.code(lon, lat))
                for p, (w, s, e, n) in enumerate(edges):
                    if w <= lon < e and s < lat <= n:
                        inside[p] += 1
    if json_codes != want:
        fail("the sample's codes from csv + json differ from the Python rules' reader")
    print(f"check-data: Porto sample (every 50th trip): {ours} = the Python rules = csv + json, every code")
    gpt_path = tmp / "sample.gpt"
    gpstiles("build", "-o", gpt_path, pts)
    for (place, _, _), (x, y), n in zip(PLACES, tiles, inside):
        got_count = count(gpt_path, 14, x, y)
        if got_count != n or n == 0:
            fail(f"{place}: tile 14/{x}/{y} holds {got_count} sample points, Python finds {n} inside its edges")
        print(f"check-data: {place}: tile 14/{x}/{y} holds {got_count:,} sample points = Python's points inside its edges")


def main():
    if not DATA.exists():
        print(f"check-data: SKIPPED (Porto): no {DATA.relative_to(ROOT)}")
        return
    with tempfile.TemporaryDirectory() as tmp:
        tmp = pathlib.Path(tmp)
        pts = tmp / "porto.pts"
        start = time.monotonic()
        ours = gpstiles("import", "--polyline", 9, "--skip", 1, "-o", pts, DATA)
        seconds = time.monotonic() - start
        theirs = python_counts(DATA)
        for name, answer in [("DESIGN §13", DESIGN_13), ("csv + json", theirs)]:
            if ours != answer:
                fail(f"counts differ from {name}:\n  gpstiles {ours}\n  {name:10} {answer}")
        print(f"check-data: Porto import counts = DESIGN §13 = csv + json: {ours} ({seconds:.1f} s)")

        check_sample(tmp)

        (tmp / "runs").mkdir()
        built = {}
        for name, extra in [("default", ()), ("256M", ("--mem", "256M", "--tmp", tmp / "runs"))]:
            start = time.monotonic()
            out = gpstiles("build", *extra, "-o", tmp / f"{name}.gpt", pts)
            built[name] = time.monotonic() - start
            runs = int(out.split("runs=")[1])
            if (name == "256M") != (runs > 1):
                fail(f"build --mem {name} made {runs} runs: 256M must sort in several, the default in one")
            print(f"check-data: Porto build --mem {name}: {out} ({built[name]:.1f} s)")
        if os.listdir(tmp / "runs"):
            fail(f"run files left: {os.listdir(tmp / 'runs')}")
        if subprocess.run(["cmp", "-s", tmp / "default.gpt", tmp / "256M.gpt"]).returncode != 0:
            fail("the default and --mem 256M builds differ")
        path = tmp / "default.gpt"
        info = dict(line.split("=", 1) for line in gpstiles("info", path).splitlines())
        if info["points"] != str(POINTS) or count(path, 0, 0, 0) != POINTS:
            fail(f"info says points={info['points']}, expected {POINTS:,}")
        x, y = map(int, osm.tile(-8.61, 41.15, 10).split("/")[1:])
        prefix = gpt.code_of(x, y)
        slow, kids = 0, {}
        for c in stream_codes(pts):
            if c >> 44 == prefix:
                slow += 1
                kids[c >> 42] = kids.get(c >> 42, 0) + 1
        got = count(path, 10, x, y)
        children = [count(path, 11, 2 * x + dx, 2 * y + dy) for dx in (0, 1) for dy in (0, 1)]
        want = [kids.get(gpt.code_of(2 * x + dx, 2 * y + dy), 0) for dx in (0, 1) for dy in (0, 1)]
        if got != slow or children != want or sum(children) != got:
            fail(f"count 10/{x}/{y} = {got} (4 zoom-11 tiles {children}), slow count {slow} ({want})")
        print(f"check-data: Porto: the two builds are identical, no run file left · info points={info['points']} = 0/0/0"
              f" · count 10/{x}/{y} (Porto) = {got:,} = slow count = its 4 zoom-11 tiles · view={info['view']}")


if __name__ == "__main__":
    main()
