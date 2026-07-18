"""
run_pipeline.py

    python run_pipeline.py timeline   -> the main product: renders T-3..T+3
                                          (7 days) for all 3 regions, writes
                                          assets/maps/timeline/<date>.png,
                                          data/timeline/<date>.json, and
                                          data/timeline_index.json. Also
                                          copies the "today" (offset 0) files
                                          to assets/maps/today.png /
                                          data/today.json for backward
                                          compatibility with the rest of the
                                          site.
    python run_pipeline.py monthly    -> the 12 assets/maps/monthly/*.png
                                          climate-normal products (unchanged
                                          from before; still single-day-per-
                                          month demo data, see README).

Live path: fetch_open_meteo.py, tried first for each region. Falls back
to demo_data.py (with the same 7-day-schema and per-region climate
character) if the live fetch fails for any reason.
"""

import calendar
import json
import os
import sys
import shutil
import datetime as dt

sys.path.insert(0, ".")
from regions import REGIONS
from demo_data import make_demo_grid, make_demo_timeseries
from compute_ldi import compute_ldi
from make_map import render_map, export_json

STATES_GEOJSON = "../assets/us-states.json"
COUNTIES_GEOJSON = "../assets/us-counties.json"


def get_region_timeseries(region_key: str) -> dict:
    cfg = REGIONS[region_key]
    try:
        from fetch_open_meteo import fetch_region_timeseries
        ts = fetch_region_timeseries(cfg["bbox"], cfg["spacing"])
        print(f"[{region_key}] Using LIVE Open-Meteo data ({len(ts)} days).")
        return ts
    except Exception as e:
        print(f"[{region_key}] [fallback] Live fetch unavailable ({e}); using synthetic demo data.")
        return make_demo_timeseries(cfg["bbox"], cfg["spacing"])


def run_timeline():
    os.makedirs("../assets/maps/timeline", exist_ok=True)
    os.makedirs("../data/timeline", exist_ok=True)

    # Fetch (or demo) each region's 7-day series independently
    region_series = {key: get_region_timeseries(key) for key in REGIONS}

    # Union of dates across regions (should match, but be defensive)
    all_dates = sorted(set().union(*[set(s.keys()) for s in region_series.values()]))
    today_str = dt.date.today().strftime("%Y-%m-%d")

    index_entries = []
    for date_str in all_dates:
        offset = (dt.date.fromisoformat(date_str) - dt.date.today()).days
        ldi_results = {}
        for region_key, series in region_series.items():
            grid = series.get(date_str)
            if grid is None:
                ldi_results[region_key] = None
                continue
            result = compute_ldi(grid)
            result["raw_vars"] = grid["vars"]
            ldi_results[region_key] = result

        if ldi_results.get("conus") is None:
            print(f"[skip] No CONUS data for {date_str}, skipping this day.")
            continue

        label = ("Forecast" if offset > 0 else "Archive" if offset < 0 else "Current Conditions") \
            + f" — Lotion Demand Index ({date_str})"
        product_id = f"NLS-LDI-CONUS-{'FCST' if offset > 0 else 'ARCH' if offset < 0 else 'DAILY'}"

        png_path = f"../assets/maps/timeline/{date_str}.png"
        json_path = f"../data/timeline/{date_str}.json"
        render_map(ldi_results, STATES_GEOJSON, COUNTIES_GEOJSON, png_path,
                   product_id=product_id, label=label)
        export_json(ldi_results, json_path, states_geojson=STATES_GEOJSON,
                    counties_geojson=COUNTIES_GEOJSON)

        tab_label = "TODAY" if offset == 0 else (f"T{offset:+d}")
        index_entries.append({"date": date_str, "offset": offset, "label": tab_label})
        print(f"  {date_str} (offset {offset:+d}) done.")

        if date_str == today_str:
            shutil.copy(png_path, "../assets/maps/today.png")
            shutil.copy(json_path, "../data/today.json")

    index_entries.sort(key=lambda e: e["offset"])
    with open("../data/timeline_index.json", "w") as f:
        json.dump(index_entries, f)
    print("Timeline complete:", [e["label"] for e in index_entries])


def run_monthly():
    conus = REGIONS["conus"]
    for month in range(1, 13):
        seed = month * 17
        rep_date = dt.date(2026, month, 15)
        grid = make_demo_grid(conus["bbox"], conus["spacing"], date=rep_date, seed=seed)
        result = compute_ldi(grid)
        result["raw_vars"] = grid["vars"]
        month_name = calendar.month_abbr[month].lower()
        render_map({"conus": result}, STATES_GEOJSON, COUNTIES_GEOJSON,
                   f"../assets/maps/monthly/{month_name}.png",
                   product_id=f"NLS-LDI-CONUS-NORMAL-{calendar.month_abbr[month].upper()}",
                   label=f"{calendar.month_name[month]} Climate Normal (1991-2020) — Lotion Demand Index")
        print(f"  {month_name}.png done.")
    print("Monthly normals set complete.")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "timeline"
    if mode == "timeline":
        run_timeline()
    elif mode == "monthly":
        run_monthly()
    elif mode == "today":  # kept as an alias for backward compatibility
        run_timeline()
    else:
        print(f"Unknown mode: {mode}. Use 'timeline' or 'monthly'.")
        sys.exit(1)
