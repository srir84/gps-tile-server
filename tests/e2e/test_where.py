"""`gpstiles where LON LAT --zoom Z` (DESIGN §9.1, step 1): tiles against tests/fixtures/places.csv
and the OpenStreetMap formula in tests/oracle/osm_tile.py, plus bad input (TESTING.md §9)."""
import csv
import importlib.util
import os
import pathlib
import random
import subprocess

TESTS = pathlib.Path(__file__).resolve().parents[1]
MAX_LAT = "85.05112877980659"
JUST_PAST_MAX_LAT = "85.0511287798066"  # the next 16-digit decimal north of the edge

spec = importlib.util.spec_from_file_location("osm_tile", TESTS / "oracle" / "osm_tile.py")
osm_tile = importlib.util.module_from_spec(spec)
spec.loader.exec_module(osm_tile)


def where(*args):
    return subprocess.run([os.environ["GPSTILES_BIN"], "where", *args], capture_output=True, text=True,
                          timeout=10)


def assert_tile(args, expected):
    result = where(*args)
    assert (result.returncode, result.stdout, result.stderr) == (0, expected + "\n", ""), (args, result)


def assert_refused(args, word):
    """Exit 2, nothing on stdout, one line on stderr that names the bad part."""
    result = where(*args)
    assert result.returncode == 2, (args, result)
    assert result.stdout == "", (args, result.stdout)
    lines = result.stderr.splitlines()
    assert len(lines) == 1 and word in lines[0], (args, lines)


def test_known_places_print_known_tiles():
    """catches: a wrong tile for a real place (y flipped, x/y swapped, wrong zoom scale) or extra output"""
    with open(TESTS / "fixtures" / "places.csv", newline="") as f:
        rows = list(csv.DictReader(line for line in f if not line.startswith("#")))
    assert len(rows) >= 13, len(rows)
    for row in rows:
        assert_tile([row["lon"], row["lat"], "--zoom", row["zoom"]], row["tile"])


def test_random_places_match_the_openstreetmap_formula():
    """catches: tiles that drift from OpenStreetMap's numbering somewhere other than the few known places"""
    seed = int(os.environ.get("TEST_SEED") or 1)
    rng = random.Random(seed)
    for _ in range(100):
        lon = rng.uniform(-180.0, 180.0)
        lat = rng.uniform(-float(MAX_LAT), float(MAX_LAT))
        zoom = rng.randint(0, 24)
        assert_tile([repr(lon), repr(lat), "--zoom", str(zoom)], osm_tile.tile(lon, lat, zoom)), f"seed={seed}"


def test_map_edge_is_accepted_and_just_past_it_is_refused():
    """catches: < instead of <= drops the map's edge, the south edge overflows instead of clamping, or impossible latitudes get a tile"""
    assert_tile(["0", MAX_LAT, "--zoom", "10"], "10/512/0")
    assert_tile(["0", "-" + MAX_LAT, "--zoom", "10"], "10/512/1023")
    assert_refused(["0", JUST_PAST_MAX_LAT, "--zoom", "10"], "latitude")
    assert_refused(["0", "-" + JUST_PAST_MAX_LAT, "--zoom", "10"], "latitude")
    assert_refused(["180.0000001", "0", "--zoom", "10"], "longitude")
    assert_refused(["-180.0000001", "0", "--zoom", "10"], "longitude")


def test_longitude_180_is_the_same_line_as_minus_180():
    """catches: lon 180 lands one past the last column (x = 2^zoom) instead of wrapping to x = 0"""
    for zoom in ["1", "10", "24"]:
        assert_tile(["180", "10", "--zoom", zoom], where("-180", "10", "--zoom", zoom).stdout.strip())
    assert_tile(["180", "0", "--zoom", "1"], "1/0/1")


def test_longitude_just_below_180_stays_in_the_last_column():
    """catches: lon + 180 rounding up to 360 wraps a place just west of 180 to the far-west column (Codex step 1 round 1)"""
    for zoom, last in [("1", 1), ("10", 1023), ("24", 2 ** 24 - 1)]:
        assert_tile(["179.99999999999997", "0", "--zoom", zoom], f"{zoom}/{last}/{2 ** (int(zoom) - 1)}")


def test_not_a_number_is_refused():
    """catches: NaN, infinity, hex or trailing junk accepted as a coordinate, giving a garbage tile or a crash"""
    for bad in ["nan", "NaN", "inf", "-inf", "infinity", "1e999", "0x10", "", " 1", "1 ", "1,5", "abc",
                "1e", ".", "+-1", "1.2.3"]:
        assert_refused([bad, "0", "--zoom", "1"], "longitude")
        assert_refused(["0", bad, "--zoom", "1"], "latitude")


def test_bad_zoom_is_refused():
    """catches: a zoom past 24, negative or non-numeric zoom is accepted, shifting bits past the code"""
    for bad in ["25", "100", "-1", "1.5", "", "abc", " 3", "3 ", "999999999999999999999"]:
        assert_refused(["0", "0", "--zoom", bad], "zoom")


def test_wrong_arguments_are_a_usage_error():
    """catches: missing, extra or unknown arguments ignored, so a typo silently prints some tile"""
    for args, word in [([], "missing"), (["0"], "missing"), (["0", "0"], "missing"), (["--zoom", "1"], "missing"),
                       (["0", "0", "--zoom"], "argument"), (["0", "0", "--zoom", "1", "5"], "argument"),
                       (["0", "0", "--zom", "1"], "argument"), (["0", "0", "--zoom", "1", "--zoom", "2"], "argument")]:
        assert_refused(args, word)


def test_arguments_can_come_in_either_order():
    """catches: --zoom before the place is misread as a coordinate"""
    assert_tile(["--zoom", "10", "116.391", "39.907"], "10/843/388")


def test_huge_or_control_character_argument_stays_one_short_line():
    """catches: a 5,000-character or multi-line argument is echoed in full, breaking the one-line error rule"""
    assert_refused(["0", "1" * 5000, "--zoom", "1"], "latitude")
    assert len(where("0", "1" * 5000, "--zoom", "1").stderr) < 200
    assert_refused(["0", "1\n2", "--zoom", "1"], "latitude")
