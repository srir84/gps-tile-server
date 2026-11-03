"""make check-data for GBIF's occurrences of 2024 with coordinates (step 18, DESIGN §12.7): one zip from
tools/fetch-gbif.py holding one tab-separated CSV (161 GB unzipped). Light, so that it runs on every `make verify`:
the zip is GBIF's own description of it (download.json: its key, size, the query) and its header names columns 22 and 23
decimalLatitude and decimalLongitude; then the first 500,000 rows, taken out of the stream, are imported with
`gpstiles import` and compared with row_counts.awk and, code by code, with the Python rules
(tests/oracle/import_rules.py). The whole file is checked against awk and GBIF's totalRecords by tests/validate/
step-18.sh. Prints SKIPPED and exits 0 without the data. Needs GPSTILES_BIN. Exit 0 = every check passed."""
import array
import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "raw" / "gbif"
LAT_COL, LON_COL, SKIP = 22, 23, 1
SAMPLE_ROWS = 500_000


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tests" / "oracle" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


rules = load("import_rules")


def fail(message):
    print(f"check-data FAILED (GBIF): {message}")
    sys.exit(1)


def is_the_2024_download(info):
    """True when download.json describes a finished simple-CSV download of exactly HAS_COORDINATE = true AND YEAR =
    2024 (an "or", a ">=", or a third condition would be another download: Codex, step 18)."""
    request = info.get("request") or {}
    query = request.get("predicate") or {}
    parts = query.get("predicates", []) if query.get("type") == "and" else []
    predicates = {p.get("key"): str(p.get("value")).lower() for p in parts if p.get("type") == "equals"}
    return (len(parts) == 2 and predicates == {"HAS_COORDINATE": "true", "YEAR": "2024"}
            and request.get("format") == "SIMPLE_CSV" and info.get("status") == "SUCCEEDED")


def main():
    zips = sorted(DATA.glob("*.zip"))
    if not zips or not (DATA / "download.json").exists():
        print(f"check-data: SKIPPED (GBIF): no zip and download.json in {DATA.relative_to(ROOT)} (tools/fetch-gbif.py)")
        return
    if len(zips) != 1:
        fail(f"expected one zip, found {len(zips)}")
    zip_path = zips[0]
    info = json.loads((DATA / "download.json").read_text())
    if zip_path.stem != info["key"] or zip_path.stat().st_size != int(info["size"]) or not is_the_2024_download(info):
        fail(f"{zip_path.name} isn't the download download.json describes (key, size, the 2024 query, SIMPLE_CSV, SUCCEEDED)")
    with tempfile.TemporaryDirectory() as tmp:
        sample = pathlib.Path(tmp) / "sample.tsv"
        unzip = subprocess.Popen(["unzip", "-p", str(zip_path)], stdout=subprocess.PIPE)
        with open(sample, "wb") as out:
            for n, line in enumerate(unzip.stdout):
                out.write(line)
                if n == SAMPLE_ROWS:  # the header and SAMPLE_ROWS rows
                    break
        unzip.kill()  # the rest of the 161 GB isn't needed
        unzip.wait()
        lines = sample.open("rb").read(1 << 20).count(b"\n")
        header = sample.open("rb").readline().rstrip(b"\r\n").split(b"\t")
        if lines < 2 or len(header) < max(LAT_COL, LON_COL):
            fail(f"{zip_path.name}: unzip gave {lines} lines and a header of {len(header)} fields (not a readable zip?)")
        if header[LAT_COL - 1] != b"decimalLatitude" or header[LON_COL - 1] != b"decimalLongitude":
            fail(f"columns {LAT_COL} and {LON_COL} are {header[LAT_COL - 1]!r} and {header[LON_COL - 1]!r}")
        pts = pathlib.Path(tmp) / "sample.pts"
        ours = subprocess.run([os.environ["GPSTILES_BIN"], "import", "--delim", "tab", "--lat-col", str(LAT_COL),
                               "--lon-col", str(LON_COL), "--skip", str(SKIP), "-o", str(pts), str(sample)],
                              capture_output=True, text=True)
        awk = subprocess.run(["awk", "-v", f"LON={LON_COL}", "-v", f"LAT={LAT_COL}", "-v", f"SKIP={SKIP}", "-v",
                              "DELIM=\\t", "-f", str(ROOT / "tests" / "data" / "row_counts.awk"), str(sample)],
                             capture_output=True, text=True, env={**os.environ, "LC_ALL": "C"})
        if ours.returncode != 0 or awk.returncode != 0:
            fail(f"import or awk failed: {ours.stderr.strip()} {awk.stderr.strip()}")
        counts, codes = rules.import_files([sample], LON_COL, LAT_COL, delim=b"\t", skip=SKIP)
        if ours.stdout.strip() != awk.stdout.strip() or ours.stdout.strip() != rules.counts_line(counts):
            fail(f"first {SAMPLE_ROWS:,} rows:\n  gpstiles {ours.stdout.strip()}\n  awk      {awk.stdout.strip()}\n"
                 f"  Python   {rules.counts_line(counts)}")
        if counts["rows"] != SAMPLE_ROWS or counts["imported"] == 0:
            fail(f"the sample has {counts['rows']} rows, {counts['imported']} imported")
        got = array.array("Q")
        got.frombytes(pts.read_bytes())
        if sys.byteorder == "big":
            got.byteswap()
        if list(got) != codes:
            fail("the sample's codes differ from the Python rules")
        print(f"check-data: GBIF {zip_path.name} = download.json (key, {int(info['size']):,} bytes, the 2024 query, "
              f"{info['totalRecords']:,} records, DOI {info.get('doi')}) · header: columns 22, 23 = decimalLatitude, decimalLongitude")
        print(f"check-data: GBIF first {SAMPLE_ROWS:,} rows: {ours.stdout.strip()} = awk = the Python rules, every code")


if __name__ == "__main__":
    main()
