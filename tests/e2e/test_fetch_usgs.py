"""tools/fetch-usgs.py (step 11, DESIGN §12.4) against a fake USGS event service on 127.0.0.1: windows cut until each
holds at most --page quakes, joined with no row lost or doubled, each period's rows = the service's count, server errors,
a changed header, an empty year, resuming. The fake answers like USGS (/count, and /query?format=csv&limit=N, both times
included), but sends rows newest first: USGS's own time order isn't strict, so nothing may depend on it."""
import http.server
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import threading
import urllib.parse

FETCH = pathlib.Path(__file__).resolve().parents[2] / "tools" / "fetch-usgs.py"
HEADER = ("time,latitude,longitude,depth,mag,magType,nst,gap,dmin,rms,net,id,updated,place,type,horizontalError,"
          "depthError,magError,magNst,status,locationSource,magSource")


def quake(time, n, lat=35.5, lon=139.5):
    """One CSV row in USGS's layout; the place has a comma inside quotes, as USGS's do."""
    return (f"{time}Z,{lat},{lon},10,4.5,mb,,,,,us,us{n:06d},2026-01-01T00:00:00.000Z,"
            f"\"{n} km E of Somewhere, Japan\",earthquake,,,,,reviewed,us,us")


class Fake:
    """A fake event service. quakes: (time without Z, row) sorted by time; faults: changed by the tests."""

    def __init__(self, quakes):
        self.quakes = sorted(quakes)
        # count_bias: added to every count; period_bias: only to a whole year's (as if a quake came in mid-download)
        # cut: answers to send cut short, with no length header and the connection closed (as a dropped link would)
        # failing: [time, n]: the next n requests from that time on get a 503
        self.faults = dict(errors=[], count_bias=0, period_bias=0, header=HEADER, cut=0, failing=None)
        self.requests, self.cut_off = [], 0  # cut_off: answers that had more rows than their limit
        fake = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                url = urllib.parse.urlsplit(self.path)
                q = dict(urllib.parse.parse_qsl(url.query))
                fake.requests.append((url.path, q))
                if fake.faults["errors"]:
                    self.send_error(fake.faults["errors"].pop(0))
                    return
                failing = fake.faults["failing"]
                if failing and failing[1] > 0 and q["starttime"] >= failing[0]:
                    failing[1] -= 1
                    self.send_error(503)
                    return
                start, end = q["starttime"].ljust(23, "0"), q["endtime"].ljust(23, "0")
                rows = [row for time, row in fake.quakes if start <= time <= end]
                if url.path.endswith("/count"):
                    whole_year = start.endswith("-01-01T00:00:00.000") and end.endswith("-12-31T23:59:59.999")
                    body = f"{len(rows) + fake.faults['count_bias'] + fake.faults['period_bias'] * whole_year}\n"
                else:
                    fake.cut_off += len(rows) > int(q["limit"])
                    body = "\n".join([fake.faults["header"], *reversed(rows[-int(q["limit"]):])]) + "\n"
                data = body.encode()
                if fake.faults["cut"] and not url.path.endswith("/count"):
                    fake.faults["cut"] -= 1
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(data[:-2])  # inside the last row's last value: still 22 columns
                    return
                self.send_response(200)
                self.send_header("Content-Type", "text/csv")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}/fdsnws/event/1"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def fetch(out, fake, *extra, since="1990-01-01", until="1993-01-01"):
    return subprocess.run([sys.executable, "-I", "-B", str(FETCH), str(out), "--since", since, "--until", until,
                           "--pause", "0", "--page", "5", "--url", fake.url, *extra],
                          capture_output=True, text=True, timeout=60)


def rows_of(path):
    lines = pathlib.Path(path).read_text().splitlines()
    assert lines[0] == HEADER, lines[:1]
    return lines[1:]


def quakes_1990s():
    """12 quakes in 1990 (3 at one time, where a page of 5 ends; the last at its last moment), 5 in 1991 (the first at
    midnight on 1 January), none in 1992."""
    times = [f"1990-0{m}-01T00:00:00.000" for m in range(1, 5)] + ["1990-05-01T12:00:00.000"] * 3 + \
        [f"1990-0{m}-01T00:00:00.000" for m in range(6, 10)] + ["1990-12-31T23:59:59.999", "1991-01-01T00:00:00.000"] + \
        [f"1991-0{m}-15T08:30:00.250" for m in range(2, 6)]
    return [(t, quake(t, n)) for n, t in enumerate(times)]


def test_windows_join_without_losing_or_doubling_rows():
    """catches: a request for more quakes than its limit (USGS then cuts rows off), rows lost or doubled where two windows meet (3 quakes at one time, a quake at midnight on 1 January: USGS's end time is included), or rows taken in USGS's order"""
    fake = Fake(quakes_1990s())
    try:
        with tempfile.TemporaryDirectory() as tmp:
            result = fetch(tmp, fake)
            assert result.returncode == 0, result.stderr
            want = {"usgs-1990-01-01_1991-01-01.csv": [r for t, r in fake.quakes if t < "1991"],
                    "usgs-1991-01-01_1992-01-01.csv": [r for t, r in fake.quakes if "1991" <= t < "1992"],
                    "usgs-1992-01-01_1993-01-01.csv": []}
            assert len(want["usgs-1990-01-01_1991-01-01.csv"]) == 12 and len(want["usgs-1991-01-01_1992-01-01.csv"]) == 5
            for name, rows in want.items():
                got = rows_of(pathlib.Path(tmp) / name)
                assert sorted(got) == sorted(rows) and len(set(got)) == len(got), (name, got)
            assert fake.cut_off == 0, f"{fake.cut_off} answers were cut off at their limit"
            manifest = (pathlib.Path(tmp) / "MANIFEST.txt").read_text()
            assert "usgs-1990-01-01_1991-01-01.csv 12 12 " in manifest and "\ntotal 17 17\n" in manifest, manifest
            assert sorted(os.listdir(tmp)) == sorted([*want, "MANIFEST.txt", "state.json"]), os.listdir(tmp)
            assert all(q["eventtype"] == "earthquake" for _, q in fake.requests)
    finally:
        fake.close()


def test_server_errors_are_retried_and_a_failed_period_leaves_no_file():
    """catches: a passing server error ends the download, or a period that failed leaves a half-written file that a rerun keeps"""
    fake = Fake(quakes_1990s())
    try:
        with tempfile.TemporaryDirectory() as tmp:
            fake.faults["errors"] = [503, 500]
            assert fetch(tmp, fake).returncode == 0
            assert len(rows_of(pathlib.Path(tmp) / "usgs-1990-01-01_1991-01-01.csv")) == 12
        with tempfile.TemporaryDirectory() as tmp:
            # 1990 is fetched; then every request for 1991 fails: it is given up after 5 tries, with nothing left of it.
            fake.faults["failing"] = ["1991", 5]
            result = fetch(tmp, fake)
            assert result.returncode == 1 and "5 tries" in result.stderr, result.stderr
            # MANIFEST.txt is written only when the whole download is done.
            assert sorted(os.listdir(tmp)) == ["state.json", "usgs-1990-01-01_1991-01-01.csv"], os.listdir(tmp)
            # A rerun resumes: 1990 is not asked for again, 1991 and 1992 are fetched.
            fake.requests.clear()
            assert fetch(tmp, fake).returncode == 0
            assert all(q["starttime"] >= "1991" for _, q in fake.requests), fake.requests[:2]
            assert len(rows_of(pathlib.Path(tmp) / "usgs-1991-01-01_1992-01-01.csv")) == 5
    finally:
        fake.close()


def test_a_cut_answer_is_retried_and_other_dates_need_another_folder():
    """catches: an answer cut off inside its last column kept (the row count still matches), a second download with other dates added to a folder (its files overlap the kept ones and the totals count quakes twice), or a kept file that lost rows or changed trusted on a rerun (Claude skeptic and Codex, step 11)"""
    fake = Fake(quakes_1990s())
    try:
        with tempfile.TemporaryDirectory() as tmp:
            fake.faults["cut"] = 2
            assert fetch(tmp, fake).returncode == 0
            assert fake.faults["cut"] == 0
            rows = rows_of(pathlib.Path(tmp) / "usgs-1990-01-01_1991-01-01.csv")
            assert sorted(rows) == sorted(r for t, r in fake.quakes if t < "1991"), rows
            result = fetch(tmp, fake, until="1992-06-01")
            assert result.returncode == 2 and "another download" in result.stderr, result.stderr
            assert "\ntotal 17 17\n" in (pathlib.Path(tmp) / "MANIFEST.txt").read_text()
            (pathlib.Path(tmp) / "usgs-1991-01-01_1992-01-01.csv").write_text(HEADER + "\n")  # rows lost after the fetch
            kept = pathlib.Path(tmp) / "usgs-1990-01-01_1991-01-01.csv"
            kept.write_text(kept.read_text().replace("35.5,139.5", "35.5,139.6", 1))  # one place changed, same lines
            fake.requests.clear()
            assert fetch(tmp, fake).returncode == 0
            assert {q["starttime"][:4] for _, q in fake.requests} == {"1990", "1991"}, fake.requests[:2]  # not 1992
            assert len(rows_of(pathlib.Path(tmp) / "usgs-1991-01-01_1992-01-01.csv")) == 5
            assert "139.6" not in kept.read_text()
        with tempfile.TemporaryDirectory() as tmp:
            # A file of another download, with no state.json: refused, not left beside this download's files.
            (pathlib.Path(tmp) / "usgs-1991-01-01_1991-06-01.csv").write_text(HEADER + "\n" + fake.quakes[13][1] + "\n")
            result = fetch(tmp, fake)
            assert result.returncode == 2 and "files of another download" in result.stderr, result.stderr
    finally:
        fake.close()


def test_rows_unequal_to_the_count_and_a_changed_header_are_refused():
    """catches: a window or a whole year that lost rows (or gained some) kept as complete (the year's own count differs when quakes come in mid-download), a changed column order imported silently into the wrong columns, or more quakes in one millisecond than a request may hold"""
    fake = Fake(quakes_1990s())
    try:
        with tempfile.TemporaryDirectory() as tmp:
            fake.faults["count_bias"] = 1
            result = fetch(tmp, fake)
            assert result.returncode == 1 and "rows, USGS counts" in result.stderr, result.stderr
            assert os.listdir(tmp) == [], os.listdir(tmp)
        with tempfile.TemporaryDirectory() as tmp:
            # Every window matches its own count, but the year's count is one more: the year is refused.
            fake.faults.update(count_bias=0, period_bias=1)
            result = fetch(tmp, fake)
            assert result.returncode == 1 and "12 rows, USGS counts 13" in result.stderr, result.stderr
            assert os.listdir(tmp) == [], os.listdir(tmp)
        with tempfile.TemporaryDirectory() as tmp:
            fake.faults.update(period_bias=0, header=HEADER.replace("latitude,longitude", "longitude,latitude"))
            result = fetch(tmp, fake)
            assert result.returncode == 1 and "unexpected header" in result.stderr, result.stderr
            assert os.listdir(tmp) == [], os.listdir(tmp)
        # 6 quakes in one millisecond can't be cut into windows of 5.
        fake.faults["header"] = HEADER
        fake.quakes += [("1992-03-03T03:03:03.003", quake("1992-03-03T03:03:03.003", 100 + n)) for n in range(6)]
        fake.quakes.sort()
        with tempfile.TemporaryDirectory() as tmp:
            result = fetch(tmp, fake)
            assert result.returncode == 1 and "more than 5 quakes in one millisecond" in result.stderr, result.stderr
        for bad in (["--page", "0"], ["--page", "20001"], ["--since", "1993-01-01"]):
            with tempfile.TemporaryDirectory() as tmp:
                assert fetch(tmp, fake, *bad).returncode == 2, bad
    finally:
        fake.close()
