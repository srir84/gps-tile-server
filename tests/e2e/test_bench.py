"""`gpstiles bench` (DESIGN §9.1, step 9): it records speed, so the test checks the table, not the times: one
row per zoom, p50 ≤ p99 ≤ max, and the points per tile Python expects from the same choice of tiles
(TESTING.md §9)."""
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


def gpstiles(*args, timeout=120):
    return subprocess.run([os.environ["GPSTILES_BIN"], *map(str, args)], capture_output=True, text=True,
                          timeout=timeout)


def test_bench_prints_one_row_per_zoom_with_the_expected_tiles():
    """catches: a zoom skipped, percentiles taken from unsorted times, or the wrong tiles timed (points per tile off)"""
    rng = random.Random(int(os.environ.get("TEST_SEED", "1")))
    codes = sorted(gpt.code_of(3_536_000_000 ^ rng.getrandbits(22), 1_626_000_000 ^ rng.getrandbits(22))
                   for _ in range(3000))
    with tempfile.TemporaryDirectory() as tmp:
        pts, path = pathlib.Path(tmp) / "in.pts", pathlib.Path(tmp) / "in.gpt"
        pts.write_bytes(gpt.to_le_bytes(codes))
        assert gpstiles("build", "-o", path, pts).returncode == 0
        result = gpstiles("bench", path)
    assert result.returncode == 0 and result.stderr == "", result
    lines = result.stdout.splitlines()
    assert lines[0] == "zoom renders tiles p50_ms p99_ms max_ms points_per_render", lines[0]
    assert len(lines) == 26, len(lines)
    for zoom, line in enumerate(lines[1:]):
        z, renders, tiles, p50, p99, top, per_render = line.split()
        assert int(z) == zoom and int(renders) == 100, line
        assert 0 <= float(p50) <= float(p99) <= float(top) and float(top) > 0, line  # a render takes time
        # The tiles of the points at index k * n / 100, k = 0..99 (spread evenly through the file).
        timed = [gpt.tile_of(codes[k * len(codes) // 100], zoom) for k in range(100)]
        want = sum(sum(1 for c in codes if gpt.tile_of(c, zoom) == t) for t in timed) // 100
        assert int(per_render) == want and int(tiles) == len(set(timed)), (zoom, per_render, want, tiles, len(set(timed)))


def test_bench_refuses_bad_arguments_and_empty_files():
    """catches: bench crashing on a file with no points to time, or a typo ignored"""
    with tempfile.TemporaryDirectory() as tmp:
        pts, path = pathlib.Path(tmp) / "in.pts", pathlib.Path(tmp) / "in.gpt"
        pts.write_bytes(b"")
        assert gpstiles("build", "-o", path, pts).returncode == 0
        result = gpstiles("bench", path)
        assert result.returncode == 1 and "no points" in result.stderr, result
        for args, code, named in [([], 2, "missing"), ([path, path], 2, str(path)[:20]), (["--fast", path], 2, "--fast"),
                                  ([pathlib.Path(tmp) / "missing.gpt"], 1, "missing.gpt")]:
            result = gpstiles("bench", *args)
            assert result.returncode == code and len(result.stderr.splitlines()) == 1 and named in result.stderr, (args, result)
