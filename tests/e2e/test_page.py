"""The map page (DESIGN §1, step 6) over real HTTP: the page and Leaflet are served from the program with
Leaflet's official 1.9.4 integrity hashes, and headless Chrome, driven with the real mouse (browser.py),
shows that the page lists the served datasets, asks for exactly the tiles the map shows, that the dataset
switch, the layer boxes and the address work, and that failures are shown (TESTING.md §9)."""
import base64
import functools
import hashlib
import html.parser
import http.server
import importlib.util
import json
import math
import pathlib
import re
import tempfile
import threading

E2E = pathlib.Path(__file__).resolve().parent

# Leaflet 1.9.4's published integrity hashes (leafletjs.com/download.html), not taken from our page.
LEAFLET_SRI = {"/leaflet/leaflet.css": "sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=",
               "/leaflet/leaflet.js": "sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo="}


def load(name):
    spec = importlib.util.spec_from_file_location(name, E2E / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


server_test, browser = load("test_server"), load("browser")
gpt, Server, make_gpt = server_test.gpt, server_test.Server, server_test.make_gpt

# The heat tiles on the map have loaded: there are some, and each one's picture is a decoded 256 × 256 image.
LOADED = """(() => { const t = [...document.querySelectorAll("#map .heat-tile img")];
  return t.length > 0 && t.every((i) => i.complete && i.naturalWidth === 256); })()"""
# Every heat tile the page asked the server for, in order: "id/z/x/y" (the browser's own record).
REQUESTED = """performance.getEntriesByType("resource").map((e) => new URL(e.name).pathname)
  .filter((p) => p.startsWith("/tiles/")).map((p) => p.slice(7, -4))"""
ON_MAP = """[...document.querySelectorAll("#map .heat-tile")].map((t) => t.dataset.tile)"""
# The heat tiles of the current zoom that overlap the window by at least a pixel, each once: what "Tiles on
# screen" must count (Leaflet also keeps a few tiles around the screen, off it).
VISIBLE = """(() => { const z = map.getZoom(), w = innerWidth, h = innerHeight;
  const seen = [...document.querySelectorAll("#map .heat-tile")].filter((t) => { const r = t.getBoundingClientRect();
    return t.dataset.tile.startsWith(`${z}/`) && r.right > 0 && r.bottom > 0 && r.left < w && r.top < h; });
  return [...new Set(seen.map((t) => t.dataset.tile))]; })()"""
# The heat layer is drawn above the base map: a higher z-index, or the same one and later in the page.
HEAT_ON_TOP = """(() => { const heat = document.querySelector("#map .heat-tile").closest(".leaflet-layer");
  const base = document.querySelector("#map .base-dark"), z = (e) => Number(getComputedStyle(e).zIndex) || 0;
  return z(heat) > z(base) || (z(heat) === z(base) && !!(base.compareDocumentPosition(heat) & Node.DOCUMENT_POSITION_FOLLOWING)); })()"""
# The map's center as a pixel at its zoom (whole map 256 × 2^zoom pixels across): where a reload must put it back.
CENTER_PIXEL = """(() => { const p = map.project(map.getCenter(), map.getZoom()); return [map.getZoom(), p.x, p.y]; })()"""


class Assets(html.parser.HTMLParser):
    """The scripts and stylesheets a page loads (<script src>, <link rel="stylesheet" href>), with their
    integrity attributes."""

    def __init__(self):
        super().__init__()
        self.found = {}

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "script" and a.get("src") or tag == "link" and a.get("rel") == "stylesheet":
            self.found[a.get("src") or a.get("href")] = a.get("integrity")


def tile_center(z, x, y):
    """(lat, lon) of the middle of tile z/x/y: the OpenStreetMap tile formula, inverted."""
    return pixel_latlon(z, (x + 0.5) * 256, (y + 0.5) * 256)


def pixel_latlon(z, px, py):
    """(lat, lon) of map pixel (px, py) at zoom z (256 pixels a tile)."""
    n = 256 * 2**z
    return math.degrees(math.atan(math.sinh(math.pi * (1.0 - 2.0 * py / n)))), px / n * 360.0 - 180.0


def text_of(chrome, id):
    return chrome.js(f"document.getElementById({json.dumps(id)}).textContent")


def test_the_page_and_leaflet_are_served_with_matching_integrity_hashes():
    """catches: the page missing from the program, Leaflet changed or not 1.9.4 (its file and the page's pin both changed: the published hash no longer matches), a wrong content type, or a page that may load scripts or styles from anywhere (no CSP)"""
    with tempfile.TemporaryDirectory() as tmp:
        path = make_gpt(pathlib.Path(tmp), "tiny", [1, 2, 3])
        with Server(path) as server:
            status, headers, body = server.get("/")
            assert status == 200 and headers["Content-Type"] == "text/html; charset=utf-8", (status, headers)
            # The browser may load only this server's files and OpenStreetMap's tiles (DESIGN §11.1).
            policy = headers["Content-Security-Policy"]
            assert "default-src 'none'" in policy and "script-src 'self'" in policy, policy
            assert "img-src 'self' data: blob: https://tile.openstreetmap.org;" in policy, policy
            assert "unsafe-inline" not in policy and "connect-src 'self'" in policy, policy
            for rule in ("base-uri 'none'", "form-action 'none'", "frame-ancestors 'none'"):  # no other site may frame it
                assert rule in policy, (rule, policy)
            parser = Assets()
            parser.feed(body.decode())
            assert set(parser.found) == {"/leaflet/leaflet.css", "/leaflet/leaflet.js", "/app.css", "/app.js"}, parser.found
            for asset, integrity in parser.found.items():
                status, headers, data = server.get(asset)
                want_type = "text/css" if asset.endswith(".css") else "text/javascript"
                assert status == 200 and headers["Content-Type"].startswith(want_type), (asset, status, headers)
                if asset in LEAFLET_SRI:  # the page pins the published hash, and the file has it
                    digest = "sha256-" + base64.b64encode(hashlib.sha256(data).digest()).decode()
                    assert integrity == digest == LEAFLET_SRI[asset], (asset, integrity, digest)
                if asset == "/leaflet/leaflet.js":
                    assert data.startswith(b"/* @preserve\n * Leaflet 1.9.4,"), data[:80]
            assert b"tile.openstreetmap.org" in server.get("/app.js")[2]  # the base map, the one internet source
            assert server.get("/leaflet/")[0] == 404 and server.get("/index.html")[0] == 404
            status, headers, body = server.get("/", method="HEAD")
            assert status == 200 and body == b"" and int(headers["Content-Length"]) > 1000, (status, headers)


def test_chrome_shows_the_datasets_asks_for_exactly_the_tiles_on_the_map_and_switches():
    """catches: a dataset switch that doesn't list the served files or doesn't change the map and the count, tile URLs with the wrong id, zoom, x or y, tiles asked for a view the map doesn't end up showing, a wrong tile count (one too many at a tile edge, or columns lost or doubled in a copy of the world), a points-on-screen count that isn't the exact count of the view (step 7: the count API), a wrong legend or pixel size, a layer box that does nothing, the base map drawn over the heat, or a script error, console error or blocked load (CSP) on the page"""
    if not browser.available():
        return "SKIPPED: no Google Chrome"
    with tempfile.TemporaryDirectory() as tmp:
        tmp = pathlib.Path(tmp)
        beijing = [gpt.code_of((843 * 256 + i) << 14, (388 * 256 + i) << 14) for i in range(200)]  # in tile 10/843/388
        files = [make_gpt(tmp, "first", beijing), make_gpt(tmp, "second-set", [gpt.code_of(0, 0)])]
        max_pixel = gpt.header(beijing)["max_pixel"]  # the color scale, from the oracle
        with Server(*files) as server, browser.Browser(1200, 800) as chrome:
            text = functools.partial(text_of, chrome)

            def tiles_counted_right():  # "Tiles on screen" = the distinct tiles overlapping the window
                visible = chrome.js(VISIBLE)
                assert int(text("tiles")) == len(visible), (text("tiles"), sorted(visible))

            # Centered on the middle of tile 10/843/388, the 1200 × 800 map covers tiles 841–845 × 386–390,
            # every screen edge at least 15 px from a tile edge.
            lat, lon = tile_center(10, 843, 388)
            chrome.open(f"http://127.0.0.1:{server.port}/#first/10/{lat:.6f}/{lon:.6f}")
            chrome.wait(LOADED)
            expected = {f"10/{x}/{y}" for x in range(841, 846) for y in range(386, 391)}
            assert sorted(chrome.js(ON_MAP)) == sorted(expected), chrome.js(ON_MAP)
            requested = chrome.js(REQUESTED)
            assert sorted(requested) == sorted(f"first/{t}" for t in expected), requested  # each once, nothing else
            assert chrome.js("[...document.querySelectorAll('#switch button')].map((b) => b.dataset.id)") == ["first", "second-set"]
            assert (text("points"), text("file"), text("zoom"), text("tiles")) == ("200", "first.gpt", "10", "25")
            chrome.wait("document.getElementById('in-view').textContent === '200'")  # the exact count of the view
            assert text("legend-max") == f"{max_pixel[10]:,}" and text("legend-mid") == "", (text("legend-max"), max_pixel[10])
            shown_lat = float(chrome.js("location.hash").split("/")[2])
            meters = 40075016.686 * math.cos(math.radians(shown_lat)) / 2 ** (10 + 8)  # the equator / pixels around it
            assert text("pixel") == f"{round(meters)} m", (text("pixel"), meters)
            # The request list: the last 9, each a tile on the map with its X-Points (200 in 10/843/388, else 0).
            rows = chrome.js("[...document.querySelectorAll('#requests > div')].map((r) => r.textContent)")
            assert len(rows) == 9, rows
            for row in rows:
                tile, points = re.fullmatch(r"200GET /tiles/first/(\d+/\d+/\d+)\.png([\d,]+) pts", row).groups()
                assert tile in expected and points == ("200" if tile == "10/843/388" else "0"), row

            # The layer boxes, clicked with the mouse.
            chrome.click("#show-borders")
            chrome.wait("[...document.querySelectorAll('#map .heat-tile')].every((t) => t.classList.contains('tile-border'))")
            label = chrome.js("getComputedStyle(document.querySelector('[data-tile=\"10/843/388\"]'), '::after').content")
            assert label == '"10/843/388"', label  # the border carries the tile's address
            chrome.click("#show-heat")
            chrome.wait("document.querySelectorAll('#map .heat-tile').length === 0")
            assert text("in-view") == "200", text("in-view")  # the exact count needs no heat tiles
            chrome.click("#show-heat")
            chrome.wait(LOADED)
            chrome.wait("document.getElementById('in-view').textContent === '200'")
            chrome.click("#show-base")
            chrome.wait("document.querySelector('#map .base-dark') === null")
            chrome.click("#show-base")
            chrome.wait("document.querySelector('#map .base-dark') !== null")
            assert chrome.js(HEAT_ON_TOP), "the base map, turned off and on, covers the heat"

            # The tile count where the screen's right and bottom edges lie exactly on tile edges: the center at
            # map pixel (843 × 256 + 168, 388 × 256 + 112) puts them at x = 846 × 256 and y = 390 × 256.
            chrome.js("void map.setView([%r, %r], 10, { animate: false })" % pixel_latlon(10, 843 * 256 + 168, 388 * 256 + 112))
            chrome.wait(LOADED)
            assert text("tiles") == "20", text("tiles")  # 841–845 × 386–389
            tiles_counted_right()
            # Copies of the world: east of the antimeridian the same tiles and points; at zoom 1 several copies
            # are on screen, each tile counted once. (The map is moved the way dragging would move it.)
            chrome.js(f"void map.setView([{lat}, {lon + 360}], 10, {{ animate: false }})")
            chrome.wait(LOADED)
            chrome.wait("document.getElementById('in-view').textContent === '200'")
            assert text("tiles") == "25" and abs(float(chrome.js("location.hash").split("/")[3]) - lon) < 1e-4, (text("tiles"), chrome.js("location.hash"))
            tiles_counted_right()
            chrome.js("void map.setView([0, 0], 1, { animate: false })")
            chrome.wait(LOADED)
            chrome.wait("document.getElementById('in-view').textContent === '200'")
            assert text("tiles") == "4", text("tiles")
            tiles_counted_right()

            # The switch: the other dataset's count, its own tiles only, at its own view box (the world's
            # north-west corner, so the screen crosses the 180° line).
            before = len(chrome.js(REQUESTED))
            chrome.click('#switch button[data-id="second-set"]')
            chrome.wait("document.getElementById('points').textContent === '1' && location.hash.startsWith('#second-set/')")
            chrome.wait(LOADED)
            after, on_map = chrome.js(REQUESTED)[before:], chrome.js(ON_MAP)
            assert after and all(r.startswith("second-set/") for r in after), after
            assert {r.split("/", 1)[1] for r in after} <= set(on_map), (after, on_map)  # only tiles it shows
            assert "0/0" in {"/".join(t.split("/")[1:]) for t in on_map}, on_map  # the corner tile with the point
            assert chrome.js("[...document.querySelectorAll('#switch button.on')].map((b) => b.dataset.id)") == ["second-set"]
            chrome.wait("document.getElementById('in-view').textContent === '1'")
            tiles_counted_right()
            assert not chrome.problems(), chrome.problems()


def test_chrome_keeps_the_address_right_and_opens_any_address_safely():
    """catches: an address that stops following the map (the page rewriting it so often that the browser ignores it), a reload that opens another view, a typed address that does nothing, lat and lon swapped in the address, or an address with numbers out of range that freezes the page or breaks the legend"""
    if not browser.available():
        return "SKIPPED: no Google Chrome"
    with tempfile.TemporaryDirectory() as tmp:
        beijing = [gpt.code_of((843 * 256 + i) << 14, (388 * 256 + i) << 14) for i in range(200)]
        path = make_gpt(pathlib.Path(tmp), "first", beijing)
        max_pixel = gpt.header(beijing)["max_pixel"]
        with Server(path) as server, browser.Browser(1200, 800) as chrome:
            url = f"http://127.0.0.1:{server.port}/"
            lat, lon = tile_center(10, 843, 388)
            chrome.open(f"{url}#first/10/{lat:.6f}/{lon:.6f}")
            chrome.wait(LOADED)
            # Ten zooms in with the + button, each one waited for: hundreds of tiles, one address per view.
            for zoom in range(11, 21):
                chrome.click(".leaflet-control-zoom-in")
                chrome.wait(f"document.getElementById('zoom').textContent === '{zoom}'")
                chrome.wait(LOADED)
            chrome.wait("location.hash.startsWith('#first/20/')")
            address, (zoom, x, y) = chrome.js("location.hash"), chrome.js(CENTER_PIXEL)
            chrome.js("window.beforeReload = true")
            chrome.reload()  # a reload (or a copied link) opens the same view
            chrome.wait("!window.beforeReload && document.getElementById('zoom').textContent === '20'")
            chrome.wait(LOADED)
            zoom2, x2, y2 = chrome.js(CENTER_PIXEL)
            assert zoom2 == zoom == 20 and abs(x2 - x) < 1 and abs(y2 - y) < 1, (address, (x, y), (x2, y2))  # within a pixel
            assert chrome.js("location.hash") == address, (address, chrome.js("location.hash"))
            shown_lat, shown_lon = map(float, address.split("/")[2:])
            assert abs(shown_lat - lat) < 0.01 and abs(shown_lon - lon) < 0.01, (address, lat, lon)  # lat, then lon

            # Typed addresses move the map; numbers out of range are brought into range.
            for typed, zoom in [("first/9/39.9/1e20", "9"), ("first/99/91/0", "24"), ("first/24/0/400000000000", "24"),
                                ("first/-3/-91/-540", "0")]:
                chrome.open(f"{url}#{typed}")
                chrome.wait(f"document.getElementById('zoom').textContent === '{zoom}' && location.hash !== '#{typed}'")
                chrome.wait(LOADED)
                shown_lat, shown_lon = map(float, chrome.js("location.hash").split("/")[2:])
                assert abs(shown_lat) <= 85.0512 and -180 <= shown_lon <= 180, (typed, chrome.js("location.hash"))
            # Zoom 0: all 200 points in one pixel, so the legend has a middle label, √200.
            assert (text_of(chrome, "legend-max"), text_of(chrome, "legend-mid")) == (f"{max_pixel[0]:,}", f"{round(math.sqrt(max_pixel[0]))}")
            assert max_pixel[0] == 200
            assert not chrome.problems(), chrome.problems()


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def test_chrome_shows_when_the_dataset_list_or_the_tiles_fail():
    """catches: a page that stays blank and silent when the dataset list can't be loaded, or when the server stops answering tile requests; a test helper that hides the page's own failed requests"""
    if not browser.available():
        return "SKIPPED: no Google Chrome"
    with tempfile.TemporaryDirectory() as tmp:
        tmp = pathlib.Path(tmp)
        path = make_gpt(tmp, "first", [gpt.code_of(843 << 22, 388 << 22)])
        with Server(path) as server, browser.Browser(1200, 800) as chrome:
            # The page and Leaflet, served by a plain file server that has no /api/datasets (404).
            site = tmp / "site"
            for name in ["/", "/app.css", "/app.js", "/leaflet/leaflet.css", "/leaflet/leaflet.js"]:
                target = site / ("index.html" if name == "/" else name.lstrip("/"))
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(server.get(name)[2])
            stub = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=str(site)))
            threading.Thread(target=stub.serve_forever, daemon=True).start()
            try:
                chrome.open(f"http://127.0.0.1:{stub.server_address[1]}/")
                chrome.wait("getComputedStyle(document.getElementById('error')).display === 'block'")
                assert text_of(chrome, "error") == "Can't load the dataset list: the server answered 404", text_of(chrome, "error")
            finally:
                stub.shutdown()
                stub.server_close()

            # The real server, then stopped: the next tile requests fail, and the page says so.
            chrome.open(f"http://127.0.0.1:{server.port}/#first/10/39.9/116.4")
            chrome.wait(LOADED)
            assert chrome.js("getComputedStyle(document.getElementById('error')).display") == "none"
            # A failed request of the page's own (here a missing file) is reported by browser.py.
            assert chrome.js("fetch('/no-such-file').then((r) => r.status)") == 404
            assert any("404" in e["text"] for e in chrome.page_log()), chrome.log
            server.process.kill()
            server.process.wait()
            chrome.js("void map.panBy([1500, 0], { animate: false })")
            chrome.wait("document.querySelector('#requests > div').textContent.startsWith('ERRGET /tiles/first/10/')")
            assert chrome.js("document.querySelector('#requests > div').textContent").endswith("failed")
            assert text_of(chrome, "error") == "Tile requests fail: is the server running?"
            assert chrome.js("getComputedStyle(document.getElementById('error')).display") == "block"
