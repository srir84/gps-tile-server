#!/usr/bin/env python3
"""fetch-usgs.py: downloads USGS's earthquake catalog as CSV (DESIGN §12.4, step 11), from USGS's own event service, one
period at a time: 1900–1969 together, then one file per year. USGS answers at most 20,000 rows a request, so a period is
cut into time windows USGS counts at most 20,000 quakes in, each read with one request and checked against its count,
and a quake's id may come only once. A period's file is kept only when its rows = USGS's own count of the period, and it is
written under a temporary name first, so a stopped run leaves no half file; MANIFEST.txt is written when all are done. Rerun to resume: kept periods are skipped
(state.json records them, and the dates and service of the download: a folder holds one download only).
Usage: tools/fetch-usgs.py OUT_DIR [--since 1900-01-01] [--until 2026-10-01] [--pause 1] [--page 20000] [--url URL]
Writes OUT_DIR/usgs-<start>_<end>.csv (USGS's header and rows, as sent), state.json and MANIFEST.txt. Built-in modules only."""
import argparse
import csv
import datetime
import hashlib
import http.client
import io
import json
import os
import pathlib
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

SERVICE = "https://earthquake.usgs.gov/fdsnws/event/1"
HEADER = ("time,latitude,longitude,depth,mag,magType,nst,gap,dmin,rms,net,id,updated,place,type,horizontalError,"
          "depthError,magError,magNst,status,locationSource,magSource")
COLUMNS = HEADER.split(",")
ID = COLUMNS.index("id")
MAX_PAGE = 20000  # USGS's limit for one request
TRIES = 5
AGENT = "gpstiles fetch-usgs.py (test data for a local map)"
# Python from python.org brings no certificates of its own: add the ones macOS keeps here. Checks stay on.
MACOS_CERTS = "/etc/ssl/cert.pem"


class FetchError(Exception):
    pass


def periods(since, until):
    """[start, end) pairs: since to 1970 as one period (about 50,000 quakes in 70 years), then a year each."""
    edges = [since] + [datetime.date(year, 1, 1) for year in range(1970, until.year + 1)] + [until]
    edges = sorted({e for e in edges if since <= e <= until})
    return list(zip(edges, edges[1:]))


def tls():
    context = ssl.create_default_context()
    if os.path.exists(MACOS_CERTS):
        context.load_verify_locations(MACOS_CERTS)
    return context


def get(url, pause, whole_lines=False):
    """GET after a pause, with retries on connection errors, time-outs, cut-off answers and 5xx/429 answers (waiting
    5, 10, 20, 40 × pause seconds). whole_lines: an answer must end with a newline (USGS's CSV always does), so one
    cut off by a closed connection with no length header isn't taken for a whole one."""
    for attempt in range(TRIES):
        time.sleep(pause)
        try:
            request = urllib.request.Request(url, headers={"User-Agent": AGENT})
            with urllib.request.urlopen(request, timeout=300, context=tls()) as response:
                status, body = response.status, response.read().decode("utf-8")
            if not (whole_lines and body and not body.endswith("\n")):
                return status, body
            problem = "an answer cut short (no final newline)"
        except urllib.error.HTTPError as e:
            if e.code < 500 and e.code != 429:
                raise FetchError(f"{url}: HTTP {e.code}: {e.read()[:300].decode('utf-8', 'replace').strip()}")
            problem = f"HTTP {e.code}"
        except (urllib.error.URLError, http.client.HTTPException, TimeoutError, ConnectionError) as e:
            if isinstance(getattr(e, "reason", None), ssl.SSLError):  # won't mend by waiting
                raise FetchError(f"{url}: {e}")
            problem = str(e)
        if attempt + 1 < TRIES:
            wait = 5 * 2 ** attempt * pause
            print(f"  {problem}: trying again in {wait:.0f} s", file=sys.stderr)
            time.sleep(wait)
    raise FetchError(f"{url}: {problem}, {TRIES} tries")


def stamp(moment):
    return moment.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3]


def query(args, **params):
    return f"{args.url}/{'count' if params.pop('count', False) else 'query'}?" + urllib.parse.urlencode(params)


MS = datetime.timedelta(milliseconds=1)


def count_of(args, first, last):
    """USGS's count of the quakes from `first` to `last`, both included (to the millisecond)."""
    _, text = get(query(args, count=True, starttime=stamp(first), endtime=stamp(last), eventtype="earthquake"), args.pause)
    if not text.strip().isdigit():
        raise FetchError(f"{stamp(first)}–{stamp(last)}: USGS's count is not a number: {text[:100]!r}")
    return int(text)


def windows(args, first, last, total):
    """Cuts [first, last] into equal pieces, and those again, until USGS counts at most --page quakes in each: yields
    (first, last, count). One request then gets a whole piece, and nothing depends on the order USGS sends rows in
    (its "time" order isn't strict: in the 2018 Anchorage aftershocks a quake at 23:59:50.170 follows one at 51.262)."""
    if total <= args.page:
        yield first, last, total
        return
    span = (last - first) // MS + 1  # milliseconds
    if span < 2:
        raise FetchError(f"{stamp(first)}: more than {args.page} quakes in one millisecond")
    parts = min(span, -(-total * 10 // (args.page * 9)))  # aim at 90 % of the limit a piece
    edges = [first + (span * k // parts) * MS for k in range(parts + 1)]
    for a, b in zip(edges, edges[1:]):
        piece_last = b - MS
        yield from windows(args, a, piece_last, count_of(args, a, piece_last))


def fetch_window(args, first, last, expected):
    """The rows of one piece, as USGS sent them, checked: USGS's header, one line of 22 columns a row, `expected` rows."""
    _, text = get(query(args, format="csv", orderby="time-asc", limit=args.page, starttime=stamp(first),
                        endtime=stamp(last), eventtype="earthquake"), args.pause, whole_lines=True)
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    if not lines:
        lines = [HEADER]  # an empty answer (HTTP 204)
    if lines[0] != HEADER:
        raise FetchError(f"{stamp(first)}–{stamp(last)}: unexpected header {lines[0][:200]!r}")
    page = lines[1:]
    records = list(csv.reader(io.StringIO("\n".join(page))))
    if len(records) != len(page) or any(len(r) != len(COLUMNS) for r in records):
        raise FetchError(f"{stamp(first)}–{stamp(last)}: a row isn't one line of {len(COLUMNS)} columns")
    if len(page) != expected:
        raise FetchError(f"{stamp(first)}–{stamp(last)}: {len(page)} rows, USGS counts {expected}")
    return page, records


def fetch_period(args, start, end):
    """The period's rows as USGS sent them (lines), checked against USGS's count of the whole period."""
    first = datetime.datetime.combine(start, datetime.time())
    last = datetime.datetime.combine(end, datetime.time()) - MS  # USGS's end time is included
    expected = count_of(args, first, last)
    rows, ids = [], set()
    for a, b, n in windows(args, first, last, expected):
        page, records = fetch_window(args, a, b, n)
        for line, record in zip(page, records):
            if record[ID] in ids:
                raise FetchError(f"{start}–{end}: quake {record[ID]} came twice")
            ids.add(record[ID])
            rows.append(line)
    if len(rows) != expected:
        raise FetchError(f"{start}–{end}: {len(rows)} rows, USGS counts {expected}")
    return rows, expected


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("out")
    parser.add_argument("--since", default="1900-01-01", type=datetime.date.fromisoformat)
    parser.add_argument("--until", default="2026-10-01", type=datetime.date.fromisoformat)
    parser.add_argument("--pause", default=1.0, type=float, help="seconds between requests (be kind to USGS)")
    parser.add_argument("--page", default=MAX_PAGE, type=int, help="rows a request, at most 20000")
    parser.add_argument("--url", default=SERVICE, help="the event service (tests use a fake one)")
    args = parser.parse_args()
    if not (1 <= args.page <= MAX_PAGE) or args.pause < 0 or not args.since < args.until:
        parser.error("want 1 ≤ --page ≤ 20000, --pause ≥ 0 and --since before --until")

    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    state_path = out / "state.json"
    # One folder holds one download: other dates or another service would add files that overlap the kept ones.
    settings = dict(since=str(args.since), until=str(args.until), url=args.url, eventtype="earthquake")
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else dict(settings=settings, files={})
    if state.get("settings") != settings:
        print(f"fetch-usgs: {out} holds another download ({state.get('settings')}); use another folder", file=sys.stderr)
        return 2
    files = state["files"]
    names = [f"usgs-{start}_{end}.csv" for start, end in periods(args.since, args.until)]
    strays = sorted({p.name for p in out.glob("usgs-*.csv")} - set(names))
    if strays:  # from another download: importing usgs-*.csv would read their quakes twice
        print(f"fetch-usgs: {out} holds files of another download ({', '.join(strays[:3])}); use another folder",
              file=sys.stderr)
        return 2
    for (start, end), name in zip(periods(args.since, args.until), names):
        path = out / name
        # Kept only if the file is still exactly what was fetched.
        if name in files and path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() == files[name].get("sha256"):
            continue
        try:
            for attempt in (1, 2):  # once more if the catalog changed between the count and the pages
                try:
                    rows, expected = fetch_period(args, start, end)
                    break
                except FetchError as e:
                    if attempt == 2 or "USGS counts" not in str(e):
                        raise
                    print(f"  {e}: once more", file=sys.stderr)
        except FetchError as e:
            print(f"fetch-usgs: {e}", file=sys.stderr)
            return 1
        part = out / (name + ".part")
        data = ("\n".join([HEADER, *rows]) + "\n").encode("utf-8")  # as USGS sent it, whatever the locale
        try:
            part.write_bytes(data)
            os.replace(part, path)
        except OSError as e:
            part.unlink(missing_ok=True)
            print(f"fetch-usgs: can't write {path}: {e}", file=sys.stderr)
            return 1
        files[name] = dict(rows=len(rows), usgs_count=expected, sha256=hashlib.sha256(data).hexdigest(),
                           fetched=datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
        state_part = out / "state.json.part"
        state_part.write_text(json.dumps(state, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(state_part, state_path)
        print(f"{name}: {len(rows):,} rows = USGS's count")

    total = sum(files[name]["rows"] for name in names)
    lines = [f"USGS earthquakes (eventtype=earthquake) from {args.since} to {args.until}, from {args.url}",
             "file rows usgs_count fetched"]
    lines += [f"{name} {files[name]['rows']} {files[name]['usgs_count']} {files[name]['fetched']}" for name in names]
    lines.append(f"total {total} {sum(files[name]['usgs_count'] for name in names)}")
    (out / "MANIFEST.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"fetch-usgs: {len(names)} files, {total:,} rows, each file = USGS's count (MANIFEST.txt)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
