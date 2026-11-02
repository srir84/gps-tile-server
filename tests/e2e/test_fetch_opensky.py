"""tools/fetch-opensky.py (step 17) against a fake OpenSky bucket on 127.0.0.1 (--url): a day is exactly its 24 hours;
an hour is kept only whole (its size and ETag = the listing's, one .csv.gz inside), a bad one or a stop leaves nothing,
a rerun resumes, a listing in pages is read to its end and one that never ends is refused."""
import functools
import gzip
import hashlib
import http.server
import io
import os
import pathlib
import signal
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import urllib.parse

FETCH = pathlib.Path(__file__).resolve().parents[2] / "tools" / "fetch-opensky.py"
DAY = "2022-06-27"


def name(hour):
    return f"states_{DAY}-{hour:02d}.csv.tar"


def an_hour(hour, csv_files=1):
    """A tar like OpenSky's: states_<day>-<HH>.csv.gz (csv_files of them) and a LICENSE.txt."""
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode="w") as tar:
        for n in range(csv_files):
            body = gzip.compress(f"time,icao24,lat,lon\n1656288000,abc{n},50.0,8.5\n".encode(), mtime=0)  # the same bytes every call
            info = tarfile.TarInfo(f"states_{DAY}-{hour:02d}{'' if n == 0 else f'-{n}'}.csv.gz")
            info.size = len(body)
            tar.addfile(info, io.BytesIO(body))
        info = tarfile.TarInfo("LICENSE.txt")
        info.size = 7
        tar.addfile(info, io.BytesIO(b"license"))
    return data.getvalue()


class Bucket:
    """Serves files under states/<DAY>/<HH>/ and S3's list-type=2 listing of them. lie: {file name: ETag} listed
    instead of the true MD5; size_extra: {file name: n} listed n bytes bigger; page: keys per listing page;
    endless: every page says there is more, with the same token; slow: files are sent a little at a time."""

    def __init__(self, root, lie=None, page=1000, size_extra=None, endless=False, slow=False):
        lie, size_extra = lie or {}, size_extra or {}

        class Handler(http.server.SimpleHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def copyfile(self, source, outputfile):
                if not slow:
                    return super().copyfile(source, outputfile)
                try:
                    while block := source.read(4096):
                        outputfile.write(block)
                        outputfile.flush()
                        time.sleep(0.05)
                except (BrokenPipeError, ConnectionResetError):
                    pass  # the fetcher was stopped: the test wants that

            def do_GET(self):
                url = urllib.parse.urlparse(self.path)
                if url.path != "/":
                    return super().do_GET()
                query = urllib.parse.parse_qs(url.query)
                prefix = query["prefix"][0]
                keys = sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())
                keys = [k for k in keys if k.startswith(prefix)]
                start = 0 if endless else int(query.get("continuation-token", ["0"])[0])
                shown = keys[start:start + page]
                more = endless or start + page < len(keys)
                items = "".join(
                    f"<Contents><Key>{k}</Key><ETag>&#34;{lie.get(k.rsplit('/', 1)[1], hashlib.md5((root / k).read_bytes()).hexdigest())}&#34;</ETag>"
                    f"<Size>{(root / k).stat().st_size + size_extra.get(k.rsplit('/', 1)[1], 0)}</Size></Contents>" for k in shown)
                body = ('<?xml version="1.0" encoding="UTF-8"?><ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
                        f"<IsTruncated>{'true' if more else 'false'}</IsTruncated>"
                        + (f"<NextContinuationToken>{start + page}</NextContinuationToken>" if more else "")
                        + items + "</ListBucketResult>").encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/xml")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        handler = functools.partial(Handler, directory=str(root))
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def put(root, hour, data, folder=None):
    path = root / "states" / DAY / f"{hour if folder is None else folder:02d}" / name(hour)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def a_day(root, skip=()):
    for hour in range(24):
        if hour not in skip:
            put(root, hour, an_hour(hour))


def fetch(out, url, day=DAY):
    return subprocess.run([sys.executable, "-I", str(FETCH), str(out), day, "--url", url, "--pause", "0"],
                          capture_output=True, text=True, timeout=60)


def files_in(out):
    return sorted(os.listdir(out)) if out.exists() else []


def test_whole_hours_are_kept_a_bad_one_leaves_nothing_and_a_rerun_resumes():
    """catches: an hour whose bytes differ from the listing's MD5 kept (its rows would be lost or wrong), a .part left behind, a rerun that fetches kept hours again or keeps a damaged one, a damaged hour left in place when its new download fails (Claude skeptic L4)"""
    with tempfile.TemporaryDirectory() as tmp:
        site, out = pathlib.Path(tmp) / "site", pathlib.Path(tmp) / "out"
        a_day(site)
        bucket = Bucket(site, lie={name(1): "0" * 32})  # the listing's MD5 for hour 01 isn't its bytes'
        try:
            r = fetch(out, bucket.url)
            assert r.returncode == 1 and name(1) in r.stderr and "MD5" in r.stderr, r
            assert files_in(out) == [name(0)], files_in(out)
        finally:
            bucket.close()
        bucket = Bucket(site)
        try:
            kept = (out / name(0)).stat().st_mtime_ns
            r = fetch(out, bucket.url)
            assert r.returncode == 0 and "24 hours" in r.stdout, r
            assert (out / name(0)).stat().st_mtime_ns == kept, "a kept hour was fetched again"
            assert (out / name(1)).read_bytes() == an_hour(1)
            spoilt = bytearray((out / name(1)).read_bytes())
            spoilt[600] ^= 0xFF
            (out / name(1)).write_bytes(bytes(spoilt))
            r = fetch(out, bucket.url)
            assert r.returncode == 0 and (out / name(1)).read_bytes() == an_hour(1), r  # fetched again
            for day in ("2022-6-27", "2022-02-30", "today"):
                assert fetch(out, bucket.url, day).returncode == 2, day
        finally:
            bucket.close()
        # A damaged kept hour whose new download fails too: removed, not left under its name.
        (out / name(1)).write_bytes(bytes(spoilt))
        bucket = Bucket(site, lie={name(1): "0" * 32})
        try:
            r = fetch(out, bucket.url)
            assert r.returncode == 1 and name(1) not in files_in(out), (r, files_in(out))
            assert not [n for n in files_in(out) if n.endswith(".part")]
        finally:
            bucket.close()


def test_a_day_must_be_its_24_hours():
    """catches: a day with hours missing taken as whole (Codex), a day with no files, or a file in the wrong hour's folder kept under another hour's name (Claude skeptic L1)"""
    with tempfile.TemporaryDirectory() as tmp:
        site, out = pathlib.Path(tmp) / "site", pathlib.Path(tmp) / "out"
        a_day(site, skip=(13,))
        bucket = Bucket(site)
        try:
            r = fetch(out, bucket.url)
            assert r.returncode == 1 and "not the 24 hours" in r.stderr and files_in(out) == [], r
            r = fetch(out, bucket.url, "2022-06-20")
            assert r.returncode == 1 and "none" in r.stderr, r
            put(site, 13, an_hour(13))
            put(site, 14, an_hour(14), folder=3)  # hour 14's file in hour 03's folder too
            r = fetch(out, bucket.url)
            assert r.returncode == 1 and "named for hour 14" in r.stderr and files_in(out) == [], r
        finally:
            bucket.close()


def test_a_file_that_isnt_one_csv_gz_or_of_another_size_is_refused():
    """catches: a tar holding two CSVs (import would read both as one hour) or none kept as an hour, or a file whose size isn't the listing's kept because its MD5 matched (Codex)"""
    with tempfile.TemporaryDirectory() as tmp:
        site, out = pathlib.Path(tmp) / "site", pathlib.Path(tmp) / "out"
        a_day(site)
        for data in (an_hour(0, csv_files=2), an_hour(0, csv_files=0)):
            put(site, 0, data)
            bucket = Bucket(site)
            try:
                r = fetch(out, bucket.url)
                assert r.returncode == 1 and "one .csv.gz" in r.stderr and files_in(out) == [], (r, files_in(out))
            finally:
                bucket.close()
        put(site, 0, an_hour(0))
        bucket = Bucket(site, size_extra={name(0): 1})
        try:
            r = fetch(out, bucket.url)
            assert r.returncode == 1 and "bytes" in r.stderr and files_in(out) == [], (r, files_in(out))
        finally:
            bucket.close()


def multipart_etag(data, mib):
    """S3's ETag for data uploaded in parts of mib MiB."""
    part = mib << 20
    digests = b"".join(hashlib.md5(data[i:i + part]).digest() for i in range(0, len(data), part))
    return f"{hashlib.md5(digests).hexdigest()}-{-(-len(data) // part)}"


def test_a_listing_in_pages_is_read_to_its_end_and_multipart_etags_are_checked():
    """catches: only the listing's first page read (hours silently missing from the day), a listing that never ends followed forever (Claude skeptic M3), or a file uploaded in parts (OpenSky's hours 14-17 of 2022-06-27: "...-42") refused, or kept unchecked when its parts' MD5s don't match"""
    with tempfile.TemporaryDirectory() as tmp:
        site, out = pathlib.Path(tmp) / "site", pathlib.Path(tmp) / "out"
        a_day(site)
        bucket = Bucket(site, page=5)
        try:
            r = fetch(out, bucket.url)
            assert r.returncode == 0 and "24 hours" in r.stdout and len(files_in(out)) == 24, (r, files_in(out))
        finally:
            bucket.close()
        bucket = Bucket(site, page=5, endless=True)
        try:
            r = fetch(out, bucket.url)
            assert r.returncode == 1 and "no new token" in r.stderr, r
        finally:
            bucket.close()
        # Hour 05 uploaded in parts (padded to 12 MiB): its multipart ETag is checked part by part.
        big = an_hour(5) + b"\0" * ((12 << 20) - len(an_hour(5)))  # zero blocks end a tar: still one .csv.gz
        put(site, 5, big)
        bucket = Bucket(site, lie={name(5): "0123456789abcdef0123456789abcdef-3"})  # 3 parts, wrong MD5s
        try:
            r = fetch(out, bucket.url)
            assert r.returncode == 1 and name(5) in r.stderr and name(5) not in files_in(out), r
        finally:
            bucket.close()
        for mib in (5, 8):  # 3 parts of 5 MiB, 2 of 8 MiB
            bucket = Bucket(site, lie={name(5): multipart_etag(big, mib)})
            try:
                (out / name(5)).unlink(missing_ok=True)
                r = fetch(out, bucket.url)
                assert r.returncode == 0 and (out / name(5)).read_bytes() == big, (mib, r)
            finally:
                bucket.close()
        bucket = Bucket(site, lie={name(5): "not-an-etag"})
        try:
            (out / name(5)).unlink()
            r = fetch(out, bucket.url)
            assert r.returncode == 1 and "neither an MD5" in r.stderr, r
        finally:
            bucket.close()


def test_a_stopped_download_leaves_no_part_file():
    """catches: a .part left behind when the download is stopped (kill, Ctrl-C) halfway (Claude skeptic: the stop handler was untested)"""
    with tempfile.TemporaryDirectory() as tmp:
        site, out = pathlib.Path(tmp) / "site", pathlib.Path(tmp) / "out"
        a_day(site)
        put(site, 0, an_hour(0) + b"\0" * (2 << 20))  # 2 MiB more: sent slowly, so the stop comes halfway
        bucket = Bucket(site, slow=True)
        run = subprocess.Popen([sys.executable, "-I", str(FETCH), str(out), DAY, "--url", bucket.url, "--pause", "0"],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            part = out / (name(0) + ".part")
            for _ in range(200):
                if part.exists() and part.stat().st_size > 0:
                    break
                time.sleep(0.05)
            assert part.exists(), "the download never started"
            run.send_signal(signal.SIGTERM)
            run.wait(timeout=30)
            assert run.returncode != 0 and files_in(out) == [], (run.returncode, files_in(out))
        finally:
            if run.poll() is None:
                run.kill()
            bucket.close()
