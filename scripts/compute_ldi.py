"""
compute_ldi.py

Converts raw meteorological grids into the Lotion Demand Index (LDI).
"""

import numpy as np

WEIGHTS = {
    "rh": 0.40,
    "dewpoint": 0.20,
    "wind": 0.15,
    "uv": 0.10,
    "elevation": 0.10,
    "t2m": 0.05,
}

CATEGORIES = [
    (0, 20, "Properly Hydrated"),
    (20, 40, "Mild Moisturizing Recommended"),
    (40, 60, "Lotion Advised"),
    (60, 80, "Elbows at Risk"),
    (80, 90, "Cocoa Butter Recommended"),
    (90, 101, "Extreme Ashiness Warning"),
]


def _normalize(arr: np.ndarray, lo: float, hi: float, invert: bool = False) -> np.ndarray:
    scaled = (arr - lo) / (hi - lo)
    scaled = np.clip(scaled, 0, 1) * 100
    return 100 - scaled if invert else scaled


def compute_ldi(grid: dict) -> dict:
    v = grid["vars"]

    contrib = {
        "rh": _normalize(v["rh"], lo=10, hi=90, invert=True),
        "dewpoint": _normalize(v["dewpoint"], lo=-10, hi=25, invert=True),
        "wind": _normalize(v["wind"], lo=0, hi=15, invert=False),
        "uv": _normalize(v["uv"], lo=0, hi=11, invert=False),
        "elevation": _normalize(v["elevation"], lo=0, hi=3500, invert=False),
        "t2m": _normalize(v["t2m"], lo=10, hi=40, invert=False),
    }

    ldi = np.zeros_like(v["rh"], dtype=float)
    for name, weight in WEIGHTS.items():
        ldi += contrib[name] * weight

    ldi = np.clip(ldi, 0, 100)

    return {
        "lats": grid["lats"],
        "lons": grid["lons"],
        "date": grid["date"],
        "ldi": ldi,
        "contributions": contrib,
    }


def categorize(score: float) -> str:
    for lo, hi, label in CATEGORIES:
        if lo <= score < hi:
            return label
    return CATEGORIES[-1][2]


def national_average(ldi_result: dict) -> float:
    return float(np.nanmean(ldi_result["ldi"]))
