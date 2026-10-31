"""`gpstiles render` (DESIGN §5.5, §9.1, step 4): tiles of a .gpt built by the test, decoded by the Python
PNG reader in tests/oracle/tile_rules.py and compared pixel by pixel with its own counts and color rule;
an empty tile is fully transparent; bad arguments and files are refused."""
import importlib.util
import os
import pathlib
import random
import resource
import subprocess
import tempfile

TESTS = pathlib.Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, TESTS / "oracle" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gpt = load("gpt_rules")
tile = load("tile_rules")


def gpstiles(*args, timeout=30):
    return subprocess.run([os.environ["GPSTILES_BIN"], *map(str, args)], capture_output=True, text=True,
                          timeout=timeout)


def make_gpt(folder, codes):
    pts, out = folder / "in.pts", folder / "in.gpt"
    pts.write_bytes(gpt.to_le_bytes(codes))
    assert gpstiles("build", "-o", out, pts).returncode == 0
    return out


def render(path, zoom, x, y, out):
    result = gpstiles("render", path, zoom, x, y, "-o", out)
    assert result.returncode == 0 and result.stderr == "", result
    return result.stdout, tile.decode_png(out.read_bytes())


def test_a_hand_made_tile_has_the_expected_pixels():
    """catches: x/y swapped, a pixel off by one, the top row flipped to the bottom, or a point drawn in the wrong tile"""
    # Tile 10/843/388 (Beijing). Its pixel (px, py) starts at world x = (843 * 256 + px) << 14.
    def code(px, py, dx=0, dy=0):
        return gpt.code_of(((843 * 256 + px) << 14) + dx, ((388 * 256 + py) << 14) + dy)
    codes = ([code(0, 0)] + [code(255, 0)] * 3 + [code(0, 255, 5, 9)] * 9 + [code(10, 200)] * 27
             + [code(255, 255, 2**14 - 1, 2**14 - 1)]
             + [gpt.code_of((843 * 256 + 256) << 14, 388 * 256 << 14)])  # one pixel east: the next tile
    with tempfile.TemporaryDirectory() as tmp:
        tmp = pathlib.Path(tmp)
        path = make_gpt(tmp, codes)
        stdout, (width, height, rows) = render(path, 10, 843, 388, tmp / "t.png")
        assert stdout == f"points=41 bytes={(tmp / 't.png').stat().st_size}\n", stdout
    assert (width, height) == (256, 256)
    want = {(0, 0): 1, (255, 0): 3, (0, 255): 9, (10, 200): 27, (255, 255): 1}
    max_count = gpt.header(sorted(codes))["max_pixel"][10]
    assert max_count == 27
    for py in range(256):
        for px in range(256):
            assert rows[py][px] == tile.color(want.get((px, py), 0), max_count), (px, py, rows[py][px])
    assert rows[200][10] == (0xfc, 0xfd, 0xbf, 255)  # the densest pixel gets the top color
    assert rows[0][0] == (0x8c, 0x29, 0x81, 255)  # a single point gets the bottom color, still opaque


def test_random_tiles_match_python_counts_and_colors():
    """catches: a wrong color scale (not log, not per zoom, max from the tile instead of the header), pixel counts merged or split"""
    rng = random.Random(int(os.environ.get("TEST_SEED", "1")))
    cx, cy = rng.getrandbits(32), rng.getrandbits(32)
    codes = []
    while len(codes) < 2000:
        mask = (1 << rng.randrange(10, 33)) - 1
        codes += [gpt.code_of(cx ^ (rng.getrandbits(32) & mask), cy ^ (rng.getrandbits(32) & mask))] * rng.choice([1, 1, 2, 7])
    header = gpt.header(sorted(codes))
    with tempfile.TemporaryDirectory() as tmp:
        tmp = pathlib.Path(tmp)
        path = make_gpt(tmp, codes)
        for zoom in (0, 3, 9, 14, 18, 24):
            x, y = gpt.tile_of(rng.choice(codes), zoom)
            stdout, (_, _, rows) = render(path, zoom, x, y, tmp / "t.png")
            counts = tile.pixel_counts(codes, zoom, x, y, gpt.x_of, gpt.y_of)
            assert stdout.startswith(f"points={sum(counts.values())} "), (zoom, stdout)
            for py in range(256):
                for px in range(256):
                    want = tile.color(counts.get((px, py), 0), header["max_pixel"][zoom])
                    assert rows[py][px] == want, (zoom, x, y, px, py, rows[py][px], want)


def test_an_empty_tile_is_fully_transparent():
    """catches: an empty tile drawn black or with junk, so the base map disappears under it"""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = pathlib.Path(tmp)
        for codes in ([], [gpt.code_of(0, 0)]):
            path = make_gpt(tmp, codes)
            stdout, (width, height, rows) = render(path, 5, 31, 31, tmp / "t.png")
            assert stdout.startswith("points=0 ") and (width, height) == (256, 256)
            assert all(pixel == (0, 0, 0, 0) for row in rows for pixel in row)


def test_bad_arguments_and_files_are_refused():
    """catches: a tile outside the world drawn anyway, a missing -o ignored, or a broken .gpt drawn from garbage"""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = pathlib.Path(tmp)
        path = make_gpt(tmp, [1, 2, 3])
        out = tmp / "t.png"
        usage = [(["render", path, 0, 0, 0], "missing"), (["render", path, 25, 0, 0, "-o", out], "zoom"),
                 (["render", path, 1, 2, 0, "-o", out], "x"), (["render", path, 1, 0, 2, "-o", out], "y"),
                 (["render", "-o", out], "missing"), (["render", path, 0, 0, 0, 0, "-o", out], "argument"),
                 (["render", path, 0, 0, 0, "-o"], "-o"), (["render", path, 0, 0, 0, "-x", out], "-x")]
        for args, word in usage:
            result = gpstiles(*args)
            assert result.returncode == 2 and word in result.stderr and len(result.stderr.splitlines()) == 1, (args, result)
        broken = tmp / "broken.gpt"
        broken.write_bytes(path.read_bytes()[:-1])
        for args, word in [([broken], "size"), ([tmp / "missing.gpt"], "missing.gpt")]:
            result = gpstiles("render", *args, 0, 0, 0, "-o", out)
            assert result.returncode == 1 and word in result.stderr and len(result.stderr.splitlines()) == 1, result
        result = gpstiles("render", path, 0, 0, 0, "-o", tmp / "no-such-folder" / "t.png")
        assert result.returncode == 1 and "no-such-folder" in result.stderr, result
        assert sorted(os.listdir(tmp)) == ["broken.gpt", "in.gpt", "in.pts"], os.listdir(tmp)  # no temp files left


def test_a_failed_write_leaves_the_old_png_and_no_temp_file():
    """catches: -o naming the input .gpt (the dataset replaced by a picture), a failed rename or write reported as success, a temp file left behind, or the old PNG cut short"""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = pathlib.Path(tmp)
        path = make_gpt(tmp, [gpt.code_of(i * 4097, i * 8191) for i in range(2000)])
        gpt_bytes = path.read_bytes()
        result = gpstiles("render", path, 0, 0, 0, "-o", path)
        assert result.returncode == 2 and "also the input" in result.stderr, result
        assert path.read_bytes() == gpt_bytes, "the dataset was overwritten"
        out = tmp / "out"
        out.mkdir()
        result = gpstiles("render", path, 0, 0, 0, "-o", out)  # -o names a folder: the rename fails
        assert result.returncode == 1 and str(out) in result.stderr, result
        old = out / "t.png"
        old.write_bytes(b"previous picture")

        def limit_file_size():
            resource.setrlimit(resource.RLIMIT_FSIZE, (100, 100))  # any 256 × 256 PNG is bigger: its write fails
        result = subprocess.run([os.environ["GPSTILES_BIN"], "render", str(path), "0", "0", "0", "-o", str(old)],
                                capture_output=True, text=True, timeout=30, preexec_fn=limit_file_size)
        assert result.returncode == 1 and "File too large" in result.stderr, result
        assert old.read_bytes() == b"previous picture", "the old PNG was changed"
        assert os.listdir(out) == ["t.png"] and sorted(os.listdir(tmp)) == ["in.gpt", "in.pts", "out"], os.listdir(tmp)
