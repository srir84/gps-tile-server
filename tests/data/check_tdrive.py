"""make check-data (TESTING.md level 6): `gpstiles import` on all of T-Drive, checked three ways:
the counts against DESIGN §13 and against tdrive_counts.awk, and every code against the Python
rules in tests/oracle/import_rules.py. Prints SKIPPED and exits 0 when data/ is missing.
Needs GPSTILES_BIN. Exit code 0 = every check passed."""
import array
import importlib.util
import os
import pathlib
import subprocess
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parents[2]
TDRIVE = ROOT / "data" / "raw" / "tdrive_txt"
DESIGN_13 = "rows=10088351 imported=10064891 skipped_zero=23357 skipped_out_of_range=103 skipped_malformed=0"

spec = importlib.util.spec_from_file_location("import_rules", ROOT / "tests" / "oracle" / "import_rules.py")
rules = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rules)


def fail(message):
    print(f"check-data FAILED: {message}")
    sys.exit(1)


def main():
    files = sorted(TDRIVE.glob("*.txt"))
    if not files:
        print(f"check-data: SKIPPED: no T-Drive files in {TDRIVE.relative_to(ROOT)}")
        return
    if len(files) != 8911:
        fail(f"expected 8,911 T-Drive files (DESIGN §13), found {len(files)}")

    with tempfile.TemporaryDirectory() as tmp:
        pts = pathlib.Path(tmp) / "tdrive.pts"
        start = time.monotonic()
        result = subprocess.run([os.environ["GPSTILES_BIN"], "import", "--lon-col", "3", "--lat-col", "4",
                                 "-o", str(pts), *map(str, files)], capture_output=True, text=True)
        seconds = time.monotonic() - start
        if result.returncode != 0:
            fail(f"gpstiles import exited {result.returncode}: {result.stderr.strip()}")
        ours = result.stdout.strip()

        awk = subprocess.run(["awk", "-f", str(ROOT / "tests" / "data" / "tdrive_counts.awk"), *map(str, files)],
                             capture_output=True, text=True, env={**os.environ, "LC_ALL": "C"})
        if awk.returncode != 0:
            fail(f"awk exited {awk.returncode}: {awk.stderr.strip()}")
        for name, answer in [("DESIGN §13", DESIGN_13), ("awk", awk.stdout.strip())]:
            if ours != answer:
                fail(f"counts differ from {name}:\n  gpstiles {ours}\n  {name:8} {answer}")
        print(f"check-data: import counts = DESIGN §13 = awk: {ours} ({seconds:.1f} s)")

        counts, codes = rules.import_files(files, 3, 4)
        if rules.counts_line(counts) != ours:
            fail(f"counts differ from the Python rules: {rules.counts_line(counts)}")
        got = array.array("Q")
        got.frombytes(pts.read_bytes())
        if sys.byteorder == "big":
            got.byteswap()
        if len(got) != len(codes):
            fail(f".pts has {len(got)} codes, the Python rules {len(codes)}")
        for i, (a, b) in enumerate(zip(got, codes)):
            if a != b:
                fail(f"code {i} differs: gpstiles {a:#018x}, Python {b:#018x}")
        print(f"check-data: all {len(codes):,} codes in the .pts = the Python rules")


if __name__ == "__main__":
    main()
