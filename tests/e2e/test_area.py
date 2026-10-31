"""Box counts over real HTTP (DESIGN §5.6, §9.2, step 7): /api/datasets/{id}/count against the slow count in
tests/oracle/box_rules.py for random boxes, boxes on tile and pixel edges and pixel-sized hover boxes,
and bad boxes refused with 400 (TESTING.md §9)."""
import importlib.util
import json
import os
import pathlib
import random
import tempfile
import urllib.parse

TESTS = pathlib.Path(__file__).resolve().parents[1]


def load(name, folder="oracle"):
    spec = importlib.util.spec_from_file_location(name, TESTS / folder / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gpt, box_rules, server_test = load("gpt_rules"), load("box_rules"), load("test_server", "e2e")
Server, make_gpt = server_test.Server, server_test.make_gpt


def clustered_points(rng, n):
    """(x, y) world units around Beijing at many spreads, with repeats."""
    cx, cy = 3_536_000_000, 1_626_000_000
    points = []
    while len(points) < n:
        mask = (1 << rng.randrange(8, 30)) - 1
        points += [(cx ^ (rng.getrandbits(32) & mask), cy ^ (rng.getrandbits(32) & mask))] * rng.choice([1, 1, 3])
    return points[:n]


def count(server, name, bbox):
    status, headers, body = server.get(f"/api/datasets/{name}/count?bbox={bbox}")
    assert status == 200 and headers["Content-Type"] == "application/json", (bbox, status, body)
    answer = json.loads(body)
    assert answer["id"] == name, answer
    return answer["count"]


def degrees(x0, y0, x1, y1):
    """A box in world units as bbox text that turns back into exactly those units: each edge is put in the
    middle of its unit, written with 17 digits."""
    def lon(x):
        return f"{box_rules.lon_of_x(x + 0.5):.17g}"

    def lat(y):
        return f"{box_rules.lat_of_y(y + 0.5):.17g}"
    return f"{lon(x0)},{lat(y1)},{lon(x1)},{lat(y0)}"


def test_box_counts_equal_the_slow_count():
    """catches: points on a box edge or on a tile edge lost or counted twice, an edge square counted whole, north and south swapped"""
    rng = random.Random(int(os.environ.get("TEST_SEED", "1")))
    points = clustered_points(rng, 3000)
    with tempfile.TemporaryDirectory() as tmp:
        path = make_gpt(pathlib.Path(tmp), "pts", [gpt.code_of(x, y) for x, y in points])
        with Server(path) as server:
            assert count(server, "pts", "-180,-85.05112877980659,180,85.05112877980659") == 3000
            for k in range(60):
                x, y = rng.choice(points)
                if k % 3 == 0:  # random size around a point
                    half = 1 << rng.randrange(4, 28)
                    box = (max(x - half, 0), max(y - half // 2, 0), min(x + half, 2**32 - 1), min(y + half, 2**32 - 1))
                elif k % 3 == 1:  # exactly one tile at a random zoom: its edges are where slices split
                    zoom = rng.randrange(4, 25)
                    span = 1 << (32 - zoom)
                    box = (x // span * span, y // span * span, x // span * span + span - 1, y // span * span + span - 1)
                else:  # a box whose edges go through points
                    x2, y2 = rng.choice(points)
                    box = (min(x, x2), min(y, y2), max(x, x2), max(y, y2))
                bbox = degrees(*box)
                assert box_rules.parse_bbox(bbox) == box, (box, bbox)  # the text means exactly this box
                assert count(server, "pts", bbox) == box_rules.slow_count(points, box), (k, box)


def test_a_hovered_pixel_counts_like_the_slow_count():
    """catches: the hover count (a pixel-sized box, as the page asks for it) disagreeing with the points drawn in that pixel"""
    rng = random.Random(int(os.environ.get("TEST_SEED", "1")) + 1)
    points = clustered_points(rng, 2000)
    with tempfile.TemporaryDirectory() as tmp:
        path = make_gpt(pathlib.Path(tmp), "pts", [gpt.code_of(x, y) for x, y in points])
        with Server(path) as server:
            for _ in range(40):
                x, y = rng.choice(points)
                zoom = rng.randrange(0, 25)
                size = 1 << (24 - zoom)  # a pixel at this zoom, in world units
                px, py = x // size * size, y // size * size
                # The page sends the pixel's own world units, from its first to its last (DESIGN §1 hover).
                box = (px, py, px + size - 1, py + size - 1)
                assert count(server, "pts", degrees(*box)) == box_rules.slow_count(points, box), (zoom, box)


def test_longitude_180_as_a_box_edge_is_the_worlds_east_edge():
    """catches: longitude 180 as a box edge read as x = 0 (where points at 180 are stored), so that -180,…,180,… (the whole world) becomes a sliver at -180 and 180,…,180,… counts the points at -180"""
    west, east = (0, 2**31), (2**32 - 1, 2**31)  # at -180, and on the world's last unit (just west of 180)
    with tempfile.TemporaryDirectory() as tmp:
        path = make_gpt(pathlib.Path(tmp), "pts", [gpt.code_of(*west), gpt.code_of(*east)])
        with Server(path) as server:
            assert count(server, "pts", "-180,-1,180,1") == 2  # the whole world's width
            assert count(server, "pts", "-180,-1,-180,1") == 1  # the first column: the point at -180
            assert count(server, "pts", "180,-1,180,1") == 1  # the last column: the point just west of 180
            assert count(server, "pts", "179.9999999,-1,180,1") == 1
            for bbox, want in [("-180,-1,-180,1", 1), ("180,-1,180,1", 1)]:  # which point: the oracle says
                assert box_rules.slow_count([west, east], box_rules.parse_bbox(bbox)) == want


def test_bad_boxes_are_refused():
    """catches: west > east, south > north, NaN, infinity, text or a box outside the map accepted (a wrong count instead of an error)"""
    with tempfile.TemporaryDirectory() as tmp:
        path = make_gpt(pathlib.Path(tmp), "pts", [1, 2, 3])
        with Server(path) as server:
            for bbox in ["2,0,1,1", "0,2,1,1", "nan,0,1,1", "0,0,inf,1", "a,b,c,d", "0,0,1", "0,0,1,1,1", "",
                         "-181,0,0,1", "0,-86,1,0", "0,0,1,86", "0,0,180.000001,1", "1e999,0,1,1", "0x1,0,1,1",
                         "%201,0,2,1", "1,0,2,1%20", "0;0;1;1"]:
                assert box_rules.parse_bbox(bbox.replace("%20", " ")) is None, bbox
                status, headers, body = server.get(f"/api/datasets/pts/count?bbox={bbox}")
                assert status == 400 and headers["Content-Type"].startswith("text/plain"), (bbox, status, body)
            for query in ["", "?", "?box=0,0,1,1", "?bbox=0,0,1,1&bbox=0,0,1,1", "?bbox=0,0,1,1&limit=5"]:
                status, _, body = server.get(f"/api/datasets/pts/count{query}")
                assert status == 400, (query, status, body)
            # Each refusal says what is wrong; the length limits are the oracle's too.
            long_number = "0." + "0" * 70 + "1"  # 73 characters
            for query, why in [("", "bbox=west,south,east,north is required"),
                               ("?bbox=0,0,1,1&bbox=0,0,1,1", "bbox is given more than once"),
                               ("?bbox=" + "1" * 130, "bbox is too long (127 characters at most)"),
                               ("?bbox=0,0,1,1%00", "bbox has a bad %-escape"), ("?bbox=0,0,1,1%2", "bbox has a bad %-escape"),
                               (f"?bbox=0,0,1,{long_number}", "bbox must be four numbers: west,south,east,north")]:
                status, _, body = server.get(f"/api/datasets/pts/count{query}")
                assert (status, body.decode().strip()) == (400, f"400 {why}"), (query, status, body)
            assert box_rules.parse_bbox(f"0,0,1,{long_number}") is None and box_rules.parse_bbox("1" * 130) is None
            assert server.get("/api/datasets/nope/count?bbox=0,0,1,1")[0] == 404
            assert server.get("/api/datasets/pts/count/x?bbox=0,0,1,1")[0] == 404
            # A comma sent as %2C (as some HTTP libraries do) means the same box.
            world = "-180,-85.05112877980659,180,85.05112877980659"  # the 3 points are at the north-west corner
            assert count(server, "pts", world.replace(",", "%2C")) == count(server, "pts", world) == 3


def test_chrome_hover_and_a_drawn_box_show_the_exact_counts():
    """catches: the hover count taken for the wrong pixel or a pixel-and-a-bit (the next pixel's first row or column), a drawn box counted for another box than the one drawn, points on screen not the exact count, or a script error on the page"""
    browser = load("browser", "e2e")
    if not browser.available():
        return "SKIPPED: no Google Chrome"
    unit = 1 << 14  # one pixel at zoom 10, in world units
    x0, y0 = (843 * 256) << 14, (388 * 256) << 14  # the north-west corner of tile 10/843/388
    # Pixel (10, 20) of the tile: 5 points, one on its last unit. Pixel (11, 20): 1 point on its first unit,
    # right next to them. Pixel (100, 100): 37 points spread over it.
    points = [(x0 + 10 * unit + k * 1000, y0 + 20 * unit + k * 900) for k in range(4)] + [(x0 + 11 * unit - 1, y0 + 21 * unit - 1)]
    points += [(x0 + 11 * unit, y0 + 20 * unit)]
    points += [(x0 + 100 * unit + (k * 7919) % unit, y0 + 100 * unit + (k * 104729) % unit) for k in range(37)]
    with tempfile.TemporaryDirectory() as tmp:
        path = make_gpt(pathlib.Path(tmp), "pts", [gpt.code_of(x, y) for x, y in points])
        with Server(path) as server, browser.Browser(1200, 800) as chrome:
            lat, lon = box_rules.lat_of_y(y0 + 128 * unit), box_rules.lon_of_x(x0 + 128 * unit)  # the tile's middle
            chrome.open(f"http://127.0.0.1:{server.port}/#pts/10/{lat:.9f}/{lon:.9f}")
            chrome.wait("document.getElementById('in-view').textContent === '43'")  # every point is on screen

            # The tile's north-west corner on screen: a whole pixel (Leaflet rounds the projected corner).
            corner = chrome.js(f"(() => {{ const p = map.latLngToContainerPoint([{box_rules.lat_of_y(y0)}, {box_rules.lon_of_x(x0)}]);"
                               " return [p.x, p.y]; })()")

            def screen(px, py):  # the mouse on the north-west corner of a pixel of the tile: that pixel is under it
                return corner[0] + px, corner[1] + py
            for (px, py), want in [((10, 20), "5 points"), ((11, 20), "1 point"), ((100, 100), "37 points"), ((50, 50), "0 points")]:
                chrome.mouse("mouseMoved", *screen(px, py))
                chrome.wait(f"document.getElementById('hover').textContent === '{want}'")
                pixel = (x0 + px * unit, y0 + py * unit, x0 + (px + 1) * unit - 1, y0 + (py + 1) * unit - 1)
                assert f"{box_rules.slow_count(points, pixel)} point" in want, (px, py, want)  # the oracle agrees

            # Draw a box from pixel (5, 5) to pixel (105, 103) of the tile.
            chrome.click("#box-tool")
            chrome.drag(screen(5, 5), screen(105, 103))
            chrome.wait("/^[0-9,]+ points?$/.test(document.getElementById('box-count').textContent)")
            asked = [p for p in chrome.js("performance.getEntriesByType('resource').map((e) => e.name)") if "/count?" in p]
            bbox = urllib.parse.unquote(asked[-1].split("bbox=")[1])
            box = box_rules.parse_bbox(bbox)
            assert box is not None and abs(box[0] - (x0 + 5 * unit)) <= 1 and abs(box[3] - (y0 + 103 * unit)) <= 1, (bbox, box, x0 + 5 * unit)
            shown = int(chrome.js("document.getElementById('box-count').textContent").split()[0].replace(",", ""))
            assert shown == box_rules.slow_count(points, box) == 43, (shown, box)
            assert not chrome.problems(), chrome.problems()


def test_chrome_hover_and_box_counts_stay_right_when_things_change():
    """catches: a hover count left from before a zoom, a hover above the world counted as the edge row, a box above the world counted as an edge strip, an old box count shown after a switch (a slow answer), or a drag released over the side panel that never ends"""
    browser = load("browser", "e2e")
    if not browser.available():
        return "SKIPPED: no Google Chrome"
    unit = 1 << 14
    x0, y0 = (843 * 256) << 14, (388 * 256) << 14  # tile 10/843/388
    points = [(x0 + 10 * unit + k * 1000, y0 + 20 * unit + k * 900) for k in range(5)]  # pixel (10, 20) at zoom 10
    points.append((2**31, 0))  # on the world's top edge, at longitude 0
    with tempfile.TemporaryDirectory() as tmp:
        tmp = pathlib.Path(tmp)
        files = [make_gpt(tmp, "pts", [gpt.code_of(x, y) for x, y in points]), make_gpt(tmp, "other", [gpt.code_of(1, 1)])]
        with Server(*files) as server, browser.Browser(1200, 800) as chrome:
            text = lambda id: chrome.js(f"document.getElementById('{id}').textContent")
            lat, lon = box_rules.lat_of_y(y0 + 128 * unit), box_rules.lon_of_x(x0 + 128 * unit)
            chrome.open(f"http://127.0.0.1:{server.port}/#pts/10/{lat:.9f}/{lon:.9f}")
            chrome.wait("document.getElementById('in-view').textContent === '5'")
            corner = chrome.js(f"(() => {{ const p = map.latLngToContainerPoint([{box_rules.lat_of_y(y0)}, {box_rules.lon_of_x(x0)}]);"
                               " return [p.x, p.y]; })()")
            mouse = (corner[0] + 10, corner[1] + 20)
            chrome.mouse("mouseMoved", *mouse)
            chrome.wait("document.getElementById('hover').textContent === '5 points'")

            # A zoom under the still mouse: the count is for the zoom-11 pixel now under it.
            chrome.js("void map.setZoom(11, { animate: false })")
            px, py = chrome.js(f"(() => {{ const p = map.getPixelOrigin().add(map.containerPointToLayerPoint([{mouse[0]}, {mouse[1]}])).floor();"
                               " return [p.x, p.y]; })()")
            size = 1 << 13  # a zoom-11 pixel, in world units
            want = box_rules.slow_count(points, (px * size, py * size, px * size + size - 1, py * size + size - 1))
            chrome.wait(f"document.getElementById('hover').textContent === '{want} point{'' if want == 1 else 's'}'")

            # Zoom 1: the world is 512 px tall, so there is empty map above it. Hover there: no pixel.
            chrome.js("void map.setView([0, 0], 1, { animate: false })")
            chrome.mouse("mouseMoved", 600, 300)  # on the world
            chrome.wait("/^[0-9,]+ points?$/.test(document.getElementById('hover').textContent)")
            chrome.mouse("mouseMoved", 600, 40)  # above it, over the top-edge point's column
            chrome.js("new Promise((done) => setTimeout(done, 400))")
            assert text("hover") == "–", text("hover")
            # A box drawn wholly above the world: nothing in it.
            chrome.click("#box-tool")
            chrome.drag((500, 20), (700, 100))
            chrome.wait("document.getElementById('box-count').textContent === '0 points'")
            assert text("box-text") == "The box is outside the map.", text("box-text")

            # A drag let go over the side panel still ends, with its count.
            assert chrome.js("!!document.elementFromPoint(1000, 500).closest('#side')"), "(1000, 500) isn't on the side panel"
            chrome.click("#box-tool")
            chrome.drag((300, 300), (1000, 500))  # the side panel covers the right of the map
            chrome.wait("/^[0-9,]+ points?$/.test(document.getElementById('box-count').textContent)")
            assert not chrome.js("document.getElementById('box-tool').classList.contains('on')"), "still drawing"

            # A slow count answer, and a switch before it comes: the cleared box stays cleared.
            chrome.js("""(() => { const real = window.fetch; window.fetch = (url, options) => String(url).includes("/count?")
              ? new Promise((done) => setTimeout(() => done(real(url, options)), 600)) : real(url, options); })()""")
            chrome.click("#box-tool")
            chrome.drag((300, 300), (500, 500))
            chrome.click('#switch button[data-id="other"]')
            chrome.js("new Promise((done) => setTimeout(done, 1200))")
            assert text("box-count") == "" and text("points") == "1", (text("box-count"), text("points"))
            assert not chrome.problems(), chrome.problems()


def pixel_latlon(z, px, py):
    """(lat, lon) of map pixel (px, py) at zoom z (the map is 256 × 2^z pixels across)."""
    n = 256 * 2**z
    return box_rules.lat_of_y(py * 2**32 / n), box_rules.lon_of_x(px * 2**32 / n)


def test_chrome_points_on_screen_is_exact_at_the_edges_and_across_180():
    """catches: points on screen counted one world unit (at zoom 24 a whole pixel) past an edge of the screen, a view across the 180° line counted on one side only, a hover in a copy of the world refused, a slow old count shown over a newer one, a hover that asks on every mouse move, or a click (no drag) counted as a box"""
    browser = load("browser", "e2e")
    if not browser.available():
        return "SKIPPED: no Google Chrome"
    world = 2**32
    views = {16: (843 * 256 * 64 + 1000, 388 * 256 * 64 + 700), 24: (844 * 256 * 2**14 + 5, 388 * 256 * 2**14 + 9)}
    points = []
    for z, (cx, cy) in views.items():  # around a 1200 × 800 view centered on map pixel (cx, cy) at zoom z
        size = 2 ** (24 - z)
        x0, x1, y0, y1 = (cx - 600) * size, (cx + 600) * size - 1, (cy - 400) * size, (cy + 400) * size - 1
        xm, ym = cx * size, cy * size
        points += [(x0, ym), (x1, ym), (xm, y0), (xm, y1)]  # the first and last units on screen: in view
        points += [(x0 - 1, ym), (x1 + 1, ym), (xm, y0 - 1), (xm, y1 + 1)]  # one unit past each edge: not
    y180 = 388 * 2**23
    points += [(world - 1, y180), (0, y180), (world // 2, y180)]  # just west of 180, at -180, and far away
    pixel = [(843 * 2**22 + 10 * 2**14 + k * 1000, 388 * 2**22 + 20 * 2**14) for k in range(5)]  # pixel (10, 20) of tile 10/843/388
    points += pixel
    with tempfile.TemporaryDirectory() as tmp:
        path = make_gpt(pathlib.Path(tmp), "pts", [gpt.code_of(x, y) for x, y in points])
        with Server(path) as server, browser.Browser(1200, 800) as chrome:
            chrome.open(f"http://127.0.0.1:{server.port}/#pts/10/40/116.4")
            chrome.wait("/^[0-9,]+$/.test(document.getElementById('in-view').textContent)")
            in_view = lambda want: chrome.wait(f"document.getElementById('in-view').textContent === '{want}'")
            for z, (cx, cy) in views.items():
                chrome.js("void map.setView([%r, %r], %d, { animate: false })" % (*pixel_latlon(z, cx, cy), z))
                in_view("4")  # the four probes on the screen's first and last units, none past it
            chrome.js("void map.setView([%r, 180], 16, { animate: false })" % box_rules.lat_of_y(y180))
            in_view("2")  # across the 180° line: one point on each side

            # A slow answer for an older view must not replace the newer view's count.
            chrome.js("""(() => { const real = window.fetch; let first = true; window.fetch = (url, options) => {
              const slow = first && String(url).includes("/count?"); first = first && !slow;
              return slow ? new Promise((done) => setTimeout(() => done(real(url, options)), 800)) : real(url, options); }; })()""")
            cx, cy = views[16]
            chrome.js("void map.setView([%r, %r], 16, { animate: false })" % pixel_latlon(16, cx, cy))  # slow: 4
            chrome.js("void map.setView([%r, 180], 16, { animate: false })" % box_rules.lat_of_y(y180))  # quick: 2
            chrome.js("new Promise((done) => setTimeout(done, 1200))")
            assert chrome.js("document.getElementById('in-view').textContent") == "2"

            # A hover in the next copy of the world east: pixel (10, 20) of tile 10/843/388 there.
            lat, lon = pixel_latlon(10, 843 * 256 + 128, 388 * 256 + 128)
            chrome.js(f"void map.setView([{lat}, {lon + 360}], 10, {{ animate: false }})")
            corner = chrome.js(f"(() => {{ const p = map.latLngToContainerPoint([{box_rules.lat_of_y(388 * 2**22)}, "
                               f"{box_rules.lon_of_x(843 * 2**22) + 360}]); return [p.x, p.y]; }})()")
            asked = lambda: len([e for e in chrome.js("performance.getEntriesByType('resource').map((e) => e.name)") if "/count?" in e])
            before = asked()
            for k in range(20):  # a quick move, ending on the pixel: one question, after the mouse rests
                chrome.mouse("mouseMoved", corner[0] + 10 - 19 + k, corner[1] + 20)
            chrome.wait("document.getElementById('hover').textContent === '5 points'")
            assert asked() - before <= 2, asked() - before

            # A box drawn across the 180° line (zoom 3, the line in the middle of the screen): both sides count.
            chrome.js("void map.setView([%r, 180], 3, { animate: false })" % box_rules.lat_of_y(y180))
            chrome.click("#box-tool")
            chrome.drag((560, 360), (640, 440))
            chrome.wait("/^[0-9,]+ points?$/.test(document.getElementById('box-count').textContent)")
            assert chrome.js("document.getElementById('box-count').textContent") == "2 points"  # one each side
            assert chrome.js("document.getElementById('box-text').textContent").count("Box ") == 2

            # A click with "Draw a box" on, without a drag: no box, still drawing.
            chrome.click("#box-tool")
            chrome.mouse("mouseMoved", 600, 400)
            chrome.mouse("mousePressed", 600, 400, "left", 1)
            chrome.mouse("mouseReleased", 600, 400, "left", 0)
            assert chrome.js("document.getElementById('box-count').textContent") == ""
            assert chrome.js("document.getElementById('box-tool').classList.contains('on')"), "the click ended drawing"
            assert not chrome.problems(), chrome.problems()
