"""tools/fetch-gbif.py (step 18) against a fake GBIF API on 127.0.0.1 (--url): the download is asked for at most once
(an earlier one with the same query is used; the request is never retried), with the login from a private netrc file,
never sent on a redirect; waited for; kept only whole (GBIF's size, one .csv, its CRC); a rerun never asks again."""
import base64
import http.server
import io
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import threading
import zipfile

FETCH = pathlib.Path(__file__).resolve().parents[2] / "tools" / "fetch-gbif.py"
KEY = "0012345-261102120000000"
LOGIN = "Basic " + base64.b64encode(b"user:secret").decode()


def a_zip(files=("0012345-261102120000000.csv",)):
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w", zipfile.ZIP_STORED) as z:  # stored: a flipped byte is in the CSV itself
        for name in files:
            z.writestr(name, "gbifID\tdecimalLatitude\tdecimalLongitude\n1\t50.0\t8.5\n" * 20)
    return data.getvalue()


def damaged(data):
    """The same zip, the same size, one byte of the CSV changed (its CRC no longer matches)."""
    data = bytearray(data)
    data[data.index(b"8.5\n") + 2] ^= 0x01
    return bytes(data)


def deflated_damaged():
    """A deflated zip with a byte of its compressed data changed: reading it fails inside zlib (Codex, round 2)."""
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(f"{KEY}.csv", "".join(f"{i}\t{i % 80}.5\t{i % 170}.25\n" for i in range(5000)))
    data = bytearray(data.getvalue())
    data[60] ^= 0xFF  # inside the compressed CSV, after its 30 + name bytes of local header
    return bytes(data)


def unreadable_method(data):
    """The stored zip relabelled as compressed with Deflate64 (method 9), which Python's zipfile can't read."""
    data = bytearray(data)
    for signature, offset in ((b"PK\x03\x04", 8), (b"PK\x01\x02", 10)):
        at = data.index(signature)
        data[at + offset:at + offset + 2] = (9).to_bytes(2, "little")
    return bytes(data)


def a_request(year="2024", shape="ours"):
    """A download's request as GBIF lists it: "ours" as this script sends it, "gbif" as GBIF stores it (matchCase,
    type, the predicates in another order)."""
    year_p = {"type": "equals", "key": "YEAR", "value": year}
    coord = {"type": "equals", "key": "HAS_COORDINATE", "value": "true"}
    if shape == "gbif":
        year_p, coord = {**year_p, "matchCase": False}, {**coord, "matchCase": False}
        return {"predicate": {"type": "and", "predicates": [year_p, coord]}, "sendNotification": False,
                "format": "SIMPLE_CSV", "type": "OCCURRENCE", "creator": "user"}
    return {"format": "SIMPLE_CSV", "predicate": {"type": "and", "predicates": [coord, year_p]}}


def listed(key, status, created, request):
    return {"key": key, "status": status, "created": created, "request": request}


class Server:
    def __init__(self, handler):
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class Gbif(Server):
    """A fake GBIF: POST /occurrence/download/request (wants the login) → KEY, and the download is then the user's;
    GET /occurrence/download/user/user (wants the login) → the user's downloads; GET /occurrence/download/KEY →
    statuses in turn (the last repeats); GET /dl/KEY.zip → the zip. post_fails: the request is taken, then answered
    503. size_extra: GBIF states a size the zip hasn't. user_redirect: the user's list answers 302 to that URL."""

    def __init__(self, statuses=("RUNNING", "SUCCEEDED"), data=None, size_extra=0, post_fails=False, user_redirect=None,
                 earlier=None, post_redirect=None):
        self.posts, self.bodies, self.downloads = 0, [], list(earlier or [])
        self.data = a_zip() if data is None else data
        statuses = list(statuses)
        fake = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def reply(self, code, body, kind="application/json", extra=()):
                self.send_response(code)
                self.send_header("Content-Type", kind)
                self.send_header("Content-Length", str(len(body)))
                for k, v in extra:
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                body = self.rfile.read(int(self.headers["Content-Length"]))
                if self.headers.get("Authorization") != LOGIN:
                    return self.reply(401, b"")
                if post_redirect:
                    return self.reply(307, b"", extra=[("Location", post_redirect)])
                fake.posts += 1
                fake.bodies.append(json.loads(body))
                fake.downloads.append({"key": KEY, "status": "RUNNING", "created": "2026-11-02T12:00:00",
                                       "request": json.loads(body)})
                if post_fails:
                    return self.reply(503, b"")
                self.reply(201, KEY.encode(), "text/plain")

            def do_GET(self):
                if self.path.startswith("/occurrence/download/user/"):
                    if self.headers.get("Authorization") != LOGIN:
                        return self.reply(401, b"")
                    if user_redirect:
                        return self.reply(302, b"", extra=[("Location", user_redirect)])
                    return self.reply(200, json.dumps({"results": fake.downloads}).encode())
                if self.path == f"/occurrence/download/{KEY}":
                    status = statuses.pop(0) if len(statuses) > 1 else statuses[0]
                    info = {"key": KEY, "status": status, "doi": "10.15468/dl.test", "totalRecords": 20,
                            "size": len(fake.data) + size_extra, "downloadLink": f"{fake.url}/dl/{KEY}.zip"}
                    return self.reply(200, json.dumps(info).encode())
                if self.path == f"/dl/{KEY}.zip":
                    return self.reply(200, fake.data, "application/zip")
                self.reply(404, b"")

        super().__init__(Handler)


class Catcher(Server):
    """Another host: records the Authorization header of anything sent to it."""

    def __init__(self):
        self.seen = []
        catcher = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                catcher.seen.append(self.headers.get("Authorization"))
                self.send_response(200)
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"{}")

            do_POST = do_GET

        super().__init__(Handler)


def a_login(tmp, text="machine api.gbif.org login user password secret\n", mode=0o600):
    path = pathlib.Path(tmp) / "gbif.netrc"
    path.write_text(text)
    path.chmod(mode)
    return path


def fetch(out, url, netrc_file, year="2024"):
    return subprocess.run([sys.executable, "-I", str(FETCH), str(out), year, "--url", url, "--netrc", str(netrc_file),
                           "--poll", "0"], capture_output=True, text=True, timeout=60)


def test_the_download_is_requested_once_waited_for_kept_whole_and_a_rerun_doesnt_ask_again():
    """catches: a rerun that asks GBIF for a new download (hours of GBIF's work each time), the wrong query sent (another year, records without coordinates), the zip kept before GBIF says it is done, or the password printed"""
    with tempfile.TemporaryDirectory() as tmp:
        out, gbif = pathlib.Path(tmp) / "out", Gbif(statuses=("PREPARING", "RUNNING", "SUCCEEDED"))
        try:
            r = fetch(out, gbif.url, a_login(tmp))
            assert r.returncode == 0 and KEY in r.stdout and "10.15468/dl.test" in r.stdout, r
            assert "secret" not in r.stdout + r.stderr
            assert (out / f"{KEY}.zip").read_bytes() == gbif.data
            assert json.loads((out / "download.json").read_text())["totalRecords"] == 20
            predicates = {p["key"]: p["value"] for p in gbif.bodies[0]["predicate"]["predicates"]}
            assert predicates == {"HAS_COORDINATE": "true", "YEAR": "2024"} and gbif.bodies[0]["format"] == "SIMPLE_CSV"
            kept = (out / f"{KEY}.zip").stat().st_mtime_ns
            r = fetch(out, gbif.url, a_login(tmp))
            assert r.returncode == 0 and gbif.posts == 1, (r, gbif.posts)
            assert (out / f"{KEY}.zip").stat().st_mtime_ns == kept, "a kept zip was fetched again"
            (out / f"{KEY}.zip").write_bytes(damaged(gbif.data))  # a kept zip damaged, the same size: fetched again
            r = fetch(out, gbif.url, a_login(tmp))
            assert r.returncode == 0 and (out / f"{KEY}.zip").read_bytes() == gbif.data and gbif.posts == 1, r
            r = fetch(out, gbif.url, a_login(tmp), year="2023")  # the folder holds 2024's download
            assert r.returncode == 1 and "2024" in r.stderr and gbif.posts == 1, r
            assert fetch(out, gbif.url, a_login(tmp), year="99").returncode == 2
        finally:
            gbif.close()


def test_a_request_whose_answer_is_lost_is_not_sent_again():
    """catches: the download request retried after GBIF took it but its answer failed (two downloads, both prepared by GBIF: Claude skeptic M1, Codex), or a rerun that asks again instead of finding the first; an earlier download of another year used"""
    with tempfile.TemporaryDirectory() as tmp:
        out, gbif = pathlib.Path(tmp) / "out", Gbif(post_fails=True)
        try:
            r = fetch(out, gbif.url, a_login(tmp))
            assert r.returncode == 1 and "rerun looks for it" in r.stderr and gbif.posts == 1, (r, gbif.posts)
            assert not (out / "state.json").exists()
            r = fetch(out, gbif.url, a_login(tmp))  # GBIF has it: found among the user's downloads, not asked again
            assert r.returncode == 0 and "asked for earlier" in r.stdout and gbif.posts == 1, (r, gbif.posts)
            assert (out / f"{KEY}.zip").read_bytes() == gbif.data
        finally:
            gbif.close()
        other_year = {"key": "0000001-000000000000000", "status": "SUCCEEDED", "created": "2026-11-02T13:00:00",
                      "request": {"format": "SIMPLE_CSV", "predicate": {"type": "and", "predicates": [
                          {"type": "equals", "key": "HAS_COORDINATE", "value": "true"},
                          {"type": "equals", "key": "YEAR", "value": "2023"}]}}}
        out2, gbif = pathlib.Path(tmp) / "out2", Gbif(earlier=[other_year])
        try:
            r = fetch(out2, gbif.url, a_login(tmp))
            assert r.returncode == 0 and gbif.posts == 1 and json.loads((out2 / "state.json").read_text())["key"] == KEY, r
        finally:
            gbif.close()


def test_the_login_is_never_sent_elsewhere_or_shown():
    """catches: the GBIF password sent on to another host by a redirect (Claude skeptic M2) or over plain http, or part of it printed by netrc's error message (skeptic L2)"""
    with tempfile.TemporaryDirectory() as tmp:
        catcher = Catcher()
        gbif = Gbif(user_redirect=f"{catcher.url}/elsewhere")
        try:
            r = fetch(pathlib.Path(tmp) / "out", gbif.url, a_login(tmp))
            assert r.returncode == 1 and "redirected" in r.stderr and catcher.seen == [] and gbif.posts == 0, (r, catcher.seen)
        finally:
            gbif.close()
            catcher.close()
        r = fetch(pathlib.Path(tmp) / "out", "http://gbif.invalid/v1", a_login(tmp))
        assert r.returncode == 1 and "only over https" in r.stderr, r
        r = fetch(pathlib.Path(tmp) / "out", "http://127.0.0.1:9/v1",
                  a_login(tmp, "machine api.gbif.org login user password correct horse battery\n"))
        assert r.returncode == 1 and "horse" not in r.stderr and "battery" not in r.stderr, r


def test_a_bad_or_unsafe_login_is_refused_before_anything_is_asked():
    """catches: a login file others can read used anyway, a placeholder or missing login sent, or a refused login taken for a download"""
    with tempfile.TemporaryDirectory() as tmp:
        out, gbif = pathlib.Path(tmp) / "out", Gbif()
        try:
            r = fetch(out, gbif.url, a_login(tmp, mode=0o644))
            assert r.returncode == 1 and "chmod 600" in r.stderr and gbif.posts == 0, r
            r = fetch(out, gbif.url, a_login(tmp, "machine api.gbif.org login YOUR_GBIF_USERNAME password YOUR_GBIF_PASSWORD\n"))
            assert r.returncode == 1 and "no GBIF login" in r.stderr and gbif.posts == 0, r
            r = fetch(out, gbif.url, pathlib.Path(tmp) / "missing.netrc")
            assert r.returncode == 1 and "no " in r.stderr, r
            r = fetch(out, gbif.url, a_login(tmp, "machine api.gbif.org login user password wrong\n"))
            assert r.returncode == 1 and "refused the login" in r.stderr and "wrong" not in r.stderr, r
            assert not (out / "state.json").exists()
        finally:
            gbif.close()


def test_a_failed_download_or_a_bad_zip_leaves_nothing():
    """catches: a download GBIF gave up on waited for forever, an unknown status waited on forever, a zip of another size, with two files (import would read one) or damaged inside at the same size (Codex) kept, or a .part left behind"""
    with tempfile.TemporaryDirectory() as tmp:
        for gbif, says in [(Gbif(statuses=("RUNNING", "FAILED")), "FAILED"), (Gbif(statuses=("ODD",)), "'ODD'"),
                           (Gbif(size_extra=5), "bytes"), (Gbif(data=a_zip(("a.csv", "b.csv"))), "one whole .csv"),
                           (Gbif(data=damaged(a_zip())), "CRC")]:
            out = pathlib.Path(tmp) / f"out-{len(os.listdir(tmp))}"
            try:
                r = fetch(out, gbif.url, a_login(tmp))
                assert r.returncode == 1 and says in r.stderr, (says, r)
                assert sorted(os.listdir(out)) in (["state.json"], ["download.json", "state.json"]), os.listdir(out)
            finally:
                gbif.close()


def test_a_download_key_from_any_source_must_be_a_key():
    """catches: a key from GBIF's list of downloads or from state.json used as a file name or URL path unchecked: '../victim/important' deleted a file outside the folder (Claude skeptic and Codex, round 2)"""
    with tempfile.TemporaryDirectory() as tmp:
        victim = pathlib.Path(tmp) / "victim"
        victim.mkdir()
        (victim / "important.zip").write_bytes(b"keep me")
        out = pathlib.Path(tmp) / "out"
        gbif = Gbif(earlier=[listed("../victim/important", "SUCCEEDED", "2026-11-02T13:00:00", a_request())])
        try:
            r = fetch(out, gbif.url, a_login(tmp))
            assert r.returncode == 1 and "not a GBIF download key" in r.stderr and gbif.posts == 0, r
            assert (victim / "important.zip").read_bytes() == b"keep me"
            for key in ("/etc/passwd", "a/b", "..", "0012345-2611021200.zip", ""):
                (out / "state.json").write_text(json.dumps({"year": 2024, "key": key}))
                r = fetch(out, gbif.url, a_login(tmp))
                assert r.returncode == 1 and "not a GBIF download key" in r.stderr, (key, r)
        finally:
            gbif.close()


def test_the_newest_good_download_with_the_same_query_is_used():
    """catches: a FAILED download with the same query adopted, an older one used before a newer, or the query not recognised in the shape GBIF stores it (matchCase, type, another order: Claude skeptic, round 2), each costing GBIF a second download"""
    with tempfile.TemporaryDirectory() as tmp:
        earlier = [listed("0000009-000000000000009", "FAILED", "2026-11-02T15:00:00", a_request()),
                   listed(KEY, "SUCCEEDED", "2026-11-02T14:00:00", a_request(shape="gbif")),
                   listed("0000008-000000000000008", "SUCCEEDED", "2026-11-02T13:00:00", a_request()),
                   listed("0000007-000000000000007", "SUCCEEDED", "2026-11-02T16:00:00", a_request(year="2023"))]
        out, gbif = pathlib.Path(tmp) / "out", Gbif(earlier=earlier)
        try:
            r = fetch(out, gbif.url, a_login(tmp))
            assert r.returncode == 0 and gbif.posts == 0 and "asked for earlier" in r.stdout, (r, gbif.posts)
            assert json.loads((out / "state.json").read_text())["key"] == KEY
        finally:
            gbif.close()


def test_the_request_is_not_sent_on_a_redirect_and_damaged_zips_of_any_kind_are_refused():
    """catches: the login and query sent on by a redirect of the request itself, a deflated zip damaged inside crashing every run instead of being fetched again (Codex, round 2), or a zip Python can't read (Deflate64) not handed to unzip (Claude skeptic, round 2)"""
    with tempfile.TemporaryDirectory() as tmp:
        catcher = Catcher()
        gbif = Gbif(post_redirect=f"{catcher.url}/elsewhere")
        try:
            r = fetch(pathlib.Path(tmp) / "out-redirect", gbif.url, a_login(tmp))
            assert r.returncode == 1 and "redirected" in r.stderr and catcher.seen == [], (r, catcher.seen)
        finally:
            gbif.close()
            catcher.close()
        for data, label in [(deflated_damaged(), "deflated"), (unreadable_method(a_zip()), "Deflate64")]:
            out, gbif = pathlib.Path(tmp) / f"out-{label}", Gbif(data=data)
            try:
                r = fetch(out, gbif.url, a_login(tmp))
                assert r.returncode == 1 and "CRC" in r.stderr and "Traceback" not in r.stderr, (label, r)
                assert sorted(os.listdir(out)) == ["download.json", "state.json"], (label, os.listdir(out))
            finally:
                gbif.close()
        # A deflated zip damaged after it was kept: found, fetched again, not a crash.
        out, gbif = pathlib.Path(tmp) / "out-kept", Gbif()
        try:
            assert fetch(out, gbif.url, a_login(tmp)).returncode == 0
            (out / f"{KEY}.zip").write_bytes(deflated_damaged()[:len(gbif.data)].ljust(len(gbif.data), b"\0"))
            r = fetch(out, gbif.url, a_login(tmp))
            assert r.returncode == 0 and (out / f"{KEY}.zip").read_bytes() == gbif.data, r
        finally:
            gbif.close()
