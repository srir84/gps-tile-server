"""nyc-taxi.py: TLC's yellow-taxi Parquet files (2009–2010: the years whose trips still have places) → CSV rows
"lon,lat" on stdout, a header, then each file's pickups and then its dropoffs (DESIGN §12.6, step 14). Needs DuckDB:
run it with data/tools/venv/bin/python. A missing place prints as an empty field (a malformed row for import). The output
must be a pipe: DuckDB writes each COPY to /dev/stdout from its start, so into a file the second would overwrite the first.
A converter that stops early (a bad file) exits non-zero, but import only sees the rows end: check both (pipefail).
Usage: data/tools/venv/bin/python tools/nyc-taxi.py FILE.parquet... | gpstiles import --lon-col 1 --lat-col 2 --skip 1 -o nyc.pts /dev/stdin"""
import os
import stat
import sys

import duckdb

COLUMNS = [("Start_Lon", "Start_Lat", "End_Lon", "End_Lat"),  # 2009
           ("pickup_longitude", "pickup_latitude", "dropoff_longitude", "dropoff_latitude")]  # 2010


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__.splitlines()[-1])
    if not stat.S_ISFIFO(os.fstat(sys.stdout.fileno()).st_mode):
        sys.exit("nyc-taxi: write to a pipe (| gpstiles import ... /dev/stdin): into a file, DuckDB's writes overwrite each other")
    db = duckdb.connect()
    db.sql("SET threads TO 2")  # keep the Mac light
    db.sql("SET preserve_insertion_order = false")  # the rows' order doesn't matter to import: 1.5 GB of memory less
    sys.stdout.write("lon,lat\n")
    sys.stdout.flush()
    for path in sys.argv[1:]:
        names = {row[0] for row in db.sql("DESCRIBE SELECT * FROM read_parquet(?)", params=[path]).fetchall()}
        cols = next((c for c in COLUMNS if set(c) <= names), None)
        if cols is None:
            sys.exit(f"nyc-taxi: {path} has no pickup and dropoff places (TLC's files from 2011 on hold zone numbers)")
        # Doubles as DuckDB writes them: the shortest text that reads back as the same number.
        for lon, lat in (cols[:2], cols[2:]):
            db.sql(f'COPY (SELECT "{lon}", "{lat}" FROM read_parquet(?)) TO \'/dev/stdout\' (HEADER false)',
                   params=[path])
    sys.stdout.flush()


if __name__ == "__main__":
    main()
