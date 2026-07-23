# Project Context

- **Owner:** Michael Castle
- **Project:** Fisher — an interactive GIS web app that generates "bite score" heat maps for tuna and other large pelagic fish off the Sunshine Coast, Brisbane, and Gold Coast, using publicly available oceanographic and bathymetric data.
- **Stack:** Python (`bite_score` package), Flask webapp, Folium for map rendering, rioxarray/xarray for raster processing, Copernicus Marine + NOAA ERDDAP for ocean data, GEBCO + local surveys for bathymetry.
- **Created:** 2026-07-22

## Learnings

<!-- Append new learnings below. Each entry is something lasting about the project. -->

- Team hired 2026-07-22. Established validation convention on this project: kill stale python/webapp processes and delete cached derived files (e.g., `static_bathymetry.tif`, `depth_suitability.tif`/`.png`/`_meta.json`, `bathymetry_contours.json`, `land_outline.json`) before re-testing pipeline changes, since the pipeline aggressively caches generated rasters.
- Full pipeline (`main.py::run_pipeline()`) requires live Copernicus Marine + NOAA credentials — not runnable in an isolated/offline validation pass. Static-layer endpoints (`/api/static-layer/<key>/*`) can be validated without those credentials.
