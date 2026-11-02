#!/usr/bin/env python3
"""fetch-opensky.py: downloads one day of OpenSky's public state-vector samples (DESIGN §12.7, step 17): OpenSky's
pre-curated data for individuals, no account needed, one Monday a week from 2020-05-25 to 2022-06-27. A day is 24
hourly `states_<day>-<HH>.csv.tar` files, each holding one gzipped CSV (and OpenSky's LICENSE.txt and README.txt). The
bucket's listing gives each file's size and ETag (its MD5, or for a file uploaded in N parts the MD5 of its parts'
MD5s, "-N"): a file is kept only when both match and it holds exactly one .csv.gz, and it is written under a temporary
name first, so a stopped run leaves no half file. Rerun to resume: a kept file is checked again and skipped (a damaged
one is fetched again). A day must list exactly the 24 hours 00-23. The data's use is bound by OpenSky's license (in
each file): non-profit research and education, internal testing and evaluation.
Usage: tools/fetch-opensky.py OUT_DIR DAY [--url URL] [--pause SECONDS]   (DAY as YYYY-MM-DD)
Writes OUT_DIR/states_<DAY>-<HH>.csv.tar. Built-in modules only."""
import argparse
import datetime
import hashlib
import os
import pathlib
import re
import signal
import ssl
import sys
import tarfile
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

BUCKET = "https://s3.opensky-network.org/data-samples"
S3 = "{http://s3.amazonaws.com/doc/2006-03-01/}"
TRIES = 3
AGENT = "gpstiles fetch-opensky.py (test data for a local map)"
# Python from python.org brings no certificates of its own: add the ones macOS keeps here. Checks stay on.
MACOS_CERTS = "/etc/ssl/cert.pem"
CHUNK = 1 << 20


class FetchError(Exception):
    pass


def tls():
    context = ssl.create_default_context()
    if os.path.exists(MACOS_CERTS):
        context.load_verify_locations(MACOS_CERTS)
    return context


def opened(url, pause):
    """The answer to a GET after a pause, with retries on connection errors and 5xx answers."""
    for attempt in range(TRIES):
        time.sleep(pause * (2 ** attempt if attempt else 1))
        try:
            request = urllib.request.Request(url, headers={"User-Agent": AGENT})
            return urllib.request.urlopen(request, timeout=120, context=tls() if url.startswith("https:") else None)
        except urllib.error.HTTPError as e:
            if e.code < 500 or attempt == TRIES - 1:
                raise FetchError(f"{url}: HTTP {e.code}") from None
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            if attempt == TRIES - 1:
                raise FetchError(f"{url}: {e}") from None
    raise FetchError(url)


MAX_PAGES = 100  # a day is a few dozen objects: a listing that goes on past this is broken


def listing(url, day, pause):
    """[(key, size, etag)] of the day's .csv.tar files, from the bucket's listing (every page of it): exactly one for
    each hour 00-23, its folder's hour = its name's."""
    files, token, seen_tokens = [], None, set()
    for _ in range(MAX_PAGES):
        query = {"list-type": "2", "prefix": f"states/{day}/", "max-keys": "1000"}
        if token:
            query["continuation-token"] = token
        with opened(f"{url}/?{urllib.parse.urlencode(query)}", pause) as answer:
            root = ET.fromstring(answer.read())
        for item in root.iter(f"{S3}Contents"):
            key = item.findtext(f"{S3}Key", "")
            match = re.fullmatch(rf"states/{day}/(\d\d)/states_{day}-(\d\d)\.csv\.tar", key)
            if not match:
                continue
            if match[1] != match[2]:
                raise FetchError(f"{key}: in the folder of hour {match[1]} but named for hour {match[2]}")
            etag = item.findtext(f"{S3}ETag", "").strip('"').lower()
            if not re.fullmatch(r"[0-9a-f]{32}(-[1-9][0-9]*)?", etag):
                raise FetchError(f"{key}: ETag {etag!r} is neither an MD5 nor a multipart one, so the file can't be checked")
            size = item.findtext(f"{S3}Size", "")
            if not size.isdigit():
                raise FetchError(f"{key}: the listing's size {size!r} isn't a number")
            files.append((key, int(size), etag))
        if root.findtext(f"{S3}IsTruncated") != "true":
            hours = sorted(key.rsplit("-", 1)[1][:2] for key, _, _ in files)
            if hours != [f"{h:02d}" for h in range(24)]:
                raise FetchError(f"{day} has hours {', '.join(hours) or 'none'} in the listing: not the 24 hours 00-23"
                                 " (the samples are Mondays, 2020-05-25 to 2022-06-27)")
            return sorted(files)
        token = root.findtext(f"{S3}NextContinuationToken")
        if not token or token in seen_tokens:
            raise FetchError("the listing says it goes on but gives no new token")
        seen_tokens.add(token)
    raise FetchError(f"the listing goes on past {MAX_PAGES} pages")


PART_MIB = (5, 8, 15, 16, 32, 64, 100, 128, 256, 512)  # the part sizes S3 tools use (AWS CLI 8, MinIO 5 or 16, ...)


def etag_of(path, size, etag):
    """The file's own ETag, worked out the way the listed one was: its MD5, or for "-N" the MD5 of the MD5s of its
    N parts. The part size isn't listed: each usual size (PART_MIB) that makes N parts of this size is tried, at most
    10 reads of the file, and the one that matches is returned (else the first, for the message)."""
    if "-" not in etag:
        digest = hashlib.md5()
        with open(path, "rb") as f:
            while block := f.read(CHUNK):
                digest.update(block)
        return digest.hexdigest()
    parts = int(etag.split("-")[1])
    found = None
    for mib in PART_MIB:
        part = mib * CHUNK
        if -(-size // part) != parts:
            continue
        digests = hashlib.md5()
        with open(path, "rb") as f:
            while block := f.read(part):
                digests.update(hashlib.md5(block).digest())
        found = found or f"{digests.hexdigest()}-{parts}"
        if f"{digests.hexdigest()}-{parts}" == etag:
            return etag
    return found or f"none (no usual part size makes {parts} parts)"


def one_csv_gz(path):
    """True when the tar holds exactly one .csv.gz and only regular files."""
    try:
        with tarfile.open(path) as tar:
            members = tar.getmembers()
    except (tarfile.TarError, OSError):
        return False
    return all(m.isfile() for m in members) and sum(m.name.endswith(".csv.gz") for m in members) == 1


def fetch_file(url, key, size, etag, out, pause):
    """Downloads one file to out/<name>, kept only whole; returns its name."""
    name = key.rsplit("/", 1)[1]
    target = out / name
    if target.exists():
        if target.stat().st_size == size and etag_of(target, size, etag) == etag and one_csv_gz(target):
            return name
        target.unlink()  # damaged: gone before fetching again, so a failed download leaves nothing
    part = out / (name + ".part")
    try:
        with opened(f"{url}/{urllib.parse.quote(key)}", pause) as answer, open(part, "wb") as f:
            while block := answer.read(CHUNK):
                f.write(block)
        got = part.stat().st_size
        mine = etag_of(part, got, etag) if got == size else "not worked out"
        if got != size or mine != etag:
            raise FetchError(f"{name}: {got} bytes, MD5 (ETag) {mine}; the listing says {size}, {etag}")
        if not one_csv_gz(part):
            raise FetchError(f"{name}: not a tar holding one .csv.gz")
        os.replace(part, target)
        print(f"{name} {size} {etag}", flush=True)
        return name
    finally:
        part.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("out")
    parser.add_argument("day")
    parser.add_argument("--url", default=BUCKET)
    parser.add_argument("--pause", type=float, default=1.0)
    args = parser.parse_args()
    try:
        if not re.fullmatch(r"\d{4}-\d\d-\d\d", args.day):
            raise ValueError
        datetime.date.fromisoformat(args.day)
    except ValueError:
        print(f"fetch-opensky: want a real day, YYYY-MM-DD, not {args.day!r}", file=sys.stderr)
        return 2
    # A stop (Ctrl-C, kill) runs the clean-up above: no .part is left.
    for sig in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, lambda *_: sys.exit(1))
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    try:
        files = listing(args.url.rstrip("/"), args.day, args.pause)
        for key, size, etag in files:
            fetch_file(args.url.rstrip("/"), key, size, etag, out, args.pause)
    except (FetchError, OSError, ET.ParseError) as e:
        print(f"fetch-opensky: {e}", file=sys.stderr)
        return 1
    print(f"fetch-opensky: {len(files)} hours of {args.day} in {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
