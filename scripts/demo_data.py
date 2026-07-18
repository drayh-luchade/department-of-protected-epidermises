"""
demo_data.py

Synthetic fallback generator, matching the schema of
fetch_open_meteo.fetch_region_timeseries(). Used when live fetch fails,
and for local development without hammering Open-Meteo.

Now parameterized by:
  - bbox: so it can generate CONUS, Alaska, or Hawaii (see regions.py)
  - day_offset: so a 7-day run (T-3..T+3) actually shows a smooth drift
    day to day rather than 7 unrelated random maps
"""

import datetime as dt
import numpy as np


def _region_profile(bbox: dict):
    """Rough per-region climate character so Alaska doesn't come out looking
    like Arizona. Returns (base_rh, base_t2m, arid_center_lon, arid_center_lat,
    arid_strength) -- tuned by eye for plausibility, not measurement."""
    lat_mid = (bbox["lat_min"] + bbox["lat_max"]) / 2
    if lat_mid > 50:  # Alaska: cold, generally humid, low UV
        return dict(base_rh=72, base_t2m=2, arid_strength=0.25, uv_scale=0.4)
    if bbox["lon_min"] > -165 and lat_mid < 25:  # Hawaii: tropical, humid, high UV
        return dict(base_rh=68, base_t2m=25, arid_strength=0.15, uv_scale=1.3)
    return dict(base_rh=75, base_t2m=22, arid_strength=1.0, uv_scale=1.0)  # CONUS


def make_demo_grid(bbox: dict, spacing: float, date: dt.date | None = None,
                    seed: int = 0, day_offset: int = 0) -> dict:
    date = date or dt.date.today()
    rng = np.random.default_rng(abs(seed + day_offset * 97) + 1)
    profile = _region_profile(bbox)

    lats = np.arange(bbox["lat_min"], bbox["lat_max"] + 0.01, spacing)
    lons = np.arange(bbox["lon_min"], bbox["lon_max"] + 0.01, spacing)
    LON, LAT = np.meshgrid(lons, lats)

    # Smooth day-to-day drift so the 7-day sequence looks like a moving
    # weather pattern rather than independent noise per day.
    drift = np.sin(day_offset / 2.0) * 8.0

    sw_center_lon = -112.0 + drift
    sw_center_lat = (bbox["lat_min"] + bbox["lat_max"]) / 2 - 5
    dist_sw = np.sqrt((LON - sw_center_lon) ** 2 + (LAT - sw_center_lat) ** 2)
    aridity = np.clip((1.4 - dist_sw / 14.0), 0, 1) * profile["arid_strength"]

    rh = profile["base_rh"] - aridity * 55 + rng.normal(0, 4, LON.shape)
    rh = np.clip(rh, 5, 100)

    t2m = profile["base_t2m"] + (LAT.max() - LAT) * -0.3 + aridity * 6 + rng.normal(0, 1.5, LON.shape)
    dewpoint = t2m - (100 - rh) * 0.4 + rng.normal(0, 1, LON.shape)
    wind = 3 + aridity * 4 + np.abs(LAT - 40) * 0.15 + rng.normal(0, 1, LON.shape)
    wind = np.clip(wind, 0.5, 20)
    uv = np.clip((4 + (LAT.max() - LAT) * 0.25 + aridity * 2) * profile["uv_scale"]
                 + rng.normal(0, 0.5, LON.shape), 0, 12)

    rockies = np.exp(-((LON + 106.5) ** 2) / 8.0) * 2200
    appalachia = np.exp(-((LON + 80) ** 2) / 6.0) * np.clip((LAT - 33) / 10, 0, 1) * 900
    elevation = np.clip(rockies + appalachia + rng.normal(0, 30, LON.shape), 0, None)

    return {
        "lats": lats,
        "lons": lons,
        "date": date.strftime("%Y-%m-%d"),
        "vars": {
            "t2m": t2m, "dewpoint": dewpoint, "rh": rh,
            "wind": wind, "uv": uv, "elevation": elevation,
        },
    }


def make_demo_timeseries(bbox: dict, spacing: float, seed: int = 0) -> dict:
    """Matches fetch_open_meteo.fetch_region_timeseries()'s return shape:
    {date_str: grid_dict} for T-3..T+3."""
    today = dt.date.today()
    out = {}
    for offset in range(-3, 4):
        d = today + dt.timedelta(days=offset)
        out[d.strftime("%Y-%m-%d")] = make_demo_grid(bbox, spacing, date=d, seed=seed, day_offset=offset)
    return out


if __name__ == "__main__":
    from regions import REGIONS
    ts = make_demo_timeseries(**{k: REGIONS["conus"][k] for k in ("bbox", "spacing")})
    for date_str, g in ts.items():
        v = g["vars"]
        print(f"{date_str}  rh_mean={v['rh'].mean():.1f}  t2m_mean={v['t2m'].mean():.1f}")
