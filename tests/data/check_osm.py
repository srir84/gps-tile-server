"""make check-data for OpenStreetMap's public GPS traces of 2013 (step 16, DESIGN §12.7), light: 3 GPX files near the start
of the 22 GB dump (taken out with `tar -q`, which stops once it has them), each imported with `gpstiles import --gpx` and
checked three ways: counts and every code = the Python rules (tests/oracle/import_rules.py), the track points and their
places = Python's own XML parser's, and the count = the file's `points` in metadata.xml (OpenStreetMap's own count). The whole dump is imported and
checked against metadata.xml's total by tests/validate/step-16.sh. Prints SKIPPED and exits 0 without the data. Needs
GPSTILES_BIN. Exit 0 = every check passed."""
import array
import importlib.util
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

ROOT = pathlib.Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "raw" / "osm-gps"
DUMP = DATA / "gpx-planet-2013-04-09.tar.xz"
MEMBERS = ["gpx-planet-2013-04-09/identifiable/001/005/001005252.gpx",
           "gpx-planet-2013-04-09/identifiable/001/005/001005107.gpx",
           "gpx-planet-2013-04-09/identifiable/001/005/001005876.gpx"]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tests" / "oracle" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


rules = load("import_rules")


def fail(message):
    print(f"check-data FAILED (OSM): {message}")
    sys.exit(1)


def main():
    if not DUMP.exists() or not (DATA / "metadata.xml").exists():
        print(f"check-data: SKIPPED (OSM): no {DUMP.relative_to(ROOT)} or its metadata.xml")
        return
    metadata = (DATA / "metadata.xml").read_bytes()
    with tempfile.TemporaryDirectory() as tmp:
        tmp = pathlib.Path(tmp)
        xz = subprocess.Popen(["xz", "-dc", str(DUMP)], stdout=subprocess.PIPE)
        tar = subprocess.run(["tar", "-xqf", "-", "-C", str(tmp), *MEMBERS], stdin=xz.stdout, capture_output=True)
        xz.stdout.close()
        xz.kill()  # tar stops once it has the files; the rest of the stream isn't needed
        xz.wait()
        if tar.returncode != 0:
            fail(f"tar couldn't take out the sample: {tar.stderr.decode().strip()}")
        for member in MEMBERS:
            path = tmp / member
            out = tmp / "out.pts"
            result = subprocess.run([os.environ["GPSTILES_BIN"], "import", "--gpx", "-o", str(out), str(path)],
                                    capture_output=True, text=True)
            if result.returncode != 0:
                fail(f"import --gpx {path.name} exited {result.returncode}: {result.stderr.strip()}")
            counts, codes = rules.gpx_files([path])
            got = array.array("Q")
            got.frombytes(out.read_bytes())
            if sys.byteorder == "big":
                got.byteswap()
            if result.stdout.strip() != rules.counts_line(counts) or list(got) != codes:
                fail(f"{path.name}: {result.stdout.strip()}, the Python rules {rules.counts_line(counts)}")
            tags = [e for e in ET.parse(path).iter() if e.tag.endswith("}trkpt") or e.tag == "trkpt"]
            parsed = len(tags)
            # Every kept place = the XML parser's own lat and lon (these files have only good places).
            if any(e.get("lat") is None or e.get("lon") is None for e in tags):
                fail(f"{path.name}: a track point without lat or lon (the sample should have none)")
            if list(got) != [rules.code(float(e.get("lon")), float(e.get("lat"))) for e in tags]:
                fail(f"{path.name}: the places differ from Python's XML parser's")
            ident = int(path.stem)
            listed = re.search(rb'<gpxFile id="%d" [^>]*?points="(\d+)"' % ident, metadata)
            if listed is None:
                fail(f"{path.name}: not in metadata.xml")
            if not counts["rows"] == parsed == int(listed.group(1)):
                fail(f"{path.name}: {counts['rows']} rows, the XML parser {parsed} track points, metadata.xml {listed.group(1)}")
            print(f"check-data: OSM {path.name}: {result.stdout.strip()} = the Python rules, every code ·"
                  f" {parsed:,} track points and places = Python's XML parser = metadata.xml")


if __name__ == "__main__":
    main()
