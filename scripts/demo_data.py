"""
demo_data.py

Generates a synthetic CONUS grid with the SAME shape/schema as
grid_utils.power_json_to_grid(), so the rest of the pipeline (LDI
computation, map rendering) can be built and tested without live
internet access to NASA POWER.

The synthetic fields are not measurements -- they're smooth functions
tuned to roughly resemble real US climate geography (arid Southwest,
humid Southeast/Pacific Northwest, Rockies elevation) purely so the
demo map looks plausible. Swap fetch_power_data.py in for production.
"""

import datetime as dt
import numpy as np
from grid_utils import CONUS_BBOX


def make_demo_grid(date: dt.date | None = None, seed: int = 0) -> dict:
    date = date or dt.date.today()
    rng = np.random.default_rng(seed)

    lats = np.arange(CONUS_BBOX["lat_min"], CONUS_BBOX["lat_max"] + 0.01, 0.5)
    lons = np.arange(CONUS_BBOX["lon_min"], CONUS_BBOX["lon_max"] + 0.01, 0.5)
    LON, LAT = np.meshgrid(lons, lats)

    # Aridity increases toward the Southwest (low lon distance from -115,
    # low-mid lat), decreases toward Southeast/Pacific NW.
    sw_center_lon, sw_center_lat = -112.0, 35.0
    dist_sw = np.sqrt((LON - sw_center_lon) ** 2 + (LAT - sw_center_lat) ** 2)
    aridity = np.clip(1.4 - dist_sw / 14.0, 0, 1)

    rh = 75 - aridity * 55 + rng.normal(0, 4, LON.shape)
    rh = np.clip(rh, 5, 100)

    t2m = 22 + (LAT.max() - LAT) * -0.3 + aridity * 6 + rng.normal(0, 1.5, LON.shape)
    dewpoint = t2m - (100 - rh) * 0.4 + rng.normal(0, 1, LON.shape)
    wind = 3 + aridity * 4 + np.abs(LAT - 40) * 0.15 + rng.normal(0, 1, LON.shape)
    wind = np.clip(wind, 0.5, 20)
    uv = np.clip(4 + (LAT.max() - LAT) * 0.25 + aridity * 2 + rng.normal(0, 0.5, LON.shape), 0, 12)

    # Rockies ridge running roughly north-south around -108 to -105 lon
    rockies = np.exp(-((LON + 106.5) ** 2) / 8.0) * 2200
    appalachia = np.exp(-((LON + 80) ** 2) / 6.0) * np.clip((LAT - 33) / 10, 0, 1) * 900
    elevation = np.clip(rockies + appalachia + rng.normal(0, 30, LON.shape), 0, None)

    return {
        "lats": lats,
        "lons": lons,
        "date": date.strftime("%Y-%m-%d"),
        "vars": {
            "t2m": t2m,
            "dewpoint": dewpoint,
            "rh": rh,
            "wind": wind,
            "uv": uv,
            "elevation": elevation,
        },
    }


if __name__ == "__main__":
    g = make_demo_grid()
    for name, arr in g["vars"].items():
        print(f"{name:10s} min={arr.min():7.1f} max={arr.max():7.1f} mean={arr.mean():7.1f}")
