"""make check-data for GeoLife (step 10, DESIGN §12.4), the second file layout: `.plt` files with 6 header lines and
the latitude first. `gpstiles import` of all 18,670 files: its counts against DESIGN §13 and row_counts.awk. Every
10th file again: its counts and every code against the Python rules (tests/oracle/import_rules.py). Then `gpstiles
build` of the whole .pts: `info` and the zoom-0 tile hold every point, and Beijing's zoom-6 tile = its 4 zoom-7 tiles
added up = a slow count over every code. Last, places GeoLife's people went to: each one's zoom-11 tile in the
sample's .gpt holds exactly the sample rows Python finds inside the tile's edges in degrees (OpenStreetMap's formula,
tests/oracle/osm_tile.py). Prints SKIPPED and exits 0 without the data. Needs GPSTILES_BIN. Exit 0 = every check passed."""
import array
import importlib.util
import math
import os
import pathlib
import subprocess
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "raw" / "geolife" / "Geolife Trajectories 1.3" / "Data"
DESIGN_13 = "rows=24876978 imported=24876977 skipped_zero=0 skipped_out_of_range=1 skipped_malformed=0"
FILES, POINTS = 18670, 24876977
LON_COL, LAT_COL, SKIP = 2, 1, 6
BEIJING_Z6 = (52, 24)  # the zoom-6 tile around Beijing (`gpstiles where 116.4 39.9 --zoom 6`)
PLACES = [("Zhongguancun, Beijing (Microsoft Research Asia)", 116.3100, 39.9800),
          ("Bellevue, near Microsoft in Redmond", -122.0800, 47.5770),
          ("San Diego", -117.1580, 32.7690),
          ("Nice, France", 7.2950, 43.6440)]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tests" / "oracle" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


rules = load("import_rules")
gpt = load("gpt_rules")
osm = load("osm_tile")


def fail(message):
    print(f"check-data FAILED (GeoLife): {message}")
    sys.exit(1)


def gpstiles(*args):
    # Run inside DATA, with the file names relative to it: 18,670 full paths would pass the argument size limit.
    result = subprocess.run([os.environ["GPSTILES_BIN"], *map(str, args)], capture_output=True, text=True, cwd=DATA)
    if result.returncode != 0:
        fail(f"gpstiles {' '.join(map(str, args[:8]))} … exited {result.returncode}: {result.stderr.strip()}")
    return result.stdout.strip()


def gpstiles_import(out, files):
    return gpstiles("import", "--lat-col", LAT_COL, "--lon-col", LON_COL, "--skip", SKIP, "-o", out, *files)


def count(path, zoom, x, y):
    return int(gpstiles("count", path, zoom, x, y).removeprefix("points="))


def read_codes(path):
    codes = array.array("Q")
    codes.frombytes(pathlib.Path(path).read_bytes())
    if sys.byteorder == "big":
        codes.byteswap()
    return codes


def stream_codes(path, chunk=1 << 20):
    """The codes of a .pts or of a .gpt's points, a chunk at a time: the whole file never sits in memory."""
    with open(path, "rb") as f:
        while data := f.read(8 * chunk):
            codes = array.array("Q")
            codes.frombytes(data)
            if sys.byteorder == "big":
                codes.byteswap()
            yield from codes


def tile_edges(zoom, x, y):
    """A tile's edges in degrees (OpenStreetMap's formula): west, south, east, north."""
    n = 2 ** zoom
    lat = lambda row: math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * row / n))))
    return x / n * 360 - 180, lat(y + 1), (x + 1) / n * 360 - 180, lat(y)


def check_sample(tmp, files):
    """Every 10th file: counts and codes = the Python rules, and the rows inside each place's tile, by degrees."""
    sample = files[::10]
    pts = tmp / "sample.pts"
    ours = gpstiles_import(pts, sample)
    got = read_codes(pts)
    counts = dict(rows=0, imported=0, skipped_zero=0, skipped_out_of_range=0, skipped_malformed=0)
    tiles = [tuple(map(int, osm.tile(lon, lat, 11).split("/")[1:])) for _, lon, lat in PLACES]
    edges = [tile_edges(11, x, y) for x, y in tiles]
    inside = [0] * len(PLACES)
    i = 0
    for name in sample:
        lines = (DATA / name).read_bytes().split(b"\n")
        if lines[-1] == b"":
            lines.pop()
        for line in lines[SKIP:]:
            kind, code = rules.classify(line, LON_COL, LAT_COL)
            if kind == "blank":
                continue
            counts["rows"] += 1
            if kind != "point":
                counts["skipped_" + kind] += 1
                continue
            counts["imported"] += 1
            if i >= len(got) or got[i] != code:
                fail(f"code {i} ({name}) differs: gpstiles {got[i] if i < len(got) else None}, Python {code:#018x}")
            i += 1
            fields = line.rstrip(b"\r").split(b",")
            lat, lon = float(fields[LAT_COL - 1]), float(fields[LON_COL - 1])
            for p, (w, s, e, n) in enumerate(edges):
                if w <= lon < e and s < lat <= n:
                    inside[p] += 1
    if ours != rules.counts_line(counts) or i != len(got):
        fail(f"the sample's counts differ:\n  gpstiles {ours}\n  Python   {rules.counts_line(counts)} ({len(got)} codes, {i} checked)")
    print(f"check-data: GeoLife sample (every 10th file, {len(sample):,} files): {ours} = the Python rules, every code too")

    gpt_path = tmp / "sample.gpt"
    gpstiles("build", "-o", gpt_path, pts)
    for (place, _, _), (x, y), want in zip(PLACES, tiles, inside):
        got_count = count(gpt_path, 11, x, y)
        if got_count != want or want == 0:
            fail(f"{place}: tile 11/{x}/{y} holds {got_count} sample points, Python finds {want} rows inside its edges")
        print(f"check-data: {place}: tile 11/{x}/{y} holds {got_count:,} sample points = Python's rows inside its edges")


def main():
    if not DATA.is_dir():
        print(f"check-data: SKIPPED (GeoLife): no {DATA.relative_to(ROOT)}")
        return
    files = sorted(str(p.relative_to(DATA)) for p in DATA.glob("*/Trajectory/*.plt"))
    if len(files) != FILES:
        fail(f"expected {FILES:,} .plt files (DESIGN §13), found {len(files):,}")

    with tempfile.TemporaryDirectory() as tmp:
        tmp = pathlib.Path(tmp)
        pts = tmp / "geolife.pts"
        start = time.monotonic()
        ours = gpstiles_import(pts, files)
        seconds = time.monotonic() - start
        awk = subprocess.run(["awk", "-v", f"LON={LON_COL}", "-v", f"LAT={LAT_COL}", "-v", f"SKIP={SKIP}",
                              "-f", str(ROOT / "tests" / "data" / "row_counts.awk"), *files],
                             capture_output=True, text=True, cwd=DATA, env={**os.environ, "LC_ALL": "C"})
        if awk.returncode != 0:
            fail(f"awk exited {awk.returncode}: {awk.stderr.strip()}")
        for name, answer in [("DESIGN §13", DESIGN_13), ("awk", awk.stdout.strip())]:
            if ours != answer:
                fail(f"counts differ from {name}:\n  gpstiles {ours}\n  {name:8} {answer}")
        print(f"check-data: GeoLife import counts = DESIGN §13 = awk: {ours} ({seconds:.1f} s)")

        check_sample(tmp, files)

        gpt_path = tmp / "geolife.gpt"
        start = time.monotonic()
        built = gpstiles("build", "-o", gpt_path, pts)
        print(f"check-data: GeoLife build: {built} ({time.monotonic() - start:.1f} s)")
        info = dict(line.split("=", 1) for line in gpstiles("info", gpt_path).splitlines())
        if info["points"] != str(POINTS) or int(info["bytes"]) != 256 + 8 * POINTS or count(gpt_path, 0, 0, 0) != POINTS:
            fail(f"info says points={info['points']} bytes={info['bytes']}, 0/0/0 holds {count(gpt_path, 0, 0, 0)}: expected {POINTS:,}")
        x, y = BEIJING_Z6
        prefix = gpt.code_of(x, y)  # the tile's top 12 bits
        slow, children = 0, {}
        for c in stream_codes(pts):
            if c >> 52 == prefix:
                slow += 1
                children[c >> 50] = children.get(c >> 50, 0) + 1
        got = count(gpt_path, 6, x, y)
        kids = [count(gpt_path, 7, 2 * x + dx, 2 * y + dy) for dx in (0, 1) for dy in (0, 1)]
        want_kids = [children.get(gpt.code_of(2 * x + dx, 2 * y + dy), 0) for dx in (0, 1) for dy in (0, 1)]
        if got != slow or kids != want_kids or sum(kids) != got:
            fail(f"count 6/{x}/{y} = {got} (its 4 zoom-7 tiles {kids}), the slow count {slow} ({want_kids})")
        print(f"check-data: GeoLife info: points={info['points']} = 0/0/0 · count 6/{x}/{y} (Beijing) = {got:,}"
              f" = slow count = sum of its 4 zoom-7 tiles · view={info['view']}")


if __name__ == "__main__":
    main()
