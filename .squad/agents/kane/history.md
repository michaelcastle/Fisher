# Project Context

- **Owner:** Michael Castle
- **Project:** Fisher — an interactive GIS web app that generates "bite score" heat maps for tuna and other large pelagic fish off the Sunshine Coast, Brisbane, and Gold Coast, using publicly available oceanographic and bathymetric data.
- **Stack:** Python (`bite_score` package), Flask webapp, Folium for map rendering, rioxarray/xarray for raster processing, Copernicus Marine + NOAA ERDDAP for ocean data, GEBCO + local surveys for bathymetry.
- **Created:** 2026-07-22

## Learnings

<!-- Append new learnings below. Each entry is something lasting about the project. -->

- Team hired 2026-07-22 specifically to add fisheries-science grounding: what oceanographic signals actually predict pelagic fish location, and where to source the public data for them (Copernicus Marine, NOAA ERDDAP, IMOS, GEBCO, AusSeabed, BOM).
- Existing pipeline already scores depth suitability from composite bathymetry. Known gap to evaluate: SST fronts/gradients, chlorophyll-a, current shear — not yet confirmed whether these are already implemented in the scoring pipeline; check `bite_score/data_ingestion.py` and scoring modules before assuming.
