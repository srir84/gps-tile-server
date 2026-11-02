"""`gpstiles import` (DESIGN §8, §9.1, step 2): counts and .pts codes against the fixtures' known
counts and tests/oracle/import_rules.py, plus bad input and file errors (TESTING.md §9).
tests/fixtures/bad_rows.txt: 4 blank lines and 17 lines that are each wrong in one way."""
import array
import importlib.util
import os
import pathlib
import random
import subprocess
import sys
import tempfile

TESTS = pathlib.Path(__file__).resolve().parents[1]
FIXTURES = TESTS / "fixtures"

spec = importlib.util.spec_from_file_location("import_rules", TESTS / "oracle" / "import_rules.py")
rules = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rules)

ROW = b"1,2008-02-02 15:36:08,116.51172,39.92123"  # a good T-Drive row


def gpstiles_import(out, *files, cols=("3", "4"), extra=()):
    args = [os.environ["GPSTILES_BIN"], "import", "--lon-col", cols[0], "--lat-col", cols[1], *extra,
            "-o", str(out), *map(str, files)]
    return subprocess.run(args, capture_output=True, text=True, timeout=30)


def read_codes(path):
    codes = array.array("Q")
    codes.frombytes(pathlib.Path(path).read_bytes())
    if sys.byteorder == "big":
        codes.byteswap()  # .pts is little-endian (DESIGN §9.3)
    return list(codes)


def assert_matches_oracle(tmp, files, cols=(3, 4), delim=b",", skip=0, extra=()):
    """Runs import and checks the counts line and every code against the Python rules."""
    out = pathlib.Path(tmp) / "out.pts"
    result = gpstiles_import(out, *files, cols=(str(cols[0]), str(cols[1])), extra=extra)
    assert result.returncode == 0 and result.stderr == "", result
    counts, codes = rules.import_files(files, cols[0], cols[1], delim, skip)
    assert result.stdout == rules.counts_line(counts) + "\n", (result.stdout, counts)
    assert read_codes(out) == codes, "codes differ from the Python rules"
    return counts


def write(tmp, name, data):
    path = pathlib.Path(tmp) / name
    path.write_bytes(data)
    return path


def test_tdrive_small_gives_its_known_counts_and_codes():
    """catches: wrong counts or codes on real-style rows: CRLF left on the latitude, the last line without a newline lost, (0,0) or impossible places kept"""
    with tempfile.TemporaryDirectory() as tmp:
        counts = assert_matches_oracle(tmp, [FIXTURES / "tdrive_small.txt"])
        assert counts == dict(rows=50, imported=44, skipped_zero=3, skipped_out_of_range=3, skipped_malformed=0)
        assert (pathlib.Path(tmp) / "out.pts").stat().st_size == 44 * 8


def test_bad_rows_are_counted_as_malformed_and_blank_lines_are_not_rows():
    """catches: a bad row imported as a point, a crash on junk, or blank lines counted as rows"""
    with tempfile.TemporaryDirectory() as tmp:
        counts = assert_matches_oracle(tmp, [FIXTURES / "bad_rows.txt"])
        assert counts == dict(rows=17, imported=0, skipped_zero=0, skipped_out_of_range=0, skipped_malformed=17)


def test_long_lines_are_malformed_and_the_next_line_still_imports():
    """catches: a crash or unbounded memory on a 1 MB line, or losing the rows after it"""
    with tempfile.TemporaryDirectory() as tmp:
        exactly_max = b"1,x,116.5,39.9," + b"9" * (rules.MAX_LINE - 15)
        one_too_long = exactly_max + b"9"
        data = b"\n".join([ROW, b"1,x,116.5,39.9," + b"7" * 1_000_000, ROW, exactly_max, one_too_long, ROW,
                           b"8" * 3_000_000]) + b"\n" + ROW  # 3 MB: longer than the 1 MiB read buffer
        counts = assert_matches_oracle(tmp, [write(tmp, "long.txt", data)])
        assert counts["imported"] == 5 and counts["skipped_malformed"] == 3, counts  # 4 ROWs + exactly_max


def test_long_line_at_the_end_without_a_newline_is_one_malformed_row():
    """catches: a too-long last line counted twice, or lost, when the file ends without a newline"""
    with tempfile.TemporaryDirectory() as tmp:
        counts = assert_matches_oracle(tmp, [write(tmp, "end.txt", ROW + b"\n" + b"5" * 2_000_000)])
        assert counts == dict(rows=2, imported=1, skipped_zero=0, skipped_out_of_range=0, skipped_malformed=1)


def test_empty_file_and_no_final_newline():
    """catches: a crash on an empty file (T-Drive has 21), or the last row dropped when there is no final newline"""
    with tempfile.TemporaryDirectory() as tmp:
        assert assert_matches_oracle(tmp, [write(tmp, "empty.txt", b"")])["rows"] == 0
        assert assert_matches_oracle(tmp, [write(tmp, "last.txt", ROW)])["imported"] == 1


def test_crlf_and_lf_give_the_same_points():
    """catches: Windows line endings breaking the latitude column"""
    with tempfile.TemporaryDirectory() as tmp:
        lines = (FIXTURES / "tdrive_small.txt").read_bytes().split(b"\r\n")
        lf = write(tmp, "lf.txt", b"\n".join(lines) + b"\n")
        crlf = write(tmp, "crlf.txt", b"\r\n".join(lines) + b"\r\n")
        assert gpstiles_import(pathlib.Path(tmp) / "lf.pts", lf).stdout == \
            gpstiles_import(pathlib.Path(tmp) / "crlf.pts", crlf).stdout
        assert read_codes(pathlib.Path(tmp) / "lf.pts") == read_codes(pathlib.Path(tmp) / "crlf.pts")


def test_files_are_imported_in_order_and_counts_add_up():
    """catches: files read out of order, or counts reset between files"""
    with tempfile.TemporaryDirectory() as tmp:
        files = [FIXTURES / "tdrive_small.txt", FIXTURES / "bad_rows.txt", FIXTURES / "tdrive_small.txt"]
        counts = assert_matches_oracle(tmp, files)
        assert counts["rows"] == 50 + 17 + 50 and counts["imported"] == 88, counts


def test_header_lines_tab_delimiter_and_latitude_first():
    """catches: --skip applied once instead of per file, --delim ignored, or the lon/lat columns mixed up"""
    with tempfile.TemporaryDirectory() as tmp:
        tsv = b"lat\tlon\tname\n39.907\t116.391\tbeijing\n40.7128\t-74.006\tnew york\n0\t0\tno fix\n"
        files = [write(tmp, "a.tsv", tsv), write(tmp, "b.tsv", tsv)]
        counts = assert_matches_oracle(tmp, files, cols=(2, 1), delim=b"\t", skip=1,
                                       extra=["--delim", "tab", "--skip", "1"])
        assert counts == dict(rows=6, imported=4, skipped_zero=2, skipped_out_of_range=0, skipped_malformed=0)


def test_geolife_plt_layout_gives_its_known_counts_and_codes():
    """catches: GeoLife's own layout read wrong (step 10): its 6 header lines counted as rows, latitude and longitude mixed up, or the glitch at latitude 400 kept"""
    plt = FIXTURES / "geolife_small.plt"
    with tempfile.TemporaryDirectory() as tmp:
        counts = assert_matches_oracle(tmp, [plt, plt], cols=(2, 1), skip=6, extra=["--skip", "6"])
        assert counts == dict(rows=24, imported=22, skipped_zero=0, skipped_out_of_range=2, skipped_malformed=0)
        # One header line too few: the 6th header line, "0", is a row without a second column.
        counts = assert_matches_oracle(tmp, [plt], cols=(2, 1), skip=5, extra=["--skip", "5"])
        assert counts == dict(rows=13, imported=11, skipped_zero=0, skipped_out_of_range=1, skipped_malformed=1)
        # The columns swapped: Beijing's longitude, 116, read as a latitude is past the map's edge.
        counts = assert_matches_oracle(tmp, [plt], cols=(1, 2), skip=6, extra=["--skip", "6"])
        assert counts == dict(rows=12, imported=0, skipped_zero=0, skipped_out_of_range=12, skipped_malformed=0)


def test_row_counts_awk_gives_the_python_rules_counts():
    """catches: tests/data/row_counts.awk drifting from DESIGN §8, the answer make check-data trusts for T-Drive and GeoLife: a row rule, an edge (the map's, 65,536 bytes), a number that overflows (macOS's awk then compares text), the columns or the header lines"""
    with tempfile.TemporaryDirectory() as tmp:
        edges = [b"1,x,180,85.05112877980659", b"1,x,-180,-85.05112877980659", b"1,x,0,85.0511287798066",
                 b"1,x,180.0000001,0", b"1,x,1e999,0", b"1,x,-0,0", b"1,x,.5,1.", b"1,x,+1e1,-1E-1", b"",
                 b"1,x,116.5,1e999", b"1,x,-1e999,39.9", b"1,x,1e-400,39.9", b"1,x,116.5,-1e999", b"1,x,1e-400,1e-400",
                 b"1,x,116.5,39.9," + b"9" * (rules.MAX_LINE - 15), b"1,x,116.5,39.9," + b"9" * (rules.MAX_LINE - 14)]
        cases = [("tdrive_small.txt", 3, 4, 0), ("bad_rows.txt", 3, 4, 0), ("geolife_small.plt", 2, 1, 6),
                 ("geolife_small.plt", 2, 1, 5), ("geolife_small.plt", 1, 2, 6), ("edges.txt", 3, 4, 0),
                 ("edges.txt", 3, 4, 1), ("long.txt", 3, 4, 0)]
        write(tmp, "edges.txt", b"\r\n".join(edges))
        # LF only: exactly 65,536 bytes is a row, one more is malformed.
        write(tmp, "long.txt", b"\n".join([b"1,x,116.5,39.9," + b"9" * (rules.MAX_LINE - 15 + extra) for extra in (0, 1)]) + b"\n")
        for name, lon, lat, skip in cases:
            files = [FIXTURES / name if (FIXTURES / name).exists() else pathlib.Path(tmp) / name] * 2
            awk = subprocess.run(["awk", "-v", f"LON={lon}", "-v", f"LAT={lat}", "-v", f"SKIP={skip}",
                                  "-f", str(TESTS / "data" / "row_counts.awk"), *map(str, files)],
                                 capture_output=True, text=True, env={**os.environ, "LC_ALL": "C"}, timeout=30)
            counts, _ = rules.import_files(files, lon, lat, skip=skip)
            assert awk.returncode == 0 and awk.stdout == rules.counts_line(counts) + "\n", (name, skip, awk, counts)


def assert_polylines_match_oracle(tmp, files, col=9, skip=1, delim=b","):
    """Runs import --polyline and checks the counts line and every code against the Python rules."""
    out = pathlib.Path(tmp) / "out.pts"
    option = "tab" if delim == b"\t" else delim.decode()
    result = subprocess.run([os.environ["GPSTILES_BIN"], "import", "--polyline", str(col), "--skip", str(skip),
                             "--delim", option, "-o", str(out), *map(str, files)], capture_output=True, text=True,
                            timeout=60)
    assert result.returncode == 0 and result.stderr == "", result
    counts, codes = rules.polyline_files(files, col, delim, skip=skip)
    assert result.stdout == rules.polyline_counts_line(counts) + "\n", (result.stdout, counts)
    assert read_codes(out) == codes, "codes differ from the Python rules"
    return counts


def test_porto_small_polylines_give_their_known_counts_and_codes():
    """catches: Porto's layout read wrong (step 12): the quoted list split at its commas, an empty trip or a broken list miscounted, a (0,0) or faraway pair kept, or the header read as a trip"""
    with tempfile.TemporaryDirectory() as tmp:
        counts = assert_polylines_match_oracle(tmp, [FIXTURES / "porto_small.csv"] * 2)
        assert counts == dict(rows=16, points=32, imported=28, skipped_zero=2, skipped_out_of_range=2,
                              skipped_malformed=2), counts


def test_random_polylines_match_the_python_rules():
    """catches: any disagreement with DESIGN §8's polyline rules on rows the hand-written tests didn't think of: quotes, spaces, broken lists, numbers at the map's edges"""
    seed = int(os.environ.get("TEST_SEED") or 1)
    rng = random.Random(seed)
    numbers = ["-8.6", "41.1", "0", "-0", "180", "-180", "85.05112877980659", "85.0511287798066", "1e999", ".5", "5.",
               "+1", "1e2", "x", "", "1 2", "0x1", "1" * 63, "1" * 64, "0." + "0" * 61]  # 63 characters fit, 64 don't
    def pair():
        a, b = rng.choice(numbers), rng.choice(numbers)
        return rng.choice(["[{}, {}]", "[{},{}]", "[ {} ,{} ]", "[{}]", "[{},{},{}]"]).format(a, b, a)
    lines = []
    for _ in range(2000):
        body = "[" + rng.choice([",", ", ", " ,"]).join(pair() for _ in range(rng.randrange(0, 5))) + "]"
        body = rng.choice([body, body, body, body[:-1], body + ",", " " + body + " "])
        field = rng.choice(['"' + body + '"', '"' + body + '"', body, '"' + body, '"' + body + '"x'])
        tail = rng.choice(["", "", ",tail", ',"open', ',"x"y', ',"ok",z'])  # a broken quote after the list too
        lines.append(rng.choice(["1,", '"a,b",', '"q""q",', ""]) + field + tail + rng.choice(["", "", "\r", "\r\r"]))
    lines += ["", "\r", "\r\r"]
    rng.shuffle(lines)
    with tempfile.TemporaryDirectory() as tmp:
        path = write(tmp, "random.csv", "\n".join(lines).encode())
        for col in (1, 2):
            try:
                counts = assert_polylines_match_oracle(tmp, [path], col=col, skip=0)
            except AssertionError:
                print(f"seed={seed}")
                raise
            assert counts["imported"] > 0 and counts["skipped_malformed"] > 0, counts


def test_polylines_with_other_delimiters_quoted_or_not():
    """catches: a polyline row that only works with commas (the delimiter ignored), or an unquoted list refused when the delimiter isn't in it (Codex, step 12)"""
    with tempfile.TemporaryDirectory() as tmp:
        for delim in (b";", b"\t", b"|"):
            rows = [b"trip" + delim + b"[[-8.61,41.14],[-8.62,41.15]]", b"trip" + delim + b'"[[-8.6,41.1]]"' + delim + b"x",
                    b'"a' + delim + b'b"' + delim + b"[]", b"trip" + delim + b"[[0,0],[1,2]]", b"trip" + delim + b"[[1,2],]"]
            path = write(tmp, "d.csv", b"\n".join(rows) + b"\n")
            counts = assert_polylines_match_oracle(tmp, [path], col=2, skip=0, delim=delim)
            assert counts == dict(rows=5, points=5, imported=4, skipped_zero=1, skipped_out_of_range=0,
                                  skipped_malformed=1), (delim, counts)


def test_polyline_arguments_are_checked():
    """catches: --polyline mixed with --lon-col (one column or two?), a delimiter that is part of the list's syntax, or column 0 taken"""
    with tempfile.TemporaryDirectory() as tmp:
        fixture = str(FIXTURES / "porto_small.csv")
        for extra in (["--polyline", "9", "--lon-col", "1"], ["--polyline", "9", "--lat-col", "2"],
                      ["--polyline", "9", "--delim", '"'], ["--polyline", "9", "--delim", "["],
                      ["--polyline", "0"], ["--polyline", "x"]):
            result = subprocess.run([os.environ["GPSTILES_BIN"], "import", *extra, "-o", str(pathlib.Path(tmp) / "o.pts"),
                                     fixture], capture_output=True, text=True, timeout=30)
            assert result.returncode == 2 and result.stderr, (extra, result)
            assert not (pathlib.Path(tmp) / "o.pts").exists()


def assert_gpx_matches_oracle(tmp, files):
    """Runs import --gpx and checks the counts line and every code against the Python rules."""
    out = pathlib.Path(tmp) / "out.pts"
    result = subprocess.run([os.environ["GPSTILES_BIN"], "import", "--gpx", "-o", str(out), *map(str, files)],
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0 and result.stderr == "", result
    counts, codes = rules.gpx_files(files)
    assert result.stdout == rules.counts_line(counts) + "\n", (result.stdout, counts)
    assert read_codes(out) == codes, "codes differ from the Python rules"
    return counts


def test_gpx_track_points_give_their_known_counts_and_codes():
    """catches: GPX read wrong (step 16): attributes in the other order or quotes, a tag over several lines, a waypoint or <trkptx> taken as a track point, a missing or doubled lat kept, or a place off by the XML"""
    import xml.etree.ElementTree as ET
    gpx = FIXTURES / "small.gpx"
    with tempfile.TemporaryDirectory() as tmp:
        counts = assert_gpx_matches_oracle(tmp, [gpx, gpx])
        assert counts == dict(rows=18, imported=10, skipped_zero=2, skipped_out_of_range=2, skipped_malformed=4), counts
        # Python's own XML parser finds the same track points where both attributes are good numbers (it refuses the
        # whole file for the doubled lat, so that line is left out for it).
        text = gpx.read_text().replace('<trkpt lat="55.2" lat="55.3" lon="30.1"/>', "")
        points = [(float(t.get("lon")), float(t.get("lat"))) for t in ET.fromstring(text).iter("{http://www.topografix.com/GPX/1/0}trkpt")
                  if t.get("lat") and t.get("lon")]
        kept = [rules.code(lon, lat) for lon, lat in points if (lon, lat) != (0, 0) and abs(lat) <= rules.MAX_LAT]
        assert read_codes(pathlib.Path(tmp) / "out.pts")[:5] == kept, "the kept places differ from the XML parser's"


def test_random_gpx_matches_the_python_rules():
    """catches: a tag split by the 1 MiB read buffer lost or doubled, a tag past 4,096 bytes kept, one cut off by the end of the file miscounted, or any other disagreement with DESIGN §8's GPX rules"""
    seed = int(os.environ.get("TEST_SEED") or 1)
    rng = random.Random(seed)
    def tag():
        lat, lon = rng.choice(["55.21", "0", "-85.05112877980659", "91", "x", "1e2"]), rng.choice(["30.1", "0", "180", "-180.5", ""])
        parts = [f'lat="{lat}"', f"lon='{lon}'"] + ([f'ele="{"9" * rng.randrange(0, 5000)}"'] if rng.random() < 0.02 else [])
        rng.shuffle(parts)
        space = rng.choice([" ", "\n  ", "\t", " \r\n "])
        return "<trkpt" + space + space.join(parts) + rng.choice(["/>", ">", " >", "/>\n"]) + rng.choice(["", "<ele>1</ele></trkpt>"])
    body = "".join(rng.choice([tag(), tag(), "<trkptx lat='1' lon='2'/>", "<trk>", "\n"]) for _ in range(60000))
    with tempfile.TemporaryDirectory() as tmp:
        files = [write(tmp, "a.gpx", ("<gpx>" + body + "</gpx>").encode()), write(tmp, "b.gpx", (body + '<trkpt lat="1"').encode())]
        assert sum(f.stat().st_size for f in files) > 3 << 20, "the files must pass the 1 MiB read buffer"
        try:
            counts = assert_gpx_matches_oracle(tmp, files)
        except AssertionError:
            print(f"seed={seed}")
            raise
        assert counts["imported"] > 0 and counts["skipped_malformed"] > 0 and counts["skipped_out_of_range"] > 0, counts


def test_gpx_tags_at_the_read_buffer_edge_and_the_tag_limit():
    """catches: a tag lost or doubled when the 1 MiB read buffer is refilled (at any start near its edge), a tag of exactly 4,096 bytes refused or one of 4,097 kept, a '>' inside a quoted value taken as the tag's end (Codex), a stray or unclosed quote or an unclosed tag hiding the track points after it (both reviewers), or a NUL byte taken as a space or kept in a value (step 16)"""
    tag = b'<trkpt lat="55.2" lon="30.1"/>'
    with tempfile.TemporaryDirectory() as tmp:
        files = [write(tmp, f"edge{k}.gpx", b" " * ((1 << 20) - k) + tag + b"\n" + tag) for k in range(0, 40)]
        for k in (6, 5, 1):  # the file ends inside a "<trkpt"
            files.append(write(tmp, f"end{k}.gpx", b" " * ((1 << 20) - k) + tag[:k]))
        counts = assert_gpx_matches_oracle(tmp, files)
        assert counts["rows"] == 80 and counts["imported"] == 80, counts
        pad = lambda n: b'<trkpt lat="55.2" lon="30.1" ele="' + b"9" * (n - 36) + b"\">"  # n bytes from '<' to '>'
        assert len(pad(4096)) == 4096
        limit = [write(tmp, "4096.gpx", pad(4096)), write(tmp, "4097.gpx", pad(4097)),
                 write(tmp, "gt.gpx", b'<trkpt lat="55.2" name="a>b" lon="30.1"/><trkpt lat=\'55.2\' name=\'a>b\' lon=\'30.1\'/>'),
                 write(tmp, "stray.gpx", b'<trkpt lat="55.2" lon="30.1" it\'s><trkpt lat="55.2" lon="30.1"/><name>Bob\'s</name>'
                       b'<trkpt lat="55.2" lon="30.1" name="no end><trkpt lat="55.2" lon="30.1"/>'
                       b'<trkpt lat="1"\n<trkpt lat="55.2" lon="30.1"/>'),  # Codex's: an unclosed tag before a good one
                 write(tmp, "nul2.gpx", b'<trkpt lat="55.2" lon="30.1" name="a\x00b"/><trkpt lat="55.2" lon="30.1" na\x00me="a"/>'),
                 write(tmp, "nul.gpx", b'<trkpt\x00lat="55.2" lon="30.1"/><trkpt lat="55.2"\x00lon="30.1"/>')]
        counts = assert_gpx_matches_oracle(tmp, limit)  # 4096 and gt.gpx kept (XML allows '>' in a value); in stray.gpx
        # a stray quote or an unclosed one breaks only its own tag (a '<' ends it), not the track points after it
        assert counts == dict(rows=13, imported=6, skipped_zero=0, skipped_out_of_range=0, skipped_malformed=7), counts


def test_gpx_arguments_are_checked():
    """catches: --gpx mixed with column options, --delim or --skip (silently ignored instead of refused)"""
    with tempfile.TemporaryDirectory() as tmp:
        for extra in (["--gpx", "--lon-col", "1"], ["--gpx", "--polyline", "2"], ["--gpx", "--delim", ";"], ["--gpx", "--skip", "1"]):
            result = subprocess.run([os.environ["GPSTILES_BIN"], "import", *extra, "-o", str(pathlib.Path(tmp) / "o.pts"),
                                     str(FIXTURES / "small.gpx")], capture_output=True, text=True, timeout=30)
            assert result.returncode == 2 and result.stderr, (extra, result)


def test_number_edges_follow_the_rules():
    """catches: the map edge refused, a value past it kept, "1e999" or "-0" mishandled, or a NUL byte hiding junk"""
    with tempfile.TemporaryDirectory() as tmp:
        rows = [b"1,x,180,85.05112877980659", b"1,x,-180,-85.05112877980659", b"1,x,0,85.0511287798066",
                b"1,x,180.0000001,0", b"1,x,1e999,0", b"1,x,-0,0", b"1,x,.5,1.", b"1,x,+1e1,-1E-1",
                b"1,x,116.5\x00junk,39.9", b"1,x,116\x00,39.9", b"1,x,179.99999999999997,0"]
        counts = assert_matches_oracle(tmp, [write(tmp, "edges.txt", b"\n".join(rows))])
        assert counts == dict(rows=11, imported=5, skipped_zero=1, skipped_out_of_range=3, skipped_malformed=2)


def test_random_rows_match_the_python_rules():
    """catches: any disagreement with DESIGN §8 on rows the hand-written tests didn't think of, including lines that cross the read buffer"""
    seed = int(os.environ.get("TEST_SEED") or 1)
    rng = random.Random(seed)
    pieces = [b"116.5", b"39.9", b"-74.006", b"0", b"0.0", b"193", b"95", b"-85.06", b"1e3", b"abc", b"", b"nan",
              b" 1", b"1.2.3", b"180", b"-180", b"85.05112877980659", b".5", b"5.", b"+3", b"--1", b"\r", b"\t"]
    with tempfile.TemporaryDirectory() as tmp:
        lines = []
        for _ in range(60000):  # ≈ 1.3 MB, so lines cross the 1 MiB read buffer
            fields = [rng.choice(pieces) for _ in range(rng.choice([1, 2, 3, 4, 4, 4, 5]))]
            line = b",".join(fields)
            if rng.random() < 0.3:
                line = b"1,2008-02-02," + bytes(f"{rng.uniform(-200, 200):.6f},{rng.uniform(-90, 90):.6f}", "ascii")
            lines.append(line + (b"\r" if rng.random() < 0.5 else b""))
        files = [write(tmp, "random.txt", b"\n".join(lines))]
        counts = assert_matches_oracle(tmp, files)
        assert counts["imported"] > 1000 and counts["skipped_malformed"] > 1000, (counts, f"seed={seed}")


def assert_usage_error(args, word):
    result = subprocess.run([os.environ["GPSTILES_BIN"], "import", *args], capture_output=True, text=True, timeout=10)
    assert result.returncode == 2, (args, result)
    lines = result.stderr.splitlines()
    assert result.stdout == "" and len(lines) == 1 and word in lines[0], (args, lines)


def test_bad_arguments_are_a_usage_error():
    """catches: a missing or bad option ignored, so a typo silently imports the wrong columns or nothing"""
    good = str(FIXTURES / "tdrive_small.txt")
    with tempfile.TemporaryDirectory() as tmp:
        out = str(pathlib.Path(tmp) / "out.pts")
        cases = [([], "missing"), (["--lon-col", "3", "-o", out, good], "missing"),
                 (["--lon-col", "3", "--lat-col", "4", good], "missing"),
                 (["--lon-col", "3", "--lat-col", "4", "-o", out], "missing"),
                 (["--lon-col", "0", "--lat-col", "4", "-o", out, good], "--lon-col"),
                 (["--lon-col", "x", "--lat-col", "4", "-o", out, good], "--lon-col"),
                 (["--lon-col", "3", "--lat-col", "10001", "-o", out, good], "--lat-col"),
                 (["--lon-col", "3", "--lat-col", "3", "-o", out, good], "same column"),
                 (["--lon-col", "3", "--lat-col", "4", "--delim", ".", "-o", out, good], "--delim"),
                 (["--lon-col", "3", "--lat-col", "4", "--delim", ",,", "-o", out, good], "--delim"),
                 (["--lon-col", "3", "--lat-col", "4", "--skip", "-1", "-o", out, good], "--skip"),
                 (["--lon-col", "3", "--lat-col", "4", "--colour", "red", "-o", out, good], "--colour"),
                 (["--lon-col", "3", "--lat-col", "4", "-o"], "-o"),
                 (["--lon-col", "3", "--lat-col", "4", "-o", good, good], "also an input")]
        for args, word in cases:
            assert_usage_error(args, word)
        assert not pathlib.Path(out).exists(), "a usage error created the output file"


def test_file_errors_exit_1_and_leave_no_output():
    """catches: a missing or unreadable input ignored, or a half-written .pts left behind after an error"""
    good = str(FIXTURES / "tdrive_small.txt")
    with tempfile.TemporaryDirectory() as tmp:
        out = pathlib.Path(tmp) / "out.pts"
        for files in [[good, str(pathlib.Path(tmp) / "missing.txt")], [good, tmp]]:  # missing file, a folder
            result = gpstiles_import(out, *files)
            assert result.returncode == 1, (files, result)
            assert len(result.stderr.splitlines()) == 1 and result.stdout == "", result
            assert not out.exists(), "half-written output left behind"
        result = gpstiles_import(pathlib.Path(tmp) / "no-such-folder" / "out.pts", good)
        assert result.returncode == 1 and "no-such-folder" in result.stderr, result
        assert os.listdir(tmp) == [], f"files left behind: {os.listdir(tmp)}"


def test_a_failed_import_leaves_an_existing_output_unchanged():
    """catches: -o existing.pts emptied before the inputs are read, so a typo in an input name destroys the old dataset (Codex step 2 round 1)"""
    good = str(FIXTURES / "tdrive_small.txt")
    with tempfile.TemporaryDirectory() as tmp:
        folder = pathlib.Path(tmp) / "out"
        folder.mkdir()
        out = folder / "keep.pts"
        out.write_bytes(b"previous dataset")
        mode = out.stat().st_mode & 0o777
        result = gpstiles_import(out, good, pathlib.Path(tmp) / "missing.txt")
        assert result.returncode == 1, result
        assert out.read_bytes() == b"previous dataset", "existing output changed by a failed import"
        folder.chmod(0o555)  # can't create the temp file: refused before anything is written
        try:
            result = gpstiles_import(out, good)
        finally:
            folder.chmod(0o755)
        assert result.returncode == 1 and len(result.stderr.splitlines()) == 1, result
        assert out.read_bytes() == b"previous dataset", "existing output changed by a failed import"
        assert sorted(os.listdir(folder)) == ["keep.pts"], f"temp files left: {os.listdir(folder)}"
        assert gpstiles_import(out, good).returncode == 0
        assert len(read_codes(out)) == 44, "a good import didn't replace the old output"
        assert sorted(os.listdir(folder)) == ["keep.pts"], f"temp files left: {os.listdir(folder)}"
        assert out.stat().st_mode & 0o777 == mode, oct(out.stat().st_mode)  # kept from the file it replaced


def test_replacing_an_output_keeps_its_permissions():
    """catches: re-importing over a private 0600 dataset makes it readable by other users (Codex step 2 round 2)"""
    good = str(FIXTURES / "tdrive_small.txt")
    with tempfile.TemporaryDirectory() as tmp:
        new = pathlib.Path(tmp) / "new.pts"
        assert gpstiles_import(new, good).returncode == 0
        assert new.stat().st_mode & 0o777 == 0o666 & ~current_umask(), oct(new.stat().st_mode)
        private = pathlib.Path(tmp) / "private.pts"
        private.write_bytes(b"old")
        private.chmod(0o600)
        assert gpstiles_import(private, good).returncode == 0
        assert len(read_codes(private)) == 44
        assert private.stat().st_mode & 0o777 == 0o600, oct(private.stat().st_mode)


def current_umask():
    mask = os.umask(0)
    os.umask(mask)
    return mask


def test_delimiter_x_does_not_turn_fields_into_hex():
    """catches: with --delim x, strtod reads "0x10" as one hex number instead of lon 0, lat 10 (Codex step 2 round 1)"""
    with tempfile.TemporaryDirectory() as tmp:
        counts = assert_matches_oracle(tmp, [write(tmp, "x.txt", b"0x10\n0X10\n116.5x39.9\n")], cols=(1, 2),
                                       delim=b"x", extra=["--delim", "x"])
        assert counts["imported"] == 2 and counts["skipped_malformed"] == 1, counts  # "0X10" has no x delimiter
