"""
fetch_open_meteo.py

Primary live data source for the full 7-day product (T-3 .. today .. T+3).

Why Open-Meteo instead of stitching NASA POWER + a separate forecast
model: Open-Meteo's /v1/forecast endpoint accepts both `past_days` and
`forecast_days` in the same request and returns one continuous daily
time series spanning both -- so a single HTTP call per grid point gives
us history AND a real model-based forecast together, from one
consistent source. It's free, keyless, and its docs explicitly
document combining past_days + forecast_days for "seamless access to
recent history without switching endpoints":
https://open-meteo.com/en/docs

Bonus: the response includes each point's actual elevation (meters),
so we get real elevation data for free instead of needing a separate
DEM raster -- see the `elevation` field in `_fetch_point()`.

Docs for parameter names used below:
https://open-meteo.com/en/docs#daily=relative_humidity_2m_mean,temperature_2m_max,temperature_2m_min,wind_speed_10m_max,uv_index_max
"""

import datetime as dt
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import requests

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
MAX_WORKERS = 8
PAST_DAYS = 3
FORECAST_DAYS = 4  # today + 3 days ahead

DAILY_PARAMS = [
    "temperature_2m_max",
    "temperature_2m_min",
    "relative_humidity_2m_mean",
    "wind_speed_10m_max",
    "uv_index_max",
]


def _dewpoint_from_t_rh(t_c: np.ndarray, rh_pct: np.ndarray) -> np.ndarray:
    """Magnus-Tetens approximation. Open-Meteo's daily aggregation doesn't
    include a dewpoint mean directly, but it's a standard, well-understood
    derivation from temperature + relative humidity, so computing it here
    is more reliable than trying to average hourly dewpoint ourselves."""
    a, b = 17.62, 243.12
    gamma = (a * t_c) / (b + t_c) + np.log(np.clip(rh_pct, 1, 100) / 100.0)
    return (b * gamma) / (a - gamma)


def _fetch_point(lat: float, lon: float, max_retries: int = 2) -> dict | None:
    params = {
        "latitude": lat,
        "longitude": lon,
        "daily": ",".join(DAILY_PARAMS),
        "past_days": PAST_DAYS,
        "forecast_days": FORECAST_DAYS,
        "timezone": "UTC",
    }
    for attempt in range(max_retries + 1):
        try:
            resp = requests.get(FORECAST_URL, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            daily = data["daily"]
            dates = daily["time"]
            t_mean = (np.array(daily["temperature_2m_max"], dtype=float) +
                      np.array(daily["temperature_2m_min"], dtype=float)) / 2.0
            rh = np.array(daily["relative_humidity_2m_mean"], dtype=float)
            wind_kmh = np.array(daily["wind_speed_10m_max"], dtype=float)
            uv = np.array(daily["uv_index_max"], dtype=float)
            dewpoint = _dewpoint_from_t_rh(t_mean, rh)
            return {
                "dates": dates,
                "elevation": float(data.get("elevation", np.nan)),
                "t2m": t_mean,
                "rh": rh,
                "wind": wind_kmh / 3.6,  # km/h -> m/s, matches compute_ldi's bounds
                "uv": uv,
                "dewpoint": dewpoint,
            }
        except Exception:
            if attempt < max_retries:
                continue
            return None


def fetch_region_timeseries(bbox: dict, spacing: float) -> dict:
    """
    Returns {date_str: {"lats":..., "lons":..., "date":..., "vars": {...}}}
    for each of the 7 days (T-3..T+3), for one region.
    """
    lats = np.arange(bbox["lat_min"], bbox["lat_max"] + 0.01, spacing)
    lons = np.arange(bbox["lon_min"], bbox["lon_max"] + 0.01, spacing)

    point_results = {}  # (i, j) -> fetched dict or None
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

    # Figure out the canonical date list from the first successful point
    sample = next(v for v in point_results.values() if v is not None)
    n_days = len(sample["dates"])

    grids_by_date = {}
    for day_idx in range(n_days):
        date_str = sample["dates"][day_idx]
        vars_ = {v: np.full((len(lats), len(lons)), np.nan) for v in
                 ["t2m", "dewpoint", "rh", "wind", "uv", "elevation"]}
        for (i, j), result in point_results.items():
            if result is None:
                continue
            for varname in ["t2m", "dewpoint", "rh", "wind", "uv"]:
                vars_[varname][i, j] = result[varname][day_idx]
            vars_["elevation"][i, j] = result["elevation"]
        grids_by_date[date_str] = {
            "lats": lats, "lons": lons, "date": date_str, "vars": vars_,
        }

    return grids_by_date


if __name__ == "__main__":
    from regions import REGIONS
    ts = fetch_region_timeseries(**{k: REGIONS["conus"][k] for k in ("bbox", "spacing")})
    for date_str, grid in ts.items():
        t2m = grid["vars"]["t2m"]
        print(f"{date_str}: t2m mean={np.nanmean(t2m):.1f}  "
              f"nan_count={int(np.isnan(t2m).sum())}")
