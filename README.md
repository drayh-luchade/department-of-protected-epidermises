# National Lotion Service (NLS)

A parody government weather service publishing a scientifically-inspired
**Lotion Demand Index (LDI)** across the United States (CONUS + Alaska +
Hawaii insets), built on real meteorological data and rendered in the
visual language of an official NOAA/NWS product.

Live status: this repo is a **working prototype**. The full pipeline
(fetch &rarr; model &rarr; map &rarr; site &rarr; automation) runs end to end today
using synthetic demo data, because the sandbox this was built in has no
outbound access to Open-Meteo/NASA. It should just work on real data
once it runs somewhere with normal internet access (e.g. GitHub Actions).

## How it works

```
scripts/regions.py             -> defines CONUS + Alaska + Hawaii bboxes and inset placement
scripts/fetch_open_meteo.py    -> PRIMARY live source: past 3 days + today + 3-day forecast,
                                   plus real elevation, all in one call per grid point
scripts/fetch_power_data.py    -> alternate source (NASA POWER), not wired into the pipeline
                                   by default -- see its docstring for why Open-Meteo is primary
scripts/demo_data.py           -> synthetic fallback, same schema, per-region climate character
scripts/compute_ldi.py         -> normalizes variables, applies the weighting model, categorizes
scripts/make_map.py            -> renders the NOAA-style PNG (CONUS + AK/HI insets) + JSON
scripts/run_pipeline.py        -> orchestrator: `timeline` (7-day) or `monthly` (climate normals)
site/                           -> static site (HTML/CSS/JS), day-tabs (T-3..T+3) + month-tabs
.github/workflows/update.yml   -> runs the timeline every 6 hours, deploys to GitHub Pages
```

### The 7-day timeline

`python run_pipeline.py timeline` fetches (or synthesizes) **T-3 through
T+3** for all three regions in one pass, using Open-Meteo's combined
`past_days` + `forecast_days` parameters -- one HTTP call per grid point
covers the whole week from a single, consistent source. Output:

- `assets/maps/timeline/<date>.png` + `data/timeline/<date>.json` for each of the 7 days
- `data/timeline_index.json` -- ordered list of `{date, offset, label}` the site uses to build its day-tabs
- `assets/maps/today.png` / `data/today.json` -- a copy of the offset-0 day, kept for convenience

The site's Area Forecast Discussion and advisories are regenerated
client-side from whichever day's JSON is currently selected, so
switching tabs changes more than just the map image.

### Alaska & Hawaii

Shown as inset boxes on the PNG (the standard NOAA convention), each
with their own bounding box, grid spacing, and state boundaries (see
`regions.py`). They're included in the per-state JSON (`data.states`,
via `compute_states_for_region`) and so show up in the "Highest Demand"
list -- but the *interactive* SVG hover overlay on the site currently
only covers the lower 48 + DC. Extending hover to the insets would mean
projecting each region into its own little coordinate patch in the SVG
viewBox; worth doing if the insets turn out to be a focal point.

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

See `scripts/compute_ldi.py` for the exact normalization bounds.

## Running it locally

```bash
pip install -r requirements.txt
cd scripts
python run_pipeline.py timeline   # writes the 7-day set (see above)
python run_pipeline.py monthly    # writes the 12 ../assets/maps/monthly/*.png products
```

Then serve `site/` locally (it reads `assets/` and `data/` as relative
paths, so copy/symlink them alongside it -- the GH Actions workflow does
this automatically):

```bash
cp -r assets site/assets && cp -r data site/data
cd site && python3 -m http.server 8000
```

## What you'd need to hand me as static files (vs. what's already live)

Short answer: **not much, anymore.** Elevation used to be the one piece
that would've needed a manual DEM download, but Open-Meteo's response
includes each point's real elevation for free, so that's now live data,
not a static file.

The one legitimate case for transferring in static files is:

- **True 30-year climate normals for the monthly product.** Right now
  `monthly` normals are a single representative day per month (see
  `run_monthly()`), not real 1991&ndash;2020 climatology. Getting the real
  thing means PRISM's normals
  (https://prism.oregonstate.edu/normals/) -- PRISM doesn't offer a
  simple keyless bulk API the way Open-Meteo does; their intended
  workflow is downloading BIL/ASC raster files (Prism Climate Group /
  Oregon State) and processing them locally. If you grab the monthly
  normals rasters for the variables in the weighting table, transfer
  them in and I'll wire `run_monthly()` to read real climatology
  instead of the demo generator.

Everything else -- CONUS/Alaska/Hawaii weather (current + history +
forecast), elevation, and state boundaries -- now comes from live,
keyless, free sources (Open-Meteo + the bundled `assets/us-states.json`).

## Extending the DOPE universe

The site's org chart (`#agency` section in `site/index.html`) names
three sibling agencies under the fictional Department of Protected
Epidermises. Each would follow the same pipeline pattern:

- **Bureau of Lip Protection** — National Chapstick Index (likely
  weighted toward wind chill + humidity), Winter Lip Hazard Outlook
- **Office of Cuticle Preparedness** — Weekly Hand Care Bulletin

## Disclaimer

The National Lotion Service is a fictional agency. This index is a
humorous visualization based on real environmental data and is not
intended as medical advice.
