"""`gpstiles info` and `gpstiles count` (DESIGN §9.1, step 3b) on a tiny .gpt built by the test: the
header against tests/oracle/gpt_rules.py, tile counts against a slow count of every point and
against their 4 smaller tiles, and broken .gpt files refused (TESTING.md §7, §9)."""
import importlib.util
import os
import pathlib
import random
import subprocess
import tempfile

TESTS = pathlib.Path(__file__).resolve().parents[1]

spec = importlib.util.spec_from_file_location("gpt_rules", TESTS / "oracle" / "gpt_rules.py")
gpt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gpt)


def gpstiles(*args, timeout=30):
    return subprocess.run([os.environ["GPSTILES_BIN"], *map(str, args)], capture_output=True, text=True,
                          timeout=timeout)


def clustered_codes(rng, n, corners=True, widest=32):
    """Points around one spot at many spreads (so tiles are shared at every zoom), repeats, and both
    corners of the world unless corners=False."""
    cx, cy = rng.getrandbits(32), rng.getrandbits(32)
    codes = [0, 2**64 - 1] if corners else []
    while len(codes) < n:
        mask = (1 << rng.randrange(widest + 1)) - 1
        x, y = cx ^ (rng.getrandbits(32) & mask), cy ^ (rng.getrandbits(32) & mask)
        codes += [gpt.code_of(x, y)] * rng.choice([1, 1, 1, 4])
    return codes[:n]


def make_gpt(folder, name, codes):
    pts, out = folder / f"{name}.pts", folder / f"{name}.gpt"
    pts.write_bytes(gpt.to_le_bytes(codes))
    result = gpstiles("build", "-o", out, pts)
    assert result.returncode == 0, result
    return out


def info(path):
    result = gpstiles("info", path)
    assert result.returncode == 0 and result.stderr == "", result
    return dict(line.split("=", 1) for line in result.stdout.splitlines())


def count(path, zoom, x, y):
    result = gpstiles("count", path, zoom, x, y)
    assert result.returncode == 0 and result.stderr == "", (zoom, x, y, result)
    assert result.stdout.startswith("points="), result.stdout
    return int(result.stdout.strip().split("=")[1])


def degrees(box):
    """A box in world units (min x, min y, max x, max y) as west, south, east, north."""
    return [gpt.lon_of_x(box[0]), gpt.lat_of_y(box[3]), gpt.lon_of_x(box[2]), gpt.lat_of_y(box[1])]


def test_info_prints_the_header_the_oracle_expects():
    """catches: a header field read from the wrong offset, bounds or view box with x/y or south/north swapped, a wrong file size"""
    rng = random.Random(int(os.environ.get("TEST_SEED", "1")))
    codes = clustered_codes(rng, 400, corners=False, widest=26)  # x and y extremes differ: swaps show
    with tempfile.TemporaryDirectory() as tmp:
        path = make_gpt(pathlib.Path(tmp), "tiny", codes)
        got = info(path)
    expected = gpt.header(sorted(codes))
    assert list(got) == ["points", "bytes", "bounds", "view", "max_pixel"], got
    assert int(got["points"]) == 400 and int(got["bytes"]) == 256 + 8 * 400, got
    for name, box in [("bounds", expected["bounds"]), ("view", expected["view"])]:
        numbers = [float(v) for v in got[name].split(",")]
        assert all(abs(a - b) < 2e-6 for a, b in zip(numbers, degrees(box))) and len(numbers) == 4, (
            name, numbers, degrees(box))
    assert [int(v) for v in got["max_pixel"].split(",")] == expected["max_pixel"], got["max_pixel"]


def test_count_is_the_slow_count_and_the_sum_of_its_4_children():
    """catches: a tile slice off by one, x/y swapped in the tile, the world's first or last tile lost, a zoom off by one"""
    rng = random.Random(int(os.environ.get("TEST_SEED", "1")))
    codes = clustered_codes(rng, 300)
    tiles = [(0, 0, 0), (24, 0, 0), (24, 2**24 - 1, 2**24 - 1), (3, 7, 7)]
    for _ in range(14):
        zoom, code = rng.randrange(25), rng.choice(codes)
        tiles.append((zoom, *gpt.tile_of(code, zoom)))
        tiles.append((zoom, rng.randrange(2**zoom), rng.randrange(2**zoom)))  # mostly empty
    with tempfile.TemporaryDirectory() as tmp:
        path = make_gpt(pathlib.Path(tmp), "tiny", codes)
        assert count(path, 0, 0, 0) == 300
        for zoom, x, y in tiles:
            slow = sum(1 for c in codes if gpt.tile_of(c, zoom) == (x, y))
            got = count(path, zoom, x, y)
            assert got == slow, (zoom, x, y, got, slow)
            if zoom < 24:
                children = sum(count(path, zoom + 1, 2 * x + dx, 2 * y + dy) for dx in (0, 1) for dy in (0, 1))
                assert children == got, (zoom, x, y, children, got)


def test_info_at_the_edges_of_the_world():
    """catches: an overflow at the world's last unit (east printed as -180, or south past the map's edge)"""
    with tempfile.TemporaryDirectory() as tmp:
        path = make_gpt(pathlib.Path(tmp), "corners", [0, 2**64 - 1])  # the north-west and south-east units
        got = info(path)
    assert got["bounds"] == "-180.000000,-85.051129,180.000000,85.051129", got["bounds"]


def test_an_empty_gpt_has_no_bounds():
    """catches: a 0-point file shown with made-up bounds at the world's corner, or crashing"""
    with tempfile.TemporaryDirectory() as tmp:
        path = make_gpt(pathlib.Path(tmp), "empty", [])
        assert info(path) == {"points": "0", "bytes": "256", "bounds": "none", "view": "none",
                              "max_pixel": ",".join(["0"] * 25)}
        assert count(path, 0, 0, 0) == 0 and count(path, 24, 5, 5) == 0


def broken_files(good):
    """name → bytes of a broken .gpt (TESTING.md §7), each made from a good one."""
    def patched(offset, value):
        return good[:offset] + value + good[offset + len(value):]
    return {
        "broken_label.gpt": patched(0, b"GPSTILF\0"),
        "broken_pts.gpt": good[256:],  # a .pts given by mistake
        "broken_version.gpt": patched(8, (2).to_bytes(4, "little")),
        "broken_unfinished.gpt": patched(8, (0).to_bytes(4, "little")),  # what a killed build leaves
        "broken_header_size.gpt": patched(12, (512).to_bytes(4, "little")),
        "broken_cut_header.gpt": good[:100],
        "broken_cut_points.gpt": good[:-3],
        "broken_extra_point.gpt": good + good[-8:],
        "broken_tail.gpt": good + b"junk",  # 1-7 bytes after the last point
        "broken_stats.gpt": patched(24, (2**32 - 1).to_bytes(4, "little")),  # min x > max x
        "broken_count_overflow.gpt": patched(16, (2**61 + 3).to_bytes(8, "little")),  # 8 × count wraps to 24
        "broken_empty.gpt": b"",
    }


def test_broken_gpt_files_are_refused_with_a_clear_message():
    """catches: a broken or cut .gpt read past its end (crash or garbage counts), a .pts taken for a .gpt, a hang on a named pipe"""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = pathlib.Path(tmp)
        good = make_gpt(tmp, "good", [1, 2, 3]).read_bytes()
        reasons = {"label": "not a .gpt", "pts": "not a .gpt", "version": "version", "unfinished": "unfinished",
                   "header_size": "header",
                   "cut_header": "cut short", "cut_points": "size", "extra_point": "size", "count_overflow": "size",
                   "tail": "size", "stats": "impossible header stats",
                   "empty": "not a .gpt"}
        cases = []
        for name, data in broken_files(good).items():
            (tmp / name).write_bytes(data)
            cases.append((tmp / name, reasons[name[len("broken_"):-len(".gpt")]]))
        os.mkfifo(tmp / "pipe.gpt")
        cases += [(tmp / "missing.gpt", "No such file"), (tmp, "not a regular file"),
                  (tmp / "pipe.gpt", "not a regular file")]
        for path, reason in cases:
            for args in (["info", path], ["count", path, 0, 0, 0]):
                result = gpstiles(*args, timeout=10)
                lines = result.stderr.splitlines()
                assert result.returncode == 1 and result.stdout == "", (args, result)
                assert len(lines) == 1 and str(path) in lines[0] and reason in lines[0], (args, lines)


def test_bad_arguments_are_a_usage_error():
    """catches: a zoom or tile number out of range accepted (a slice outside the world), or a typo ignored or blamed on the wrong argument"""
    with tempfile.TemporaryDirectory() as tmp:
        path = make_gpt(pathlib.Path(tmp), "good", [1, 2, 3])
        cases = [(["info"], "missing"), (["info", path, path], "argument"), (["info", "--all", path], "'--all'"),
                 (["count"], "missing"), (["count", path, 1, 0], "missing"), (["count", path, 1, 0, 0, 0], "argument"),
                 (["count", "-v", path, 1, 0, 0], "'-v'"), (["count", path, "--zoom", 10, 843, 388], "'--zoom'"),
                 (["info", path, "--all"], "'--all'"),
                 (["count", path, 25, 0, 0], "zoom"), (["count", path, -1, 0, 0], "zoom"),
                 (["count", path, "1x", 0, 0], "zoom"), (["count", path, "", 0, 0], "zoom"),
                 (["count", path, 1, 2, 0], "x"), (["count", path, 1, 0, 2], "y"),
                 (["count", path, 0, 1, 0], "x"), (["count", path, 24, 2**24, 0], "x"),
                 (["count", path, 3, "+1", 0], "x"), (["count", path, 3, 0, " 1"], "y")]
        for args, word in cases:
            result = gpstiles(*args, timeout=10)
            lines = result.stderr.splitlines()
            assert result.returncode == 2 and result.stdout == "", (args, result)
            assert len(lines) == 1 and word in lines[0], (args, lines)
        assert count(path, 24, 2**24 - 1, 2**24 - 1) == 0  # the largest tile number is accepted


def test_a_result_that_cannot_be_written_is_an_error():
    """catches: a command reporting success (exit 0) when its result was lost: stdout closed or the disk full"""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = pathlib.Path(tmp)
        path = make_gpt(tmp, "good", [1, 2, 3])
        (tmp / "in.csv").write_text("1,2\n")
        commands = [["info", path], ["count", path, 0, 0, 0], ["where", "116.391", "39.907", "--zoom", "10"],
                    ["help"], ["import", "--lon-col", "1", "--lat-col", "2", "-o", tmp / "x.pts", tmp / "in.csv"],
                    ["build", "-o", tmp / "x.gpt", tmp / "good.pts"]]
        for args in commands:
            result = subprocess.run([os.environ["GPSTILES_BIN"], *map(str, args)], capture_output=False,
                                    stderr=subprocess.PIPE, text=True, timeout=30, preexec_fn=lambda: os.close(1))
            assert result.returncode == 1, (args[0], result)
            assert "can't write the result" in result.stderr, (args[0], result.stderr)
