const LDI_COLORS = [
  { max: 20, color: "#2b6cb0", label: "Properly Hydrated" },
  { max: 40, color: "#38a169", label: "Mild Moisturizing Recommended" },
  { max: 60, color: "#d69e2e", label: "Lotion Advised" },
  { max: 80, color: "#dd6b20", label: "Elbows at Risk" },
  { max: 90, color: "#c53030", label: "Cocoa Butter Recommended" },
  { max: 101, color: "#6b46c1", label: "Extreme Ashiness Warning" },
];

function colorFor(ldi) {
  return (LDI_COLORS.find(b => ldi < b.max) || LDI_COLORS[LDI_COLORS.length - 1]).color;
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

function ringsToPathD(polys) {
  let d = "";
  for (const poly of polys) {
    for (const ring of poly) {
      d += ring.map((pt, i) => `${i === 0 ? "M" : "L"}${project(pt).join(",")}`).join(" ") + " Z ";
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
    path.setAttribute("d", ringsToPathD(polys));
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
    path.setAttribute("d", ringsToPathD(polys));
    path.setAttribute("class", "state-outline");
    g.appendChild(path);
  });

  applyZoomTransform();
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

function buildDiscussion(data, sortedEntries, dayMeta) {
  const dry = sortedEntries.slice(0, 5).map(e => e[0]);
  const moist = sortedEntries.slice(-5).map(e => e[0]).reverse();
  const avg = data.national_average.toFixed(1);
  const issued = fmtIssued(data.issued_utc);
  const periodLine = dayMeta.offset === 0
    ? "THIS ANALYSIS REPRESENTS CURRENT CONDITIONS."
    : dayMeta.offset > 0
      ? `THIS IS A MODEL-BASED OUTLOOK FOR ${dayMeta.date}, ${dayMeta.offset} DAY(S) AHEAD. FORECAST CONFIDENCE DECREASES WITH LEAD TIME.`
      : `THIS IS AN ARCHIVED ANALYSIS FOR ${dayMeta.date}, ${Math.abs(dayMeta.offset)} DAY(S) IN THE PAST.`;

  const text =
`NLS AREA FORECAST DISCUSSION
NATIONAL LOTION SERVICE
${issued}

.SYNOPSIS...
NATIONAL MEAN LOTION DEMAND INDEX AT ${avg} (${data.national_category.toUpperCase()})
FOR ${dayMeta.date}. ${periodLine}

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
DRAG TO PAN, DOUBLE-CLICK TO RESET. SEE THE 7-DAY TAB SELECTOR FOR
ARCHIVED ANALYSES (T-3..T-1) AND THE MODEL-BASED OUTLOOK (T+1..T+3).

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

async function selectDay(entry) {
  document.querySelectorAll(".day-tab").forEach(t => {
    t.classList.toggle("active", t.dataset.date === entry.date);
  });
  document.getElementById("today-map").src = `assets/maps/timeline/${entry.date}.png`;

  try {
    const dayData = await loadJSON(`data/timeline/${entry.date}.json`);
    const sorted = populateSummary(dayData);
    if (!statesGeoCache) statesGeoCache = await loadJSON("assets/us-states.json");
    if (!countiesGeoCache) countiesGeoCache = await loadJSON("assets/us-counties.json");
    buildCountyMap(countiesGeoCache, statesGeoCache, dayData);
    buildDiscussion(dayData, sorted, entry);
    buildAdvisories(sorted);
  } catch (err) {
    console.error(err);
    document.getElementById("afd-text").textContent =
      "Discussion unavailable: could not load data for " + entry.date + " (" + err.message + ").";
  }
}

async function setupDayTabs() {
  const container = document.getElementById("day-tabs");
  try {
    const index = await loadJSON("data/timeline_index.json");
    container.innerHTML = index.map(e =>
      `<button class="day-tab ${e.offset > 0 ? "forecast" : ""}" data-date="${e.date}">${e.label}</button>`
    ).join("");
    container.querySelectorAll(".day-tab").forEach((btn, i) => {
      btn.addEventListener("click", () => selectDay(index[i]));
    });
    const todayEntry = index.find(e => e.offset === 0) || index[Math.floor(index.length / 2)];
    if (todayEntry) await selectDay(todayEntry);
  } catch (err) {
    console.error("Could not load timeline index, falling back to today.json", err);
    container.innerHTML = "";
    try {
      const dayData = await loadJSON("data/today.json");
      const sorted = populateSummary(dayData);
      statesGeoCache = await loadJSON("assets/us-states.json");
      countiesGeoCache = await loadJSON("assets/us-counties.json");
      buildCountyMap(countiesGeoCache, statesGeoCache, dayData);
      buildDiscussion(dayData, sorted, { date: dayData.date, offset: 0 });
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
