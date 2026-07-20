"""
run_pipeline.py

    python run_pipeline.py timeline   -> the main product: renders every
                                          synoptic-hour timestamp (00/06/12/18
                                          UTC) from T-3 to T+3 -- 28 steps
                                          total -- for all 3 regions. Writes
                                          site/assets/maps/timeline/<date>_<hh>z.png,
                                          site/data/timeline/<date>_<hh>z.json, and
                                          site/data/timeline_index.json. Also
                                          copies whichever timestamp is
                                          closest to "now" to
                                          site/assets/maps/today.png / site/data/today.json
                                          for backward compatibility. Prunes
                                          any leftover timeline files whose
                                          date/hour falls outside the current
                                          window -- this used to be missing
                                          entirely, which is why old dates and
                                          a legacy bare-date (pre-hourly)
                                          filename format both accumulated
                                          indefinitely in git history.
    python run_pipeline.py monthly    -> the 12 site/assets/maps/monthly/*.png
                                          climate-normal products (unchanged
                                          single-day-per-month demo data).

Live path: fetch_open_meteo.py, tried first for each region -- now hourly,
sampled at the 4 synoptic hours (see that module's docstring for why).
Falls back to demo_data.py (same timestamp-keyed schema, with a diurnal
cycle) if the live fetch fails for any reason.

NOTE: this writes directly into site/, which is the actual GitHub Pages
deployment root -- there is deliberately no separate root-level assets/ or
data/ anymore. Previously the pipeline wrote to root assets/data/ and a
workflow step copied everything into site/, which meant every generated
file was committed twice (see repo cleanup notes in README). Writing
straight into site/ removes that duplication at the source instead of
copying around it.
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

SITE_ROOT = "../site"
STATES_GEOJSON = f"{SITE_ROOT}/assets/us-states.json"
COUNTIES_GEOJSON = f"{SITE_ROOT}/assets/us-counties.json"
TIMELINE_MAPS_DIR = f"{SITE_ROOT}/assets/maps/timeline"
TIMELINE_DATA_DIR = f"{SITE_ROOT}/data/timeline"


def get_region_timeseries(region_key: str) -> dict:
    cfg = REGIONS[region_key]
    try:
        from fetch_open_meteo import fetch_region_timeseries
        ts = fetch_region_timeseries(cfg["bbox"], cfg["spacing"])
        print(f"[{region_key}] Using LIVE Open-Meteo data ({len(ts)} timestamps).")
        return ts
    except Exception as e:
        print(f"[{region_key}] [fallback] Live fetch unavailable ({e}); using synthetic demo data.")
        return make_demo_timeseries(cfg["bbox"], cfg["spacing"])


def _parse_timestamp(ts: str):
    """'2026-07-15T00:00' -> (date_str, hour_int)"""
    date_part, time_part = ts.split("T")
    return date_part, int(time_part[:2])


def _filename_base(date_str: str, hour: int) -> str:
    return f"{date_str}_{hour:02d}z"


def _prune_stale_timeline_files(valid_bases: set):
    """Delete any timeline PNG/JSON whose base name isn't part of the
    current T-3..T+3 window. This also incidentally removes the legacy
    bare-date files (e.g. '2026-07-15.png') left over from before the
    hourly format existed, since their base never matches a current
    '<date>_<hh>z' entry."""
    for directory in (TIMELINE_MAPS_DIR, TIMELINE_DATA_DIR):
        if not os.path.isdir(directory):
            continue
        for fname in os.listdir(directory):
            base = fname.rsplit(".", 1)[0]
            if base not in valid_bases:
                path = os.path.join(directory, fname)
                os.remove(path)
                print(f"  [prune] removed stale {path}")


def run_timeline():
    os.makedirs(TIMELINE_MAPS_DIR, exist_ok=True)
    os.makedirs(TIMELINE_DATA_DIR, exist_ok=True)

    region_series = {key: get_region_timeseries(key) for key in REGIONS}
    all_timestamps = sorted(set().union(*[set(s.keys()) for s in region_series.values()]))
    today_date = dt.date.today()

    index_entries = []
    now_utc = dt.datetime.now(dt.timezone.utc)
    closest_ts, closest_diff, closest_base = None, None, None

    for ts in all_timestamps:
        date_str, hour = _parse_timestamp(ts)
        offset_days = (dt.date.fromisoformat(date_str) - today_date).days

        ldi_results = {}
        for region_key, series in region_series.items():
            grid = series.get(ts)
            if grid is None:
                ldi_results[region_key] = None
                continue
            result = compute_ldi(grid)
            result["raw_vars"] = grid["vars"]
            ldi_results[region_key] = result

        if ldi_results.get("conus") is None:
            print(f"[skip] No CONUS data for {ts}, skipping this timestamp.")
            continue

        period_word = "Forecast" if offset_days > 0 else "Archive" if offset_days < 0 else "Current Conditions"
        label = f"{period_word} — Lotion Demand Index ({date_str} {hour:02d}Z)"
        product_id = f"NLS-LDI-CONUS-{'FCST' if offset_days > 0 else 'ARCH' if offset_days < 0 else 'DAILY'}-{hour:02d}Z"

        base = _filename_base(date_str, hour)
        png_path = f"{TIMELINE_MAPS_DIR}/{base}.png"
        json_path = f"{TIMELINE_DATA_DIR}/{base}.json"
        render_map(ldi_results, STATES_GEOJSON, COUNTIES_GEOJSON, png_path,
                   product_id=product_id, label=label)
        export_json(ldi_results, json_path, states_geojson=STATES_GEOJSON,
                    counties_geojson=COUNTIES_GEOJSON)

        day_label = "TODAY" if offset_days == 0 else f"T{offset_days:+d}"
        entry = {
            "timestamp": ts, "date": date_str, "hour": hour,
            "offset_days": offset_days, "day_label": day_label,
            "hour_label": f"{hour:02d}Z", "file_base": base,
        }
        index_entries.append(entry)
        print(f"  {ts} (offset {offset_days:+d}, {hour:02d}Z) done.")

        ts_dt = dt.datetime.fromisoformat(ts).replace(tzinfo=dt.timezone.utc)
        diff = abs((ts_dt - now_utc).total_seconds())
        if closest_diff is None or diff < closest_diff:
            closest_diff, closest_ts, closest_base = diff, ts, base

    if closest_ts:
        shutil.copy(f"{TIMELINE_MAPS_DIR}/{closest_base}.png", f"{SITE_ROOT}/assets/maps/today.png")
        shutil.copy(f"{TIMELINE_DATA_DIR}/{closest_base}.json", f"{SITE_ROOT}/data/today.json")
        print(f"'today' alias -> {closest_ts} (closest to current time)")
        for e in index_entries:
            e["is_now"] = (e["timestamp"] == closest_ts)

    index_entries.sort(key=lambda e: e["timestamp"])
    with open(f"{SITE_ROOT}/data/timeline_index.json", "w") as f:
        json.dump(index_entries, f)

    valid_bases = {e["file_base"] for e in index_entries}
    _prune_stale_timeline_files(valid_bases)

    print("Timeline complete:", len(index_entries), "timestamps "
          f"({len(index_entries)//4} days x 4 synoptic hours).")


def run_monthly():
    monthly_dir = f"{SITE_ROOT}/assets/maps/monthly"
    os.makedirs(monthly_dir, exist_ok=True)
    for month in range(1, 13):
        seed = month * 17
        rep_date = dt.date(2026, month, 15)
        month_name = calendar.month_abbr[month].lower()

        ldi_results = {}
        for region_key, cfg in REGIONS.items():
            grid = make_demo_grid(cfg["bbox"], cfg["spacing"], day_offset=0, hour_utc=12,
                                   timestamp=f"{rep_date.isoformat()}T12:00", seed=seed)
            result = compute_ldi(grid)
            result["raw_vars"] = grid["vars"]
            ldi_results[region_key] = result

        render_map(ldi_results, STATES_GEOJSON, COUNTIES_GEOJSON,
                   f"{monthly_dir}/{month_name}.png",
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
