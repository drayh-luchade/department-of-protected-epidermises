"""
counties.py

County-level detail for the LDI map, interpolated from the same
regional-model grid used for the state-level map (see compute_ldi.py) --
not independently fetched per county.
"""

import json
import numpy as np
from scipy.interpolate import griddata

from fips import STATE_FIPS, REGION_FIPS


def load_counties(geojson_path: str):
    with open(geojson_path) as f:
        gj = json.load(f)
    counties = []
    for feat in gj["features"]:
        props = feat["properties"]
        state_fips = props.get("STATE", "")
        if state_fips not in STATE_FIPS:
            continue
        geom = feat["geometry"]
        polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
        biggest_ring = max((ring for poly in polys for ring in poly), key=len)
        pts = np.array(biggest_ring)
        counties.append({
            "fips": props.get("GEO_ID", "")[-5:] or (state_fips + props.get("COUNTY", "")),
            "state_fips": state_fips,
            "state_name": STATE_FIPS[state_fips],
            "name": props.get("NAME", "Unknown"),
            "polys": polys,
            "centroid": (float(pts[:, 1].mean()), float(pts[:, 0].mean())),
        })
    return counties


def counties_for_region(counties: list, region_key: str) -> list:
    fips_set = REGION_FIPS.get(region_key, set())
    return [c for c in counties if c["state_fips"] in fips_set]


def interpolate_field_at_counties(lats, lons, field: np.ndarray, counties: list) -> np.ndarray:
    LON, LAT = np.meshgrid(lons, lats)
    valid = ~np.isnan(field)
    if valid.sum() < 4:
        return np.full(len(counties), np.nan)
    pts = np.array([[c["centroid"][1], c["centroid"][0]] for c in counties])
    values_linear = griddata((LON[valid], LAT[valid]), field[valid], pts, method="linear")
    values_nearest = griddata((LON[valid], LAT[valid]), field[valid], pts, method="nearest")
    return np.where(np.isnan(values_linear), values_nearest, values_linear)


def interpolate_ldi_at_counties(ldi_result: dict, counties: list) -> dict:
    lats, lons, ldi = ldi_result["lats"], ldi_result["lons"], ldi_result["ldi"]
    values = interpolate_field_at_counties(lats, lons, ldi, counties)
    return {c["fips"]: float(v) for c, v in zip(counties, values)}
