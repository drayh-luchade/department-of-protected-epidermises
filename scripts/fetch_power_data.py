"""
fetch_power_data.py

Pulls a CONUS-wide grid of meteorological variables from NASA POWER's
regional API. NASA POWER is used instead of ERA5/NOAA for the live
pipeline because it requires no API key or registration (ERA5 via
Copernicus CDS needs an account + key, which is fine for a one-time
manual pull but adds friction for a public GitHub Actions workflow).

Docs: https://power.larc.nasa.gov/docs/services/api/temporal/regional/

Variables pulled (POWER parameter codes):
  T2M          - Temperature at 2m (deg C)
  T2MDEW       - Dew point at 2m (deg C)
  RH2M         - Relative humidity at 2m (%)
  WS10M        - Wind speed at 10m (m/s)
  ALLSKY_SFC_UV_INDEX - Surface UV index

NOTE: This script needs outbound internet access to
power.larc.nasa.gov. It will not run inside a sandboxed environment
with a restricted egress allowlist -- run it locally or in the
GitHub Actions workflow (.github/workflows/update.yml), where GitHub's
default runners have unrestricted network access.
"""

import datetime as dt
import time
import requests

POWER_BASE = "https://power.larc.nasa.gov/api/temporal/daily/regional"

# CONUS bounding box, kept coarse (1-degree-ish steps handled server-side
# by the "regional" endpoint, which returns a native ~0.5deg grid).
CONUS_BBOX = dict(lat_min=24.5, lat_max=49.5, lon_min=-125.0, lon_max=-66.5)

PARAMETERS = ["T2M", "T2MDEW", "RH2M", "WS10M", "ALLSKY_SFC_UV_INDEX"]


def latest_available_date(lag_days: int = 3) -> dt.date:
    """POWER's near-real-time data typically lags ~2-3 days behind."""
    return dt.date.today() - dt.timedelta(days=lag_days)


def fetch_conus_grid(date: dt.date | None = None, max_retries: int = 3) -> dict:
    """
    Fetch one day of CONUS-wide gridded data from NASA POWER.

    Returns the raw POWER JSON response, whose `properties.parameter`
    field maps each parameter -> {"lat,lon": {"YYYYMMDD": value}}.
    """
    date = date or latest_available_date()
    date_str = date.strftime("%Y%m%d")

    params = {
        "parameters": ",".join(PARAMETERS),
        "community": "RE",
        "start": date_str,
        "end": date_str,
        "format": "JSON",
        **CONUS_BBOX,
    }

    last_err = None
    for attempt in range(max_retries):
        try:
            resp = requests.get(POWER_BASE, params=params, timeout=120)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            last_err = e
            time.sleep(2 ** attempt)
    raise RuntimeError(f"NASA POWER fetch failed after {max_retries} attempts: {last_err}")


if __name__ == "__main__":
    data = fetch_conus_grid()
    import json
    with open("data/power_raw.json", "w") as f:
        json.dump(data, f)
    print("Saved data/power_raw.json")
