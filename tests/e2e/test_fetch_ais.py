"""tools/fetch-ais.sh (step 15) against a fake MarineCadastre on 127.0.0.1 (AIS_URL): a day is kept only whole (its
size = the server's Content-Length and `unzip -t` passes), a bad one leaves nothing, a rerun resumes."""
import functools
import http.server
import io
import os
import pathlib
import subprocess
import tempfile
import threading
import zipfile

FETCH = pathlib.Path(__file__).resolve().parents[2] / "tools" / "fetch-ais.sh"


def a_day(name):
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(name.replace(".zip", ".csv"), "MMSI,BaseDateTime,LAT,LON\n1,2023-01-01T00:00:00,29.7,-95.0\n")
    return data.getvalue()


class Server:
    def __init__(self, root, head_extra=0):
        class Quiet(http.server.SimpleHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def send_header(self, key, value):  # head_extra: HEAD states a size the GET won't send
                if key == "Content-Length" and self.command == "HEAD":
                    value = str(int(value) + head_extra)
                super().send_header(key, value)

        handler = functools.partial(Quiet, directory=str(root))
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def fetch(out, url, first, last):
    return subprocess.run(["bash", str(FETCH), str(out), first, last], capture_output=True, text=True, timeout=60,
                          env={**os.environ, "AIS_URL": url})


def test_whole_days_are_kept_a_bad_one_leaves_nothing_and_a_rerun_resumes():
    """catches: a corrupt or cut-off zip kept as a day (its rows would be lost or half-read by import), a .part file left behind, or a rerun that fetches kept days again or misses one"""
    with tempfile.TemporaryDirectory() as tmp:
        site, out = pathlib.Path(tmp) / "site" / "2023", pathlib.Path(tmp) / "out"
        site.mkdir(parents=True)
        (site / "AIS_2023_01_01.zip").write_bytes(a_day("AIS_2023_01_01.zip"))
        good = a_day("AIS_2023_01_02.zip")
        (site / "AIS_2023_01_02.zip").write_bytes(good[:20] + b"\x00" * (len(good) - 20))  # right size, not a zip
        server = Server(site.parent)
        try:
            r = fetch(out, server.url, "2023-01-01", "2023-01-02")
            assert r.returncode == 1 and "AIS_2023_01_02.zip failed" in r.stderr, r
            assert sorted(os.listdir(out)) == ["AIS_2023_01_01.zip"], os.listdir(out)
            kept = (out / "AIS_2023_01_01.zip").stat().st_mtime_ns
            (site / "AIS_2023_01_02.zip").write_bytes(good)
            r = fetch(out, server.url, "2023-01-01", "2023-01-02")
            assert r.returncode == 0 and "2 days" in r.stdout, r
            assert (out / "AIS_2023_01_01.zip").stat().st_mtime_ns == kept, "a kept day was fetched again"
            assert (out / "AIS_2023_01_02.zip").read_bytes() == good
            r = fetch(out, server.url, "2023-01-03", "2023-01-03")
            assert r.returncode == 1 and "no " in r.stderr, r  # a day the server doesn't have
            assert fetch(out, server.url, "2023-1-1", "2023-01-02").returncode == 2
            # A day that doesn't exist (macOS's date would read it as March 1st) and a range backwards: refused.
            for first, last in [("2023-02-29", "2023-03-01"), ("2023-01-02", "2023-01-01"), ("2023-99-99", "2023-12-01")]:
                assert fetch(out, server.url, first, last).returncode == 2, (first, last)
            # A kept day damaged inside (its list of files still readable) is fetched again (Codex, step 15).
            kept = bytearray((out / "AIS_2023_01_01.zip").read_bytes())
            kept[40] ^= 0xFF  # in the compressed CSV, before the directory at the end
            (out / "AIS_2023_01_01.zip").write_bytes(bytes(kept))
            r = fetch(out, server.url, "2023-01-01", "2023-01-01")
            assert r.returncode == 0 and (out / "AIS_2023_01_01.zip").read_bytes() == (site / "AIS_2023_01_01.zip").read_bytes(), r
            # An empty file where a kept day should be is fetched again.
            (out / "AIS_2023_01_01.zip").write_bytes(b"")
            r = fetch(out, server.url, "2023-01-01", "2023-01-01")
            assert r.returncode == 0 and (out / "AIS_2023_01_01.zip").read_bytes() == (site / "AIS_2023_01_01.zip").read_bytes(), r
        finally:
            server.close()


def test_a_day_that_isnt_one_csv_is_refused():
    """catches: a downloaded zip holding two files kept as a day (Claude skeptic, step 15): import would read only one of them"""
    with tempfile.TemporaryDirectory() as tmp:
        site, out = pathlib.Path(tmp) / "site" / "2023", pathlib.Path(tmp) / "out"
        site.mkdir(parents=True)
        data = io.BytesIO()
        with zipfile.ZipFile(data, "w") as z:
            z.writestr("AIS_2023_01_01.csv", "MMSI,BaseDateTime,LAT,LON\n")
            z.writestr("extra.csv", "MMSI,BaseDateTime,LAT,LON\n")
        (site / "AIS_2023_01_01.zip").write_bytes(data.getvalue())
        server = Server(site.parent)
        try:
            r = fetch(out, server.url, "2023-01-01", "2023-01-01")
            assert r.returncode == 1 and "failed" in r.stderr and os.listdir(out) == [], (r, os.listdir(out))
        finally:
            server.close()


def test_a_download_of_another_size_than_the_server_said_is_refused():
    """catches: a cut-off or padded download kept because the size check is gone or compares the wrong numbers (Claude skeptic, step 15)"""
    with tempfile.TemporaryDirectory() as tmp:
        site, out = pathlib.Path(tmp) / "site" / "2023", pathlib.Path(tmp) / "out"
        site.mkdir(parents=True)
        (site / "AIS_2023_01_01.zip").write_bytes(a_day("AIS_2023_01_01.zip"))
        server = Server(site.parent, head_extra=7)
        try:
            r = fetch(out, server.url, "2023-01-01", "2023-01-01")
            assert r.returncode == 1 and "failed" in r.stderr, r
            assert os.listdir(out) == [], os.listdir(out)  # no .part left
        finally:
            server.close()
