"""The answer source for OpenStreetMap's 2013 GPS traces (step 16, DESIGN §13), independent of gpstiles: counts the
track-point tags ("<trkpt" then a space, tab, CR, LF, '/' or '>') in every member of the dump with Python's tarfile and a
regular expression, and compares each .gpx with its `points` in metadata.xml. Run by hand (about 30 minutes, xz's time):
  xz -dc data/raw/osm-gps/gpx-planet-2013-04-09.tar.xz | python3 -I tests/data/osm_count.py data/raw/osm-gps/metadata.xml"""
import re
import sys
import tarfile

TAG = re.compile(rb"<trkpt[ \t\r\n/>]")


def main():
    listed = {int(m.group(1)): int(m.group(2))
              for m in re.finditer(rb'<gpxFile id="(\d+)" [^>]*?points="(\d+)"', open(sys.argv[1], "rb").read())}
    total, seen, differ = 0, set(), []
    with tarfile.open(fileobj=sys.stdin.buffer, mode="r|") as tar:
        for member in tar:
            if not member.isfile():
                continue
            n = len(TAG.findall(tar.extractfile(member).read()))
            total += n
            if member.name.endswith(".gpx"):
                ident = int(member.name.rsplit("/", 1)[1][:-4])
                seen.add(ident)
                if listed.get(ident) != n:
                    differ.append((member.name, n, listed.get(ident)))
            elif n:
                print(f"{member.name}: {n} track points outside a .gpx")
    print(f"track points {total}, in {len(seen)} .gpx files; metadata.xml lists {len(listed)} files, {sum(listed.values())} points")
    print(f"listed but not in the dump: {len(set(listed) - seen)}; files whose count differs from metadata.xml: {len(differ)}")
    for name, n, m in differ:
        print(f"  {name}: {n} (metadata.xml {m})")


if __name__ == "__main__":
    main()
