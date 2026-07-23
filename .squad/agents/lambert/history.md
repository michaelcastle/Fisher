# Project Context

- **Owner:** Michael Castle
- **Project:** Fisher — an interactive GIS web app that generates "bite score" heat maps for tuna and other large pelagic fish off the Sunshine Coast, Brisbane, and Gold Coast, using publicly available oceanographic and bathymetric data.
- **Stack:** Python (`bite_score` package), Flask webapp, Folium for map rendering, rioxarray/xarray for raster processing, Copernicus Marine + NOAA ERDDAP for ocean data, GEBCO + local surveys for bathymetry.
- **Created:** 2026-07-22

## Learnings

<!-- Append new learnings below. Each entry is something lasting about the project. -->

- Team hired 2026-07-22. `bite_score/visualize.py` already implements the pane + placeholder ImageOverlay + `overlayadd` JS lazy-load pattern for bathymetry, depth-suitability, lidar, Moreton Bay Approaches, Mudjimba Island, and relief-map layers — reuse this pattern for any new layer rather than inventing a new one.
