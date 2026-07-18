"""
regions.py

NOAA/NWS national maps conventionally show Alaska and Hawaii as inset
boxes (usually bottom-left) rather than at true geographic scale next
to CONUS -- otherwise the Pacific between them dominates the canvas.
We follow that convention here.

Alaska's bbox is cropped to -170..-130 lon, which excludes the far
western Aleutian tail (it crosses the antimeridian, which would
otherwise require special-casing the projection math for a handful of
sparsely-populated islands). Fine for a parody lotion map.
"""

REGIONS = {
    "conus": {
        "bbox": dict(lat_min=24.5, lat_max=49.5, lon_min=-125.0, lon_max=-66.5),
        "spacing": 3.0,
        "exclude_state_names": {"Alaska", "Hawaii", "Puerto Rico"},
    },
    "alaska": {
        "bbox": dict(lat_min=51.0, lat_max=71.5, lon_min=-170.0, lon_max=-130.0),
        "spacing": 4.0,
        "exclude_state_names": set(),
        "only_state_names": {"Alaska"},
        # inset placement as fraction of the figure, matplotlib add_axes coords.
        # Same footprint as Hawaii's box below -- true shape is preserved by
        # computing a real aspect ratio in make_map.py rather than stretching
        # to fill the box, so this is a bounding box, not a target shape.
        "inset_rect": [0.045, 0.13, 0.34, 0.19],
    },
    "hawaii": {
        "bbox": dict(lat_min=18.5, lat_max=22.5, lon_min=-160.5, lon_max=-154.5),
        "spacing": 1.0,
        "exclude_state_names": set(),
        "only_state_names": {"Hawaii"},
        "inset_rect": [0.40, 0.13, 0.34, 0.19],
    },
}
