# National Lotion Service (NLS)

A parody government weather service publishing a scientifically-inspired
**Lotion Demand Index (LDI)** across the continental United States, built
on real meteorological data and rendered in the visual language of an
official NOAA/NWS product.

Live status: this repo is a **working prototype**. The full pipeline
(fetch &rarr; model &rarr; map &rarr; site &rarr; automation) runs end to end today
using synthetic demo data, because the environment this was built in
has no outbound access to `power.larc.nasa.gov`. Swap one flag and it
runs on real NASA POWER data — see "Going live" below.

## How it works

```
scripts/fetch_power_data.py   -> pulls a CONUS grid from NASA POWER (free, no API key)
scripts/demo_data.py          -> synthetic fallback with the same schema, for offline dev
scripts/grid_utils.py         -> shared grid representation both sources produce
scripts/compute_ldi.py        -> normalizes variables, applies the weighting model, categorizes
scripts/make_map.py           -> renders the NOAA-style PNG + exports today.json (incl. per-state values)
scripts/run_pipeline.py       -> orchestrator: today's map, or the 12 monthly-normals maps
site/                          -> static site (HTML/CSS/JS), reads assets/maps + data/today.json directly
.github/workflows/update.yml  -> runs the pipeline every 6 hours and deploys to GitHub Pages
```

### The model

Each variable is normalized to a 0&ndash;100 "dryness contribution" against
fixed physical bounds (not the sample min/max, so a 90 means the same
thing in July and January), then combined:

| Variable | Weight | Direction |
|---|---|---|
| Relative Humidity | 40% | lower = drier |
| Dew Point | 20% | lower = drier |
| Wind | 15% | higher = drier |
| UV Index | 10% | higher = drier |
| Elevation | 10% | higher = drier |
| Temperature | 5% | higher = drier |

See `scripts/compute_ldi.py` for the exact normalization bounds — those
are the numbers most worth tuning once you're looking at real data,
since they were picked to be *plausible*, not calibrated against
anything.

## Running it locally

```bash
pip install -r requirements.txt
cd scripts
python run_pipeline.py today      # writes ../assets/maps/today.png + ../data/today.json
python run_pipeline.py monthly    # writes the 12 ../assets/maps/monthly/*.png products
```

Then serve `site/` locally (it reads `assets/` and `data/` as relative
paths, so it needs to be copied/symlinked alongside them — the workflow
does this automatically; see the "Sync generated assets into site/" step):

```bash
cp -r assets site/assets && cp -r data site/data
cd site && python3 -m http.server 8000
```

## Going live (real data instead of demo)

The pipeline already tries the real path first — `run_pipeline.py`
calls `fetch_power_data.py`, and only falls back to `demo_data.py` if
that fails. To go fully live:

1. **Nothing to configure for weather data.** NASA POWER needs no API
   key. It just needs outbound network access, which GitHub Actions
   runners have by default (unlike the sandbox this was built in).
2. **Elevation is still synthetic.** Replace the placeholder Rockies/
   Appalachia approximation in `demo_data.py` with a real DEM: the
   `elevation` PyPI package can pull SRTM tiles, or use NOAA's ETOPO
   global relief model, resampled onto the same lat/lon grid as the
   POWER data (see `attach_elevation()` in `grid_utils.py`).
3. **Monthly normals are currently a single representative day per
   month**, not true 30-year (1991&ndash;2020) climate normals. For the
   real version, pull PRISM or ERA5 monthly-normal products instead of
   a daily snapshot, and swap the source in `run_monthly()`.
4. **Enable GitHub Pages**: repo Settings &rarr; Pages &rarr; Source: GitHub
   Actions. The included workflow builds and deploys `site/` automatically.

## Extending the DOPE universe

The site's org chart (`#agency` section in `site/index.html`) already
names three sibling agencies under the fictional Department of
Protected Epidermises. Each would follow the same pipeline pattern —
a new index computed from a different variable mix, its own product
ID scheme, its own text-product voice:

- **Bureau of Lip Protection** — National Chapstick Index (likely
  weighted toward wind chill + humidity), Winter Lip Hazard Outlook
- **Office of Cuticle Preparedness** — Weekly Hand Care Bulletin
  (probably a slower-cadence, less map-heavy product — more bulletin,
  less analysis)

## Disclaimer

The National Lotion Service is a fictional agency. This index is a
humorous visualization based on real environmental data and is not
intended as medical advice.
