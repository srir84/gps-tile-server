// app.js: the map page (www/index.html): datasets, heat tiles, the side panel, hover counts, the box tool and
// its CSV export.
"use strict";
// State: the datasets the server lists and the one shown.
const state = { datasets: [], current: null };
const MAX_LAT = 85.05112877980659; // Web Mercator's edge (DESIGN §9.4)
const $ = (id) => document.getElementById(id);
const format = (n) => n.toLocaleString("en-US");

const map = L.map("map", { zoomControl: false, minZoom: 0, maxZoom: 24 });
L.control.zoom({ position: "bottomleft" }).addTo(map);
L.control.scale({ imperial: false, position: "bottomleft" }).addTo(map);
// OpenStreetMap's own tiles (no key needed), darkened by the .base-dark filter so the heat stands out.
// zIndex 1, the heat layer 2: the heat stays on top when the base map is turned off and on again.
const base = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxNativeZoom: 19, maxZoom: 24, className: "base-dark", zIndex: 1,
  attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
}).addTo(map);

// Heat tiles are fetched rather than set as <img src>, so the page can read each tile's X-Points header.
// A tile is a <div data-tile="z/x/y"> holding the picture, so its border can carry its address.
const Heat = L.GridLayer.extend({
  createTile(coords, done) {
    const tile = document.createElement("div"), image = document.createElement("img");
    tile.className = "heat-tile";
    image.alt = "";
    tile.append(image);
    const id = state.current.id, key = `${coords.z}/${coords.x}/${coords.y}`;
    const path = `/tiles/${id}/${key}.png`;
    tile.dataset.tile = key;
    if ($("show-borders").checked) tile.classList.add("tile-border");
    tile.abort = new AbortController(); // a tile Leaflet removes (pan, zoom) stops its request
    fetch(path, { signal: tile.abort.signal }).then(async (response) => {
      const points = Number(response.headers.get("X-Points") || 0);
      logRequest(response.status, path, `${format(points)} pts`);
      $("error").style.display = "none";
      if (!response.ok) throw new Error(`${response.status}`);
      const url = URL.createObjectURL(await response.blob());
      image.onload = () => { URL.revokeObjectURL(url); done(null, tile); };
      image.onerror = () => { URL.revokeObjectURL(url); done(new Error(`not an image: ${path}`), tile); };
      image.src = url;
    }).catch((error) => {
      if (error.name !== "AbortError" && error instanceof TypeError) { // no answer at all (not a 404)
        logRequest("ERR", path, "failed");
        showError("Tile requests fail: is the server running?");
      }
      done(error, tile);
    });
    return tile;
  },
});
let heat = null;

// One row of "Tile requests": the status (ERR when the server didn't answer), the path, the result.
function logRequest(status, path, result) {
  const row = document.createElement("div");
  row.innerHTML = `<span class="status"></span><span class="path"></span><span class="pts"></span>`;
  row.children[0].textContent = status;
  row.children[0].classList.toggle("bad", status !== 200);
  row.children[1].textContent = `GET ${path}`;
  row.children[1].title = path;
  row.children[2].textContent = result;
  const list = $("requests");
  list.prepend(row);
  while (list.children.length > 9) list.lastChild.remove();
}

// Ground size of one screen pixel at the map's center, in Web Mercator.
function pixelSize() {
  const meters = 156543.03392 * Math.cos((map.getCenter().lat * Math.PI) / 180) / 2 ** map.getZoom();
  return meters >= 1000 ? `${(meters / 1000).toFixed(1)} km` : meters >= 1 ? `${Math.round(meters)} m`
    : `${Math.round(meters * 100)} cm`;
}

// The tiles on screen at the current zoom, as Leaflet loads them: x wraps around (the map shows copies of
// the world side by side, with the same tiles), y stops at the top and bottom of the world. At most n
// columns, so each tile is listed once even when several copies of the world are on screen.
function tilesOnScreen() {
  const z = map.getZoom(), bounds = map.getPixelBounds(), n = 2 ** z, keys = [];
  const min = bounds.min.divideBy(256).floor(), max = bounds.max.divideBy(256).ceil().subtract([1, 1]);
  for (let x = min.x; x <= max.x && x < min.x + n; x++)
    for (let y = Math.max(min.y, 0); y <= Math.min(max.y, n - 1); y++) keys.push(`${z}/${((x % n) + n) % n}/${y}`);
  return keys;
}

// After every move: the panel, the exact count of the points on screen, the legend for this zoom, and the
// address. The address is written only here and only when it changes: browsers ignore a page that rewrites
// it hundreds of times.
function updateView() {
  if (!state.current) return;
  const z = map.getZoom();
  $("zoom").textContent = z;
  $("pixel").textContent = pixelSize();
  $("tiles").textContent = tilesOnScreen().length;
  countView();
  const max = state.current.max_pixel[Math.min(z, 24)] || 1;
  $("legend-max").textContent = format(max);
  $("legend-mid").textContent = max >= 100 ? format(Math.round(Math.sqrt(max))) : "";
  // The center wrapped into -180..180 (even in a copy of the world), with enough decimals to put it back
  // within a tenth of a pixel: a pixel is 360 / (256 × 2^zoom) degrees across, less in latitude up north.
  const center = map.getCenter().wrap(), digits = Math.max(4, Math.ceil(Math.log10((256 * 2 ** z) / 36)) + 1);
  const address = `#${state.current.id}/${z}/${center.lat.toFixed(digits)}/${center.lng.toFixed(digits)}`;
  if (location.hash !== address) history.replaceState(null, "", address);
}

function showError(message) {
  $("error").style.display = "block";
  $("error").textContent = message;
}

// Count API (step 7, DESIGN §9.2): a box is west,south,east,north in degrees. A world unit is 360 / 2^32 =
// 8.4e-8 degrees, so 9 decimals name one unit exactly when an edge is put in the middle of its unit.
const WORLD = 2 ** 32;
const lonOfX = (x) => (x / WORLD) * 360 - 180;
const latOfY = (y) => (Math.atan(Math.sinh(Math.PI * (1 - (2 * y) / WORLD))) * 180) / Math.PI;
const bboxText = (w, s, e, n) => [w, s, e, n].map((v) => v.toFixed(9)).join(",");
// World units x0..x1, y0..y1 (edges included) as bbox text: each edge in the middle of its unit.
const unitBox = (x0, y0, x1, y1) => bboxText(lonOfX(x0 + 0.5), latOfY(y1 + 0.5), lonOfX(x1 + 0.5), latOfY(y0 + 0.5));

// The view as boxes of whole world units: the pixels on screen, from the first column and row to the last.
// (The screen's edges are pixel edges; a box from its corners would take in the next pixel's first unit.)
// Columns wrap around the world, a view across the 180° line is two boxes, one wider than the world is the
// whole width, and rows stop at the world's top and bottom.
function viewBoxes() {
  const z = map.getZoom(), size = 2 ** (24 - z), across = 256 * 2 ** z, b = map.getPixelBounds();
  const top = Math.max(b.min.y, 0), bottom = Math.min(b.max.y, across) - 1;
  if (top > bottom) return []; // all above or below the world
  const y0 = top * size, y1 = (bottom + 1) * size - 1, width = b.max.x - b.min.x;
  if (width >= across) return [unitBox(0, y0, WORLD - 1, y1)];
  const left = ((b.min.x % across) + across) % across, right = left + width - 1;
  if (right < across) return [unitBox(left * size, y0, (right + 1) * size - 1, y1)];
  return [unitBox(left * size, y0, WORLD - 1, y1), unitBox(0, y0, (right - across + 1) * size - 1, y1)];
}

// A drawn box as boxes the count API takes: longitudes wrapped into -180..180, split in two
// where it crosses the 180° line (the API takes no box across it), the whole world when it is wider.
// Latitudes stop at 85.051128779: MAX_LAT written with 9 decimals would round up, past the map's edge
// (the API refuses that), and this is still inside the map's first and last world unit.
function boxesOf(bounds) {
  if (bounds.getSouth() > MAX_LAT || bounds.getNorth() < -MAX_LAT) return []; // all above or below the world
  const clampLat = (v) => Math.min(Math.max(v, -85.051128779), 85.051128779);
  const s = clampLat(bounds.getSouth()), n = clampLat(bounds.getNorth());
  let w = bounds.getWest(), e = bounds.getEast();
  if (e - w >= 360) return [bboxText(-180, s, 180, n)];
  const shift = Math.floor((w + 180) / 360) * 360;
  w -= shift;
  e -= shift;
  if (e <= 180) return [bboxText(w, s, e, n)];
  return [bboxText(w, s, 180, n), bboxText(-180, s, e - 360, n)];
}

// The points in some boxes of the shown dataset, added up; rejects with the HTTP status.
function countBoxes(boxes) {
  const id = state.current.id;
  return Promise.all(boxes.map((bbox) => fetch(`/api/datasets/${id}/count?bbox=${bbox}`)
    .then((r) => (r.ok ? r.json() : Promise.reject(r.status))).then((answer) => answer.count)))
    .then((counts) => counts.reduce((a, b) => a + b, 0));
}

// Points on screen. Only the answer to the latest question is shown (an older one may arrive later).
let viewAsked = 0;
function countView() {
  const ask = ++viewAsked;
  countBoxes(viewBoxes())
    .then((n) => { if (ask === viewAsked) $("in-view").textContent = format(n); })
    .catch(() => { if (ask === viewAsked) $("in-view").textContent = "–"; });
}

// Hover: the points in the screen pixel under the mouse, exactly the ones drawn in it (step 4 colors it by
// that count). The pixel comes from the mouse's position on the map's pixel grid, whole numbers, with no
// round trip through degrees (which can land one pixel off at an edge). The box is that pixel's world
// units, 2^(24 - zoom) on a side, its edges put in the middle of its first and last unit. Asked when the
// mouse rests for 100 ms, and again when the map has moved under a still mouse. Above or below the world
// there is no pixel: "–".
let hoverTimer = null, hoverAsked = 0, mouseAt = null; // mouseAt: the mouse on the map (container point)
function pixelBox(layerPoint) {
  const z = map.getZoom(), size = 2 ** (24 - z), across = 256 * 2 ** z;
  const p = map.getPixelOrigin().add(layerPoint).floor();
  if (p.y < 0 || p.y >= across) return null;
  const x0 = (((p.x % across) + across) % across) * size, y0 = p.y * size;
  return unitBox(x0, y0, x0 + size - 1, y0 + size - 1);
}
// Drops the shown count and any answer still on its way (it would be for another pixel or dataset).
function forgetHover() {
  clearTimeout(hoverTimer);
  hoverAsked++;
  $("hover").textContent = "–";
}
function askHover() {
  forgetHover();
  if (!mouseAt || drawing || !state.current) return;
  hoverTimer = setTimeout(() => {
    const ask = ++hoverAsked, bbox = pixelBox(map.containerPointToLayerPoint(mouseAt));
    if (!bbox) return;
    countBoxes([bbox])
      .then((n) => { if (ask === hoverAsked) $("hover").textContent = `${format(n)} point${n === 1 ? "" : "s"}`; })
      .catch(() => { if (ask === hoverAsked) $("hover").textContent = "–"; });
  }, 100);
}
map.on("mousemove", (event) => { mouseAt = event.containerPoint; askHover(); });
map.on("mouseout", () => { mouseAt = null; forgetHover(); });
map.on("movestart", forgetHover);
map.on("moveend", askHover);

// Box tool: press "Draw a box", drag on the map, get the exact count of the points inside. The drag ends
// wherever the button is let go (also over the side panel or outside the window); Escape or leaving the
// window stops it, and a half-drawn box goes.
let drawing = false, corner = null, box = null, pressedAt = null; // corner, pressedAt: where the drag began
function setDrawing(on) {
  drawing = on;
  corner = null;
  $("box-tool").classList.toggle("on", on);
  $("map").classList.toggle("drawing", on);
  if (on) map.dragging.disable(); else map.dragging.enable();
}
function clearBox() {
  boxAsked++; // an answer still on its way is for this box: not shown
  if (box) map.removeLayer(box);
  box = null;
  $("box-count").textContent = "";
  $("export").hidden = true;
  $("box-text").textContent = "Drag on the map to count the points inside.";
}
$("box-tool").addEventListener("click", () => setDrawing(!drawing));
function stopDrawing() {
  if (corner) clearBox();
  setDrawing(false);
}
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && drawing) stopDrawing(); });
window.addEventListener("blur", () => { if (drawing) stopDrawing(); });
map.on("mousedown", (event) => {
  if (!drawing) return;
  L.DomEvent.preventDefault(event.originalEvent); // the drag draws the box; it doesn't select text on the page
  clearBox();
  corner = event.latlng;
  pressedAt = event.containerPoint;
  box = L.rectangle(L.latLngBounds(corner, corner), { color: "#4fd1b5", weight: 1, fillOpacity: 0.08, interactive: false }).addTo(map);
});
window.addEventListener("mousemove", (e) => { if (drawing && corner) box.setBounds(L.latLngBounds(corner, map.mouseEventToLatLng(e))); });
window.addEventListener("mouseup", (e) => {
  if (!drawing || !corner) return;
  if (map.mouseEventToContainerPoint(e).distanceTo(pressedAt) < 3) { // a click, not a drag: no box, keep drawing
    clearBox();
    corner = null;
    return;
  }
  const bounds = L.latLngBounds(corner, map.mouseEventToLatLng(e));
  setDrawing(false);
  box.setBounds(bounds);
  countBox(bounds);
});
let boxAsked = 0;
function countBox(bounds) {
  const boxes = boxesOf(bounds), ask = ++boxAsked, id = state.current.id;
  $("box-text").textContent = boxes.length === 0 ? "The box is outside the map."
    : boxes.map((b) => `Box ${b.split(",").map((v) => Number(v).toFixed(4)).join(", ")}`).join(" + ");
  $("box-count").textContent = "…";
  countBoxes(boxes)
    .then((n) => {
      if (ask !== boxAsked) return;
      $("box-count").textContent = `${format(n)} point${n === 1 ? "" : "s"}`;
      exportLink(id, boxes, n);
    })
    .catch((status) => { if (ask === boxAsked) $("box-count").textContent = `error ${status}`; });
}

// Export (step 8): a link to the CSV of the box's points, at most 1,000,000 rows (the server's limit). A box
// across the 180° line is two boxes and can't be one file: no link, and the note says why.
const MAX_EXPORT = 1000000;
function exportLink(id, boxes, n) {
  const link = $("export"), rows = Math.min(n, MAX_EXPORT);
  link.hidden = n === 0 || boxes.length !== 1;
  if (boxes.length === 2) $("box-text").textContent += " · across the 180° line: draw one box on each side to export";
  if (link.hidden) return;
  link.href = `/api/datasets/${id}/export.csv?bbox=${boxes[0]}&limit=${rows}`;
  link.textContent = n > rows ? `Export CSV (the first ${format(rows)} of ${format(n)} points, in file order)`
    : `Export CSV (${format(n)} row${n === 1 ? "" : "s"})`;
  link.title = n > rows ? "At most 1,000,000 rows, in the file's order: the box's north-west part comes first. Draw smaller boxes for the rest." : "";
}

// Shows a dataset at a view ({zoom, lat, lon}), or at its own view box (DESIGN §9.3). The map moves first,
// without animation, and only then gets the new heat layer: it asks only for the tiles it will show.
function show(dataset, view) {
  state.current = dataset;
  clearBox();
  setDrawing(false);
  forgetHover();
  $("file").textContent = `${dataset.id}.gpt`;
  $("points").textContent = format(dataset.points);
  for (const button of $("switch").children) button.classList.toggle("on", button.dataset.id === dataset.id);
  if (heat) map.removeLayer(heat);
  const still = { animate: false };
  if (view) map.setView([view.lat, view.lon], view.zoom, still);
  else if (dataset.view) map.fitBounds([[dataset.view[1], dataset.view[0]], [dataset.view[3], dataset.view[2]]], still);
  else map.setView([0, 0], 1, still);
  heat = new Heat({ maxZoom: 24, maxNativeZoom: 24, tileSize: 256, zIndex: 2 });
  heat.on("tileunload", (e) => e.tile.abort.abort());
  if ($("show-heat").checked) heat.addTo(map);
  updateView();
  askHover(); // the other dataset's count for the pixel under the mouse
}

// #id/zoom/lat/lon, as written by updateView. Any address is safe to open: the zoom is rounded into 0..24,
// the latitude kept inside the map and the longitude wrapped into -180..180 (a longitude like 1e20 would
// otherwise never let Leaflet's tile loop finish).
function parseHash() {
  const [id, zoom, lat, lon] = location.hash.slice(1).split("/");
  const z = Number(zoom), y = Number(lat), x = Number(lon);
  if (zoom === undefined || ![z, y, x].every(Number.isFinite)) return { id, view: null };
  const clamp = (v, low, high) => Math.min(Math.max(v, low), high);
  return { id, view: { zoom: clamp(Math.round(z), 0, 24), lat: clamp(y, -MAX_LAT, MAX_LAT), lon: ((x + 180) % 360 + 360) % 360 - 180 } };
}

$("show-heat").addEventListener("change", (e) => { if (e.target.checked) heat.addTo(map); else map.removeLayer(heat); });
$("show-base").addEventListener("change", (e) => { if (e.target.checked) base.addTo(map); else map.removeLayer(base); });
$("show-borders").addEventListener("change", (e) => {
  document.querySelectorAll("#map .heat-tile").forEach((t) => t.classList.toggle("tile-border", e.target.checked));
});
map.on("moveend", updateView); // also after a zoom
// A changed address (typed, or a link) shows what it names; replaceState in updateView doesn't come here.
window.addEventListener("hashchange", () => {
  const wanted = parseHash(), dataset = state.datasets.find((d) => d.id === wanted.id);
  if (dataset) show(dataset, wanted.view);
});

// Start: one switch button per dataset, then the dataset and view the address names (else the first
// dataset, at its view box).
function start(datasets) {
  state.datasets = datasets;
  for (const d of datasets) {
    const button = document.createElement("button");
    button.dataset.id = d.id;
    button.textContent = d.id;
    button.title = `${format(d.points)} points`;
    button.addEventListener("click", () => show(d, null));
    $("switch").append(button);
  }
  const wanted = parseHash();
  const first = datasets.find((d) => d.id === wanted.id) || datasets[0];
  show(first, first.id === wanted.id ? wanted.view : null);
}
// Only a failed dataset list shows this error; an error inside start() is not reported as one.
fetch("/api/datasets").then((r) => (r.ok ? r.json() : Promise.reject(new Error(`the server answered ${r.status}`))))
  .then(({ datasets }) => start(datasets), (error) => showError(`Can't load the dataset list: ${error.message}`));
