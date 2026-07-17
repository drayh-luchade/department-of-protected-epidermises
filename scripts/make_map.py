"""
make_map.py

Renders the LDI grid as a PNG that deliberately apes the look of an
official NWS/NOAA weather product: muted sequential color ramp,
government-style header block with product ID and issue time, technical
legend, and a footer disclaimer.

State boundaries come from assets/us-states.json (plain GeoJSON), drawn
by hand with matplotlib -- no cartopy/geopandas dependency required.
"""

import datetime as dt
import json
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap, BoundaryNorm
from matplotlib.path import Path
from matplotlib.patches import PathPatch
from scipy.interpolate import griddata

from compute_ldi import categorize, national_average

# NWS-style sequential ramp: blue (moist) -> green -> yellow -> orange -> red -> purple (extreme)
LDI_COLORS = [
    "#2b6cb0",  # 0  Properly Hydrated
    "#38a169",  # 20 Mild Moisturizing
    "#d69e2e",  # 40 Lotion Advised
    "#dd6b20",  # 60 Elbows at Risk
    "#c53030",  # 80 Cocoa Butter Recommended
    "#6b46c1",  # 90 Extreme Ashiness Warning
]
LDI_BOUNDS = [0, 20, 40, 60, 80, 90, 100]

EXCLUDE_STATES = {"Alaska", "Hawaii", "Puerto Rico"}


def load_state_paths(geojson_path: str):
    with open(geojson_path) as f:
        gj = json.load(f)
    paths = []
    for feat in gj["features"]:
        name = feat["properties"].get("name", "")
        if name in EXCLUDE_STATES:
            continue
        geom = feat["geometry"]
        polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
        for poly in polys:
            for ring in poly:
                verts = ring
                codes = [Path.MOVETO] + [Path.LINETO] * (len(verts) - 2) + [Path.CLOSEPOLY]
                paths.append(Path(verts, codes))
    return paths


def render_map(ldi_result: dict, states_geojson: str, out_png: str, product_id: str = "NLS-LDI-CONUS"):
    lats, lons, ldi = ldi_result["lats"], ldi_result["lons"], ldi_result["ldi"]
    date_str = ldi_result["date"]

    # Interpolate the coarse model grid onto a finer raster for a smoother look
    fine_lon = np.linspace(lons.min(), lons.max(), 400)
    fine_lat = np.linspace(lats.min(), lats.max(), 250)
    FLON, FLAT = np.meshgrid(fine_lon, fine_lat)
    LON, LAT = np.meshgrid(lons, lats)
    fine_ldi = griddata(
        (LON.ravel(), LAT.ravel()), ldi.ravel(), (FLON, FLAT), method="cubic"
    )

    cmap = LinearSegmentedColormap.from_list("ldi", LDI_COLORS, N=256)
    norm = BoundaryNorm(np.linspace(0, 100, 257), cmap.N)

    fig = plt.figure(figsize=(11, 7.2), facecolor="#f5f6f3")
    ax = fig.add_axes([0.04, 0.10, 0.78, 0.78])

    mesh = ax.pcolormesh(FLON, FLAT, fine_ldi, cmap=cmap, norm=norm, shading="auto")

    state_paths = load_state_paths(states_geojson)
    clip_patch = None
    for path in state_paths:
        patch = PathPatch(path, facecolor="none", edgecolor="#2d2d2d", linewidth=0.6, zorder=5)
        ax.add_patch(patch)

    ax.set_xlim(lons.min() - 1, lons.max() + 1)
    ax.set_ylim(lats.min() - 1, lats.max() + 1)
    ax.set_aspect(1.3)
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)

    # --- Government-style header block ---
    issue_time = dt.datetime.now(dt.timezone.utc).strftime("%H%M UTC %a %b %d %Y")
    fig.text(0.04, 0.955, "NATIONAL LOTION SERVICE", fontsize=17, fontweight="bold",
              family="monospace", color="#1a1a1a")
    fig.text(0.04, 0.925, f"Product: {product_id}   |   Issued: {issue_time}   |   Valid: {date_str}",
              fontsize=9, family="monospace", color="#444")
    fig.text(0.04, 0.90, "Lotion Demand Index — Analysis (0-100 scale)",
              fontsize=10.5, family="monospace", color="#444", style="italic")

    avg = national_average(ldi_result)
    fig.text(0.04, 0.045, f"CONUS Mean LDI: {avg:.1f} ({categorize(avg)})",
              fontsize=9, family="monospace", color="#1a1a1a")
    fig.text(0.04, 0.02,
              "Disclaimer: The National Lotion Service is a fictional agency. This index is a "
              "humorous visualization based on real environmental data and is not intended as "
              "medical advice.", fontsize=6.5, family="monospace", color="#777", wrap=True)

    # --- Legend ---
    legend_ax = fig.add_axes([0.85, 0.15, 0.045, 0.68])
    cbar = fig.colorbar(mesh, cax=legend_ax, boundaries=np.linspace(0, 100, 257),
                         ticks=LDI_BOUNDS)
    cbar.ax.tick_params(labelsize=8)
    cbar.set_ticks(LDI_BOUNDS)
    cbar.set_ticklabels(["0", "20", "40", "60", "80", "90", "100"])
    fig.text(0.895, 0.855, "LDI SCALE", fontsize=8, fontweight="bold", family="monospace", ha="center")

    fig.savefig(out_png, dpi=150, facecolor=fig.get_facecolor())
    plt.close(fig)


def _state_centroids(states_geojson: str):
    """Rough centroid (mean of exterior ring vertices) per state -- good
    enough for sampling a coarse climate grid, not for cartography."""
    with open(states_geojson) as f:
        gj = json.load(f)
    centroids = {}
    for feat in gj["features"]:
        name = feat["properties"].get("name", "")
        if name in EXCLUDE_STATES or not name:
            continue
        geom = feat["geometry"]
        polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
        biggest_ring = max((ring for poly in polys for ring in poly), key=len)
        pts = np.array(biggest_ring)
        centroids[name] = (float(pts[:, 1].mean()), float(pts[:, 0].mean()))  # (lat, lon)
    return centroids


def export_json(ldi_result: dict, out_json: str, states_geojson: str = None, raw_vars: dict = None):
    avg = national_average(ldi_result)
    payload = {
        "product": "NLS-LDI-CONUS",
        "date": ldi_result["date"],
        "issued_utc": dt.datetime.now(dt.timezone.utc).isoformat() + "Z",
        "national_average": round(avg, 1),
        "national_category": categorize(avg),
        "grid": {
            "lats": ldi_result["lats"].tolist(),
            "lons": ldi_result["lons"].tolist(),
            "ldi": np.round(ldi_result["ldi"], 1).tolist(),
        },
    }
    if states_geojson:
        lats, lons, ldi = ldi_result["lats"], ldi_result["lons"], ldi_result["ldi"]
        centroids = _state_centroids(states_geojson)
        states = {}
        for name, (clat, clon) in centroids.items():
            i = int(np.argmin(np.abs(lats - clat)))
            j = int(np.argmin(np.abs(lons - clon)))
            score = float(ldi[i, j])
            entry = {"ldi": round(score, 1), "category": categorize(score)}
            if raw_vars:
                entry["humidity_pct"] = round(float(raw_vars["rh"][i, j]), 0)
                entry["wind_mph"] = round(float(raw_vars["wind"][i, j]) * 2.237, 0)
                entry["elevation_m"] = round(float(raw_vars["elevation"][i, j]), 0)
            states[name] = entry
        payload["states"] = states
    with open(out_json, "w") as f:
        json.dump(payload, f)


if __name__ == "__main__":
    from demo_data import make_demo_grid
    from compute_ldi import compute_ldi

    grid = make_demo_grid()
    result = compute_ldi(grid)
    render_map(result, "../assets/us-states.json", "../assets/maps/today.png")
    export_json(result, "../data/today.json", states_geojson="../assets/us-states.json", raw_vars=grid["vars"])
    print("Wrote ../assets/maps/today.png and ../data/today.json")
