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

// Simple equirectangular projection matched to the CONUS bbox used in the
// Python pipeline (grid_utils.CONUS_BBOX), mapped into an 800x500 viewBox.
const BBOX = { lat_min: 24.5, lat_max: 49.5, lon_min: -125.0, lon_max: -66.5 };
const VB = { w: 800, h: 500, pad: 20 };

function project([lon, lat]) {
  const x = VB.pad + ((lon - BBOX.lon_min) / (BBOX.lon_max - BBOX.lon_min)) * (VB.w - 2 * VB.pad);
  const y = VB.pad + (1 - (lat - BBOX.lat_min) / (BBOX.lat_max - BBOX.lat_min)) * (VB.h - 2 * VB.pad);
  return [x, y];
}

function ringToPath(ring) {
  return ring.map((pt, i) => `${i === 0 ? "M" : "L"}${project(pt).join(",")}`).join(" ") + " Z";
}

async function loadJSON(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Failed to load ${url}: ${res.status}`);
  return res.json();
}

function fmtIssued(isoString) {
  if (!isoString) return "--";
  const d = new Date(isoString);
  return d.toUTCString().replace("GMT", "UTC");
}

function buildStateMap(statesGeo, todayData) {
  const svg = document.getElementById("state-svg");
  const tooltip = document.getElementById("tooltip");
  const ns = "http://www.w3.org/2000/svg";
  const EXCLUDE = new Set(["Alaska", "Hawaii", "Puerto Rico"]);

  statesGeo.features.forEach(feature => {
    const name = feature.properties.name;
    if (EXCLUDE.has(name)) return;
    const polys = feature.geometry.type === "MultiPolygon"
      ? feature.geometry.coordinates
      : [feature.geometry.coordinates];
    const info = todayData.states && todayData.states[name];
    const fill = info ? colorFor(info.ldi) : "#cccccc";

    polys.forEach(poly => {
      poly.forEach(ring => {
        const path = document.createElementNS(ns, "path");
        path.setAttribute("d", ringToPath(ring));
        path.setAttribute("fill", fill);
        path.dataset.state = name;
        svg.appendChild(path);

        path.addEventListener("mousemove", (e) => {
          if (!info) return;
          tooltip.classList.remove("hidden");
          tooltip.innerHTML = `<strong>${name}</strong><br>` +
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
    });
  });
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

function buildDiscussion(data, sortedEntries) {
  const dry = sortedEntries.slice(0, 5).map(e => e[0]);
  const moist = sortedEntries.slice(-5).map(e => e[0]).reverse();
  const avg = data.national_average.toFixed(1);
  const issued = fmtIssued(data.issued_utc);

  const text =
`NLS AREA FORECAST DISCUSSION
NATIONAL LOTION SERVICE
${issued}

.SYNOPSIS...
NATIONAL MEAN LOTION DEMAND INDEX HOLDING AT ${avg} (${data.national_category.toUpperCase()})
AS OF THIS ANALYSIS. GRADIENT REMAINS STRONGEST ALONG THE INTERIOR
SOUTHWEST WHERE LOW RELATIVE HUMIDITY AND ELEVATED WIND CONTINUE TO
DRIVE ELEVATED EPIDERMAL MOISTURE LOSS.

.AREAS OF CONCERN...
HIGHEST DEMAND ANALYZED OVER ${dry.join(", ").toUpperCase()}. RESIDENTS
IN THESE AREAS SHOULD ANTICIPATE ELEVATED LOTION DEMAND THROUGH THE
PERIOD AND SHOULD NOT DELAY APPLICATION TO EXPOSED EXTREMITIES,
PARTICULARLY ELBOWS AND KNUCKLES.

.FAVORABLE CONDITIONS...
LOWEST DEMAND ANALYZED OVER ${moist.join(", ").toUpperCase()} WHERE
AMBIENT HUMIDITY REMAINS SUFFICIENT TO SUPPORT NATURAL SKIN BARRIER
FUNCTION WITHOUT SUPPLEMENTAL INTERVENTION.

.OUTLOOK...
NO SIGNIFICANT CHANGE TO THE OVERALL PATTERN IS EXPECTED. THE NEXT
ROUTINE UPDATE WILL BE ISSUED WITHIN 6 HOURS.

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
    advisories.push({
      cls: "warning",
      title: "EXTREME ASHINESS WARNING",
      body: `In effect for ${extreme.map(e => e[0]).join(", ")}. Skin barrier failure imminent without immediate moisturizing intervention.`
    });
  }
  if (cocoa.length) {
    advisories.push({
      cls: "warning",
      title: "COCOA BUTTER ADVISORY",
      body: `In effect for ${cocoa.map(e => e[0]).join(", ")}. Standard lotion may be insufficient; heavier-duty butters recommended.`
    });
  }
  if (risk.length) {
    advisories.push({
      cls: "watch",
      title: "SEVERE ELBOW DRYNESS WATCH",
      body: `Conditions favorable for elbow and knuckle dryness across ${risk.map(e => e[0]).join(", ")}.`
    });
  }
  if (!advisories.length) {
    advisories.push({
      cls: "",
      title: "NO ACTIVE ADVISORIES",
      body: "Conditions nationwide are within normal moisture parameters."
    });
  }

  list.innerHTML = advisories.map(a =>
    `<li class="advisory-item ${a.cls}"><span class="adv-title">${a.title}</span>${a.body}</li>`
  ).join("");
}

function setupMonthTabs() {
  const tabs = document.querySelectorAll(".month-tab");
  const img = document.getElementById("today-map");
  const svg = document.getElementById("state-svg");
  const caption = document.querySelector(".map-caption");

  tabs.forEach(tab => {
    tab.addEventListener("click", () => {
      tabs.forEach(t => t.classList.remove("active"));
      tab.classList.add("active");
      const month = tab.dataset.month;
      if (month === "today") {
        img.src = "assets/maps/today.png";
        svg.style.display = "";
        caption.textContent = "Interactive map below reflects live-loaded state analysis. Hover any state for details.";
      } else {
        img.src = `assets/maps/monthly/${month}.png`;
        svg.style.display = "none";
        caption.textContent = "Monthly normal (1991\u20132020 baseline). Interactive hover available on Current Conditions.";
      }
    });
  });
}

async function init() {
  try {
    const [statesGeo, todayData] = await Promise.all([
      loadJSON("assets/us-states.json"),
      loadJSON("data/today.json"),
    ]);
    const sorted = populateSummary(todayData);
    buildStateMap(statesGeo, todayData);
    buildDiscussion(todayData, sorted);
    buildAdvisories(sorted);
  } catch (err) {
    console.error(err);
    document.getElementById("afd-text").textContent =
      "Discussion unavailable: could not load current data (" + err.message + ").";
  }
  setupMonthTabs();
}

init();
