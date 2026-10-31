"""`gpstiles build` (DESIGN §5.3, §9.1, step 3a): whole .gpt files against tests/oracle/gpt_rules.py,
with lots of memory and with little (many runs), plus bad input and file errors (TESTING.md §9)."""
import getpass
import importlib.util
import os
import pathlib
import random
import resource
import signal
import subprocess
import sys
import tempfile
import time

TESTS = pathlib.Path(__file__).resolve().parents[1]
FIXTURES = TESTS / "fixtures"

spec = importlib.util.spec_from_file_location("gpt_rules", TESTS / "oracle" / "gpt_rules.py")
gpt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gpt)


def gpstiles(*args, timeout=60):
    return subprocess.run([os.environ["GPSTILES_BIN"], *map(str, args)], capture_output=True, text=True,
                          timeout=timeout)


def build(out, *inputs, extra=()):
    return gpstiles("build", *extra, "-o", out, *inputs)


def random_codes(n):
    """Seeded by TEST_SEED: half random, half from a small pool (many equal codes), and both extremes."""
    rng = random.Random(int(os.environ.get("TEST_SEED", "1")))
    pool = [rng.getrandbits(64) for _ in range(40)]
    return [rng.getrandbits(64) if i % 2 else rng.choice(pool) for i in range(n - 2)] + [0, 2**64 - 1]


def test_random_codes_build_to_the_oracle_file_with_any_mem():
    """catches: codes lost, repeated or misordered when the merge spans runs or input files; a header field wrong; a different file for a different --mem"""
    codes = random_codes(300_000)  # 2.4 MB: 3 runs with --mem 1M
    expected = gpt.gpt_bytes(codes)
    with tempfile.TemporaryDirectory() as tmp:
        tmp = pathlib.Path(tmp)
        (tmp / "a.pts").write_bytes(gpt.to_le_bytes(codes[:123_457]))
        (tmp / "b.pts").write_bytes(gpt.to_le_bytes(codes[123_457:]))
        (tmp / "runs").mkdir()
        for name, extra, runs in [("big.gpt", (), 1), ("small.gpt", ("--mem", "1M", "--tmp", tmp / "runs"), 3)]:
            result = build(tmp / name, tmp / "a.pts", tmp / "b.pts", extra=extra)
            assert result.returncode == 0 and result.stderr == "", result
            assert result.stdout == f"points=300000 runs={runs}\n", result.stdout
            got = (tmp / name).read_bytes()
            assert gpt.parse_header(got) == gpt.parse_header(expected), (name, gpt.parse_header(got))
            assert got == expected, f"{name}: points differ from a plain sort"
        assert os.listdir(tmp / "runs") == [], "run files left behind"
        assert sorted(os.listdir(tmp)) == ["a.pts", "b.pts", "big.gpt", "runs", "small.gpt"], os.listdir(tmp)


def test_tdrive_small_imports_and_builds_to_the_oracle_file():
    """catches: wrong bounds, densest pixel or view box on real-style clustered points"""
    with tempfile.TemporaryDirectory() as tmp:
        pts, out = pathlib.Path(tmp) / "small.pts", pathlib.Path(tmp) / "small.gpt"
        assert gpstiles("import", "--lon-col", "3", "--lat-col", "4", "-o", pts,
                        FIXTURES / "tdrive_small.txt").returncode == 0
        result = build(out, pts)
        assert result.returncode == 0 and result.stdout == "points=44 runs=1\n", result
        codes = [int.from_bytes(pts.read_bytes()[i:i + 8], "little") for i in range(0, 44 * 8, 8)]
        assert out.read_bytes() == gpt.gpt_bytes(codes), gpt.parse_header(out.read_bytes())
        assert gpt.parse_header(out.read_bytes())["max_pixel"][0] > 1  # the points cluster


def test_an_empty_pts_builds_to_just_a_header():
    """catches: a crash or junk stats when a dataset has no points"""
    with tempfile.TemporaryDirectory() as tmp:
        empty, out = pathlib.Path(tmp) / "empty.pts", pathlib.Path(tmp) / "empty.gpt"
        empty.write_bytes(b"")
        result = build(out, empty)
        assert result.returncode == 0 and result.stdout == "points=0 runs=0\n", result
        assert out.read_bytes() == gpt.gpt_bytes([])


def assert_usage_error(args, word):
    result = gpstiles("build", *args, timeout=10)
    assert result.returncode == 2, (args, result)
    lines = result.stderr.splitlines()
    assert result.stdout == "" and len(lines) == 1 and word in lines[0], (args, lines)


def test_bad_arguments_are_a_usage_error():
    """catches: a bad --mem or option ignored, so a typo silently builds with the wrong memory or overwrites an input"""
    with tempfile.TemporaryDirectory() as tmp:
        pts, out = pathlib.Path(tmp) / "in.pts", str(pathlib.Path(tmp) / "out.gpt")
        pts.write_bytes(gpt.to_le_bytes([1, 2, 3]))
        cases = [([], "missing"), ([pts], "missing"), (["-o", out], "missing"), (["-o"], "-o"),
                 (["--colour", "red", "-o", out, pts], "--colour"), (["-o", pts, pts], "also an input"),
                 (["-o", "", pts], "-o"), (["--tmp", "", "-o", out, pts], "--tmp"),
                 (["-o", out, pts, "--mem", "1M"], "options go before the input files")]
        for mem in ["0M", "512K", "65G", "1X", "abc", "1", "", "M", "-1M", "1.5G", "1000000000M", " 1G"]:
            cases.append((["--mem", mem, "-o", out, pts], "--mem"))
        for args, word in cases:
            assert_usage_error(args, word)
        assert sorted(os.listdir(tmp)) == ["in.pts"], f"files left: {os.listdir(tmp)}"
        for mem in ["1M", "1024k", "64G", "1g"]:  # accepted: the edges and lower case
            assert build(out, pts, extra=("--mem", mem)).returncode == 0, mem


def test_file_errors_exit_1_and_leave_no_files():
    """catches: a missing input, a cut .pts, a missing --tmp folder or an unwritable output ignored, or temp files left behind"""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = pathlib.Path(tmp)
        good, cut = tmp / "good.pts", tmp / "cut.pts"
        good.write_bytes(gpt.to_le_bytes([5, 4, 3]))
        cut.write_bytes(gpt.to_le_bytes([5, 4]) + b"\x01\x02\x03")
        out = tmp / "out" / "data.gpt"
        out.parent.mkdir()
        out.write_bytes(b"previous dataset")
        old_gpt = tmp / "old.gpt"
        old_gpt.write_bytes(gpt.gpt_bytes([7, 8]))
        cases = [([good, tmp / "missing.pts"], (), "missing.pts"), ([good, tmp], (), str(tmp)),
                 ([good, cut], (), "not a .pts file"), ([good], ("--tmp", tmp / "no-such-folder"), "no-such-folder"),
                 ([good, old_gpt], (), "is a .gpt file")]
        for inputs, extra, word in cases:
            result = build(out, *inputs, extra=extra)
            assert result.returncode == 1, (inputs, extra, result)
            lines = result.stderr.splitlines()
            assert result.stdout == "" and len(lines) == 1 and word in lines[0], (inputs, extra, lines)
            assert out.read_bytes() == b"previous dataset", "existing output changed by a failed build"
            assert os.listdir(out.parent) == ["data.gpt"], f"temp files left: {os.listdir(out.parent)}"
        result = build(tmp / "no-such-folder" / "x.gpt", good)
        assert result.returncode == 1 and "no-such-folder" in result.stderr, result
        result = build(out.parent, good)  # -o names a folder: refused before sorting anything
        assert result.returncode == 1 and "is a folder" in result.stderr, result
        out.parent.chmod(0o555)  # can't create the temp output: refused before anything is written
        try:
            result = build(out, good)
        finally:
            out.parent.chmod(0o755)
        assert result.returncode == 1 and len(result.stderr.splitlines()) == 1, result
        assert out.read_bytes() == b"previous dataset"
        assert build(out, good).returncode == 0
        assert out.read_bytes() == gpt.gpt_bytes([3, 4, 5]), "a good build didn't replace the old output"
        assert sorted(os.listdir(tmp)) == ["cut.pts", "good.pts", "old.gpt", "out"], os.listdir(tmp)
        assert os.listdir(out.parent) == ["data.gpt"], os.listdir(out.parent)


def test_a_run_file_that_cannot_be_hidden_is_reported_not_filled():
    """catches: unlink of the run file failing silently, so the sorted runs are written to a file that is then left behind (Codex step 3a round 1)"""
    if sys.platform != "darwin":
        return  # the ACL below is macOS's way to allow creating but not deleting files
    with tempfile.TemporaryDirectory() as tmp:
        tmp = pathlib.Path(tmp)
        good, runs = tmp / "good.pts", tmp / "runs"
        good.write_bytes(gpt.to_le_bytes([5, 4, 3]))
        runs.mkdir()
        deny = f"{getpass.getuser()} deny delete_child"
        subprocess.run(["chmod", "+a", deny, str(runs)], check=True)
        try:
            result = build(tmp / "out.gpt", good, extra=("--tmp", runs))
            left = list(runs.iterdir())
        finally:
            subprocess.run(["chmod", "-a", deny, str(runs)], check=True)
        assert result.returncode == 1 and result.stdout == "", result
        assert len(left) == 1 and left[0].stat().st_size == 0, "runs written to a file that stays behind"
        lines = result.stderr.splitlines()
        assert len(lines) == 1 and lines[0].startswith(f"gpstiles build: {left[0]}: "), lines  # names the leftover
        assert sorted(os.listdir(tmp)) == ["good.pts", "runs"], os.listdir(tmp)


def test_a_temp_output_that_cannot_be_removed_is_reported():
    """catches: removing the temp .gpt (or .pts) after a failure failing silently, so it stays behind unreported (Codex step 3a round 2)"""
    if sys.platform != "darwin":
        return  # the ACL below is macOS's way to allow creating but not deleting files
    with tempfile.TemporaryDirectory() as tmp:
        tmp = pathlib.Path(tmp)
        good, out = tmp / "good.pts", tmp / "out"
        good.write_bytes(gpt.to_le_bytes([5, 4, 3]))
        late = tmp / "late.fifo"  # a pipe is checked only as it is read: 12 bytes, half a code too many
        os.mkfifo(late)
        writer = subprocess.Popen(["sh", "-c", f"printf 123456789012 > '{late}'"])
        out.mkdir()
        (tmp / "runs").mkdir()
        deny = f"{getpass.getuser()} deny delete_child"
        subprocess.run(["chmod", "+a", deny, str(out)], check=True)
        try:
            results = [build(out / "x.gpt", good, late, extra=("--tmp", tmp / "runs")),
                       gpstiles("import", "--lon-col", "3", "--lat-col", "4", "-o", out / "x.pts",
                                FIXTURES / "tdrive_small.txt", tmp / "missing.txt")]
            left = sorted(out.iterdir())
        finally:
            subprocess.run(["chmod", "-a", deny, str(out)], check=True)
            writer.kill()
            writer.wait()
        assert len(left) == 2, left
        for result, leftover in zip(results, [p for p in left if ".gpt" in p.name] + [p for p in left if ".pts" in p.name]):
            lines = result.stderr.splitlines()
            assert result.returncode == 1 and len(lines) == 2, result
            assert ("late.fifo: not a .pts file" if result.args[1] == "build" else "missing") in lines[0], lines
            assert lines[1].startswith(f"gpstiles {result.args[1]}: {leftover}: left behind, delete it by hand"), lines


def test_more_than_256_runs_is_refused_at_once_with_the_mem_that_works():
    """catches: a too-small --mem found only after 256 runs were sorted and written (256 GiB at --mem 1G), or no hint how much to raise it"""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = pathlib.Path(tmp)
        big = tmp / "big.pts"
        with open(big, "wb") as f:
            f.truncate(256 * 2**20 + 8)  # sparse: takes no disk space; one byte past 256 runs of 1 MiB
        start = time.monotonic()
        result = build(tmp / "x.gpt", big, extra=("--mem", "1M"))
        assert result.returncode == 2 and "use --mem 2M or more" in result.stderr, result
        assert time.monotonic() - start < 2 and sorted(os.listdir(tmp)) == ["big.pts"]


def test_inputs_are_checked_before_any_is_read():
    """catches: a .gpt or an unreadable file among the inputs found only after the inputs before it were sorted (a whole sort pass lost at NYC scale)"""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = pathlib.Path(tmp)
        first = tmp / "first.fifo"  # nobody writes to it: reading it first would wait forever
        os.mkfifo(first)
        old_gpt, locked = tmp / "old.gpt", tmp / "locked.pts"
        old_gpt.write_bytes(gpt.gpt_bytes([7, 8]))
        locked.write_bytes(gpt.to_le_bytes([1]))
        locked.chmod(0)
        try:
            for later, word in [(old_gpt, "is a .gpt file"), (locked, "Permission denied")]:
                result = gpstiles("build", "-o", tmp / "x.gpt", first, later, timeout=10)
                assert result.returncode == 1 and word in result.stderr, (later.name, result)
        finally:
            locked.chmod(0o644)
        assert sorted(os.listdir(tmp)) == ["first.fifo", "locked.pts", "old.gpt"], os.listdir(tmp)


def wait_for_temp(folder, process):
    """Waits until the command has created its temp output in `folder`."""
    for _ in range(100):
        if any(".tmp-" in name for name in os.listdir(folder)):
            return
        assert process.poll() is None, process.communicate()
        time.sleep(0.05)
    raise AssertionError(f"no temp output appeared in {folder}")


def test_a_killed_build_or_import_leaves_no_temp_file():
    """catches: Ctrl-C, kill or a closed terminal leaving OUT.tmp-XXXXXX behind, which a later build of the folder would take in as points (Claude step 3a review)"""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = pathlib.Path(tmp)
        pipe = tmp / "in.fifo"  # nobody writes to it, so the command waits there with its temp output open
        os.mkfifo(pipe)
        out = tmp / "out"
        out.mkdir()
        for command in (["build", "-o", out / "x.gpt", pipe],
                        ["import", "--lon-col", "1", "--lat-col", "2", "-o", out / "x.pts", pipe]):
            for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP, signal.SIGQUIT):
                (out / "x.gpt").write_bytes(b"previous dataset")
                process = subprocess.Popen([os.environ["GPSTILES_BIN"], *map(str, command)],
                                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                try:
                    wait_for_temp(out, process)
                    process.send_signal(sig)
                    assert process.wait(timeout=10) == -sig, (command[0], sig)
                finally:
                    process.kill()
                    process.wait()
                assert os.listdir(out) == ["x.gpt"], (command[0], sig, os.listdir(out))
                assert (out / "x.gpt").read_bytes() == b"previous dataset"


def test_a_signal_ignored_at_start_stays_ignored():
    """catches: `nohup gpstiles build` dying when the terminal closes (SIGHUP), or a build in the background of a script dying on Ctrl-C, because the cleanup handler replaced an ignored signal (Claude step 3a round 2)"""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = pathlib.Path(tmp)
        pipe, out = tmp / "in.fifo", tmp / "out"
        os.mkfifo(pipe)
        out.mkdir()
        for sig in (signal.SIGHUP, signal.SIGINT):
            def ignore(sig=sig):
                signal.signal(sig, signal.SIG_IGN)  # what nohup (SIGHUP) and a background job (SIGINT) do
            process = subprocess.Popen([os.environ["GPSTILES_BIN"], "build", "-o", str(out / "x.gpt"), str(pipe)],
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, preexec_fn=ignore)
            try:
                wait_for_temp(out, process)
                process.send_signal(sig)
                time.sleep(0.3)
                assert process.poll() is None, f"the build died on {sig.name}, which it was started to ignore"
                process.send_signal(signal.SIGTERM)
                assert process.wait(timeout=10) == -signal.SIGTERM
            finally:
                process.kill()
                process.wait()
            assert os.listdir(out) == [], os.listdir(out)


def test_the_run_file_goes_next_to_the_output_by_default():
    """catches: runs written to the system temp folder (tmpfile, $TMPDIR) instead of next to the output, which can fill the system disk (DESIGN §5.3)"""
    if sys.platform != "darwin":
        return  # the ACL below is macOS's way to allow creating but not deleting files
    with tempfile.TemporaryDirectory() as tmp:
        tmp = pathlib.Path(tmp)
        good, out = tmp / "good.pts", tmp / "out"
        good.write_bytes(gpt.to_le_bytes([5, 4, 3]))
        out.mkdir()
        deny = f"{getpass.getuser()} deny delete_child"
        subprocess.run(["chmod", "+a", deny, str(out)], check=True)
        try:
            result = build(out / "x.gpt", good)
            left = sorted(p.name for p in out.iterdir())
        finally:
            subprocess.run(["chmod", "-a", deny, str(out)], check=True)
        lines = result.stderr.splitlines()
        assert result.returncode == 1 and len(lines) == 2 and len(left) == 2, (result, left)
        run_file = [name for name in left if name.startswith("gpstiles-runs-")]
        assert run_file and lines[0] == f"gpstiles build: {out / run_file[0]}: left behind, delete it by hand (Permission denied)", lines


def test_a_file_size_limit_is_a_clean_error():
    """catches: a failed write (disk full, file too large) killing the program or skipped by the cleanup, leaving a temp file or a changed output"""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = pathlib.Path(tmp)
        pts, out, runs = tmp / "in.pts", tmp / "out", tmp / "runs"
        pts.write_bytes(gpt.to_le_bytes(random_codes(1000)))  # runs: 8,000 bytes; .gpt: 8,256 bytes
        out.mkdir()
        runs.mkdir()
        (out / "x.gpt").write_bytes(b"previous dataset")
        for limit, failing in [(4000, runs), (8100, out / "x.gpt")]:
            def limit_file_size(limit=limit):
                resource.setrlimit(resource.RLIMIT_FSIZE, (limit, limit))
            result = subprocess.run([os.environ["GPSTILES_BIN"], "build", "--tmp", str(runs), "-o", str(out / "x.gpt"),
                                     str(pts)], capture_output=True, text=True, timeout=30, preexec_fn=limit_file_size)
            assert result.returncode == 1, (limit, result)
            assert result.stderr == f"gpstiles build: {failing}: File too large\n", (limit, result.stderr)
            assert os.listdir(out) == ["x.gpt"] and os.listdir(runs) == [], (os.listdir(out), os.listdir(runs))
            assert (out / "x.gpt").read_bytes() == b"previous dataset"
