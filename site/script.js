// Same 6 stops as LDI_COLORS in make_map.py, evenly spaced across 0-100 --
// matplotlib's LinearSegmentedColormap.from_list spaces a flat color list
// evenly by default, so this mirrors that rather than the 0/20/40/60/80/90/100
// legend boundaries (those are label positions only, not color-transition
// points -- see the scale legend in index.html).
const LDI_GRADIENT_STOPS = ["#4a6fa5", "#7fc6a4", "#b9c99a", "#e8dcc0", "#8b8fce", "#6b46c1"];

function hexToRgb(hex) {
  const n = parseInt(hex.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

function rgbToHex([r, g, b]) {
  return "#" + [r, g, b]
    .map(v => Math.round(Math.max(0, Math.min(255, v))).toString(16).padStart(2, "0"))
    .join("");
}

function colorFor(ldi) {
  const v = Math.max(0, Math.min(100, ldi));
  const nSeg = LDI_GRADIENT_STOPS.length - 1;
  const scaled = (v / 100) * nSeg;
  const i = Math.min(nSeg - 1, Math.floor(scaled));
  const t = scaled - i;
  const c0 = hexToRgb(LDI_GRADIENT_STOPS[i]);
  const c1 = hexToRgb(LDI_GRADIENT_STOPS[i + 1]);
  return rgbToHex([0, 1, 2].map(k => c0[k] + (c1[k] - c0[k]) * t));
}

// Equirectangular projection matched to the CONUS bbox used in the Python
// pipeline (regions.py REGIONS.conus.bbox). Alaska/Hawaii insets are baked
// into the PNG itself and are not part of this interactive overlay.
const BBOX = { lat_min: 24.5, lat_max: 49.5, lon_min: -125.0, lon_max: -66.5 };
const VB = { w: 800, h: 500, pad: 20 };
const CONUS_EXCLUDE_STATE_FIPS = new Set(["02", "15", "72"]);

function project([lon, lat]) {
  const x = VB.pad + ((lon - BBOX.lon_min) / (BBOX.lon_max - BBOX.lon_min)) * (VB.w - 2 * VB.pad);
  const y = VB.pad + (1 - (lat - BBOX.lat_min) / (BBOX.lat_max - BBOX.lat_min)) * (VB.h - 2 * VB.pad);
  return [x, y];
}

// Alaska/Hawaii inset maps: bbox and padding match regions.py's REGIONS
// and REGION_PAD_DEG exactly. These are hover-only, non-zoomable, so each
// gets its own small SVG with a viewBox sized to preserve true aspect
// ratio (cos(mean_lat) correction), the same fix make_map.py's
// _render_region uses for the static PNG insets -- otherwise Alaska
// would look squashed/stretched at high latitude.
const INSET_REGIONS = {
  alaska: {
    bbox: { lat_min: 51.0, lat_max: 71.5, lon_min: -170.0, lon_max: -130.0 },
    padDeg: 0.6,
    stateFips: "02",
    stateName: "Alaska",
  },
  hawaii: {
    bbox: { lat_min: 18.5, lat_max: 22.5, lon_min: -160.5, lon_max: -154.5 },
    padDeg: 0.3,
    stateFips: "15",
    stateName: "Hawaii",
  },
};

function makeInsetProjection(bbox, padDeg) {
  const meanLatRad = ((bbox.lat_min + bbox.lat_max) / 2) * Math.PI / 180;
  const cosLat = Math.cos(meanLatRad);
  const lonMin = bbox.lon_min - padDeg;
  const latMin = bbox.lat_min - padDeg;
  const width = (bbox.lon_max - bbox.lon_min + 2 * padDeg) * cosLat;
  const height = bbox.lat_max - bbox.lat_min + 2 * padDeg;
  return {
    width,
    height,
    project([lon, lat]) {
      const x = (lon - lonMin) * cosLat;
      const y = height - (lat - latMin); // flip so north is up
      return [x, y];
    },
  };
}

function ringsToPathD(polys, projector) {
  let d = "";
  for (const poly of polys) {
    for (const ring of poly) {
      d += ring.map((pt, i) => `${i === 0 ? "M" : "L"}${projector(pt).join(",")}`).join(" ") + " Z ";
    }
  }
  return d;
}

async function loadJSON(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Failed to load ${url}: ${res.status}`);
  return res.json();
}

function fmtIssued(isoString) {
  if (!isoString) return "--";
  const d = new Date(isoString);
  if (isNaN(d.getTime())) return isoString;
  return d.toUTCString().replace("GMT", "UTC");
}

let countiesGeoCache = null;
let statesGeoCache = null;

// --- Pan/zoom state for the county map ---
const zoom = { scale: 1, tx: 0, ty: 0, minScale: 1, maxScale: 14 };

function applyZoomTransform() {
  const g = document.getElementById("zoom-group");
  if (g) g.setAttribute("transform", `translate(${zoom.tx},${zoom.ty}) scale(${zoom.scale})`);
}

function resetZoom() {
  zoom.scale = 1; zoom.tx = 0; zoom.ty = 0;
  applyZoomTransform();
}

function setupZoomPan(svg) {
  let dragging = false, lastX = 0, lastY = 0;

  function svgPoint(evt) {
    const rect = svg.getBoundingClientRect();
    const x = ((evt.clientX - rect.left) / rect.width) * VB.w;
    const y = ((evt.clientY - rect.top) / rect.height) * VB.h;
    return [x, y];
  }

  svg.addEventListener("wheel", (evt) => {
    evt.preventDefault();
    const [px, py] = svgPoint(evt);
    const factor = evt.deltaY < 0 ? 1.2 : 1 / 1.2;
    const newScale = Math.min(zoom.maxScale, Math.max(zoom.minScale, zoom.scale * factor));
    // keep the point under the cursor fixed while zooming
    zoom.tx = px - ((px - zoom.tx) / zoom.scale) * newScale;
    zoom.ty = py - ((py - zoom.ty) / zoom.scale) * newScale;
    zoom.scale = newScale;
    applyZoomTransform();
  }, { passive: false });

  svg.addEventListener("mousedown", (evt) => {
    dragging = true; lastX = evt.clientX; lastY = evt.clientY;
    svg.style.cursor = "grabbing";
  });
  window.addEventListener("mousemove", (evt) => {
    if (!dragging) return;
    const dx = (evt.clientX - lastX) * (VB.w / svg.getBoundingClientRect().width);
    const dy = (evt.clientY - lastY) * (VB.h / svg.getBoundingClientRect().height);
    zoom.tx += dx; zoom.ty += dy;
    lastX = evt.clientX; lastY = evt.clientY;
    applyZoomTransform();
  });
  window.addEventListener("mouseup", () => { dragging = false; svg.style.cursor = "grab"; });
  svg.addEventListener("dblclick", resetZoom);

  document.getElementById("zoom-reset-btn")?.addEventListener("click", resetZoom);
}

function buildCountyMap(countiesGeo, statesGeo, dayData) {
  const svg = document.getElementById("state-svg");
  const tooltip = document.getElementById("tooltip");
  const ns = "http://www.w3.org/2000/svg";

  svg.innerHTML = "";
  const g = document.createElementNS(ns, "g");
  g.setAttribute("id", "zoom-group");
  svg.appendChild(g);

  const countyData = dayData.counties || {};

  countiesGeo.features.forEach(feature => {
    const props = feature.properties;
    const stateFips = props.STATE;
    if (CONUS_EXCLUDE_STATE_FIPS.has(stateFips)) return;
    const fips = (props.GEO_ID || "").slice(-5) || (stateFips + props.COUNTY);
    const info = countyData[fips];
    const fill = info ? colorFor(info.ldi) : "#dddddd";

    const geom = feature.geometry;
    const polys = geom.type === "MultiPolygon" ? geom.coordinates : [geom.coordinates];

    const path = document.createElementNS(ns, "path");
    path.setAttribute("d", ringsToPathD(polys, project));
    path.setAttribute("fill", fill);
    path.setAttribute("class", "county-path");
    g.appendChild(path);

    path.addEventListener("mousemove", (e) => {
      if (!info) return;
      tooltip.classList.remove("hidden");
      tooltip.innerHTML = `<strong>${info.name} County, ${info.state}</strong><br>` +
        `LDI: ${info.ldi} (${info.category})<br>` +
        `Humidity: ${info.humidity_pct}%<br>` +
        `Wind: ${info.wind_mph} mph<br>` +
        `Elevation: ${info.elevation_m} m`;
      const rect = svg.parentElement.getBoundingClientRect();
      tooltip.style.left = (e.clientX - rect.left + 12) + "px";
      tooltip.style.top = (e.clientY - rect.top + 12) + "px";
    });
    path.addEventListener("mouseleave", () => tooltip.classList.add("hidden"));
  });

  // State outlines drawn on top for orientation while zoomed in
  statesGeo.features.forEach(feature => {
    const name = feature.properties.name;
    if (["Alaska", "Hawaii", "Puerto Rico"].includes(name)) return;
    const geom = feature.geometry;
    const polys = geom.type === "MultiPolygon" ? geom.coordinates : [geom.coordinates];
    const path = document.createElementNS(ns, "path");
    path.setAttribute("d", ringsToPathD(polys, project));
    path.setAttribute("class", "state-outline");
    g.appendChild(path);
  });

  applyZoomTransform();
}

// Alaska/Hawaii: hover-only county detail, no zoom/pan (their bboxes are
// small enough that panning/zooming doesn't add value the way it does for
// CONUS). Reuses the same #tooltip element as the main map.
function buildInsetMap(regionKey, svgId, countiesGeo, statesGeo, dayData) {
  const svg = document.getElementById(svgId);
  const tooltip = document.getElementById("tooltip");
  const ns = "http://www.w3.org/2000/svg";
  if (!svg) return;

  const cfg = INSET_REGIONS[regionKey];
  const proj = makeInsetProjection(cfg.bbox, cfg.padDeg);
  svg.setAttribute("viewBox", `0 0 ${proj.width.toFixed(2)} ${proj.height.toFixed(2)}`);

  svg.innerHTML = "";
  const g = document.createElementNS(ns, "g");
  svg.appendChild(g);

  const countyData = dayData.counties || {};

  countiesGeo.features.forEach(feature => {
    const props = feature.properties;
    if (props.STATE !== cfg.stateFips) return;
    const fips = (props.GEO_ID || "").slice(-5) || (props.STATE + props.COUNTY);
    const info = countyData[fips];
    const fill = info ? colorFor(info.ldi) : "#dddddd";

    const geom = feature.geometry;
    const polys = geom.type === "MultiPolygon" ? geom.coordinates : [geom.coordinates];
    const path = document.createElementNS(ns, "path");
    path.setAttribute("d", ringsToPathD(polys, proj.project));
    path.setAttribute("fill", fill);
    path.setAttribute("class", "county-path inset-county-path");
    g.appendChild(path);

    path.addEventListener("mousemove", (e) => {
      if (!info) return;
      tooltip.classList.remove("hidden");
      tooltip.innerHTML = `<strong>${info.name} County, ${info.state}</strong><br>` +
        `LDI: ${info.ldi} (${info.category})<br>` +
        `Humidity: ${info.humidity_pct}%<br>` +
        `Wind: ${info.wind_mph} mph<br>` +
        `Elevation: ${info.elevation_m} m`;
      const rect = svg.closest(".map-panel")?.getBoundingClientRect() || svg.getBoundingClientRect();
      tooltip.style.left = (e.clientX - rect.left + 12) + "px";
      tooltip.style.top = (e.clientY - rect.top + 12) + "px";
    });
    path.addEventListener("mouseleave", () => tooltip.classList.add("hidden"));
  });

  statesGeo.features.forEach(feature => {
    if (feature.properties.name !== cfg.stateName) return;
    const geom = feature.geometry;
    const polys = geom.type === "MultiPolygon" ? geom.coordinates : [geom.coordinates];
    const path = document.createElementNS(ns, "path");
    path.setAttribute("d", ringsToPathD(polys, proj.project));
    path.setAttribute("class", "state-outline");
    g.appendChild(path);
  });
}

function buildInsetMaps(countiesGeo, statesGeo, dayData) {
  buildInsetMap("alaska", "alaska-svg", countiesGeo, statesGeo, dayData);
  buildInsetMap("hawaii", "hawaii-svg", countiesGeo, statesGeo, dayData);
}

function populateSummary(data) {
  document.getElementById("national-ldi").textContent = data.national_average.toFixed(1);
  document.getElementById("national-category").textContent = data.national_category;
  document.getElementById("issued-line").textContent = "ISSUED: " + fmtIssued(data.issued_utc);
  document.getElementById("afd-issued-line").textContent = "ISSUED: " + fmtIssued(data.issued_utc);

  const entries = Object.entries(data.states || {}).sort((a, b) => b[1].ldi - a[1].ldi);
  const top = entries.slice(0, 6);
  const list = document.getElementById("top-states-list");
  list.innerHTML = top.map(([name, v]) => `<li>${name} &mdash; ${v.ldi} (${v.category})</li>`).join("");
  return entries;
}

function buildDiscussion(data, sortedEntries, entryMeta) {
  const dry = sortedEntries.slice(0, 5).map(e => e[0]);
  const moist = sortedEntries.slice(-5).map(e => e[0]).reverse();
  const avg = data.national_average.toFixed(1);
  const issued = fmtIssued(data.issued_utc);
  const offset = entryMeta.offset_days;
  const hourLabel = entryMeta.hour_label || "";
  const periodLine = offset === 0
    ? `THIS ANALYSIS REPRESENTS CONDITIONS AT ${hourLabel} ON ${entryMeta.date}.`
    : offset > 0
      ? `THIS IS A MODEL-BASED OUTLOOK FOR ${entryMeta.date} ${hourLabel}, ${offset} DAY(S) AHEAD. FORECAST CONFIDENCE DECREASES WITH LEAD TIME.`
      : `THIS IS AN ARCHIVED ANALYSIS FOR ${entryMeta.date} ${hourLabel}, ${Math.abs(offset)} DAY(S) IN THE PAST.`;

  const text =
`NLS AREA FORECAST DISCUSSION
NATIONAL LOTION SERVICE
${issued}

.SYNOPSIS...
NATIONAL MEAN LOTION DEMAND INDEX AT ${avg} (${data.national_category.toUpperCase()})
FOR ${entryMeta.date} ${hourLabel}. ${periodLine}

.AREAS OF CONCERN...
HIGHEST DEMAND ANALYZED OVER ${dry.join(", ").toUpperCase()}. RESIDENTS
IN THESE AREAS SHOULD ANTICIPATE ELEVATED LOTION DEMAND AND SHOULD NOT
DELAY APPLICATION TO EXPOSED EXTREMITIES, PARTICULARLY ELBOWS AND
KNUCKLES.

.FAVORABLE CONDITIONS...
LOWEST DEMAND ANALYZED OVER ${moist.join(", ").toUpperCase()} WHERE
AMBIENT HUMIDITY REMAINS SUFFICIENT TO SUPPORT NATURAL SKIN BARRIER
FUNCTION WITHOUT SUPPLEMENTAL INTERVENTION.

.OUTLOOK...
COUNTY-LEVEL DETAIL IS AVAILABLE ON THE MAP ABOVE -- SCROLL TO ZOOM,
DRAG TO PAN, DOUBLE-CLICK TO RESET. USE THE DAY SELECTOR (T-3..T+3) AND
HOUR SELECTOR (00Z/06Z/12Z/18Z) ABOVE FOR ARCHIVED ANALYSES AND THE
MODEL-BASED OUTLOOK, EACH AT THE SAME 6-HOUR RESOLUTION.

$$
NLS FORECAST DESK`;

  document.getElementById("afd-text").textContent = text;
}

function buildAdvisories(sortedEntries) {
  const list = document.getElementById("advisory-list");
  const advisories = [];

  const extreme = sortedEntries.filter(([, v]) => v.category === "Extreme Ashiness Warning");
  const cocoa = sortedEntries.filter(([, v]) => v.category === "Cocoa Butter Recommended");
  const risk = sortedEntries.filter(([, v]) => v.category === "Elbows at Risk");

  if (extreme.length) {
    advisories.push({ cls: "warning", title: "EXTREME ASHINESS WARNING",
      body: `In effect for ${extreme.map(e => e[0]).join(", ")}. Skin barrier failure imminent without immediate moisturizing intervention.` });
  }
  if (cocoa.length) {
    advisories.push({ cls: "warning", title: "COCOA BUTTER ADVISORY",
      body: `In effect for ${cocoa.map(e => e[0]).join(", ")}. Standard lotion may be insufficient; heavier-duty butters recommended.` });
  }
  if (risk.length) {
    advisories.push({ cls: "watch", title: "SEVERE ELBOW DRYNESS WATCH",
      body: `Conditions favorable for elbow and knuckle dryness across ${risk.map(e => e[0]).join(", ")}.` });
  }
  if (!advisories.length) {
    advisories.push({ cls: "", title: "NO ACTIVE ADVISORIES",
      body: "Conditions nationwide are within normal moisture parameters." });
  }

  list.innerHTML = advisories.map(a =>
    `<li class="advisory-item ${a.cls}"><span class="adv-title">${a.title}</span>${a.body}</li>`
  ).join("");
}

let timelineIndex = [];
let currentDate = null;
let currentHour = null;

async function selectEntry(entry) {
  currentDate = entry.date;
  currentHour = entry.hour;

  document.querySelectorAll("#day-tabs .day-tab").forEach(t => {
    t.classList.toggle("active", t.dataset.date === entry.date);
  });
  document.querySelectorAll("#hour-tabs .day-tab").forEach(t => {
    t.classList.toggle("active", Number(t.dataset.hour) === entry.hour);
  });
  document.getElementById("today-map").src = `assets/maps/timeline/${entry.file_base}.png`;
  document.querySelector(".product-id-line span").textContent =
    `PRODUCT: NLS-LDI-CONUS-${entry.offset_days > 0 ? "FCST" : entry.offset_days < 0 ? "ARCH" : "DAILY"}-${entry.hour_label}`;

  try {
    const dayData = await loadJSON(`data/timeline/${entry.file_base}.json`);
    const sorted = populateSummary(dayData);
    if (!statesGeoCache) statesGeoCache = await loadJSON("assets/us-states.json");
    if (!countiesGeoCache) countiesGeoCache = await loadJSON("assets/us-counties.json");
    buildCountyMap(countiesGeoCache, statesGeoCache, dayData);
    buildInsetMaps(countiesGeoCache, statesGeoCache, dayData);
    buildDiscussion(dayData, sorted, entry);
    buildAdvisories(sorted);
  } catch (err) {
    console.error(err);
    document.getElementById("afd-text").textContent =
      "Discussion unavailable: could not load data for " + entry.timestamp + " (" + err.message + ").";
  }
}

function findEntry(date, hour) {
  return timelineIndex.find(e => e.date === date && e.hour === hour);
}

async function setupDayTabs() {
  const dayContainer = document.getElementById("day-tabs");
  const hourContainer = document.getElementById("hour-tabs");
  try {
    timelineIndex = await loadJSON("data/timeline_index.json");

    // One button per unique day, in chronological order (4 hour-entries share a day)
    const days = [];
    for (const e of timelineIndex) {
      if (!days.find(d => d.date === e.date)) {
        days.push({ date: e.date, label: e.day_label, forecast: e.offset_days > 0 });
      }
    }
    dayContainer.innerHTML = days.map(d =>
      `<button class="day-tab ${d.forecast ? "forecast" : ""}" data-date="${d.date}">${d.label}</button>`
    ).join("");
    dayContainer.querySelectorAll(".day-tab").forEach(btn => {
      btn.addEventListener("click", () => {
        const entry = findEntry(btn.dataset.date, currentHour) || timelineIndex.find(e => e.date === btn.dataset.date);
        if (entry) selectEntry(entry);
      });
    });

    // Hour buttons are the same 4 slots every day
    const hours = [...new Set(timelineIndex.map(e => e.hour))].sort((a, b) => a - b);
    hourContainer.innerHTML = hours.map(h =>
      `<button class="day-tab" data-hour="${h}">${String(h).padStart(2, "0")}Z</button>`
    ).join("");
    hourContainer.querySelectorAll(".day-tab").forEach(btn => {
      btn.addEventListener("click", () => {
        const entry = findEntry(currentDate, Number(btn.dataset.hour));
        if (entry) selectEntry(entry);
      });
    });

    const nowEntry = timelineIndex.find(e => e.is_now) || timelineIndex[Math.floor(timelineIndex.length / 2)];
    if (nowEntry) await selectEntry(nowEntry);
  } catch (err) {
    console.error("Could not load timeline index, falling back to today.json", err);
    dayContainer.innerHTML = "";
    hourContainer.innerHTML = "";
    try {
      const dayData = await loadJSON("data/today.json");
      const sorted = populateSummary(dayData);
      statesGeoCache = await loadJSON("assets/us-states.json");
      countiesGeoCache = await loadJSON("assets/us-counties.json");
      buildCountyMap(countiesGeoCache, statesGeoCache, dayData);
      buildInsetMaps(countiesGeoCache, statesGeoCache, dayData);
      buildDiscussion(dayData, sorted, { date: dayData.date, offset_days: 0, hour_label: "" });
      buildAdvisories(sorted);
    } catch (err2) {
      document.getElementById("afd-text").textContent = "Discussion unavailable: " + err2.message;
    }
  }
}

function setupMonthTabs() {
  const tabs = document.querySelectorAll(".month-tab");
  const img = document.getElementById("normal-map");
  tabs.forEach(tab => {
    tab.addEventListener("click", () => {
      tabs.forEach(t => t.classList.remove("active"));
      tab.classList.add("active");
      img.src = `assets/maps/monthly/${tab.dataset.month}.png`;
    });
  });
}

async function init() {
  const svg = document.getElementById("state-svg");
  setupZoomPan(svg);
  await setupDayTabs();
  setupMonthTabs();
}

init();
