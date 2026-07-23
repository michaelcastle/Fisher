# Project Context

- **Owner:** Michael Castle
- **Project:** Fisher — an interactive GIS web app that generates "bite score" heat maps for tuna and other large pelagic fish off the Sunshine Coast, Brisbane, and Gold Coast, using publicly available oceanographic and bathymetric data.
- **Stack:** Python (`bite_score` package), Flask webapp, Folium for map rendering, rioxarray/xarray for raster processing, Copernicus Marine + NOAA ERDDAP for ocean data, GEBCO + local surveys for bathymetry.
- **Created:** 2026-07-22

## Learnings

<!-- Append new learnings below. Each entry is something lasting about the project. -->

- Team hired 2026-07-22. `webapp.py`'s `/api/static-layer/<key>/*` routes are already generic over the `RASTER_LAYERS` registry in `static_layers.py` — new layers plug in via registry entry, no new route code needed.
- `main.py::run_pipeline()` currently builds composite bathymetry (GEBCO + local surveys merged via `bathymetry_composite.py`) as both the depth-suitability input and the alignment reference grid for all other daily layers. Full pipeline re-run needs live Copernicus/NOAA credentials — not something to assume works without live testing.
