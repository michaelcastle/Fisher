# Project Context

- **Owner:** Michael Castle
- **Project:** Fisher — an interactive GIS web app that generates "bite score" heat maps for tuna and other large pelagic fish off the Sunshine Coast, Brisbane, and Gold Coast, using publicly available oceanographic and bathymetric data.
- **Stack:** Python (`bite_score` package), Flask webapp, Folium for map rendering, rioxarray/xarray for raster processing, Copernicus Marine + NOAA ERDDAP for ocean data, GEBCO + local surveys for bathymetry.
- **Created:** 2026-07-22

## Learnings

<!-- Append new learnings below. Each entry is something lasting about the project. -->

- Team hired 2026-07-22. Prior work already merged 3 real high-res bathymetry surveys (moreton_bay_approaches 30m, lidar_sunshine_coast 10m, mudjimba_island 0.5m) onto the GEBCO reference grid (552x360 cells, ~450m/15-arcsec) in `bathymetry_composite.py`, proving a max ~83m depth correction vs raw GEBCO (6862/198720 cells differ >1m).
- Gotcha: `rioxarray.reproject_match()` renames dims to y/x even when input uses lat/lon — must rename back before `assign_coords`, otherwise `CoordinateValidationError`.
- GEBCO_2026 direct download upgrade was investigated and ruled out as not scriptable (WMS is render-only; real downloads need an async "basket" web app or CEDA account) — don't re-attempt without a stated new approach.
