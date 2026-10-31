"""CSV export over real HTTP (DESIGN §7.3, §9.2, step 8): /api/datasets/{id}/export.csv has one row per point
in the box (the slow count in tests/oracle/box_rules.py), every row inside the box, the row limit kept;
clients that hang up halfway or stop reading don't hurt the server; and the page's Export link, clicked in
headless Chrome, downloads the box's rows (TESTING.md §9)."""
import csv
import importlib.util
import io
import os
import pathlib
import random
import socket
import tempfile
import time
import urllib.parse

TESTS = pathlib.Path(__file__).resolve().parents[1]


def load(name, folder="oracle"):
    spec = importlib.util.spec_from_file_location(name, TESTS / folder / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gpt, box_rules, area_test = load("gpt_rules"), load("box_rules"), load("test_area", "e2e")
Server, make_gpt, degrees = area_test.Server, area_test.make_gpt, area_test.degrees


def export(server, name, bbox, limit=None):
    """(headers, rows as 'lon,lat' text) of one export, checked to be well-formed CSV."""
    query = f"bbox={bbox}" + (f"&limit={limit}" if limit is not None else "")
    status, headers, body = server.get(f"/api/datasets/{name}/export.csv?{query}")
    assert status == 200 and headers["Content-Type"] == "text/csv; charset=utf-8", (status, headers, body[:200])
    assert headers["Content-Disposition"] == f'attachment; filename="{name}-export.csv"', headers
    text = body.decode()
    lines = list(csv.reader(io.StringIO(text)))
    assert lines[0] == ["lon", "lat"] and all(len(row) == 2 for row in lines), lines[:2]
    rows = text.splitlines()[1:]
    assert int(headers["X-Rows"]) == len(rows), (headers["X-Rows"], len(rows))
    return headers, rows


def test_export_rows_equal_the_box_count_and_are_inside_the_box():
    """catches: points on a box edge left out of the export, rows outside the box, a row repeated or lost between chunks, a wrong total"""
    rng = random.Random(int(os.environ.get("TEST_SEED", "1")))
    points = area_test.clustered_points(rng, 6000)
    with tempfile.TemporaryDirectory() as tmp:
        path = make_gpt(pathlib.Path(tmp), "pts", [gpt.code_of(x, y) for x, y in points])
        with Server(path) as server:
            for k in range(25):
                x, y = rng.choice(points)
                x2, y2 = rng.choice(points) if k % 2 else (min(x + (1 << rng.randrange(10, 28)), 2**32 - 1), min(y + (1 << 20), 2**32 - 1))
                box = (min(x, x2), min(y, y2), max(x, x2), max(y, y2))
                headers, rows = export(server, "pts", degrees(*box))
                # Each row is the middle of a point's world unit with 9 decimals, in file order (sorted by code).
                inside = [p for p in sorted(points, key=lambda p: gpt.code_of(*p)) if box_rules.inside(*p, box)]
                want = [row_of(*p, degrees(*box)) for p in inside]
                assert int(headers["X-Total-Points"]) == len(want), (k, headers["X-Total-Points"], len(want))
                assert rows == want, (k, len(rows), len(want), [r for r in rows if r not in want][:3])
                assert [unit_of(r) for r in rows] == inside  # read back, each row is its point, inside the box
            world = "-180,-85.05112877980659,180,85.05112877980659"
            assert len(export(server, "pts", world)[1]) == 6000


def row_of(x, y, bbox):
    """A point's CSV row in an export of bbox, written apart from server.c: the middle of its world unit, kept
    inside the bbox's degrees (a west edge at 180 means no limit), 9 decimals, or 17 digits when 9 would round
    it out of them or into another unit (read back as a point)."""
    w, s, e, n = map(float, bbox.split(","))
    w = -180.0 if w == 180.0 else w
    return f"{fit(box_rules.lon_of_x(x + 0.5), w, e, x, point_x)},{fit(box_rules.lat_of_y(y + 0.5), s, n, y, box_rules.world_y)}"


def fit(v, low, high, unit, to_unit):
    v = min(max(v, low), high)
    for decimals in range(9, 31):
        text = f"{v:.{decimals}f}"
        if low <= float(text) <= high and to_unit(float(text)) == unit:
            break
    return text


def point_x(lon):
    """x of a point at a longitude (DESIGN §9.4): 180 is the same place as -180, x = 0."""
    return 0 if lon == 180.0 else box_rules.world_x(lon)


def unit_of(row):
    """The world unit a CSV row names, read back as a point (DESIGN §9.4), as an import would."""
    lon, lat = map(float, row.split(","))
    return point_x(lon), box_rules.world_y(lat)


def test_every_row_reads_back_as_its_own_point_even_at_the_edges_of_the_map():
    """catches: rows rounded into a neighbouring world unit (a re-import or a box moves the point), or past the map's edge (latitude beyond 85.05112877980659 at the top row)"""
    last = 2**32 - 1
    rng = random.Random(int(os.environ.get("TEST_SEED", "1")))
    points = [(0, 0), (last, 0), (0, last), (last, last), (2**31, 0), (0, 2**31), (last, 2**31), (2**31, last)]
    points += [(rng.getrandbits(32), rng.getrandbits(32)) for _ in range(2000)]
    with tempfile.TemporaryDirectory() as tmp:
        path = make_gpt(pathlib.Path(tmp), "pts", [gpt.code_of(x, y) for x, y in points])
        with Server(path) as server:
            _, rows = export(server, "pts", "-180,-85.05112877980659,180,85.05112877980659")
            assert sorted(unit_of(r) for r in rows) == sorted(points)
            for row in rows:
                lon, lat = map(float, row.split(","))
                assert -180 <= lon <= 180 and abs(lat) <= box_rules.MAX_LAT, row


def test_rows_stay_inside_the_box_read_as_plain_numbers():
    """catches: rows of points on a box edge printed past it (a unit's middle is up to half a unit beyond an edge inside that unit), so a spreadsheet filter by the box drops them"""
    x0, y0, x1, y1 = 3_536_000_000, 1_626_000_000, 3_536_000_100, 1_626_000_100
    points = [(x0, y0), (x1, y0), (x0, y1), (x1, y1), (x0 + 50, y0 + 50)]  # four on the box's corners, one inside
    # The edges inside the corner points' units, but not at their middles: each middle is outside the edge.
    w, e = box_rules.lon_of_x(x0 + 0.75), box_rules.lon_of_x(x1 + 0.25)
    n, s = box_rules.lat_of_y(y0 + 0.75), box_rules.lat_of_y(y1 + 0.25)
    with tempfile.TemporaryDirectory() as tmp:
        path = make_gpt(pathlib.Path(tmp), "pts", [gpt.code_of(x, y) for x, y in points])
        with Server(path) as server:
            for bbox in [f"{w:.9f},{s:.9f},{e:.9f},{n:.9f}", f"{w!r},{s!r},{e!r},{n!r}"]:  # 9 decimals (the page) and 17 digits
                west, south, east, north = map(float, bbox.split(","))
                _, rows = export(server, "pts", bbox)
                assert sorted(unit_of(r) for r in rows) == sorted(points), (bbox, rows)  # each row still its point
                for row in rows:
                    lon, lat = map(float, row.split(","))
                    assert west <= lon <= east and south <= lat <= north, (bbox, row)


def test_rows_near_0_degrees_never_use_exponents():
    """catches: a full-precision row written with an exponent (-2.5e-05), a second number style in the column"""
    x0, y0, x1, y1 = 2**31 - 300, 2**31 - 300, 2**31 + 300, 2**31 + 300  # around longitude 0, latitude 0
    points = [(x0, y0), (x1, y0), (x0, y1), (x1, y1)]
    bbox = (f"{box_rules.lon_of_x(x0 + 0.75)!r},{box_rules.lat_of_y(y1 + 0.25)!r},"
            f"{box_rules.lon_of_x(x1 + 0.25)!r},{box_rules.lat_of_y(y0 + 0.75)!r}")  # 17 digits, inside the corner units
    with tempfile.TemporaryDirectory() as tmp:
        path = make_gpt(pathlib.Path(tmp), "pts", [gpt.code_of(x, y) for x, y in points])
        with Server(path) as server:
            _, rows = export(server, "pts", bbox)
            assert sorted(unit_of(r) for r in rows) == sorted(points) and not any("e" in r.lower() for r in rows), rows


def test_a_row_in_the_last_column_does_not_round_to_180():
    """catches: a row clamped onto a box edge just west of 180 and printed as 180.000000000, which reads back as -180 (x = 0), the other side of the world"""
    last = 2**32 - 1
    with tempfile.TemporaryDirectory() as tmp:
        path = make_gpt(pathlib.Path(tmp), "pts", [gpt.code_of(last, 2**31)])
        with Server(path) as server:
            for bbox in ["179.9999999999,-1,180,1", "179.99999999,-1,180,1", "180,-1,180,1", "-180,-1,180,1"]:
                _, rows = export(server, "pts", bbox)
                assert [unit_of(r) for r in rows] == [(last, 2**31)], (bbox, rows)
                assert rows == [row_of(last, 2**31, bbox)], (bbox, rows)


def test_the_default_limit_is_a_million_rows():
    """catches: an export without a limit (or limit=1000000) that sends more than 1,000,000 rows, or a total that counts only the rows sent"""
    with tempfile.TemporaryDirectory() as tmp:
        path = make_gpt(pathlib.Path(tmp), "many", list(range(1_000_100)))  # near the world's north-west corner
        world = "-180,-85.05112877980659,180,85.05112877980659"
        with Server(path) as server:
            for query in ["", "&limit=1000000"]:
                status, headers, body = server.get(f"/api/datasets/many/export.csv?bbox={world}{query}")
                assert status == 200 and body.count(b"\n") == 1_000_001, (query, status, body.count(b"\n"))
                assert (headers["X-Rows"], headers["X-Total-Points"]) == ("1000000", "1000100"), headers


def test_the_row_limit_is_kept():
    """catches: an export that ignores limit (a huge download), a limit of 0 or over 1,000,000 accepted, or rows cut short below the limit"""
    with tempfile.TemporaryDirectory() as tmp:
        path = make_gpt(pathlib.Path(tmp), "pts", list(range(0, 50_000, 7)))  # 7,143 points near the north-west corner
        world = "-180,-85.05112877980659,180,85.05112877980659"
        with Server(path) as server:
            for limit, want in [(1, 1), (100, 100), (7143, 7143), (1_000_000, 7143), (None, 7143)]:
                headers, rows = export(server, "pts", world, limit)
                assert len(rows) == want and int(headers["X-Total-Points"]) == 7143, (limit, len(rows))
            for limit in ["0", "-1", "1000001", "1.5", "x", ""]:
                status, _, _ = server.get(f"/api/datasets/pts/export.csv?bbox={world}&limit={limit}")
                assert status == 400, (limit, status)
            for query in ["", "?limit=5", f"?bbox={world}&bbox={world}", f"?bbox={world}&format=json"]:
                assert server.get(f"/api/datasets/pts/export.csv{query}")[0] == 400, query
            assert server.get(f"/api/datasets/nope/export.csv?bbox={world}")[0] == 404


def test_a_client_that_hangs_up_halfway_does_not_hurt_the_server():
    """catches: the server dying (SIGPIPE) or stuck writing when a download is cancelled, so the map stops answering"""
    with tempfile.TemporaryDirectory() as tmp:
        codes = [gpt.code_of(x * 4096, 0) for x in range(200_000)]  # about 5 MB of CSV
        path = make_gpt(pathlib.Path(tmp), "big", codes)
        with Server(path) as server:
            for _ in range(5):
                with socket.create_connection(("127.0.0.1", server.port)) as s:
                    s.sendall(b"GET /api/datasets/big/export.csv?bbox=-180,-85.05112877980659,180,85.05112877980659"
                              b" HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n")
                    assert s.recv(4096).startswith(b"HTTP/1.1 200 OK")  # then hang up without reading the rest
            status, headers, _ = server.get("/api/datasets")
            assert status == 200 and server.process.poll() is None, "the server stopped answering"
            headers, rows = export(server, "big", "-180,-85.05112877980659,180,85.05112877980659", 10)
            assert len(rows) == 10


def test_clients_that_stop_reading_an_export_give_their_slots_back():
    """catches: an export that waits forever on a client that stopped reading, so 64 such clients take every connection slot and the map stops answering"""
    world = "-180,-85.05112877980659,180,85.05112877980659"
    with tempfile.TemporaryDirectory() as tmp:
        codes = [gpt.code_of(x * 4096, 0) for x in range(200_000)]  # about 5 MB of CSV: more than socket buffers hold
        path = make_gpt(pathlib.Path(tmp), "big", codes)
        with Server(path, extra=["--timeout", "1"]) as server:
            stuck = []
            for _ in range(70):  # more than the 64 slots; each asks for the whole export and never reads it
                s = socket.create_connection(("127.0.0.1", server.port))
                s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)
                s.sendall(f"GET /api/datasets/big/export.csv?bbox={world} HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n".encode())
                stuck.append(s)
            try:
                start = time.monotonic()
                status, _, body = server.get("/api/datasets")  # waits for a slot: one chunk's deadline (1 s), not forever
                assert status == 200 and time.monotonic() - start < 10, (status, time.monotonic() - start)
            finally:
                for s in stuck:
                    s.close()
            assert server.process.poll() is None


def test_an_http10_client_gets_the_rows_without_chunks():
    """catches: chunked encoding sent to an HTTP/1.0 client (which has none, so the chunk sizes end up in its CSV)"""
    world = "-180,-85.05112877980659,180,85.05112877980659"
    with tempfile.TemporaryDirectory() as tmp:
        path = make_gpt(pathlib.Path(tmp), "pts", list(range(0, 50_000, 7)))  # 7,143 points: more than one chunk
        with Server(path) as server:
            answer = server.raw(f"GET /api/datasets/pts/export.csv?bbox={world} HTTP/1.0\r\n\r\n".encode())
            head, _, body = answer.partition(b"\r\n\r\n")
            assert head.startswith(b"HTTP/1.1 200 OK") and b"Transfer-Encoding" not in head, head
            lines = body.decode().splitlines()
            assert lines[0] == "lon,lat" and len(lines) == 7144, (len(lines), lines[:2])
            assert lines[1:] == export(server, "pts", world)[1]  # the same rows as HTTP/1.1's chunks


def test_a_client_that_reads_steadily_gets_a_long_export():
    """catches: an export's deadline that doesn't move as the client reads, so a slow but steady reader (a script writing each row to a database) is cut off"""
    with tempfile.TemporaryDirectory() as tmp:
        codes = [gpt.code_of(x * 4096, 2**31) for x in range(120_000)]  # about 3.3 MB: well past socket buffers
        path = make_gpt(pathlib.Path(tmp), "big", codes)
        with Server(path, extra=["--timeout", "1"]) as server:  # an export's client may pause 3 s
            with socket.create_connection(("127.0.0.1", server.port)) as s:
                s.sendall(b"GET /api/datasets/big/export.csv?bbox=-180,-85.05112877980659,180,85.05112877980659"
                          b" HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n")
                data, start = bytearray(), time.monotonic()
                while chunk := s.recv(16384):
                    data += chunk
                    time.sleep(0.04)  # about 400 KB/s: the file takes twice the 3 s pause, after the buffers
            seconds = time.monotonic() - start
            rows = data.count(b"\n") - data.count(b"\r\n") - 1  # rows end with \n, chunk lines with \r\n
            assert data.endswith(b"\r\n0\r\n\r\n") and rows == 120_000 and seconds > 6, (seconds, rows, len(data))


def test_head_of_an_export_has_the_counts_and_no_rows():
    """catches: HEAD sending the whole CSV, or its counts differing from the GET's"""
    with tempfile.TemporaryDirectory() as tmp:
        path = make_gpt(pathlib.Path(tmp), "pts", list(range(0, 50_000, 7)))  # 7,143 points
        world = "-180,-85.05112877980659,180,85.05112877980659"
        with Server(path) as server:
            status, headers, _ = server.get(f"/api/datasets/pts/export.csv?bbox={world}&limit=100", method="HEAD")
            assert status == 200 and headers["X-Total-Points"] == "7143" and headers["X-Rows"] == "100", (status, headers)
            # The raw answer, read to the end: the headers and nothing after them (http.client wouldn't read a body).
            answer = server.raw(f"HEAD /api/datasets/pts/export.csv?bbox={world} HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n".encode())
            assert answer.startswith(b"HTTP/1.1 200 OK") and answer.endswith(b"\r\n\r\n") and answer.count(b"\r\n\r\n") == 1, answer[-80:]


def test_chrome_the_export_link_of_a_drawn_box_downloads_its_rows():
    """catches: an Export link for another box or dataset, a link that doesn't download, rows that differ from the box count, or a link left from a cleared box"""
    browser = load("browser", "e2e")
    if not browser.available():
        return "SKIPPED: no Google Chrome"
    unit = 1 << 14
    x0, y0 = (843 * 256) << 14, (388 * 256) << 14  # tile 10/843/388
    rng = random.Random(int(os.environ.get("TEST_SEED", "1")))
    points = [(x0 + rng.randrange(256 * unit), y0 + rng.randrange(256 * unit)) for _ in range(3000)]
    with tempfile.TemporaryDirectory() as tmp:
        tmp = pathlib.Path(tmp)
        files = [make_gpt(tmp, "pts", [gpt.code_of(x, y) for x, y in points]), make_gpt(tmp, "other", [gpt.code_of(1, 1)])]
        with Server(*files) as server, browser.Browser(1200, 800) as chrome:
            chrome.save_downloads_in(tmp)
            lat, lon = box_rules.lat_of_y(y0 + 128 * unit), box_rules.lon_of_x(x0 + 128 * unit)
            chrome.open(f"http://127.0.0.1:{server.port}/#pts/10/{lat:.9f}/{lon:.9f}")
            chrome.wait("document.getElementById('in-view').textContent === '3,000'")
            assert chrome.js("document.getElementById('export').hidden")  # no box yet: no link
            chrome.click("#box-tool")
            chrome.drag((500, 300), (700, 450))
            chrome.wait("!document.getElementById('export').hidden")
            shown = int(chrome.js("document.getElementById('box-count').textContent").split()[0].replace(",", ""))
            href = chrome.js("document.getElementById('export').getAttribute('href')")
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(href).query)
            box = box_rules.parse_bbox(query["bbox"][0])
            assert href.startswith("/api/datasets/pts/export.csv?") and query["limit"] == [str(shown)], href
            want = sorted((p for p in points if box_rules.inside(*p, box)), key=lambda p: gpt.code_of(*p))
            assert shown == len(want) > 0, (shown, len(want))
            assert text_of(chrome, "export") == f"Export CSV ({shown:,} rows)"
            chrome.click("#export")
            data = chrome.wait_for_download(tmp / "pts-export.csv").decode()
            assert data.splitlines() == ["lon,lat"] + [row_of(x, y, query["bbox"][0]) for x, y in want]
            chrome.click('#switch button[data-id="other"]')  # a switch clears the box and its link
            chrome.wait("document.getElementById('points').textContent === '1'")
            assert chrome.js("document.getElementById('export').hidden")
            assert not chrome.problems(), chrome.problems()


def test_chrome_the_export_link_says_what_it_will_send():
    """catches: "1 rows", a link to more than 1,000,000 rows (the server refuses it) or one that hides that only the first 1,000,000 come, or a link for a box across the 180° line (the file would hold one side only)"""
    browser = load("browser", "e2e")
    if not browser.available():
        return "SKIPPED: no Google Chrome"
    middle = gpt.code_of(2**31, 2**31)  # longitude 0, latitude 0; its 20 low bits are 0
    y180 = 388 * 2**23
    with tempfile.TemporaryDirectory() as tmp:
        tmp = pathlib.Path(tmp)
        files = [make_gpt(tmp, "one", [middle]),
                 make_gpt(tmp, "many", [middle + i for i in range(1_000_100)]),  # a 1,024-unit square at 0, 0
                 make_gpt(tmp, "edge", [gpt.code_of(2**32 - 1, y180), gpt.code_of(0, y180)])]  # each side of 180
        with Server(*files) as server, browser.Browser(1200, 800) as chrome:
            url = f"http://127.0.0.1:{server.port}/"
            for name, view, want in [("one", (0, 0, 10), "Export CSV (1 row)"),
                                     ("many", (0.0001, 0.0001, 18), "Export CSV (the first 1,000,000 of 1,000,100 points, in file order)")]:
                chrome.open(f"{url}#{name}/{view[2]}/{view[0]}/{view[1]}")
                chrome.wait(f"document.getElementById('file').textContent === '{name}.gpt'")
                chrome.click("#box-tool")
                assert chrome.js("document.elementFromPoint(350, 250).closest('#map') && !document.elementFromPoint(350, 250).closest('.panel')")
                chrome.drag((350, 250), (850, 600))  # around the points, in the middle of the screen, clear of the panels
                chrome.wait("!document.getElementById('export').hidden")
                assert text_of(chrome, "export") == want, (name, text_of(chrome, "export"))
                href = chrome.js("document.getElementById('export').getAttribute('href')")
                assert href.endswith("&limit=1" if name == "one" else "&limit=1000000"), href
            # Across the 180° line: counted (both sides), but no link, and the panel says why.
            chrome.open(f"{url}#edge/3/{box_rules.lat_of_y(y180)}/180")
            chrome.wait("document.getElementById('file').textContent === 'edge.gpt'")
            chrome.click("#box-tool")
            chrome.drag((560, 360), (640, 440))
            chrome.wait("document.getElementById('box-count').textContent === '2 points'")
            assert chrome.js("document.getElementById('export').hidden")
            assert "across the 180° line: draw one box on each side to export" in text_of(chrome, "box-text")
            assert not chrome.problems(), chrome.problems()


def text_of(chrome, id):
    return chrome.js(f"document.getElementById({id!r}).textContent")
