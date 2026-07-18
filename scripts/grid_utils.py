"""
grid_utils.py

Common grid representation used by every stage of the pipeline, so that
compute_ldi.py and make_map.py don't care whether the values came from
NASA POWER, a synthetic demo generator, or (in the future) ERA5/PRISM.

A "grid" is just a dict:
    {
        "lats": np.ndarray shape (ny,)
        "lons": np.ndarray shape (nx,)
        "date": "YYYY-MM-DD",
        "vars": {
            "t2m":     np.ndarray shape (ny, nx)   # deg C
            "dewpoint":np.ndarray shape (ny, nx)   # deg C
            "rh":      np.ndarray shape (ny, nx)   # %
            "wind":    np.ndarray shape (ny, nx)   # m/s
            "uv":      np.ndarray shape (ny, nx)   # index 0-11ish
            "elevation": np.ndarray shape (ny, nx) # meters
        }
    }
"""

import numpy as np

CONUS_BBOX = dict(lat_min=24.5, lat_max=49.5, lon_min=-125.0, lon_max=-66.5)


def power_json_to_grid(power_json: dict) -> dict:
    """Convert NASA POWER's regional JSON (point dict keyed 'lat,lon') into
    regular numpy grids. POWER returns points on its native ~0.5deg mesh;
    we sort the unique lat/lon values to reconstruct the 2D grid."""
    params = power_json["properties"]["parameter"]
    name_map = {
        "T2M": "t2m",
        "T2MDEW": "dewpoint",
        "RH2M": "rh",
        "WS10M": "wind",
        "ALLSKY_SFC_UV_INDEX": "uv",
    }

    any_param = next(iter(params.values()))
    date_str = next(iter(next(iter(params.values())).values()))  # placeholder, fixed below
    # Points look like "24.5,-125.0" -> {"20240101": value}
    points = list(any_param.keys())
    lats = sorted({float(p.split(",")[0]) for p in points})
    lons = sorted({float(p.split(",")[1]) for p in points})
    lat_idx = {v: i for i, v in enumerate(lats)}
    lon_idx = {v: i for i, v in enumerate(lons)}

    grids = {}
    date_found = None
    for power_name, short_name in name_map.items():
        arr = np.full((len(lats), len(lons)), np.nan)
        for point_key, by_date in params[power_name].items():
            lat, lon = (float(x) for x in point_key.split(","))
            # by_date is {"YYYYMMDD": value}; take the single day we requested
            date_found, val = next(iter(by_date.items()))
            arr[lat_idx[lat], lon_idx[lon]] = val
        grids[short_name] = arr

    return {
        "lats": np.array(lats),
        "lons": np.array(lons),
        "date": f"{date_found[:4]}-{date_found[4:6]}-{date_found[6:]}" if date_found else None,
        "vars": grids,
    }


def attach_elevation(grid: dict, elevation_grid: np.ndarray) -> dict:
    grid["vars"]["elevation"] = elevation_grid
    return grid
