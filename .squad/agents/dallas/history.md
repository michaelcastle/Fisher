# Project Context

- **Owner:** Michael Castle
- **Project:** Fisher — an interactive GIS web app that generates "bite score" heat maps for tuna and other large pelagic fish off the Sunshine Coast, Brisbane, and Gold Coast, using publicly available oceanographic and bathymetric data.
- **Stack:** Python (`bite_score` package), Flask webapp, Folium for map rendering, rioxarray/xarray for raster processing, Copernicus Marine + NOAA ERDDAP for ocean data, GEBCO + local surveys for bathymetry.
- **Created:** 2026-07-22

## Learnings

<!-- Append new learnings below. Each entry is something lasting about the project. -->

- Team hired 2026-07-22: Dallas (Lead), Lambert (Frontend/Map Dev), Ripley (Backend Dev), Ash (Data/GIS Engineer), Kane (Fishing Specialist), Parker (Tester), plus Scribe/Ralph/Rai.
- Prior work (pre-squad) already built: bathymetry composite merging GEBCO with local high-res surveys, whole-domain relief map layer, shared Folium static-layer registry pattern, depth-suitability scoring.
