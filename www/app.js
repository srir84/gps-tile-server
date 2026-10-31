// app.js: the map page (www/index.html): datasets, heat tiles, the side panel.
"use strict";
// State: the datasets the server lists, the one shown, and what each tile on screen holds.
const state = { datasets: [], current: null, tilePoints: new Map() };
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
      if (state.current && state.current.id === id) state.tilePoints.set(key, points);
      const url = URL.createObjectURL(await response.blob());
      image.onload = () => { URL.revokeObjectURL(url); done(null, tile); };
      image.onerror = () => { URL.revokeObjectURL(url); done(new Error(`not an image: ${path}`), tile); };
      image.src = url;
      updatePoints();
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

// The points in the tiles on screen: their X-Points added up as they arrive ("–" while the heat layer
// is off, as nothing then arrives).
function updatePoints() {
  if (!state.current) return;
  let sum = 0;
  for (const key of tilesOnScreen()) sum += state.tilePoints.get(key) || 0;
  $("in-view").textContent = $("show-heat").checked ? format(sum) : "–";
}

// After every move: the panel, the legend for this zoom, and the address. The address is written only
// here and only when it changes: browsers ignore a page that rewrites it hundreds of times.
function updateView() {
  if (!state.current) return;
  const z = map.getZoom();
  $("zoom").textContent = z;
  $("pixel").textContent = pixelSize();
  $("tiles").textContent = tilesOnScreen().length;
  updatePoints();
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

// Shows a dataset at a view ({zoom, lat, lon}), or at its own view box (DESIGN §9.3). The map moves first,
// without animation, and only then gets the new heat layer: it asks only for the tiles it will show.
function show(dataset, view) {
  state.current = dataset;
  state.tilePoints.clear();
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

$("show-heat").addEventListener("change", (e) => {
  if (e.target.checked) heat.addTo(map); else map.removeLayer(heat);
  updatePoints();
});
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
