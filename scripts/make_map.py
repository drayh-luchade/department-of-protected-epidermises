"""
make_map.py

Renders the LDI map as a PNG in NWS/NOAA product style: a county-level
choropleth (see counties.py for why county-level display doesn't imply
county-level weather data) with state outlines on top, CONUS as the
main map, and Alaska + Hawaii as inset boxes placed side by side below
the main map -- NOT overlapping it or the footer text.
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

from compute_ldi import categorize, national_average
from regions import REGIONS
from counties import load_counties, counties_for_region, interpolate_ldi_at_counties, interpolate_field_at_counties

# Blue (hydrated) -> Seafoam -> Light Sage -> Warm Ivory -> Periwinkle ->
# Purple (extreme ashiness warning). Leans into the lotion-report joke:
# reads like a mood-ring / moisturization-intensity scale rather than a
# standard meteorological ramp.
LDI_COLORS = ["#4A6FA5", "#7FC6A4", "#B9C99A", "#E8DCC0", "#8B8FCE", "#6B46C1"]
LDI_BOUNDS = [0, 20, 40, 60, 80, 90, 100]

# Small padding beyond each region's data bbox so state/coast lines don't
# look clipped flush against the plot edge (this was read as "the map
# doesn't reach the highest latitude" -- it did, it just had zero margin).
REGION_PAD_DEG = {"conus": 0.5, "alaska": 0.6, "hawaii": 0.3}


def _polys_to_paths(polys):
    paths = []
    for poly in polys:
        for ring in poly:
            codes = [Path.MOVETO] + [Path.LINETO] * (len(ring) - 2) + [Path.CLOSEPOLY]
            paths.append(Path(ring, codes))
    return paths


def load_state_paths(geojson_path: str, only_names=None, exclude_names=None):
    with open(geojson_path) as f:
        gj = json.load(f)
    exclude_names = exclude_names or set()
    paths = []
    for feat in gj["features"]:
        name = feat["properties"].get("name", "")
        if only_names is not None and name not in only_names:
            continue
        if name in exclude_names:
            continue
        geom = feat["geometry"]
        polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
        paths.extend(_polys_to_paths(polys))
    return paths


def _render_region(ax, ldi_result: dict, states_geojson: str, all_counties: list,
                    region_key: str, cmap, norm):
    bbox = REGIONS[region_key]["bbox"]
    pad = REGION_PAD_DEG.get(region_key, 0.4)

    region_counties = counties_for_region(all_counties, region_key)
    values = interpolate_ldi_at_counties(ldi_result, region_counties)

    for county in region_counties:
        val = values.get(county["fips"])
        color = "#dddddd" if val is None or np.isnan(val) else cmap(norm(val))
        for path in _polys_to_paths(county["polys"]):
            ax.add_patch(PathPatch(path, facecolor=color, edgecolor="#ffffff",
                                    linewidth=0.15, zorder=2))

    only = REGIONS[region_key].get("only_state_names")
    exclude = REGIONS[region_key].get("exclude_state_names", set())
    for path in load_state_paths(states_geojson, only_names=only, exclude_names=exclude):
        ax.add_patch(PathPatch(path, facecolor="none", edgecolor="#2d2d2d",
                                linewidth=0.7, zorder=5))

    ax.set_xlim(bbox["lon_min"] - pad, bbox["lon_max"] + pad)
    ax.set_ylim(bbox["lat_min"] - pad, bbox["lat_max"] + pad)
    # True aspect ratio: at higher latitudes, a degree of longitude covers
    # less physical distance than a degree of latitude (lines of longitude
    # converge toward the poles). aspect=1/cos(mean_lat) compensates for
    # that so shapes aren't stretched -- this is what was missing before
    # (aspect="auto" for insets just force-stretched Alaska to fill
    # whatever box it was given, which is what squashed it).
    mean_lat = (bbox["lat_min"] + bbox["lat_max"]) / 2
    aspect = 1 / np.cos(np.radians(mean_lat))
    ax.set_aspect(aspect, adjustable="box")
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(True)
        spine.set_edgecolor("#999")
        spine.set_linewidth(0.8)


def render_map(ldi_results: dict, states_geojson: str, counties_geojson: str, out_png: str,
                product_id: str = "NLS-LDI-CONUS", label: str = None):
    conus_result = ldi_results["conus"]
    date_str = conus_result["date"]
    all_counties = load_counties(counties_geojson)

    cmap = LinearSegmentedColormap.from_list("ldi", LDI_COLORS, N=256)
    # Colorbar/legend stays a smooth continuous gradient (256 equal bins).
    legend_norm = BoundaryNorm(np.linspace(0, 100, 257), cmap.N)
    # County fill is discretized into LDI_BOUNDS' bands (0/20/40/60/80/90/100)
    # -- a handful of solid colors per region instead of a smooth blend,
    # so the map reads as banded while the legend stays smooth.
    map_norm = BoundaryNorm(LDI_BOUNDS, cmap.N)

    fig = plt.figure(figsize=(11, 8.2), facecolor="#f5f6f3")

    # Main CONUS map takes the upper ~56% of the figure; insets and footer
    # text live in the reserved band below it, side by side, with margin.
    main_ax = fig.add_axes([0.04, 0.33, 0.78, 0.55])
    _render_region(main_ax, conus_result, states_geojson, all_counties, "conus", cmap, map_norm)

    if "alaska" in ldi_results and ldi_results["alaska"] is not None:
        ak_ax = fig.add_axes(REGIONS["alaska"]["inset_rect"])
        _render_region(ak_ax, ldi_results["alaska"], states_geojson, all_counties, "alaska", cmap, map_norm)
        ak_ax.text(0.02, 1.04, "ALASKA", transform=ak_ax.transAxes, fontsize=8,
                   family="monospace", color="#333", fontweight="bold", va="bottom")

    if "hawaii" in ldi_results and ldi_results["hawaii"] is not None:
        hi_ax = fig.add_axes(REGIONS["hawaii"]["inset_rect"])
        _render_region(hi_ax, ldi_results["hawaii"], states_geojson, all_counties, "hawaii", cmap, map_norm)
        hi_ax.text(0.02, 1.04, "HAWAII", transform=hi_ax.transAxes, fontsize=8,
                   family="monospace", color="#333", fontweight="bold", va="bottom")

    issue_time = dt.datetime.now(dt.timezone.utc).strftime("%H%M UTC %a %b %d %Y")
    fig.text(0.04, 0.965, "NATIONAL LOTION SERVICE", fontsize=17, fontweight="bold",
              family="monospace", color="#1a1a1a")
    fig.text(0.04, 0.943, f"Product: {product_id}   |   Issued: {issue_time}   |   Valid: {date_str}",
              fontsize=9, family="monospace", color="#444")
    subtitle = label or "Lotion Demand Index — County-Level Analysis (0-100 scale)"
    fig.text(0.04, 0.923, subtitle, fontsize=10.5, family="monospace", color="#444", style="italic")

    avg = national_average(conus_result)
    fig.text(0.04, 0.078, f"CONUS Mean LDI: {avg:.1f} ({categorize(avg)})",
              fontsize=9, family="monospace", color="#1a1a1a")
    fig.text(0.04, 0.045,
              "Disclaimer: The National Lotion Service is a fictional agency. This index is a "
              "humorous visualization based on real environmental data and is not intended as "
              "medical advice. County-level values are interpolated from a coarser regional "
              "model, not independently measured per county.",
              fontsize=6.3, family="monospace", color="#777", wrap=True)

    legend_ax = fig.add_axes([0.85, 0.35, 0.04, 0.53])
    mesh = plt.cm.ScalarMappable(norm=legend_norm, cmap=cmap)
    cbar = fig.colorbar(mesh, cax=legend_ax, boundaries=np.linspace(0, 100, 257), ticks=LDI_BOUNDS)
    cbar.ax.tick_params(labelsize=8)
    cbar.set_ticks(LDI_BOUNDS)
    fig.text(0.895, 0.895, "LDI SCALE", fontsize=8, fontweight="bold", family="monospace", ha="center")

    fig.savefig(out_png, dpi=150, facecolor=fig.get_facecolor())
    plt.close(fig)


def _state_centroids(states_geojson: str, only_names=None, exclude_names=None):
    with open(states_geojson) as f:
        gj = json.load(f)
    exclude_names = exclude_names or set()
    centroids = {}
    for feat in gj["features"]:
        name = feat["properties"].get("name", "")
        if not name or name in exclude_names:
            continue
        if only_names is not None and name not in only_names:
            continue
        geom = feat["geometry"]
        polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
        biggest_ring = max((ring for poly in polys for ring in poly), key=len)
        pts = np.array(biggest_ring)
        centroids[name] = (float(pts[:, 1].mean()), float(pts[:, 0].mean()))
    return centroids


def compute_states_for_region(ldi_result: dict, states_geojson: str, region_key: str) -> dict:
    lats, lons, ldi = ldi_result["lats"], ldi_result["lons"], ldi_result["ldi"]
    only = REGIONS[region_key].get("only_state_names")
    exclude = REGIONS[region_key].get("exclude_state_names", set())
    centroids = _state_centroids(states_geojson, only_names=only, exclude_names=exclude)
    v = ldi_result.get("raw_vars")
    out = {}
    for name, (clat, clon) in centroids.items():
        i = int(np.argmin(np.abs(lats - clat)))
        j = int(np.argmin(np.abs(lons - clon)))
        score = float(ldi[i, j])
        if np.isnan(score):
            continue
        entry = {"ldi": round(score, 1), "category": categorize(score)}
        if v:
            entry["humidity_pct"] = round(float(v["rh"][i, j]), 0)
            entry["wind_mph"] = round(float(v["wind"][i, j]) * 2.237, 0)
            entry["elevation_m"] = round(float(v["elevation"][i, j]), 0)
        out[name] = entry
    return out


def compute_counties_json(ldi_results: dict, all_counties: list) -> dict:
    out = {}
    for region_key, result in ldi_results.items():
        if result is None:
            continue
        region_counties = counties_for_region(all_counties, region_key)
        values = interpolate_ldi_at_counties(result, region_counties)

        v = result.get("raw_vars")
        extra = {}
        if v:
            lats, lons = result["lats"], result["lons"]
            extra["rh"] = interpolate_field_at_counties(lats, lons, v["rh"], region_counties)
            extra["wind"] = interpolate_field_at_counties(lats, lons, v["wind"], region_counties)
            extra["elevation"] = interpolate_field_at_counties(lats, lons, v["elevation"], region_counties)

        for idx, county in enumerate(region_counties):
            val = values.get(county["fips"])
            if val is None or np.isnan(val):
                continue
            entry = {
                "name": county["name"],
                "state": county["state_name"],
                "ldi": round(float(val), 1),
                "category": categorize(float(val)),
                "centroid": county["centroid"],
            }
            if extra:
                entry["humidity_pct"] = round(float(extra["rh"][idx]), 0)
                entry["wind_mph"] = round(float(extra["wind"][idx]) * 2.237, 0)
                entry["elevation_m"] = round(float(extra["elevation"][idx]), 0)
            out[county["fips"]] = entry
    return out


def export_json(ldi_results: dict, out_json: str, states_geojson: str = None,
                 counties_geojson: str = None):
    conus_result = ldi_results["conus"]
    avg = national_average(conus_result)
    payload = {
        "product": "NLS-LDI-CONUS",
        "date": conus_result["date"],
        "issued_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "national_average": round(avg, 1),
        "national_category": categorize(avg),
        "grid": {
            "lats": conus_result["lats"].tolist(),
            "lons": conus_result["lons"].tolist(),
            "ldi": np.round(np.nan_to_num(conus_result["ldi"], nan=-1), 1).tolist(),
        },
    }
    if states_geojson:
        states = {}
        for region_key, result in ldi_results.items():
            if result is None:
                continue
            states.update(compute_states_for_region(result, states_geojson, region_key))
        payload["states"] = states
    if counties_geojson:
        all_counties = load_counties(counties_geojson)
        payload["counties"] = compute_counties_json(ldi_results, all_counties)
    with open(out_json, "w") as f:
        json.dump(payload, f)


if __name__ == "__main__":
    from demo_data import make_demo_grid
    from compute_ldi import compute_ldi

    results = {}
    for key, cfg in REGIONS.items():
        grid = make_demo_grid(cfg["bbox"], cfg["spacing"])
        result = compute_ldi(grid)
        result["raw_vars"] = grid["vars"]
        results[key] = result

    render_map(results, "../assets/us-states.json", "../assets/us-counties.json", "../assets/maps/today.png")
    export_json(results, "../data/today.json", states_geojson="../assets/us-states.json",
                counties_geojson="../assets/us-counties.json")
    print("Wrote ../assets/maps/today.png and ../data/today.json (county-level, AK+HI side by side)")
