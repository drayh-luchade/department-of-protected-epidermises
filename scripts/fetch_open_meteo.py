"""
fetch_open_meteo.py

True 6-hourly resolution (00/06/12/18 UTC), spanning past_days=3 ..
forecast_days=5 (today + 4 days ahead) -- one day further out than the
site actually displays.

Why the extra day: the site buckets timestamps into each VIEWER's local
calendar day, not UTC's. Because 24 (hours/day) is evenly divisible by
6 (our sampling interval), any 24-hour local-day window always contains
exactly 4 of our synoptic-hour samples, regardless of the viewer's UTC
offset -- so client-side local-day bucketing doesn't need denser data,
just a wider UTC window to always have full coverage. The tightest case
is a viewer far behind UTC (Hawaii, UTC-10): their local "T+3" day can
extend up to 10 hours past UTC's T+3 18Z sample, reaching into what
UTC calls T+4. One extra day of forecast covers that with room to
spare; the archive side needs no equivalent padding (checked against
the same worst-case offset).

Docs: https://open-meteo.com/en/docs
  hourly=temperature_2m,relative_humidity_2m,dew_point_2m,wind_speed_10m,uv_index
"""

import datetime as dt
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import requests

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
MAX_WORKERS = 8
PAST_DAYS = 3
FORECAST_DAYS = 5  # today + 4 days ahead (1 extra day as a local-timezone buffer)
SYNOPTIC_HOURS = (0, 6, 12, 18)  # matches the site's 6-hour cron cadence

HOURLY_PARAMS = [
    "temperature_2m",
    "relative_humidity_2m",
    "dew_point_2m",
    "wind_speed_10m",
    "uv_index",
]


def _fetch_point(lat: float, lon: float, max_retries: int = 2) -> dict | None:
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": ",".join(HOURLY_PARAMS),
        "past_days": PAST_DAYS,
        "forecast_days": FORECAST_DAYS,
        "timezone": "UTC",
    }
    for attempt in range(max_retries + 1):
        try:
            resp = requests.get(FORECAST_URL, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            hourly = data["hourly"]
            times = hourly["time"]  # e.g. "2026-07-15T00:00" (UTC, no offset)

            keep_idx = [i for i, t in enumerate(times) if int(t[11:13]) in SYNOPTIC_HOURS]
            timestamps = [times[i] for i in keep_idx]

            def pick(field):
                arr = np.array(hourly[field], dtype=float)
                return arr[keep_idx]

            return {
                "timestamps": timestamps,
                "elevation": float(data.get("elevation", np.nan)),
                "t2m": pick("temperature_2m"),
                "rh": pick("relative_humidity_2m"),
                "dewpoint": pick("dew_point_2m"),
                "wind": pick("wind_speed_10m") / 3.6,  # km/h -> m/s
                "uv": pick("uv_index"),
            }
        except Exception:
            if attempt < max_retries:
                continue
            return None


def fetch_region_timeseries(bbox: dict, spacing: float) -> dict:
    """
    Returns {timestamp_str: {"lats":..., "lons":..., "date": timestamp_str,
    "vars": {...}}} for each synoptic-hour timestamp across the fetch
    window (7 nominal days + 1 buffer day = 32 timestamps), for one region.
    """
    lats = np.arange(bbox["lat_min"], bbox["lat_max"] + 0.01, spacing)
    lons = np.arange(bbox["lon_min"], bbox["lon_max"] + 0.01, spacing)

    point_results = {}
    tasks = {}
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        for i, lat in enumerate(lats):
            for j, lon in enumerate(lons):
                fut = pool.submit(_fetch_point, float(lat), float(lon))
                tasks[fut] = (i, j)
        n_failed = 0
        for fut in as_completed(tasks):
            i, j = tasks[fut]
            result = fut.result()
            if result is None:
                n_failed += 1
            point_results[(i, j)] = result

    if n_failed > 0.5 * len(tasks):
        raise RuntimeError(
            f"Too many failed points ({n_failed}/{len(tasks)}) -- "
            "treating this region's fetch as failed."
        )

    sample = next(v for v in point_results.values() if v is not None)
    n_steps = len(sample["timestamps"])

    grids_by_timestamp = {}
    for step_idx in range(n_steps):
        timestamp = sample["timestamps"][step_idx]
        vars_ = {v: np.full((len(lats), len(lons)), np.nan) for v in
                 ["t2m", "dewpoint", "rh", "wind", "uv", "elevation"]}
        for (i, j), result in point_results.items():
            if result is None:
                continue
            for varname in ["t2m", "dewpoint", "rh", "wind", "uv"]:
                vars_[varname][i, j] = result[varname][step_idx]
            vars_["elevation"][i, j] = result["elevation"]
        grids_by_timestamp[timestamp] = {
            "lats": lats, "lons": lons, "date": timestamp, "vars": vars_,
        }

    return grids_by_timestamp


if __name__ == "__main__":
    from regions import REGIONS
    ts = fetch_region_timeseries(**{k: REGIONS["conus"][k] for k in ("bbox", "spacing")})
    print(f"{len(ts)} timestamps fetched")
    for timestamp, grid in sorted(ts.items()):
        t2m = grid["vars"]["t2m"]
        print(f"{timestamp}: t2m mean={np.nanmean(t2m):.1f}  "
              f"nan_count={int(np.isnan(t2m).sum())}")
