"""make check-data for the USGS earthquakes (step 11, DESIGN §12.4): points over the whole world. Every file against
tools/fetch-usgs.py's MANIFEST.txt (its rows = USGS's own count of its period, asked when it was fetched). `gpstiles
import` of all of them: its counts against DESIGN §13 and row_counts.awk, and every code against the Python rules
(tests/oracle/import_rules.py); the rows off the map are the quakes nearer the poles than 85.05112877980659° (counted
here apart). Then `gpstiles build`: `info` and the zoom-0 tile hold every point, the 4 zoom-1 tiles all hold some and
add up, the tiles on both sides of the 180° line = their 4 smaller tiles = a slow count, and places around the
Pacific hold exactly the rows Python finds inside their zoom-5 tile's edges in degrees (OpenStreetMap's formula; a
longitude of 180 is -180, DESIGN §9.4). Prints SKIPPED and exits 0 without the data. Needs GPSTILES_BIN. Exit 0 = every
check passed."""
import array
import hashlib
import importlib.util
import math
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "raw" / "usgs"
# DESIGN §13 holds the 2026-11-01 download. USGS revises its catalog, so another download is checked against awk and the
# Python rules only. SNAPSHOT: that download's files, by content: the SHA-256 of `shasum -a 256 usgs-*.csv`'s output.
DESIGN_13 = "rows=4771181 imported=4770607 skipped_zero=9 skipped_out_of_range=565 skipped_malformed=0"
SNAPSHOT = "2adc72f5357478301bec95b69b1ebb731f05fe23d92f58a6f518aa082d91e375"
LON_COL, LAT_COL, SKIP = 3, 2, 1
# (name, lon, lat): zoom-5 tiles around the Pacific's rim, two of them on either side of the 180° line
PLACES = [("Japan (Tokyo)", 139.69, 35.69), ("Chile (Santiago)", -70.65, -33.45), ("Fiji, west of 180°", 178.0, -18.0),
          ("Tonga, east of 180°", -175.2, -21.1), ("the Aleutians, east of 180°", -175.0, 51.8),
          ("California (San Francisco)", -122.42, 37.77)]
DATELINE = [(3, 0, 4), (3, 7, 4)]  # zoom-3 tiles on the east and west side of the 180° line, at Fiji and Tonga


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tests" / "oracle" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


rules = load("import_rules")
gpt = load("gpt_rules")
osm = load("osm_tile")


def fail(message):
    print(f"check-data FAILED (USGS): {message}")
    sys.exit(1)


def gpstiles(*args):
    result = subprocess.run([os.environ["GPSTILES_BIN"], *map(str, args)], capture_output=True, text=True, cwd=DATA)
    if result.returncode != 0:
        fail(f"gpstiles {' '.join(map(str, args[:8]))} … exited {result.returncode}: {result.stderr.strip()}")
    return result.stdout.strip()


def count(path, zoom, x, y):
    return int(gpstiles("count", path, zoom, x, y).removeprefix("points="))


def tile_edges(zoom, x, y):
    n = 2 ** zoom
    lat = lambda row: math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * row / n))))
    return x / n * 360 - 180, lat(y + 1), (x + 1) / n * 360 - 180, lat(y)


def manifest():
    """MANIFEST.txt's files: name → (rows, USGS's count)."""
    lines = (DATA / "MANIFEST.txt").read_text().splitlines()
    files = {}
    for line in lines[2:]:
        parts = line.split()
        if parts[0] != "total":
            files[parts[0]] = (int(parts[1]), int(parts[2]))
    return files


def main():
    if not (DATA / "MANIFEST.txt").exists():
        print(f"check-data: SKIPPED (USGS): no {(DATA / 'MANIFEST.txt').relative_to(ROOT)} (run tools/fetch-usgs.py)")
        return
    files = manifest()
    names = sorted(p.name for p in DATA.glob("usgs-*.csv"))
    if names != sorted(files):
        fail(f"the .csv files and MANIFEST.txt differ: {sorted(set(names) ^ set(files))[:5]}")
    for name, (rows, usgs) in files.items():
        lines = (DATA / name).read_bytes().count(b"\n") - 1
        if not rows == usgs == lines:
            fail(f"{name}: {lines} rows, MANIFEST.txt says {rows}, USGS counted {usgs}")
    # The files cover the download's dates (MANIFEST.txt's first line) with no gap and no overlap (files of a second
    # download with other dates in the same folder would overlap).
    first = (DATA / "MANIFEST.txt").read_text().splitlines()[0]
    since, until = re.search(r" from (\d{4}-\d\d-\d\d) to (\d{4}-\d\d-\d\d),", first).groups()
    spans = [name.removeprefix("usgs-").removesuffix(".csv").split("_") for name in names]
    if spans[0][0] != since or spans[-1][1] != until or any(a[1] != b[0] for a, b in zip(spans, spans[1:])):
        fail(f"the files don't cover {since} to {until} end to end: {spans[:2]} … {spans[-2:]}")
    total = sum(rows for rows, _ in files.values())
    print(f"check-data: USGS: {len(names)} files, {total:,} rows, each file = USGS's own count of its period")

    with tempfile.TemporaryDirectory() as tmp:
        tmp = pathlib.Path(tmp)
        pts = tmp / "usgs.pts"
        start = time.monotonic()
        ours = gpstiles("import", "--lat-col", LAT_COL, "--lon-col", LON_COL, "--skip", SKIP, "-o", pts, *names)
        seconds = time.monotonic() - start
        awk = subprocess.run(["awk", "-v", f"LON={LON_COL}", "-v", f"LAT={LAT_COL}", "-v", f"SKIP={SKIP}",
                              "-f", str(ROOT / "tests" / "data" / "row_counts.awk"), *names],
                             capture_output=True, text=True, cwd=DATA, env={**os.environ, "LC_ALL": "C"})
        listed = "".join(f"{hashlib.sha256((DATA / name).read_bytes()).hexdigest()}  {name}\n" for name in names)
        snapshot = hashlib.sha256(listed.encode()).hexdigest() == SNAPSHOT
        answers = [("DESIGN §13", DESIGN_13)] if snapshot else []
        if not snapshot:
            print("check-data: USGS: not the 2026-11-01 download of DESIGN §13: checked against awk and Python only")
        for name, answer in answers + [("awk", awk.stdout.strip())]:
            if ours != answer:
                fail(f"counts differ from {name}:\n  gpstiles {ours}\n  {name:8} {answer}")
        if f"rows={total} " not in ours + " ":
            fail(f"import read {ours}, MANIFEST.txt has {total} rows")
        print(f"check-data: USGS import counts = {'DESIGN §13 = ' if snapshot else ''}awk: {ours} ({seconds:.1f} s)")

        # Every code against the Python rules, the rows off the map, and the rows inside each place's tile.
        got = array.array("Q")
        got.frombytes(pts.read_bytes())
        if sys.byteorder == "big":
            got.byteswap()
        tiles = [tuple(map(int, osm.tile(lon, lat, 5).split("/")[1:])) for _, lon, lat in PLACES]
        edges = [tile_edges(5, x, y) for x, y in tiles]
        inside, polar, i = [0] * len(PLACES), [0, 0], 0
        for name in names:
            lines = (DATA / name).read_bytes().split(b"\n")
            if lines[-1] == b"":
                lines.pop()
            for line in lines[SKIP:]:
                kind, code = rules.classify(line, LON_COL, LAT_COL)
                fields = line.split(b",")
                if kind == "out_of_range":
                    lat = float(fields[LAT_COL - 1])
                    if -180 <= float(fields[LON_COL - 1]) <= 180 and abs(lat) > rules.MAX_LAT:
                        polar[lat < 0] += 1
                if kind != "point":
                    continue
                if i >= len(got) or got[i] != code:
                    fail(f"code {i} ({name}) differs from the Python rules")
                i += 1
                lat, lon = float(fields[LAT_COL - 1]), float(fields[LON_COL - 1])
                lon = -180.0 if lon == 180.0 else lon
                for p, (w, s, e, n) in enumerate(edges):
                    if w <= lon < e and s < lat <= n:
                        inside[p] += 1
        if i != len(got):
            fail(f"the .pts has {len(got)} codes, the Python rules {i}")
        off = int(ours.split("skipped_out_of_range=")[1].split()[0])
        if sum(polar) != off:
            fail(f"{off} rows off the map, but {polar[0]} north of 85.05° and {polar[1]} south of -85.05°")
        print(f"check-data: USGS: all {i:,} codes = the Python rules · the {off} rows off the map are the quakes nearer"
              f" the poles than 85.05° ({polar[0]} north, {polar[1]} south)")

        gpt_path = tmp / "usgs.gpt"
        start = time.monotonic()
        built = gpstiles("build", "-o", gpt_path, pts)
        print(f"check-data: USGS build: {built} ({time.monotonic() - start:.1f} s)")
        points = i
        info = dict(line.split("=", 1) for line in gpstiles("info", gpt_path).splitlines())
        quarters = [count(gpt_path, 1, x, y) for x in (0, 1) for y in (0, 1)]
        if info["points"] != str(points) or count(gpt_path, 0, 0, 0) != points or sum(quarters) != points or min(quarters) == 0:
            fail(f"info points={info['points']}, the 4 zoom-1 tiles {quarters}: expected {points:,} in all, some in each")
        for zoom, x, y in DATELINE:
            prefix, shift = gpt.code_of(x, y), 64 - 2 * zoom
            slow = sum(1 for c in got if c >> shift == prefix)
            kids = [count(gpt_path, zoom + 1, 2 * x + dx, 2 * y + dy) for dx in (0, 1) for dy in (0, 1)]
            if count(gpt_path, zoom, x, y) != slow or sum(kids) != slow or slow == 0:
                fail(f"count {zoom}/{x}/{y} = {count(gpt_path, zoom, x, y)}, its 4 tiles {kids}, the slow count {slow}")
        for (place, _, _), (x, y), want in zip(PLACES, tiles, inside):
            got_count = count(gpt_path, 5, x, y)
            if got_count != want or want == 0:
                fail(f"{place}: tile 5/{x}/{y} holds {got_count} points, Python finds {want} rows inside its edges")
        print(f"check-data: USGS info: points={info['points']} = 0/0/0 = its 4 zoom-1 tiles {quarters} · tiles"
              f" {', '.join(f'{z}/{x}/{y}' for z, x, y in DATELINE)} (both sides of 180°) = their 4 smaller tiles = slow counts"
              f" · {len(PLACES)} places around the Pacific = Python's rows inside their tiles' edges · view={info['view']}")


if __name__ == "__main__":
    main()
