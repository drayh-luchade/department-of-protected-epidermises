"""
fetch_power_data.py

NOT currently used by run_pipeline.py -- kept as a documented, working
alternative data source. fetch_open_meteo.py is the primary source
because it covers history + forecast + elevation in one API; this
module is here in case you want to cross-check Open-Meteo's numbers
against NASA POWER's reanalysis product for a given day, or prefer
POWER's meteorological provenance (MERRA-2 assimilation) for the
"current conditions" product specifically.

Pulls a CONUS grid from NASA POWER using the **Point API**, called once
per grid point -- NOT the Regional API. Two real bugs existed in an
earlier draft of this file, worth noting since they're easy mistakes
to repeat:

  1. NASA's Regional API restricts requests to ONE weather parameter
     per call (documented at
     https://power.larc.nasa.gov/docs/services/api/temporal/daily/,
     under "Limits"). Requesting T2M, T2MDEW, RH2M, WS10M, and
     ALLSKY_SFC_UV_INDEX together in one regional call returns
     422 Unprocessable Entity.
  2. The Regional API's bounding-box parameters are hyphenated
     (`latitude-min`, not `lat_min`); an early draft used underscores
     silently produced a malformed request.

The Point API avoids both problems (up to 20 parameters per call, no
special bbox parameter naming) and is NASA's own documented pattern
for multi-point sampling:
https://power.larc.nasa.gov/docs/tutorials/service-data-request/api/
"""

import datetime as dt
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import requests

POINT_URL = "https://power.larc.nasa.gov/api/temporal/daily/point"
MAX_WORKERS = 8

PARAMETERS = ["T2M", "T2MDEW", "RH2M", "WS10M", "ALLSKY_SFC_UV_INDEX"]
PARAM_TO_VARNAME = {
    "T2M": "t2m", "T2MDEW": "dewpoint", "RH2M": "rh",
    "WS10M": "wind", "ALLSKY_SFC_UV_INDEX": "uv",
}


def latest_available_date(lag_days: int = 3) -> dt.date:
    """POWER's near-real-time data typically lags ~2-3 days behind."""
    return dt.date.today() - dt.timedelta(days=lag_days)


def _fetch_point(lat: float, lon: float, date_str: str, max_retries: int = 2) -> dict | None:
    params = {
        "parameters": ",".join(PARAMETERS), "community": "RE",
        "longitude": lon, "latitude": lat,
        "start": date_str, "end": date_str, "format": "JSON",
    }
    for attempt in range(max_retries + 1):
        try:
            resp = requests.get(POINT_URL, params=params, timeout=30)
            resp.raise_for_status()
            by_param = resp.json()["properties"]["parameter"]
            out = {}
            for power_name, varname in PARAM_TO_VARNAME.items():
                val = next(iter(by_param.get(power_name, {}).values()), np.nan)
                out[varname] = np.nan if val is None or val <= -900 else float(val)
            return out
        except Exception:
            if attempt < max_retries:
                time.sleep(1.5 ** attempt)
            else:
                return None


def fetch_conus_grid(date: dt.date | None = None, spacing: float = 3.0,
                      bbox: dict | None = None) -> dict:
    """Returns {"lats", "lons", "date", "vars": {...}} -- same schema as
    demo_data.make_demo_grid(). No elevation included (see
    fetch_open_meteo.py, which gets it for free from the same response)."""
    from regions import REGIONS
    bbox = bbox or REGIONS["conus"]["bbox"]
    date = date or latest_available_date()
    date_str = date.strftime("%Y%m%d")

    lats = np.arange(bbox["lat_min"], bbox["lat_max"] + 0.01, spacing)
    lons = np.arange(bbox["lon_min"], bbox["lon_max"] + 0.01, spacing)
    vars_ = {v: np.full((len(lats), len(lons)), np.nan) for v in PARAM_TO_VARNAME.values()}

    tasks = {}
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        for i, lat in enumerate(lats):
            for j, lon in enumerate(lons):
                tasks[pool.submit(_fetch_point, float(lat), float(lon), date_str)] = (i, j)
        n_failed = 0
        for fut in as_completed(tasks):
            i, j = tasks[fut]
            result = fut.result()
            if result is None:
                n_failed += 1
                continue
            for varname, val in result.items():
                vars_[varname][i, j] = val

    if n_failed > 0.5 * len(tasks):
        raise RuntimeError(f"Too many missing points ({n_failed}/{len(tasks)}).")

    return {"lats": lats, "lons": lons, "date": date.strftime("%Y-%m-%d"), "vars": vars_}


if __name__ == "__main__":
    grid = fetch_conus_grid()
    for name, arr in grid["vars"].items():
        print(f"{name:10s} min={np.nanmin(arr):7.1f} max={np.nanmax(arr):7.1f} "
              f"nan_count={int(np.isnan(arr).sum())}")
