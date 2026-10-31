"""`gpstiles serve` over real HTTP (DESIGN §7, §9.2, step 5a): two tiny datasets built by the test, each
endpoint's status, content type and body against tests/oracle/, bad requests answered with an error
while the server keeps working, 50 requests at once, and the command's own argument errors."""
import concurrent.futures
import http.client
import importlib.util
import json
import os
import pathlib
import random
import select
import socket
import subprocess
import tempfile
import time

TESTS = pathlib.Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, TESTS / "oracle" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gpt = load("gpt_rules")
tile = load("tile_rules")


def gpstiles(*args, timeout=30):
    return subprocess.run([os.environ["GPSTILES_BIN"], *map(str, args)], capture_output=True, text=True,
                          timeout=timeout)


def make_gpt(folder, name, codes):
    pts, out = folder / f"{name}.pts", folder / f"{name}.gpt"
    pts.write_bytes(gpt.to_le_bytes(codes))
    assert gpstiles("build", "-o", out, pts).returncode == 0
    return out


class Server:
    """`gpstiles serve --port 0` on some .gpt files, stopped on exit. Its log goes to a file, so a full
    pipe can never block it."""

    def __init__(self, *files, extra=()):
        self.log = tempfile.TemporaryFile()
        self.process = subprocess.Popen([os.environ["GPSTILES_BIN"], "serve", *extra, "--port", "0", *map(str, files)],
                                        stdout=subprocess.PIPE, stderr=self.log, text=True)
        try:  # the first line names the port; a server that never says it must not hang the tests
            ready, _, _ = select.select([self.process.stdout], [], [], 10)
            line = self.process.stdout.readline() if ready else ""
            assert line.startswith("gpstiles serve: http://127.0.0.1:"), f"no address line from the server: {line!r}"
            self.port = int(line.rsplit(":", 1)[1].strip().rstrip("/"))
        except BaseException:
            self.__exit__()
            raise

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.process.kill()
        self.process.wait()
        self.process.stdout.close()
        self.log.close()

    def get(self, path, method="GET", headers=None):
        """(status, headers, body) of one request."""
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=20)
        try:
            connection.request(method, path, headers=headers or {})
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def raw(self, data, timeout=20):
        """Sends raw bytes and returns everything the server answers before it closes."""
        with socket.create_connection(("127.0.0.1", self.port), timeout=timeout) as s:
            s.sendall(data)
            chunks = []
            while chunk := s.recv(65536):
                chunks.append(chunk)
            return b"".join(chunks)


def datasets_folder(tmp):
    """Two datasets with different points: 'big' (300 clustered points) and 'small-1' (3 points)."""
    rng = random.Random(int(os.environ.get("TEST_SEED", "1")))
    cx, cy = rng.getrandbits(32), rng.getrandbits(32)
    big = [gpt.code_of(cx ^ rng.getrandbits(20), cy ^ rng.getrandbits(20)) for _ in range(300)]
    small = [gpt.code_of(10, 20), gpt.code_of(2**32 - 1, 2**31), gpt.code_of(2**31, 5)]
    return {"big": (make_gpt(tmp, "big", big), big), "small-1": (make_gpt(tmp, "small-1", small), small)}


def expected_dataset(name, codes):
    h = gpt.header(sorted(codes))
    def box(b):
        return [gpt.lon_of_x(b[0]), gpt.lat_of_y(b[3]), gpt.lon_of_x(b[2]), gpt.lat_of_y(b[1])]
    return dict(id=name, points=len(codes), bounds=box(h["bounds"]), view=box(h["view"]), max_zoom=24,
                max_pixel=h["max_pixel"])


def same_dataset(got, want):
    return (got.keys() == want.keys() and all(got[k] == want[k] for k in ("id", "points", "max_zoom", "max_pixel"))
            and all(abs(a - b) < 2e-6 for k in ("bounds", "view") for a, b in zip(got[k], want[k])))


def test_each_endpoint_answers_with_its_status_type_and_body():
    """catches: a dataset listed with another's count or bounds, a tile drawn from the wrong dataset or tile, a wrong content type"""
    with tempfile.TemporaryDirectory() as tmp:
        sets = datasets_folder(pathlib.Path(tmp))
        with Server(*(path for path, _ in sets.values())) as server:
            status, headers, body = server.get("/api/datasets")
            assert status == 200 and headers["Content-Type"] == "application/json", (status, headers)
            listed = json.loads(body)["datasets"]
            assert [d["id"] for d in listed] == ["big", "small-1"], listed  # command-line order
            for got, (name, (_, codes)) in zip(listed, sets.items()):
                assert same_dataset(got, expected_dataset(name, codes)), (got, expected_dataset(name, codes))
                status, headers, body = server.get(f"/api/datasets/{name}")
                assert status == 200 and headers["Content-Type"] == "application/json"
                assert same_dataset(json.loads(body), expected_dataset(name, codes))
                # The tile with most of this dataset's points, at zoom 6, against the Python tile.
                zoom = 6
                x, y = max(((gpt.tile_of(c, zoom)) for c in codes), key=lambda t: sum(gpt.tile_of(c, zoom) == t for c in codes))
                status, headers, body = server.get(f"/tiles/{name}/{zoom}/{x}/{y}.png")
                assert status == 200 and headers["Content-Type"] == "image/png", (status, headers)
                counts = tile.pixel_counts(codes, zoom, x, y, gpt.x_of, gpt.y_of)
                assert int(headers["X-Points"]) == sum(counts.values()) > 0
                width, height, rows = tile.decode_png(body)
                max_count = gpt.header(sorted(codes))["max_pixel"][zoom]
                assert (width, height) == (256, 256)
                for py in range(256):
                    for px in range(256):
                        assert rows[py][px] == tile.color(counts.get((px, py), 0), max_count), (name, px, py)


def bad_requests():
    """(request bytes, expected status) for requests that must be refused. Each has a valid Host header
    unless the Host is what is wrong."""
    def get(target, host=b"Host: 127.0.0.1\r\n", version=b"HTTP/1.1"):
        return b"GET " + target + b" " + version + b"\r\n" + host + b"\r\n"
    long_target = b"/" + b"a" * 10_000
    return [
        (get(b"/nope"), 404),
        (get(b"/api/datasets/nope"), 404),
        (get(b"/api/datasets/big/extra"), 404),
        (get(b"/tiles/nope/0/0/0.png"), 404),
        (get(b"/tiles/big/25/0/0.png"), 404),
        (get(b"/tiles/big/1/2/0.png"), 404),
        (get(b"/tiles/big/1/0/2.png"), 404),
        (get(b"/tiles/big/0/0/0.jpg"), 404),
        (get(b"/tiles/big/0/0/0/0.png"), 404),
        (get(b"/tiles/big/z/0/0.png"), 400),
        (get(b"/tiles/big/-1/0/0.png"), 400),
        (get(b"/tiles/big/1/+1/0.png"), 400),
        (get(b"/tiles/big/99999999999/0/0.png"), 400),
        (get(b"/tiles/big//0/0.png"), 400),
        (b"POST /api/datasets HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Length: 0\r\n\r\n", 405),
        (b"DELETE /tiles/big/0/0/0.png HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n", 405),
        (get(b"/api/datasets", b"Host: evil.example\r\n"), 403),  # DNS rebinding
        (get(b"/api/datasets", b"Host: localhost.evil.example:8080\r\n"), 403),
        (get(b"/api/datasets", b"Host: 127.0.0.1.nip.io\r\n"), 403),
        (get(b"/api/datasets", b"Host : evil.example\r\n"), 400),  # a space before the colon
        (get(b"/api/datasets", b"Host : evil.example\r\n", b"HTTP/1.0"), 400),  # ... where Host isn't required
        (get(b"/api/datasets", b""), 400),  # HTTP/1.1 without Host
        (get(b"/api/datasets", b"Host: 127.0.0.1\r\nHost: evil.example\r\n"), 400),
        (get(b"/api/datasets", b"Host: 127.0.0.1\r\nNo-colon-here\r\n"), 400),
        (get(long_target), 414),
        (get(b"/api/datasets", b"Host: 127.0.0.1\r\nX-Pad: " + b"b" * 10_000 + b"\r\n"), 431),
        (b"GET /api/datasets\r\nHost: 127.0.0.1\r\n\r\n", 400),
        (get(b"api/datasets"), 400),
        (get(b"/api/datasets", version=b"FTP/1.0"), 400),
        (get(b"/api/datasets", version=b"HTTP/1."), 400),
        (get(b"/api/datasets", version=b"HTTP/1.garbage"), 400),
        (get(b"/api/datasets", version=b"HTTP/1.1 extra"), 400),
        (b"\x00\x01\x02\r\n\r\n", 400),
        (get(b"/api/data\x00sets"), 400),
    ]


def test_bad_requests_get_an_error_and_the_next_request_still_works():
    """catches: a crash, hang or wrong answer on a malformed URL or request line, a bad header, a huge request line or headers, a foreign Host, or a method other than GET and HEAD"""
    with tempfile.TemporaryDirectory() as tmp:
        sets = datasets_folder(pathlib.Path(tmp))
        with Server(*(path for path, _ in sets.values())) as server:
            for request, want in bad_requests():
                answer = server.raw(request)
                head, _, body = answer.partition(b"\r\n\r\n")
                assert head.startswith(f"HTTP/1.1 {want} ".encode()), (request[:80], answer[:200])
                assert b"Content-Type: text/plain" in head, answer[:300]
                # A one-line message that starts with the status, and a Content-Length that is its length.
                assert body.startswith(f"{want} ".encode()) and body.endswith(b"\n") and body.count(b"\n") == 1, body
                assert f"Content-Length: {len(body)}\r\n".encode() in head + b"\r\n", (head, len(body))
                status, _, body = server.get("/api/datasets")
                assert status == 200 and len(json.loads(body)["datasets"]) == 2, (request[:80], status)
            # Hanging up before sending anything, or halfway through, doesn't hurt either; a request cut
            # short by a half-close gets its own error.
            for partial in (b"", b"GET /api/data"):
                with socket.create_connection(("127.0.0.1", server.port)) as s:
                    s.sendall(partial)
                assert server.get("/api/datasets")[0] == 200
            with socket.create_connection(("127.0.0.1", server.port), timeout=10) as s:
                s.sendall(b"GET /api/datasets HTTP/1.0\r\n")
                s.shutdown(socket.SHUT_WR)
                assert s.recv(4096).startswith(b"HTTP/1.1 400 "), "a request cut short got no answer"
            assert server.process.poll() is None, "the server stopped"


def test_50_requests_at_once_all_get_the_right_answer():
    """catches: a data race, a connection limit that drops requests, or connections served one at a time, when the browser asks for many tiles at once"""
    with tempfile.TemporaryDirectory() as tmp:
        sets = datasets_folder(pathlib.Path(tmp))
        path, codes = sets["big"]
        with Server(path) as server:
            expected = {}
            for zoom in range(3, 13):
                x, y = gpt.tile_of(codes[0], zoom)
                expected[f"/tiles/big/{zoom}/{x}/{y}.png"] = sum(gpt.tile_of(c, zoom) == (x, y) for c in codes)
            paths = [list(expected)[i % len(expected)] for i in range(50)]
            # An idle connection that never sends its request must not block the others.
            idle = socket.create_connection(("127.0.0.1", server.port))
            try:
                start = time.monotonic()
                with concurrent.futures.ThreadPoolExecutor(50) as pool:
                    results = list(pool.map(server.get, paths))
                seconds = time.monotonic() - start  # one at a time, the idle connection would stall them for 10 s
            finally:
                idle.close()
            assert seconds < 5, f"50 requests took {seconds:.1f} s"
            for p, (status, headers, body) in zip(paths, results):
                assert status == 200 and int(headers["X-Points"]) == expected[p], (p, status, headers)
                assert tile.decode_png(body)[:2] == (256, 256)


def test_other_ways_to_ask_get_the_same_answer():
    """catches: a browser at http://localhost refused, HEAD unsupported (curl -I), or a query string breaking a route"""
    with tempfile.TemporaryDirectory() as tmp:
        sets = datasets_folder(pathlib.Path(tmp))
        with Server(*(path for path, _ in sets.values())) as server:
            _, _, want = server.get("/api/datasets")
            for host in ("localhost", f"localhost:{server.port}", "LOCALHOST", "127.0.0.1", f"127.0.0.1:{server.port}",
                         "127.0.0.2", "192.168.1.20:8080", "[::1]", f"[::1]:{server.port}", "localhost "):
                status, _, body = server.get("/api/datasets", headers={"Host": host})
                assert status == 200 and body == want, (host, status)
            assert server.get("/api/datasets?x=1")[2] == want
            status, headers, png = server.get("/tiles/big/0/0/0.png?v=1")
            assert status == 200 and png.startswith(b"\x89PNG")
            status, head_headers, body = server.get("/tiles/big/0/0/0.png", method="HEAD")
            assert status == 200 and body == b"" and head_headers["Content-Length"] == str(len(png)), head_headers
            assert head_headers["X-Points"] == headers["X-Points"]
            status, headers, _ = server.get("/api/datasets", method="PUT")
            assert status == 405 and headers["Allow"] == "GET, HEAD", headers
            # On the wire, a HEAD answer ends after its headers, also when the request is refused.
            for request, want in [(b"HEAD /api/datasets HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n", 200),
                                  (b"HEAD /nope HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n", 404),
                                  (b"HEAD /api/datasets HTTP/1.1\r\nHost : x\r\n\r\n", 400)]:
                head, _, body = server.raw(request).partition(b"\r\n\r\n")
                assert head.startswith(f"HTTP/1.1 {want} ".encode()) and body == b"", (request, head, body)


def test_a_slow_client_cannot_hold_a_connection_slot():
    """catches: a timeout that restarts with every byte, so 64 clients sending a byte now and then hold every slot and the map stops answering"""
    with tempfile.TemporaryDirectory() as tmp:
        path, _ = datasets_folder(pathlib.Path(tmp))["big"]
        with Server(path, extra=("--timeout", "1")) as server:
            # 70 clients dripping one byte every 0.3 s: more than the 64 slots, each well inside a per-byte timeout.
            drips = [socket.create_connection(("127.0.0.1", server.port)) for _ in range(70)]
            answered = {}

            def normal_request():
                time.sleep(0.5)
                start = time.monotonic()
                answered["status"] = server.get("/api/datasets")[0]
                answered["seconds"] = time.monotonic() - start
            with concurrent.futures.ThreadPoolExecutor(1) as pool:
                future = pool.submit(normal_request)
                end = time.monotonic() + 4
                while time.monotonic() < end and not future.done():
                    for d in drips:
                        try:
                            d.send(b"G")
                        except OSError:
                            pass  # the server closed it: its deadline passed
                    time.sleep(0.3)
                future.result(timeout=20)
            first = drips[0].recv(4096)
            for d in drips:
                d.close()
            assert answered["status"] == 200 and answered["seconds"] < 4, answered
            assert first.startswith(b"HTTP/1.1 408 "), first[:80]


def test_the_server_does_not_grow_with_each_request():
    """catches: memory leaked on every request (a tile, JSON or error buffer not freed), which grows the server until the Mac runs out"""
    with tempfile.TemporaryDirectory() as tmp:
        path, _ = datasets_folder(pathlib.Path(tmp))["big"]
        with Server(path) as server:
            def rss():
                ps = subprocess.run(["ps", "-o", "rss=", "-p", str(server.process.pid)], capture_output=True, text=True)
                return int(ps.stdout.strip()) * 1024
            for _ in range(200):
                server.get("/tiles/big/3/1/1.png")
            before = rss()
            for i in range(2000):  # a leaked tile shows as at least one 16 KB page: 32 MB over 2,000 tiles
                assert server.get(f"/tiles/big/{i % 4}/0/0.png")[0] == 200
            grown = rss() - before
            assert grown < 16 * 2**20, f"the server grew by {grown / 2**20:.0f} MB over 2,000 tiles"
            # Small leaks (a JSON or error answer) don't show in the size: macOS's leaks tool finds them, when
            # it can look into the process (not under AddressSanitizer, which has its own allocator).
            for path in ("/api/datasets", "/api/datasets/big", "/nope", "/tiles/big/z/0/0.png") * 25:
                server.get(path)
                server.get(path, method="HEAD")
            if os.path.exists("/usr/bin/leaks") and "/san/" not in os.environ["GPSTILES_BIN"]:
                result = subprocess.run(["/usr/bin/leaks", str(server.process.pid)], capture_output=True, text=True)
                found = [line for line in result.stdout.splitlines() if " leaks for " in line]
                if found:  # leaks could look into the process
                    assert found[0].endswith(": 0 leaks for 0 total leaked bytes."), found[0]


def test_many_requests_in_a_row_are_all_answered():
    """catches: a connection slot not given back when a connection ends, so the server stops answering after 64 requests (one map session asks for hundreds of tiles)"""
    with tempfile.TemporaryDirectory() as tmp:
        sets = datasets_folder(pathlib.Path(tmp))
        path, codes = sets["big"]
        with Server(path) as server:
            for i in range(150):
                status, headers, _ = server.get(f"/tiles/big/0/0/0.png" if i % 2 else "/api/datasets/big")
                assert status == 200, (i, status)


def test_serve_refuses_bad_arguments_and_files():
    """catches: two datasets with the same id, an id that breaks URLs, a broken .gpt or a busy port accepted (or a crash) at startup"""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = pathlib.Path(tmp)
        good = make_gpt(tmp, "good", [1, 2, 3])
        (tmp / "other").mkdir()
        twin = make_gpt(tmp / "other", "good", [4])
        bad_id = tmp / "Bad Name.gpt"
        bad_id.write_bytes(good.read_bytes())
        long_id = tmp / ("a" * 33 + ".gpt")
        long_id.write_bytes(good.read_bytes())
        no_suffix = tmp / "good.bin"
        no_suffix.write_bytes(good.read_bytes())
        broken = tmp / "broken.gpt"
        broken.write_bytes(good.read_bytes()[:-1])
        cases = [([], 2, "missing"), (["--port", "65536", good], 2, "--port"), (["--port", "-1", good], 2, "--port"),
                 (["--timeout", "0", good], 2, "--timeout"), (["--timeout", "3601", good], 2, "--timeout"),
                 (["--host", "localhost", good], 2, "--host"), (["--colour", "red", good], 2, "--colour"),
                 ([good, twin], 2, "same dataset id"), ([bad_id], 2, "file name"), ([long_id], 2, "file name"),
                 ([no_suffix], 2, "file name"), ([tmp / "missing.gpt"], 1, "missing.gpt"), ([broken], 1, "broken"),
                 ([good] * 33, 2, "at most 32")]
        for args, code, word in cases:
            result = gpstiles("serve", *args, timeout=10)
            lines = result.stderr.splitlines()
            assert result.returncode == code and result.stdout == "", (args[:3], result)
            assert len(lines) == 1 and word in lines[0], (args[:3], lines)
        with Server(good) as server:  # the port is taken now
            result = gpstiles("serve", "--port", server.port, good, timeout=10)
            assert result.returncode == 1 and "can't listen" in result.stderr, result
