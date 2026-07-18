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
        # inset placement as fraction of the figure, matplotlib add_axes coords:
        # [left, bottom, width, height]. This is a bounding box, not a target
        # shape -- true shape is preserved by computing a real aspect ratio
        # in make_map.py rather than stretching to fill the box, so Alaska
        # will letterbox within this box if its shape doesn't match Alaska's
        # true ~0.84 width/height ratio.
        # `render_map` in make_map.py reads this dict directly, so editing
        # these numbers is sufficient to resize/reposition the inset.
        #
        # Symmetric placement: the CONUS map (see main_ax in make_map.py)
        # spans x=0.04..0.82, a width of 0.78. Treating that span as a
        # 0-5 west-to-east scale gives unit = 0.78/5 = 0.156. Alaska is
        # centered at u=1 (x = 0.04 + 1*0.156 = 0.196) and Hawaii at u=3
        # (x = 0.04 + 3*0.156 = 0.508) below. Box width had to shrink from
        # 0.40 -> 0.30 for Alaska's center to land at u=1 without the left
        # edge going negative (off-canvas).
        #
        # Vertical: both boxes share center y=0.205 (bottom + height/2)
        # even though their heights differ, so their midpoints line up.
        # That keeps a ~0.03 gap below main_ax (bottom=0.33) -- the earlier
        # overlap was Alaska's old top (0.10+0.24=0.34) poking 0.01 above
        # main_ax's bottom -- and a ~0.02 gap above the footer text (0.078).
        "inset_rect": [0.046, 0.11, 0.30, 0.19],
    },
    "hawaii": {
        "bbox": dict(lat_min=18.5, lat_max=22.5, lon_min=-160.5, lon_max=-154.5),
        "spacing": 1.0,
        "exclude_state_names": set(),
        "only_state_names": {"Hawaii"},
        # Centered at u=3 (x=0.508); width unchanged from 0.22, so
        # left = 0.508 - 0.11 = 0.398. Height/bottom chosen so this box's
        # center (0.12 + 0.085 = 0.205) matches Alaska's center exactly.
        "inset_rect": [0.398, 0.12, 0.22, 0.17],
    },
}
