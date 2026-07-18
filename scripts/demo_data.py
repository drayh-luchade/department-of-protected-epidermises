"""
demo_data.py

Synthetic fallback generator, matching the schema of
fetch_open_meteo.fetch_region_timeseries(): keyed by timestamp string
("YYYY-MM-DDTHH:00", UTC, no offset -- matches Open-Meteo's format
when timezone=UTC is requested), one grid per synoptic hour (00/06/12/18)
across past_days=3..forecast_days=+3.

Parameterized by:
  - bbox: so it can generate CONUS, Alaska, or Hawaii (see regions.py)
  - timestamp: so the diurnal cycle (see below) actually varies within
    a day, not just day to day
"""

import datetime as dt
import numpy as np

SYNOPTIC_HOURS = (0, 6, 12, 18)


def _region_profile(bbox: dict):
    """Rough per-region climate character so Alaska doesn't come out looking
    like Arizona. Returns a dict of tuning knobs -- tuned by eye for
    plausibility, not measurement."""
    lat_mid = (bbox["lat_min"] + bbox["lat_max"]) / 2
    if lat_mid > 50:  # Alaska: cold, generally humid, low UV
        return dict(base_rh=72, base_t2m=2, arid_strength=0.25, uv_scale=0.4)
    if bbox["lon_min"] > -165 and lat_mid < 25:  # Hawaii: tropical, humid, high UV
        return dict(base_rh=68, base_t2m=25, arid_strength=0.15, uv_scale=1.3)
    return dict(base_rh=75, base_t2m=22, arid_strength=1.0, uv_scale=1.0)  # CONUS


def _diurnal_factor(hour_utc: int, lon_mid: float):
    """Very rough day/night cycle. UTC hour doesn't map to local solar time
    uniformly across a bbox, so we approximate local hour using the
    region's mid-longitude (15 degrees longitude ~= 1 hour), then apply a
    sinusoidal cycle peaking at ~2pm local and bottoming at ~2am local.
    This is a lighthearted approximation for a parody map, not a solar
    position calculation -- it's here so "00Z" and "12Z" actually look
    different from each other (matters more now that we show sub-daily
    resolution) rather than for meteorological accuracy."""
    local_hour = (hour_utc + lon_mid / 15.0) % 24
    # peaks at local_hour=14, trough at local_hour=2; range roughly [-1, 1]
    phase = (local_hour - 14) / 24 * 2 * np.pi
    return np.cos(phase)


def make_demo_grid(bbox: dict, spacing: float, timestamp: str | None = None,
                    seed: int = 0, day_offset: int = 0, hour_utc: int = 12) -> dict:
    """timestamp, if given, is a full "YYYY-MM-DDTHH:00" string and takes
    precedence over day_offset/hour_utc for labeling; day_offset/hour_utc
    still drive the actual synthetic pattern (so callers that only have
    offsets, like run_monthly's single-day-per-month demo, keep working)."""
    if timestamp:
        date_part, time_part = timestamp.split("T")
        hour_utc = int(time_part[:2])
    else:
        base_date = dt.date.today() + dt.timedelta(days=day_offset)
        timestamp = f"{base_date.isoformat()}T{hour_utc:02d}:00"

    rng = np.random.default_rng(abs(seed + day_offset * 97 + hour_utc * 7) + 1)
    profile = _region_profile(bbox)

    lats = np.arange(bbox["lat_min"], bbox["lat_max"] + 0.01, spacing)
    lons = np.arange(bbox["lon_min"], bbox["lon_max"] + 0.01, spacing)
    LON, LAT = np.meshgrid(lons, lats)

    lon_mid = (bbox["lon_min"] + bbox["lon_max"]) / 2
    diurnal = _diurnal_factor(hour_utc, lon_mid)  # -1 (night) .. +1 (afternoon)

    # Smooth day-to-day drift so the 7-day sequence looks like a moving
    # weather pattern rather than independent noise per day.
    drift = np.sin(day_offset / 2.0) * 8.0

    sw_center_lon = -112.0 + drift
    sw_center_lat = (bbox["lat_min"] + bbox["lat_max"]) / 2 - 5
    dist_sw = np.sqrt((LON - sw_center_lon) ** 2 + (LAT - sw_center_lat) ** 2)
    aridity = np.clip((1.4 - dist_sw / 14.0), 0, 1) * profile["arid_strength"]

    # Humidity rises at night, falls in the afternoon (inverse of temp/UV)
    rh = profile["base_rh"] - aridity * 55 - diurnal * 10 + rng.normal(0, 4, LON.shape)
    rh = np.clip(rh, 5, 100)

    t2m = (profile["base_t2m"] + (LAT.max() - LAT) * -0.3 + aridity * 6
           + diurnal * 6 + rng.normal(0, 1.5, LON.shape))
    dewpoint = t2m - (100 - rh) * 0.4 + rng.normal(0, 1, LON.shape)

    wind = 3 + aridity * 4 + np.abs(LAT - 40) * 0.15 + rng.normal(0, 1, LON.shape)
    wind = np.clip(wind, 0.5, 20)

    # UV is ~0 at night regardless of season/aridity -- daylight is the
    # dominant factor, so clip the diurnal term hard at the bottom
    uv_daylight = np.clip(diurnal, 0, 1)
    uv = np.clip((4 + (LAT.max() - LAT) * 0.25 + aridity * 2) * profile["uv_scale"] * uv_daylight
                 + rng.normal(0, 0.4, LON.shape), 0, 12)

    rockies = np.exp(-((LON + 106.5) ** 2) / 8.0) * 2200
    appalachia = np.exp(-((LON + 80) ** 2) / 6.0) * np.clip((LAT - 33) / 10, 0, 1) * 900
    elevation = np.clip(rockies + appalachia + rng.normal(0, 30, LON.shape), 0, None)

    return {
        "lats": lats,
        "lons": lons,
        "date": timestamp,
        "vars": {
            "t2m": t2m, "dewpoint": dewpoint, "rh": rh,
            "wind": wind, "uv": uv, "elevation": elevation,
        },
    }


def make_demo_timeseries(bbox: dict, spacing: float, seed: int = 0) -> dict:
    """Matches fetch_open_meteo.fetch_region_timeseries()'s return shape:
    {timestamp_str: grid_dict} for T-3..T+3, at each synoptic hour."""
    today = dt.date.today()
    out = {}
    for offset in range(-3, 4):
        d = today + dt.timedelta(days=offset)
        for hour in SYNOPTIC_HOURS:
            timestamp = f"{d.isoformat()}T{hour:02d}:00"
            out[timestamp] = make_demo_grid(bbox, spacing, timestamp=timestamp,
                                             seed=seed, day_offset=offset, hour_utc=hour)
    return out


if __name__ == "__main__":
    from regions import REGIONS
    ts = make_demo_timeseries(**{k: REGIONS["conus"][k] for k in ("bbox", "spacing")})
    for timestamp, g in sorted(ts.items()):
        v = g["vars"]
        print(f"{timestamp}  rh_mean={v['rh'].mean():.1f}  t2m_mean={v['t2m'].mean():.1f}  uv_mean={v['uv'].mean():.1f}")
