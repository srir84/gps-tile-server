"""tools/nyc-taxi.py (step 14): TLC's Parquet files → `lon,lat` rows for `gpstiles import`. Tiny Parquet files made by
DuckDB with the 2009 and 2010 column names and the places DESIGN §8 sorts apart. Needs DuckDB in data/tools/venv
(not part of the program): SKIPPED without it."""
import json
import os
import pathlib
import subprocess
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[2]
VENV_PYTHON = ROOT / "data" / "tools" / "venv" / "bin" / "python"
CONVERTER = ROOT / "tools" / "nyc-taxi.py"

# 8 trips: pickups with every kind of place, dropoffs all on the map (one at 120° E, 10° N). Per file: rows 16, imported 10, (0,0) 1,
# off the map 2 (just past 180, 1e308), malformed 3 (NULL, NaN, infinity).
PICKUPS = ["-73.98, 40.75", "0, 0", "NULL, 40.7", "'NaN'::DOUBLE, 1", "'inf'::DOUBLE, 1",
           "-180, 85.05112877980659", "180.0000001, 0", "1e308, 1"]
MAKE = """
import duckdb, json, sys
out, names, pickups = sys.argv[1], sys.argv[2].split(","), json.loads(sys.argv[3])
# The first dropoff is (120, 10): read the wrong way round it is off the map (latitude 120).
rows = " UNION ALL ".join(f"SELECT {p}, {'120, 10' if i == 0 else f'-73.9 + {i} / 1000, 40.7'}" for i, p in enumerate(pickups))
path = out.replace("'", "''")  # a quote in the path doubled, as SQL wants it (Codex, step 14)
duckdb.sql(f"COPY (SELECT * FROM ({rows}) t({', '.join(names)})) TO '{path}' (FORMAT parquet)")
"""


def make(path, names):
    subprocess.run([str(VENV_PYTHON), "-I", "-c", MAKE, str(path), ",".join(names), json.dumps(PICKUPS)],
                   check=True, capture_output=True, timeout=60)


def convert_and_import(tmp, files):
    convert = subprocess.Popen([str(VENV_PYTHON), "-I", str(CONVERTER), *map(str, files)], stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE)
    result = subprocess.run([os.environ["GPSTILES_BIN"], "import", "--lon-col", "1", "--lat-col", "2", "--skip", "1",
                             "-o", str(pathlib.Path(tmp) / "out.pts"), "/dev/stdin"], stdin=convert.stdout,
                            capture_output=True, text=True, timeout=60)
    convert.stdout.close()
    return convert.wait(timeout=60), convert.stderr.read().decode(), result


def test_the_converter_keeps_every_place_of_both_years():
    """catches: a pickup or dropoff column dropped or swapped, a year's column names not found, a NULL, NaN or infinite place imported, or a file left out (step 14)"""
    if not VENV_PYTHON.exists():
        return "SKIPPED: no DuckDB in data/tools/venv"
    with tempfile.TemporaryDirectory() as tmp:
        y2009, y2010 = pathlib.Path(tmp) / "2009.parquet", pathlib.Path(tmp) / "2010.parquet"
        make(y2009, ["Start_Lon", "Start_Lat", "End_Lon", "End_Lat"])
        make(y2010, ["pickup_longitude", "pickup_latitude", "dropoff_longitude", "dropoff_latitude"])
        status, error, result = convert_and_import(tmp, [y2009, y2010])
        assert status == 0 and result.returncode == 0, (status, error, result)
        assert result.stdout == "rows=32 imported=20 skipped_zero=2 skipped_out_of_range=4 skipped_malformed=6\n", result.stdout


def test_the_converter_refuses_a_file_and_a_year_without_places():
    """catches: output to a file, where DuckDB's second write overwrites the first and half the rows go (Claude skeptic, step 14), or a 2011-on file (zone numbers, no places) converted to nothing without a word"""
    if not VENV_PYTHON.exists():
        return "SKIPPED: no DuckDB in data/tools/venv"
    with tempfile.TemporaryDirectory() as tmp:
        y2009 = pathlib.Path(tmp) / "2009.parquet"
        make(y2009, ["Start_Lon", "Start_Lat", "End_Lon", "End_Lat"])
        with open(pathlib.Path(tmp) / "out.csv", "w") as out:
            r = subprocess.run([str(VENV_PYTHON), "-I", str(CONVERTER), str(y2009)], stdout=out, stderr=subprocess.PIPE,
                               timeout=60)
        assert r.returncode != 0 and b"pipe" in r.stderr, r
        zones = pathlib.Path(tmp) / "2011.parquet"
        make(zones, ["PULocationID", "x", "DOLocationID", "y"])
        status, error, _ = convert_and_import(tmp, [zones])
        assert status != 0 and "zone numbers" in error, (status, error)
