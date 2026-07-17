"""
run_pipeline.py

Entry point for both the manual run and the GitHub Actions cron job.

    python run_pipeline.py today       -> updates assets/maps/today.png + data/today.json
    python run_pipeline.py monthly     -> regenerates all 12 assets/maps/monthly/*.png
                                           (normally run far less often than "today")

Live data path (fetch_power_data.py) requires outbound internet access
to power.larc.nasa.gov, which is blocked in this sandbox -- so this
script automatically falls back to the synthetic demo generator when
the live fetch fails, and logs clearly which path it took. In GitHub
Actions (unrestricted network) the live path will be used.
"""

import calendar
import sys
import datetime as dt

sys.path.insert(0, ".")
from grid_utils import power_json_to_grid, attach_elevation
from demo_data import make_demo_grid
from compute_ldi import compute_ldi
from make_map import render_map, export_json

STATES_GEOJSON = "../assets/us-states.json"
ELEVATION_SOURCE_NOTE = (
    "Elevation in demo mode is a synthetic Rockies/Appalachia approximation. "
    "Production should source real elevation from a USGS DEM raster "
    "(e.g. via the `elevation` PyPI package's SRTM download, or NOAA's ETOPO), "
    "resampled onto the same grid as the meteorological data."
)


def get_today_grid():
    try:
        from fetch_power_data import fetch_conus_grid
        raw = fetch_conus_grid()
        grid = power_json_to_grid(raw)
        # TODO production: attach_elevation(grid, real_elevation_grid)
        print("Using LIVE NASA POWER data.")
        return grid
    except Exception as e:
        print(f"[fallback] Live fetch unavailable ({e}); using synthetic demo data.")
        print(f"[note] {ELEVATION_SOURCE_NOTE}")
        return make_demo_grid()


def run_today():
    grid = get_today_grid()
    result = compute_ldi(grid)
    render_map(result, STATES_GEOJSON, "../assets/maps/today.png",
               product_id="NLS-LDI-CONUS-DAILY")
    export_json(result, "../data/today.json", states_geojson=STATES_GEOJSON, raw_vars=grid["vars"])
    print("today.png / today.json updated.")


def run_monthly():
    """Generates one map per month. In production these should be built
    from 30-year (1991-2020) climate normals rather than a single day;
    here each month is seeded deterministically so the demo is stable
    and reproducible run to run."""
    for month in range(1, 13):
        seed = month * 17
        # Bias the demo seed date to mid-month for a representative day
        rep_date = dt.date(2026, month, 15)
        grid = make_demo_grid(date=rep_date, seed=seed)
        result = compute_ldi(grid)
        month_name = calendar.month_abbr[month].lower()
        render_map(result, STATES_GEOJSON, f"../assets/maps/monthly/{month_name}.png",
                   product_id=f"NLS-LDI-CONUS-NORMAL-{calendar.month_abbr[month].upper()}")
        print(f"  {month_name}.png done.")
    print("Monthly normals set complete.")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "today"
    if mode == "today":
        run_today()
    elif mode == "monthly":
        run_monthly()
    else:
        print(f"Unknown mode: {mode}. Use 'today' or 'monthly'.")
        sys.exit(1)
