// Matches make_map.py's LDI_COLORS exactly: purple and periwinkle
// dropped entirely, just blue -> seafoam -> sage -> beige stretched
// across the full 0-100 range.
const LDI_GRADIENT_STOPS = ["#4a6fa5", "#7fc6a4", "#b9c99a", "#e8dcc0"];

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
// pipeline (regions.py REGIONS.conus.bbox).
const BBOX = { lat_min: 24.5, lat_max: 49.5, lon_min: -125.0, lon_max: -66.5 };
const VB = { w: 800, h: 500, pad: 20 };
const CONUS_EXCLUDE_STATE_FIPS = new Set(["02", "15", "72"]);

function project([lon, lat]) {
  const x = VB.pad + ((lon - BBOX.lon_min) / (BBOX.lon_max - BBOX.lon_min)) * (VB.w - 2 * VB.pad);
  const y = VB.pad + (1 - (lat - BBOX.lat_min) / (BBOX.lat_max - BBOX.lat_min)) * (VB.h - 2 * VB.pad);
  return [x, y];
}

const INSET_REGIONS = {
  alaska: {
    bbox: { lat_min: 51.0, lat_max: 71.5, lon_min: -170.0, lon_max: -130.0 },
    padDeg: 0.6, stateFips: "02", stateName: "Alaska",
  },
  hawaii: {
    bbox: { lat_min: 18.5, lat_max: 22.5, lon_min: -160.5, lon_max: -154.5 },
    padDeg: 0.3, stateFips: "15", stateName: "Hawaii",
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
    width, height,
    project([lon, lat]) {
      const x = (lon - lonMin) * cosLat;
      const y = height - (lat - latMin);
      return [x, y];
    },
  };
}

const US_TIME_ZONES = [
  { key: "ET", label: "Eastern", tz: "America/New_York" },
  { key: "CT", label: "Central", tz: "America/Chicago" },
  { key: "MT", label: "Mountain", tz: "America/Denver" },
  { key: "PT", label: "Pacific", tz: "America/Los_Angeles" },
  { key: "AKT", label: "Alaska", tz: "America/Anchorage" },
  { key: "HST", label: "Hawaii", tz: "Pacific/Honolulu" },
];

// ---------------------------------------------------------------------
// Timezone math. This is the piece the whole local-day-bucketing scheme
// depends on: converting a *wall-clock* time in an arbitrary IANA zone
// into the correct UTC instant, accounting for that zone's DST rules on
// that specific date (a fixed UTC offset assumption breaks near DST
// transitions). Standard iterative offset-correction: guess an instant,
// see what wall time it actually displays as in the target zone, adjust
// by the difference, repeat until it converges (2 passes is enough for
// every real-world zone, including half/quarter-hour-offset zones).
// ---------------------------------------------------------------------
function zonedOffsetMs(ms, tz) {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: tz, hourCycle: "h23",
    year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", second: "2-digit",
  }).formatToParts(new Date(ms));
  const get = (type) => Number(parts.find(p => p.type === type).value);
  const asUtcMs = Date.UTC(get("year"), get("month") - 1, get("day"),
                            get("hour"), get("minute"), get("second"));
  return asUtcMs - ms;
}

function zonedTimeToUtc(dateStr, hour, minute, tz) {
  const naiveMs = Date.parse(`${dateStr}T${String(hour).padStart(2, "0")}:${String(minute).padStart(2, "0")}:00Z`);
  const shift1 = zonedOffsetMs(naiveMs, tz);
  const corrected = naiveMs - shift1;
  // Re-check the offset AT the corrected instant -- only re-correct if it
  // actually differs (a real DST-boundary case), never unconditionally
  // re-apply shift1 again. Applying the same correction twice was the
  // bug: it overshot the true midnight boundary by a full offset-width
  // (e.g. landed on 08:00Z for EDT midnight instead of the correct 04:00Z).
  const shift2 = zonedOffsetMs(corrected, tz);
  return new Date(shift2 === shift1 ? corrected : naiveMs - shift2);
}

function getLocalDateStr(date, tz) {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: tz, year: "numeric", month: "2-digit", day: "2-digit",
  }).format(date);
}

function addDaysToDateStr(dateStr, days) {
  const [y, m, d] = dateStr.split("-").map(Number);
  const dt = new Date(Date.UTC(y, m - 1, d + days));
  return dt.toISOString().slice(0, 10);
}

// Formats `utcDate` in the given IANA zone, and flags whether that local
// moment falls on a different calendar day than `refDateStr`.
function formatInZone(utcDate, tz, refDateStr) {
  const timeStr = new Intl.DateTimeFormat("en-US", {
    timeZone: tz, hour: "numeric", minute: "2-digit",
  }).format(utcDate);
  const localDateStr = getLocalDateStr(utcDate, tz);
  let dayNote = "";
  if (localDateStr < refDateStr) dayNote = " (prev day)";
  else if (localDateStr > refDateStr) dayNote = " (next day)";
  return { timeStr, dayNote };
}

// Buckets the raw (UTC-timestamped) timeline entries into the VIEWER's
// own local calendar days, localToday-3 .. localToday+3. Because our
// sampling interval (6h) divides evenly into a calendar day (24h), every
// bucket contains exactly 4 entries for any UTC offset -- except right
// at a DST transition, where a local day is 23 or 25 hours long and can
// hold 3 or 5; the UI just displays however many actually landed there
// rather than forcing an exact count.
function buildLocalDayBuckets(timelineIndex, tz) {
  const localToday = getLocalDateStr(new Date(), tz);
  const dayLabels = ["T-3", "T-2", "T-1", "TODAY", "T+1", "T+2", "T+3"];

  const parsed = timelineIndex.map(e => ({
    entry: e, instant: new Date(e.timestamp + "Z"),
  }));

  const days = [];
  for (let offset = -3; offset <= 3; offset++) {
    const dateStr = addDaysToDateStr(localToday, offset);
    const nextDateStr = addDaysToDateStr(dateStr, 1);
    const midnight = zonedTimeToUtc(dateStr, 0, 0, tz);
    const nextMidnight = zonedTimeToUtc(nextDateStr, 0, 0, tz);
    const entries = parsed
      .filter(p => p.instant >= midnight && p.instant < nextMidnight)
      .map(p => p.entry)
      .sort((a, b) => a.timestamp.localeCompare(b.timestamp));
    days.push({
      date: dateStr, label: dayLabels[offset + 3], forecast: offset > 0, entries,
    });
  }
  return days;
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

  let lastTouchDist = null;
  let lastTapTime = 0;

  function touchDist(t0, t1) {
    return Math.hypot(t1.clientX - t0.clientX, t1.clientY - t0.clientY);
  }
  function touchMid(t0, t1) {
    return [(t0.clientX + t1.clientX) / 2, (t0.clientY + t1.clientY) / 2];
  }
  function svgPointXY(clientX, clientY) {
    const rect = svg.getBoundingClientRect();
    return [((clientX - rect.left) / rect.width) * VB.w, ((clientY - rect.top) / rect.height) * VB.h];
  }

  svg.addEventListener("touchstart", (evt) => {
    if (evt.touches.length === 1) {
      dragging = true;
      lastX = evt.touches[0].clientX;
      lastY = evt.touches[0].clientY;
      const now = Date.now();
      if (now - lastTapTime < 300) resetZoom();
      lastTapTime = now;
    } else if (evt.touches.length === 2) {
      dragging = false;
      lastTouchDist = touchDist(evt.touches[0], evt.touches[1]);
    }
  }, { passive: true });

  svg.addEventListener("touchmove", (evt) => {
    evt.preventDefault();
    if (evt.touches.length === 1 && dragging) {
      const t = evt.touches[0];
      const dx = (t.clientX - lastX) * (VB.w / svg.getBoundingClientRect().width);
      const dy = (t.clientY - lastY) * (VB.h / svg.getBoundingClientRect().height);
      zoom.tx += dx; zoom.ty += dy;
      lastX = t.clientX; lastY = t.clientY;
      applyZoomTransform();
    } else if (evt.touches.length === 2) {
      const [t0, t1] = evt.touches;
      const dist = touchDist(t0, t1);
      const [mx, my] = touchMid(t0, t1);
      if (lastTouchDist) {
        const factor = dist / lastTouchDist;
        const newScale = Math.min(zoom.maxScale, Math.max(zoom.minScale, zoom.scale * factor));
        const [px, py] = svgPointXY(mx, my);
        zoom.tx = px - ((px - zoom.tx) / zoom.scale) * newScale;
        zoom.ty = py - ((py - zoom.ty) / zoom.scale) * newScale;
        zoom.scale = newScale;
        applyZoomTransform();
      }
      lastTouchDist = dist;
    }
  }, { passive: false });

  svg.addEventListener("touchend", (evt) => {
    lastTouchDist = null;
    if (evt.touches.length === 1) {
      dragging = true;
      lastX = evt.touches[0].clientX;
      lastY = evt.touches[0].clientY;
    } else if (evt.touches.length === 0) {
      dragging = false;
    }
  });
  svg.addEventListener("touchcancel", () => { dragging = false; lastTouchDist = null; });

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
  const top = entries.slice(0, 10);
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
DRAG TO PAN, DOUBLE-CLICK TO RESET. USE THE DAY SLIDER AND HOUR
SELECTOR ABOVE (SHOWN IN YOUR LOCAL TIME) FOR ARCHIVED ANALYSES AND
THE MODEL-BASED OUTLOOK, OR PRESS PLAY TO STEP THROUGH AUTOMATICALLY.

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
let days = [];               // local-day buckets, see buildLocalDayBuckets()
let browserTz = "UTC";
let currentEntry = null;
let currentDayIdx = 0;
let currentDayData = null;
let playState = { playing: false, timeoutId: null };

function findDayAndSlot(entry) {
  for (let di = 0; di < days.length; di++) {
    const si = days[di].entries.findIndex(e => e.timestamp === entry.timestamp);
    if (si !== -1) return { dayIdx: di, slotIdx: si };
  }
  return null;
}

// Reference table: for the currently selected local day, show every
// zone's reading of each of that day's raw instants (usually 4).
function buildTimezoneTable(day) {
  const table = document.getElementById("tz-table");
  if (!table || !day.entries.length) return;
  const thead = table.querySelector("thead");
  const tbody = table.querySelector("tbody");
  if (!thead || !tbody) return;

  thead.innerHTML = "<tr><th></th>" +
    day.entries.map(e => `<th>${e.hour_label}</th>`).join("") + "</tr>";

  tbody.innerHTML = US_TIME_ZONES.map(zone => {
    const cells = day.entries.map(e => {
      const instant = new Date(e.timestamp + "Z");
      const { timeStr, dayNote } = formatInZone(instant, zone.tz, day.date);
      return `<td>${timeStr}${dayNote ? `<span class="tz-daynote">${dayNote}</span>` : ""}</td>`;
    }).join("");
    return `<tr><th>${zone.label} (${zone.key})</th>${cells}</tr>`;
  }).join("");
}

function setupTzToggle() {
  const btn = document.getElementById("tz-toggle");
  const wrap = document.getElementById("tz-table-wrap");
  if (!btn || !wrap) return;
  btn.addEventListener("click", () => {
    const currentlyHidden = wrap.classList.contains("hidden");
    wrap.classList.toggle("hidden", !currentlyHidden);
    btn.innerHTML = currentlyHidden
      ? "Hide all U.S. time zones &#9652;"
      : "Show all U.S. time zones &#9662;";
  });
}

function renderHourTabs(day) {
  const hourContainer = document.getElementById("hour-tabs");
  const nowMs = Date.now();
  hourContainer.innerHTML = day.entries.map(e => {
    const instant = new Date(e.timestamp + "Z");
    const { timeStr } = formatInZone(instant, browserTz, day.date);
    const isActual = instant.getTime() <= nowMs;
    const active = currentEntry && e.timestamp === currentEntry.timestamp;
    return `<button class="day-tab ${isActual ? "is-actual" : ""} ${active ? "active" : ""}" data-timestamp="${e.timestamp}">${timeStr}<span class="hour-local">${e.hour_label}</span></button>`;
  }).join("");
  hourContainer.querySelectorAll(".day-tab").forEach(btn => {
    btn.addEventListener("click", () => {
      stopPlayback();
      const entry = day.entries.find(e => e.timestamp === btn.dataset.timestamp);
      if (entry) selectEntry(entry);
    });
  });
}

async function selectEntry(entry) {
  currentEntry = entry;
  const loc = findDayAndSlot(entry);
  if (loc) currentDayIdx = loc.dayIdx;
  const day = days[currentDayIdx];

  const slider = document.getElementById("day-slider");
  if (slider) slider.value = currentDayIdx;
  document.querySelectorAll("#day-slider-labels span").forEach((s, i) => {
    s.classList.toggle("active", i === currentDayIdx);
  });

  renderHourTabs(day);
  buildTimezoneTable(day);

  document.querySelector(".product-id-line span").textContent =
    `PRODUCT: NLS-LDI-CONUS-${entry.offset_days > 0 ? "FCST" : entry.offset_days < 0 ? "ARCH" : "DAILY"}-${entry.hour_label}`;

  try {
    const dayData = await loadJSON(`data/timeline/${entry.file_base}.json`);
    currentDayData = dayData;
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

// --- Play button: steps through every entry across all 7 local-day
// buckets, in chronological order, looping continuously. Uses a
// self-rescheduling setTimeout (not setInterval) so a slow fetch can't
// cause overlapping ticks. ---
function stopPlayback() {
  playState.playing = false;
  if (playState.timeoutId) clearTimeout(playState.timeoutId);
  playState.timeoutId = null;
  const btn = document.getElementById("play-btn");
  if (btn) { btn.innerHTML = "&#9654; Play"; btn.classList.remove("playing"); }
}

async function playTick() {
  if (!playState.playing) return;
  const flat = days.flatMap(d => d.entries);
  if (!flat.length) { stopPlayback(); return; }
  let idx = currentEntry ? flat.findIndex(e => e.timestamp === currentEntry.timestamp) : -1;
  idx = (idx + 1) % flat.length;
  await selectEntry(flat[idx]);
  if (!playState.playing) return;
  const speedSelect = document.getElementById("play-speed");
  const speed = Number(speedSelect && speedSelect.value) || 800;
  playState.timeoutId = setTimeout(playTick, speed);
}

function startPlayback() {
  playState.playing = true;
  const btn = document.getElementById("play-btn");
  if (btn) { btn.innerHTML = "&#9208; Pause"; btn.classList.add("playing"); }
  playTick();
}

function setupPlayButton() {
  const btn = document.getElementById("play-btn");
  if (!btn) return;
  btn.addEventListener("click", () => {
    if (playState.playing) stopPlayback();
    else startPlayback();
  });
}

async function setupDayTabs() {
  const slider = document.getElementById("day-slider");
  const sliderLabels = document.getElementById("day-slider-labels");
  try {
    timelineIndex = await loadJSON("data/timeline_index.json");
    browserTz = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
    days = buildLocalDayBuckets(timelineIndex, browserTz);

    slider.min = 0;
    slider.max = days.length - 1;
    slider.step = 1;

    sliderLabels.innerHTML = days.map(d =>
      `<span class="${d.forecast ? "forecast" : ""}" data-date="${d.date}">${d.label}</span>`
    ).join("");

    slider.addEventListener("input", () => {
      stopPlayback();
      const day = days[Number(slider.value)];
      if (!day || !day.entries.length) return;
      // preserve the same "slot within the day" across the switch, e.g.
      // staying on the 3rd of ~4 daily entries, clamped if the target
      // day has fewer entries (DST-transition edge case)
      const prevSlot = currentEntry ? (findDayAndSlot(currentEntry) || {}).slotIdx || 0 : 0;
      const slotIdx = Math.min(prevSlot, day.entries.length - 1);
      selectEntry(day.entries[slotIdx]);
    });

    const nowEntry = timelineIndex.find(e => e.is_now);
    const startEntry = nowEntry || (days[3] && days[3].entries[0]) || timelineIndex[0];
    if (startEntry) await selectEntry(startEntry);
  } catch (err) {
    console.error("Could not load timeline index, falling back to today.json", err);
    document.querySelector(".timeline-controls").style.display = "none";
    document.getElementById("hour-tabs").innerHTML = "";
    try {
      const dayData = await loadJSON("data/today.json");
      currentDayData = dayData;
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

function haversineKm(lat1, lon1, lat2, lon2) {
  const R = 6371;
  const toRad = (d) => (d * Math.PI) / 180;
  const dLat = toRad(lat2 - lat1);
  const dLon = toRad(lon2 - lon1);
  const a = Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(a));
}

async function geocodeZip(zip) {
  const res = await fetch(`https://api.zippopotam.us/us/${zip}`);
  if (!res.ok) throw new Error("ZIP code not found");
  const geo = await res.json();
  const place = geo.places && geo.places[0];
  if (!place) throw new Error("ZIP code not found");
  return {
    lat: parseFloat(place.latitude),
    lon: parseFloat(place.longitude),
    placeName: place["place name"],
    stateAbbr: place["state abbreviation"],
  };
}

function nearestCounty(lat, lon, counties) {
  let best = null, bestDist = Infinity;
  for (const info of Object.values(counties)) {
    if (!info.centroid) continue;
    const [clat, clon] = info.centroid;
    const d = haversineKm(lat, lon, clat, clon);
    if (d < bestDist) { bestDist = d; best = info; }
  }
  return best ? { info: best, distKm: bestDist } : null;
}

async function handleZipLookup(zip) {
  const resultEl = document.getElementById("zip-result");
  resultEl.className = "zip-result";

  if (!/^\d{5}$/.test(zip)) {
    resultEl.className = "zip-result error";
    resultEl.textContent = "Enter a valid 5-digit ZIP code.";
    return;
  }
  if (!currentDayData || !currentDayData.counties) {
    resultEl.className = "zip-result error";
    resultEl.textContent = "Data is still loading -- try again in a moment.";
    return;
  }

  resultEl.textContent = `Looking up ${zip}\u2026`;
  try {
    const geo = await geocodeZip(zip);
    const nearest = nearestCounty(geo.lat, geo.lon, currentDayData.counties);
    if (!nearest) throw new Error("No local data available for that area");

    const { info, distKm } = nearest;
    resultEl.className = "zip-result";
    resultEl.innerHTML =
      `<strong>${info.name} County, ${info.state}</strong><br>` +
      `LDI: ${info.ldi} (${info.category})<br>` +
      `Humidity: ${info.humidity_pct}% &middot; Wind: ${info.wind_mph} mph &middot; Elevation: ${info.elevation_m} m` +
      `<span class="zip-result-note">Nearest analyzed county to ${geo.placeName}, ${geo.stateAbbr} ${zip} ` +
      `(~${Math.round(distKm)} km away). Not an exact per-ZIP measurement -- see the disclaimer below.</span>`;
  } catch (err) {
    resultEl.className = "zip-result error";
    resultEl.textContent = "Couldn't look up that ZIP code (" + err.message + ").";
  }
}

function setupZipLookup() {
  const form = document.getElementById("zip-form");
  if (!form) return;
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    stopPlayback();
    const zip = document.getElementById("zip-input").value.trim();
    handleZipLookup(zip);
  });
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
  setupPlayButton();
  setupMonthTabs();
  setupZipLookup();
  setupTzToggle();
}

init();
