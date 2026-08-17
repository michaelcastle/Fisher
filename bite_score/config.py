"""
Configuration for the Yellowfin Tuna Bite Probability Score engine.

All tunable parameters (area of interest, dataset identifiers, WLC weights,
and suitability envelopes) live here so the rest of the pipeline stays
declarative and easy to re-tune without touching processing logic.
"""
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

# Load COPERNICUSMARINE_SERVICE_USERNAME / _PASSWORD / BATHYMETRY_NC_PATH from
# a local .env file (gitignored) if present, so credentials don't need to be
# re-entered interactively on every run. Real environment variables (e.g. set
# in CI) always take precedence over .env values.
load_dotenv()

# --- Area of Interest: Southeast Queensland, Australia -----------------------
# 26.0 S to 28.3 S, 153.0 E to 154.5 E - covers the Sunshine Coast, Moreton Bay,
# Brisbane, and now the Gold Coast shelf out to (and just past) the NSW border.
AOI = {
    "min_lon": 153.0,
    "max_lon": 154.5,
    "min_lat": -28.3,  # southernmost (28.3 S, just south of the Gold Coast/Tweed border)
    "max_lat": -26.0,  # northernmost (26.0 S, Noosa)
}

# --- Target date ---------------------------------------------------------
# Copernicus Marine near-real-time analysis products typically lag by 1-2
# days, so default to 2 days before "today" unless overridden on the CLI.
DEFAULT_TARGET_DATE = (datetime.utcnow() - timedelta(days=2)).strftime("%Y-%m-%d")

# --- Copernicus Marine Service dataset identifiers ------------------------
# NOTE: Dataset IDs occasionally change as Copernicus Marine updates its
# catalogue. Verify current IDs at https://data.marine.copernicus.eu
# before running in production. As of 2026, Copernicus Marine splits the
# Global Ocean Physics Analysis and Forecast product into separate
# single-variable datasets rather than one combined dataset.
COPERNICUS_DATASETS = {
    "sst": {
        # Global Ocean Physics Analysis and Forecast: Sea Surface Temperature.
        "dataset_id": "cmems_mod_glo_phy-thetao_anfc_0.083deg_P1D-m",
        "variables": ["thetao"],
    },
    "currents": {
        # Global Ocean Physics Analysis and Forecast: surface current vectors.
        "dataset_id": "cmems_mod_glo_phy-cur_anfc_0.083deg_P1D-m",
        "variables": ["uo", "vo"],
    },
    "ssha": {
        # Global Ocean Physics Analysis and Forecast: sea surface height.
        "dataset_id": "cmems_mod_glo_phy_anfc_0.083deg_P1D-m",
        "variables": ["zos"],
    },
    "mld": {
        # Global Ocean Physics Analysis and Forecast: mixed layer thickness
        # (mlotst). Recommended by Kane as a quick-win scoring signal (see
        # .squad/decisions.md) -- proxy for vertically-compressed forage
        # layers that concentrate tuna feeding.
        # ASSUMPTION, NOT CONFIRMED LIVE IN THIS ENVIRONMENT: mlotst is
        # assumed to live on the same combined dataset id as zos above
        # (cmems_mod_glo_phy_anfc_0.083deg_P1D-m), since Copernicus's real
        # GLOBAL_ANALYSISFORECAST_PHY_001_024 catalogue groups
        # mlotst/zos/bottomT/siconc/etc. together on that combined
        # "P1D-m" dataset, while thetao/so/uo+vo/wo were split out into
        # their own single/paired-variable datasets (see the sst/currents
        # entries above). Verify against a live `copernicusmarine describe`
        # / the Copernicus Marine Data Store before relying on this in
        # production -- flagged in
        # .squad/decisions/inbox/ash-mld-moonphase.md.
        "dataset_id": "cmems_mod_glo_phy_anfc_0.083deg_P1D-m",
        "variables": ["mlotst"],
    },
    "biogeochemistry": {
        # Global Ocean Biogeochemistry Analysis and Forecast: Chlorophyll-a.
        # Kept as a fallback source for chlorophyll if the higher-resolution
        # NOAA satellite product (see ERDDAP_DATASETS below) is unavailable
        # for the requested date.
        "dataset_id": "cmems_mod_glo_bgc-pft_anfc_0.25deg_P1D-m",
        "variables": ["chl"],
    },
}

# --- NOAA CoastWatch ERDDAP satellite products (higher accuracy) ---------
# Preferred SST/chlorophyll sources: real satellite observations at much
# finer resolution than the Copernicus *model* fields above (MUR SST is
# ~0.01deg/~1km vs Copernicus's ~0.083deg/~9km; VIIRS chlorophyll is
# ~0.0375deg/~4km vs Copernicus's ~0.25deg/~27km), which sharpens the
# thermal/chlorophyll front-detection gradients that drive the Bite Score.
# Currents and SSHA still come from Copernicus (no free satellite current
# product at comparable resolution/latency for this AOI).
ERDDAP_BASE_URL = "https://coastwatch.pfeg.noaa.gov/erddap/griddap"
ERDDAP_DATASETS = {
    "sst": {
        # NASA JPL MUR (Multi-scale Ultra-high Resolution) SST, Global, 0.01deg, daily.
        "dataset_id": "jplMURSST41",
        "variable": "analysed_sst",
        "has_altitude": False,
    },
    "chl": {
        # NOAA S-NPP VIIRS chlorophyll-a, Near Real-Time, Global 4km, Level 3, daily.
        # Rolling NRT window (~14 days). Falls back to chl_sq below for older dates.
        "dataset_id": "nesdisVHNchlaDaily",
        "variable": "chlor_a",
        "has_altitude": True,
    },
    "chl_sq": {
        # NOAA S-NPP VIIRS chlorophyll-a, Science Quality, Global 4km, Level 3, 2012-present.
        # Same sensor/resolution as chl (NRT) above but with full archive back to 2012 and
        # better reprocessing quality. Used as the first fallback when the NRT rolling window
        # has expired for the requested date (e.g. any historical analysis > ~14 days old).
        # Maintains 4km resolution for the entire 2012-present archive, avoiding the
        # resolution cliff-drop to the 27km Copernicus BGC model fallback.
        "dataset_id": "nesdisVHNSQchlaDaily",
        "variable": "chlor_a",
        "has_altitude": True,
    },
    "chl_modis": {
        # NASA MODIS Aqua chlorophyll-a, R2022 Science Quality, Global 4km, 2003-2022.
        # Second fallback for historical dates before the VIIRS SNPP archive (pre-2012).
        # MODIS Aqua was operational 2002-2023; the R2022 reprocessing covers 2003-present
        # (though 2023 onward has no data after Aqua decommissioning).
        # No altitude dimension (unlike VIIRS products above).
        "dataset_id": "erdMH1chla1day_R2022SQ",
        "variable": "chlor_a",
        "has_altitude": False,
    },
    "sla": {
        # NOAA CoastWatch satellite altimetry: Sea Level Anomaly (SLA), 0.25deg daily.
        # Source: RADS multi-satellite merged product (Jason-2/3, Sentinel-3A, CryoSat-2,
        # SARAL/AltiKa). 2017-present. No authentication required.
        # Positive SLA = warm-core eddy (EAC spin-off, fish aggregation zone).
        # Negative SLA = cold-core eddy / upwelling zone.
        # EXPERIMENTAL: ~3-day latency, may have coverage gaps on any given day.
        # Used only as a visual reference layer (not a WLC scoring factor).
        "dataset_id": "nesdisSSH1day",
        "variable": "sla",
        "has_altitude": False,
    },
}

# --- Static bathymetry grid (e.g. GEBCO 2023 or AusSeabed NetCDF) ---------
# Download once from https://www.gebco.net/data_and_products/gridded_bathymetry_data/
# or https://portal.ga.gov.au/persona/marine (AusSeabed) and point this at
# the local file (kept out of source control / not hardcoded credentials).
# `or` (not just os.environ.get's default) is used so an empty-string value
# left in a .env file doesn't shadow the sensible local default path.
BATHYMETRY_NC_PATH = os.environ.get("BATHYMETRY_NC_PATH") or os.path.join(
    os.path.dirname(__file__), "..", "data", "gebco_seq.nc"
)

# --- v2 wider-coverage bathymetry (Queensland Seamount, AOI_V2) -----------
# Live re-fetch of the same GEBCO_2020 NOAA ERDDAP griddap source as
# BATHYMETRY_NC_PATH above, but subset to the wider AOI_V2 bounds (see
# AOI_V2 below) so it genuinely covers 155.0 E / Queensland Seamount.
# Verified live 2026-07-22 (Ash): real lat -28.498 to -25.998, lon 153.002
# to 155.198 -- see .squad/decisions/inbox/ash-seq-v2-structure-layers.md
# for the full verification (incl. a real, non-NaN depth sample at the
# Queensland Seamount coordinate). This is a NEW, SEPARATE file/constant
# -- BATHYMETRY_NC_PATH/v1's AOI above are completely untouched.
# NOTE: no `load_bathymetry_v2()`-style loader exists yet -- `load_bathymetry()`
# below is hardcoded to BATHYMETRY_NC_PATH/AOI (v1). Whoever wires v2
# structure scoring into a real pipeline (Ripley) will need an equivalent
# loader that reads this path and clips to AOI_V2 instead.
BATHYMETRY_V2_NC_PATH = os.environ.get("BATHYMETRY_V2_NC_PATH") or os.path.join(
    os.path.dirname(__file__), "..", "data", "gebco_seq_v2.nc"
)

# --- Working directories --------------------------------------------------
RAW_DATA_DIR = os.environ.get(
    "BITE_SCORE_RAW_DIR", os.path.join(os.path.dirname(__file__), "..", "data", "raw")
)
OUTPUT_DIR = os.environ.get(
    "BITE_SCORE_OUTPUT_DIR", os.path.join(os.path.dirname(__file__), "..", "output")
)
# Per-date archive: each pipeline run's GeoTIFFs are kept under
# output/history/<YYYY-MM-DD>/ so past days can be browsed later instead of
# being overwritten by the next run. A single `bite_score_map.html` template
# (see visualize.py::build_folium_map()) is shared by every date -- it no
# longer needs a per-date copy of its own -- so this directory only holds
# GeoTIFFs plus their lazily-built PNG/JSON chart assets (see date_layers.py).
HISTORY_DIR = os.environ.get(
    "BITE_SCORE_HISTORY_DIR", os.path.join(OUTPUT_DIR, "history")
)
# Records which date the dashboard's "/" root route should show (i.e. the
# most recently completed `run_pipeline()` call) -- written by main.py,
# read by webapp.py's `/api/latest-date` endpoint. Kept as an explicit
# marker file (rather than just picking the chronologically-latest
# directory under HISTORY_DIR) so backfilling an older date via "Update
# Data" still becomes the one shown at "/", matching prior behaviour.
LATEST_DATE_PATH = os.environ.get("BITE_SCORE_LATEST_DATE_PATH") or os.path.join(
    OUTPUT_DIR, "latest_date.txt"
)

# --- Optional supplementary high-resolution local dataset -----------------
# A 2011 airborne LiDAR bathymetry survey for the Sunshine Coast, supplied
# locally under data/raw/DP_LIDAR_SunshineCoast/ (static local data, not
# part of any automated fetch). Only covers a narrow nearshore strip, so
# it's rendered as its own optional map layer rather than blended into the
# Bite Score. Gridded once from the raw XYZ point clouds and cached here
# (see lidar_bathymetry.py::build_lidar_bathymetry_geotiff()).
LIDAR_BATHYMETRY_TIF_PATH = os.environ.get("LIDAR_BATHYMETRY_TIF_PATH") or os.path.join(
    os.path.dirname(__file__), "..", "data", "processed", "lidar_bathymetry_sunshine_coast.tif"
)
# Plain PNG + bounds JSON derived from the GeoTIFF above -- served directly
# by the dashboard server (webapp.py, see static_layers.py) as a standalone
# static asset, fetched by the browser only when this layer is toggled on,
# instead of being embedded into every date's bite_score_map.html.
LIDAR_BATHYMETRY_PNG_PATH = os.environ.get("LIDAR_BATHYMETRY_PNG_PATH") or os.path.join(
    os.path.dirname(__file__), "..", "data", "processed", "lidar_bathymetry_sunshine_coast.png"
)
LIDAR_BATHYMETRY_META_JSON_PATH = os.environ.get("LIDAR_BATHYMETRY_META_JSON_PATH") or os.path.join(
    os.path.dirname(__file__), "..", "data", "processed", "lidar_bathymetry_sunshine_coast_meta.json"
)

# --- Optional supplementary high-resolution bathymetry from AusSeabed -----
# Real multibeam survey grids from Geoscience Australia's AusSeabed open
# data catalogue (public, no-auth, CC BY 4.0), far finer than the ~450m
# GEBCO grid used elsewhere, covering two small areas near the Sunshine
# Coast / Moreton Bay. Downloaded once and cached here (see
# ausseabed_bathymetry.py); only re-downloaded if the cached file is
# missing. Also served as static PNG + bounds JSON assets (see
# static_layers.py), same reasoning as the LiDAR PNG/JSON above.
MORETON_BAY_APPROACHES_TIF_PATH = os.environ.get("MORETON_BAY_APPROACHES_TIF_PATH") or os.path.join(
    os.path.dirname(__file__), "..", "data", "processed", "moreton_bay_approaches_bathymetry.tif"
)
MORETON_BAY_APPROACHES_PNG_PATH = os.environ.get("MORETON_BAY_APPROACHES_PNG_PATH") or os.path.join(
    os.path.dirname(__file__), "..", "data", "processed", "moreton_bay_approaches_bathymetry.png"
)
MORETON_BAY_APPROACHES_META_JSON_PATH = os.environ.get("MORETON_BAY_APPROACHES_META_JSON_PATH") or os.path.join(
    os.path.dirname(__file__), "..", "data", "processed", "moreton_bay_approaches_bathymetry_meta.json"
)
MUDJIMBA_ISLAND_TIF_PATH = os.environ.get("MUDJIMBA_ISLAND_TIF_PATH") or os.path.join(
    os.path.dirname(__file__), "..", "data", "processed", "mudjimba_island_bathymetry.tif"
)
MUDJIMBA_ISLAND_PNG_PATH = os.environ.get("MUDJIMBA_ISLAND_PNG_PATH") or os.path.join(
    os.path.dirname(__file__), "..", "data", "processed", "mudjimba_island_bathymetry.png"
)
MUDJIMBA_ISLAND_META_JSON_PATH = os.environ.get("MUDJIMBA_ISLAND_META_JSON_PATH") or os.path.join(
    os.path.dirname(__file__), "..", "data", "processed", "mudjimba_island_bathymetry_meta.json"
)

# Geoscience Australia's AusBathyTopo (Australia) 2024 250m national-scale
# depth model (public, no-auth, CC BY 4.0) -- compiled specifically for the
# Australian shelf from real multibeam/single-beam/LiDAR/ENC-chart/
# satellite-derived sources, at ~250m, finer and generally more accurate
# than raw GEBCO (~450m, which falls back to generic global satellite-
# altimetry-predicted depth in uncharted areas). The source zip is a
# ~2.6GB whole-of-Australia grid; only a small AOI-sized clip is kept on
# disk long-term (see aus_bathytopo.py::build_aus_bathytopo_geotiff()).
# Merged into build_composite_bathymetry() as the coarsest supplementary
# survey (before the 3 existing finer local patch surveys).
AUS_BATHYTOPO_TIF_PATH = os.environ.get("AUS_BATHYTOPO_TIF_PATH") or os.path.join(
    os.path.dirname(__file__), "..", "data", "processed", "aus_bathytopo_250m_seq.tif"
)

# --- Static bathymetry (GEBCO) + its derived depth-suitability factor -----
# The bathymetry grid loaded by data_ingestion.load_bathymetry() is a
# static local file (data/gebco_seq.nc, see BATHYMETRY_NC_PATH above) --
# identical on every pipeline run, so both it and the depth-suitability
# score derived purely from it (one of the 5 weighted Bite Score factors,
# see overlay.py) are cached here ONCE (see static_layers.py) rather than
# being re-exported/re-embedded into every date's map.
STATIC_BATHYMETRY_TIF_PATH = os.environ.get("STATIC_BATHYMETRY_TIF_PATH") or os.path.join(
    os.path.dirname(__file__), "..", "data", "processed", "static_bathymetry.tif"
)
DEPTH_SUITABILITY_TIF_PATH = os.environ.get("DEPTH_SUITABILITY_TIF_PATH") or os.path.join(
    os.path.dirname(__file__), "..", "data", "processed", "depth_suitability.tif"
)
DEPTH_SUITABILITY_PNG_PATH = os.environ.get("DEPTH_SUITABILITY_PNG_PATH") or os.path.join(
    os.path.dirname(__file__), "..", "data", "processed", "depth_suitability.png"
)
DEPTH_SUITABILITY_META_JSON_PATH = os.environ.get("DEPTH_SUITABILITY_META_JSON_PATH") or os.path.join(
    os.path.dirname(__file__), "..", "data", "processed", "depth_suitability_meta.json"
)
# Whole-domain shaded-relief view -- a literal elevation/depth map (not a
# 0-100 score, unlike depth_suitability), rendered with a graduated
# bathymetric colour scale + hillshade (see
# raster_utils.bathymetry_hillshade_to_rgba). This is now the SINGLE
# unified bathymetry visual layer (previously 4 separate toggles: this
# relief map plus 3 standalone high-res survey patches) -- it merges every
# real source (AusBathyTopo 2024 250m, AusSeabed Moreton Bay Approaches
# 30m, Sunshine Coast LiDAR 10m, Mudjimba Island 0.5m, GEBCO ~450m
# fallback) onto one fine ~30m grid spanning the whole AOI, rather than
# each source only being visible on its own separate small-patch layer.
# See bathymetry_composite.py::build_visual_bathymetry_mosaic().
VISUAL_BATHYMETRY_MOSAIC_TIF_PATH = os.environ.get("VISUAL_BATHYMETRY_MOSAIC_TIF_PATH") or os.path.join(
    os.path.dirname(__file__), "..", "data", "processed", "visual_bathymetry_mosaic.tif"
)
RELIEF_MAP_PNG_PATH = os.environ.get("RELIEF_MAP_PNG_PATH") or os.path.join(
    os.path.dirname(__file__), "..", "data", "processed", "relief_map.png"
)
RELIEF_MAP_META_JSON_PATH = os.environ.get("RELIEF_MAP_META_JSON_PATH") or os.path.join(
    os.path.dirname(__file__), "..", "data", "processed", "relief_map_meta.json"
)
# Depth-contour (isobath) lines + label points traced from the static
# bathymetry grid -- also identical every run, so cached as a single JSON
# asset rather than recomputed/re-embedded per date.
BATHYMETRY_CONTOURS_JSON_PATH = os.environ.get("BATHYMETRY_CONTOURS_JSON_PATH") or os.path.join(
    os.path.dirname(__file__), "..", "data", "processed", "bathymetry_contours.json"
)
# Land/coastline outline traced from the static bathymetry grid's own
# nodata mask -- identical every run (same source grid), so cached the
# same way as the contours above instead of being retraced from that
# date's Bite Score raster and re-embedded into every page.
LAND_OUTLINE_JSON_PATH = os.environ.get("LAND_OUTLINE_JSON_PATH") or os.path.join(
    os.path.dirname(__file__), "..", "data", "processed", "land_outline.json"
)

# --- Windy.com Point Forecast API key ------------------------------------
# Get a free testing key at https://api.windy.com/keys
# Free tier: 500 req/day, returns randomly shuffled data (development only).
# Professional (€990/yr): 10,000 req/day, real forecast data.
# Used by bite_score/windy_api.py and served via /api/windy/forecast.
WINDY_API_KEY = os.environ.get("WINDY_API_KEY", "")

# --- Optional supplementary local data: MBGFC fishing-locations chart -----
# The Moreton Bay Game Fish Club publishes a one-page PDF with a scanned
# nautical chart (printed lat/lon grid, reef/bank names) plus a text table
# of exact FAD/SFAD/wave-buoy coordinates. Supplied locally under
# data/raw/mbgfc/ (static reference data, not part of any automated fetch).
# Georeferenced once and cached here (see mbgfc_chart.py).
MBGFC_PDF_PATH = os.environ.get("MBGFC_PDF_PATH") or os.path.join(
    RAW_DATA_DIR, "mbgfc", "mbgfc_fishing_locations.pdf"
)
MBGFC_CHART_TIF_PATH = os.environ.get("MBGFC_CHART_TIF_PATH") or os.path.join(
    os.path.dirname(__file__), "..", "data", "processed", "mbgfc_chart_georeferenced.tif"
)
MBGFC_LOCATIONS_JSON_PATH = os.environ.get("MBGFC_LOCATIONS_JSON_PATH") or os.path.join(
    os.path.dirname(__file__), "..", "data", "processed", "mbgfc_fishing_locations.json"
)
# Plain PNG + bounds JSON derived from the GeoTIFF above -- served directly
# by the dashboard server (webapp.py) as standalone static assets, so the
# chart layer is fetched by the browser at view time instead of being
# embedded into every generated bite_score_map.html. This means the layer
# is always available/selectable on any date's map without needing that
# date's HTML to be (re)built whenever the chart changes.
MBGFC_CHART_PNG_PATH = os.environ.get("MBGFC_CHART_PNG_PATH") or os.path.join(
    os.path.dirname(__file__), "..", "data", "processed", "mbgfc_chart_georeferenced.png"
)
MBGFC_CHART_META_JSON_PATH = os.environ.get("MBGFC_CHART_META_JSON_PATH") or os.path.join(
    os.path.dirname(__file__), "..", "data", "processed", "mbgfc_chart_meta.json"
)

# --- Weighted Linear Combination (WLC) weights (must sum to 1.0) ---------
# ssha_gradient adds sea-surface-height-anomaly front/eddy-edge detection
# (from the already-fetched "ssha" dataset), which is often a cleaner eddy
# signal than current velocity alone.
#
# mld_gradient (added by Ripley, 2026-07-22 -- see
# .squad/decisions/inbox/ripley-mld-moon-scoring.md): mixed-layer-depth
# (mlotst) gradient/front score, Kane's #1-ranked recommendation (see
# .squad/decisions/inbox/kane-oceanographic-signals.md). Scored as a
# gradient/front-strength factor (same spatial_gradient_magnitude +
# robust_minmax_normalize treatment as sst/chl/ssha above -- see
# normalization.py::normalize_mld_gradient), not an absolute-shallow-MLD
# suitability envelope, since Kane's mechanism explicitly ties MLD to
# concentrating forage where a shoaling front coincides with an *existing*
# thermal/chlorophyll front -- the gradient captures that "edge" directly,
# reusing already-validated code, rather than requiring a newly-invented,
# untuned absolute-depth threshold.
#
# Weight chosen by proportionally shrinking the previous 5 weights,
# preserving their relative balance -- the same technique already used
# below to derive LAYER_WEIGHTS_LEGACY.
#
# DALLAS SIGN-OFF (2026-07-22): Ripley originally proposed 0.12 (shrink
# factor 0.88), derived by proportional shrink alone. Revised DOWN to a
# 0.06 pilot weight (shrink factor 0.94) instead -- MLD is a brand-new,
# not-yet-validated-against-a-real-pipeline-run signal sitting on top of
# an UNVERIFIED Copernicus dataset-id assumption (mlotst's presence on
# the combined zos "P1D-m" dataset was never confirmed via a live
# `copernicusmarine describe` call -- see
# .squad/decisions/inbox/ash-mld-moonphase.md). "Proportionally shrink to
# make room for X%" is a fine way to keep the other weights internally
# consistent, but it says nothing about whether X% is actually
# justified for a signal this unproven -- treating "the math re-balances
# cleanly" as evidence the weight itself is right conflates two separate
# questions. A 6% pilot weight still lets MLD influence the score enough
# to be observable in a real run, without letting an unverified/indirect
# signal outweigh any of the four established fronts (SST/CHL/current/
# SSHA) or fully match bathymetry. Revisit upward once (a) the dataset id
# is confirmed live and (b) the signal has been validated against at
# least one real pipeline run with sane, explainable output.
LAYER_WEIGHTS = {
    "sst_gradient": 0.329,
    "chl_gradient": 0.235,
    "current_velocity": 0.141,
    "ssha_gradient": 0.141,
    "bathymetry": 0.094,
    "mld_gradient": 0.060,
}

# --- Legacy WLC weights (pre-Gold-Coast-upgrade, 4-layer, no SSHA) --------
# Kept so the original (lower-resolution, SST-referenced, nearest-neighbor)
# overlay can still be produced for side-by-side comparison against the
# current higher-accuracy overlay. Derived by proportionally redistributing
# ssha_gradient's 0.15 weight across the other 4 layers, so the relative
# balance between sst/chl/current/bathymetry is unchanged.
LAYER_WEIGHTS_LEGACY = {
    "sst_gradient": 0.4118,
    "chl_gradient": 0.2941,
    "current_velocity": 0.1765,
    "bathymetry": 0.1176,
}

# --- Moon phase final-score multiplier bounds -----------------------------
# Michael Castle (project owner) decided moon phase should be a UNIFORM
# MULTIPLIER on the final computed Bite Score (not a 6th WLC raster
# weight), since illumination fraction is a single day-level scalar with
# no meaningful spatial variation across this AOI (see
# moon_phase.py::moon_illumination_fraction's docstring) -- unlike every
# WLC factor above, which is a genuine per-pixel raster.
#
# Bounds: +-20% (0.8x-1.2x), Ripley's judgment call per Kane's
# fisheries-science framing -- not yet confirmed by Michael/Kane (see
# .squad/decisions/inbox/ripley-mld-moon-scoring.md). Reasoning: the Bite
# Score is already clipped to a fixed 0-100 range (see
# overlay.py::weighted_overlay), so +-20% is large enough to meaningfully
# separate bright-moon vs. dark-moon nights on the final map, without a
# full moon ever being able to crush an otherwise-strong front signal to
# near-zero (0.8x of 100 is still 80) or a new moon inflating a weak
# signal past a believable ceiling (1.2x is re-clipped back to 100 by
# overlay.py::apply_moon_phase_multiplier in any case).
#
# Directionality (see overlay.py::apply_moon_phase_multiplier for the
# full mechanism writeup): brighter moon (illumination_fraction -> 1.0)
# -> LOWER multiplier (MOON_MULTIPLIER_MIN); darker/new moon
# (illumination_fraction -> 0.0) -> HIGHER multiplier
# (MOON_MULTIPLIER_MAX). This is an inverse relationship.
MOON_MULTIPLIER_MIN = 0.8  # full moon / fully illuminated -> dampen the score
MOON_MULTIPLIER_MAX = 1.2  # new moon / dark -> boost the score

# --- Depth suitability envelope (metres, positive = below sea level) -----
DEPTH_IDEAL_MIN = 100.0
DEPTH_IDEAL_MAX = 600.0
DEPTH_RAMP_MIN = 40.0     # below this -> 0 suitability (too shallow / inshore flats)
DEPTH_RAMP_MAX = 1000.0   # above this -> 0 suitability (abyssal, out of foraging range)

# --- Percentile clipping bounds for robust min-max normalization ----------
# Applied to gradient/velocity-edge layers so a handful of extreme outlier
# pixels don't compress the rest of the score distribution towards zero.
NORMALIZATION_LOWER_PERCENTILE = 2
NORMALIZATION_UPPER_PERCENTILE = 98

CRS = "EPSG:4326"

# --- Real-time tidal data feed (Queensland Government DES) ---------------
# Storm-tide telemetry/predictions feed published by the Queensland Dept.
# of Environment, Science and Innovation (DES): a rolling ~7-day window of
# 10-minute-interval tide data (astronomical Prediction, observed Water
# Level, and meteorological Residual) for ~23 monitored QLD sites.
#
# Supersedes the earlier conclusion that tide data is permanently
# unavailable in this pipeline (see
# .squad/decisions/inbox/ripley-moon-tide-data.md, which correctly found
# that astral has zero tidal capability, but hadn't checked for an actual
# tide-gauge data source). See
# .squad/decisions/inbox/ripley-tide-data-ingestion.md for the live-fetch
# verification (2026-07-22) that confirmed this URL, schema, and both
# site codes below actually work.
TIDE_DATA_URL = "https://apps.des.qld.gov.au/data-sets/storm-tides/stdtide-7dayopdata.csv"

# Site code (the feed's lowercase, no-space `Site` values) -> plain-English
# location, per Michael's task:
#   - "tangalooma" IS a real locality, literally on the north-western
#     shore of Moreton Island (Moreton Bay) -- not just "near" it.
#   - "maroochydore" sits immediately adjacent to (effectively the same
#     stretch of coast as) Mooloolaba, the locality more commonly
#     referenced for Sunshine Coast game fishing -- treated as the same
#     tidal regime for this project's purposes.
TIDE_SITES = {
    "tangalooma": "Tangalooma, Moreton Island",
    "maroochydore": "Maroochydore (adjacent to Mooloolaba), Sunshine Coast",
}

# Queensland does not observe daylight saving, so this is a fixed UTC+10
# offset year-round -- no DST-transition ambiguity when localizing the
# feed's naive timestamps (data_ingestion.py::fetch_tide_data()) or a
# caller-supplied naive `at_time`/`from_time` (tide.py).
TIDE_TIMEZONE = ZoneInfo("Australia/Brisbane")

# A tide-state (Flooding/Ebbing) is only classified as "Slack" when within
# this many minutes of a High/Low turning point -- see
# tide.py::classify_tide_state(). 30 minutes is roughly half of one
# 10-minute-sampled turning point's typical near-flat window for this
# semi-diurnal (~2-per-day) tide pattern, without being so wide it eats
# into the genuinely-flooding/ebbing part of the cycle.
TIDE_SLACK_WINDOW_MINUTES = 30

# How long webapp.py's in-memory tide-data cache (see
# webapp.py::_get_tide_dataframe(), backing GET /api/tide-state/<date>) is
# reused before re-fetching the live QLD DES feed. The feed is a 7-day
# rolling window sampled every 10 minutes, so re-downloading it on every
# single page view would needlessly hammer the external DES server for no
# new information -- 15 minutes keeps the page responsive while still
# refreshing well within one 10-minute sample tick's usefulness window.
TIDE_CACHE_TTL_MINUTES = 15

# --- v2 bite-score model: expanded AOI + structure-scoring parameters ----
# Michael approved building a fully SEPARATE "v2" scoring model (structure/
# shelf-break scoring, named canyon/seamount proximity, bell-curve SST,
# optimal-band chlorophyll, real clockwise-eddy detection via vorticity)
# for side-by-side comparison against v1 -- see
# .squad/decisions/inbox/ash-seq-v2-feasibility.md,
# .squad/decisions/inbox/kane-seq-v2-validation.md,
# .squad/decisions/inbox/ash-seq-v2-structure-layers.md.
#
# CRITICAL: v1's `AOI` above (and everything derived from it -- v1's
# bathymetry grid, v1 outputs) must NOT change, so this is a NEW,
# ADDITIONAL constant, not a mutation of `AOI`. Only v2 code should ever
# read `AOI_V2`.
#
# Bounds: same west/north edges as v1 (153.0 E / 26.0 S -- Tweed Canyon and
# Noosa Canyon are already comfortably inside those). Extended east to
# 155.2 E (past Queensland Seamount at 155.00 E, which sits ~50km outside
# v1's max_lon=154.5, leaving a ~22km buffer past the seamount itself for
# the Gaussian proximity falloff/shelf-break zone to render without an
# edge-clip artifact) and extended south to -28.5 (past v1's -28.3, so
# Tweed Canyon's full 20km-outside shelf-break proximity zone doesn't get
# clipped at the AOI edge).
AOI_V2 = {
    "min_lon": 153.0,
    "max_lon": 155.2,
    "min_lat": -28.5,
    "max_lat": -26.0,
}

# --- v2 bathymetry coverage caveat -----------------------------------------
# UPDATE (2026-07-22, Ash): the wider file now EXISTS -- see
# BATHYMETRY_V2_NC_PATH above. It was live-fetched from the same NOAA
# ERDDAP GEBCO_2020 griddap endpoint below, verified to genuinely cover
# lon 153.002-155.198 E / lat -28.498 to -25.998 S (includes 155.0 E,
# Queensland Seamount's own coordinate), and confirmed to have a real,
# non-NaN/non-land depth sample there (~4770m). See
# .squad/decisions/inbox/ash-seq-v2-structure-layers.md for full details.
# The original `data/gebco_seq.nc` (BATHYMETRY_NC_PATH, v1) is untouched.
#
# The paragraph below is kept for historical context (it was true when
# written) but is now superseded by the above -- `load_bathymetry()`
# still only reads BATHYMETRY_NC_PATH/AOI (v1); no v2-aware loader exists
# yet, so Ripley (or whoever wires v2 into a real pipeline) still needs
# to write one pointing at BATHYMETRY_V2_NC_PATH/AOI_V2.
#
# The existing `data/gebco_seq.nc` (see BATHYMETRY_NC_PATH above) was a
# ONE-OFF, manually-fetched GEBCO_2020 NOAA ERDDAP griddap subset (see
# /memories/repo/fisher-bite-score.md and the URL pattern documented
# there) -- there is NO scriptable re-download function anywhere in this
# codebase (confirmed: no `fetch_bathymetry`/`download_gebco`-style
# function exists in data_ingestion.py; `load_bathymetry()` only ever
# reads the already-local file). Directly verified its real coverage
# (2026-07-22): longitude 153.0020833 to 154.5020833 E, latitude
# -28.297916 to -26.0 S -- i.e. it does NOT reach 155.2 E (or even
# 155.0 E, Queensland Seamount's own coordinate). Queensland Seamount
# proximity scoring will therefore see NaN/no-data for its own location
# and everywhere east of ~154.5 E until Michael re-fetches a wider file.
#
# To get real GEBCO coverage for the full AOI_V2 extent, Michael would
# need to re-run the same manual NOAA ERDDAP griddap request with the
# new bounds, e.g.:
#   https://coastwatch.pfeg.noaa.gov/erddap/griddap/GEBCO_2020.nc?elevation[(-28.5):(-26.0)][(153.0):(155.2)]
# and save the result over (or alongside) data/gebco_seq.nc /
# BATHYMETRY_NC_PATH. This is NOT done automatically by any code in this
# task -- the shelf-break/structure-scoring functions below are written
# to work correctly on whatever depth grid they're given (they do not
# hardcode AOI_V2's bounds), but will only produce meaningful (non-NaN)
# scores near Queensland Seamount once a wider bathymetry file actually
# exists on disk.

# Named point features for v2 structure scoring (canyon/seamount proximity
# via Gaussian distance-decay). Coordinates as supplied by Michael --
# Kane's scientific review (kane-seq-v2-validation.md) flagged these as
# geographically plausible but NOT independently verifiable against a
# real named-feature chart; treat as approximate anchors, not surveyed
# feature centroids.
#
# FINAL DECISION (Michael, v2 scoring model task): Queensland Seamount is
# DROPPED entirely, not just given a wider bathymetry file to render
# against -- the real GEBCO_2020 depth sample at its coordinate (155.00 E,
# 27.20 S) is ~4770m, a flat abyssal plain with no seamount-like relief
# whatsoever (see BATHYMETRY_V2_NC_PATH's coverage verification above).
# Only Tweed Canyon and Noosa Canyon ("Jim's Mountain") remain real,
# bathymetrically-plausible structure features for v2.
STRUCTURE_FEATURES_V2 = {
    "tweed_canyon": {"lat": -28.17, "lon": 154.00},
    "noosa_canyon": {"lat": -26.38, "lon": 153.80},
}

# Gaussian proximity-decay "halo" radius (kilometres) for the named-point
# feature scoring above (score = exp(-distance_km**2 / (2*sigma_km**2))).
# TUNABLE, NOT SCIENTIFICALLY VALIDATED: chosen as a middle-of-the-road
# estimate of a typical canyon/seamount current-acceleration/upwelling
# influence radius (~10-20km is a common order-of-magnitude range cited
# for shelf-break canyon aggregation effects), not derived from any
# dataset specific to these 3 features. Revisit once real catch data or
# a survey-confirmed feature extent is available.
STRUCTURE_POINT_SIGMA_KM = 15.0

# Shelf-break (100-200m contour) proximity zone, per Michael's spec: high
# score from 5km inside (shallower than the band) to 20km outside (deeper
# than the band) the contour band itself.
SHELF_BREAK_MIN_DEPTH_M = 100.0
SHELF_BREAK_MAX_DEPTH_M = 200.0
SHELF_BREAK_INSIDE_KM = 5.0
SHELF_BREAK_OUTSIDE_KM = 20.0

# --- v2 SST bell-curve suitability (normalization_v2.py) ------------------
# Michael's spec: a bell curve peaking at 22C, with a 20-24C "optimal
# window". Implemented as a Gaussian, exp(-(sst-peak)**2 / (2*sigma**2)),
# rather than a flat trapezoidal plateau (unlike the chlorophyll band
# below) since Michael explicitly called this a "bell curve", i.e. a
# smooth single peak rather than a flat-topped optimal range.
#
# SST_BELL_SIGMA_C is chosen so the 20-24C window brackets the curve's
# half-maximum (FWHM) width around the 22C peak: FWHM = 2*sqrt(2*ln(2))*sigma
# ~= 2.3548*sigma, so sigma = 4.0 / 2.3548 ~= 1.7. At exactly 20C or 24C
# (peak +-2C) the score is ~0.50 -- i.e. "the optimal window" is read as
# "still at least half-maximum suitability", not "score == 1.0 across the
# whole window" (that would make it a trapezoid, not a bell curve).
SST_BELL_PEAK_C = 22.0
SST_BELL_SIGMA_C = 1.7

# Kane's explicit correction (kane-seq-v2-validation.md 1c): combine the
# bell-curve absolute-temperature suitability with the existing gradient/
# front-strength score (normalization.py::normalize_sst_gradient, reused
# unmodified) as a WEIGHTED AVERAGE, not a product -- multiplying two
# independent [0,1] fractional terms would crush the combined score
# toward zero everywhere except where both happen to be simultaneously
# near-maximal, which is not what "SST suitability" should mean (a
# textbook-optimal 22C reading with a merely-average gradient should still
# score reasonably well, not get zeroed out by the multiplication).
# 50/50 is a neutral starting split (neither component assumed more
# informative than the other) pending real-pipeline validation.
SST_BELL_COMPONENT_WEIGHT = 0.5
SST_GRADIENT_COMPONENT_WEIGHT = 0.5

# --- v2 chlorophyll optimal-band suitability (normalization_v2.py) -------
# Michael's spec: 0.1-0.3 mg/m3 ideal, <0.1 "barren" (too little forage
# base), >0.5 "murky" (excessive turbidity/algal bloom, hurts sight-feeding
# predators like Yellowfin Tuna). Reuses the existing
# normalization.py::_trapezoidal_membership() helper (Kane's explicit
# recommendation) rather than inventing a new fuzzy-membership function --
# same shape as normalize_depth's envelope, just re-parameterized for
# chlorophyll concentration instead of metres of depth.
#
# Ramp bounds (0.05 / 0.5) are Kane's suggested "sensible ramp bounds" from
# kane-seq-v2-validation.md, not independently re-derived here: a hard
# cliff straight from 1.0 to 0.0 exactly at the ideal_min/ideal_max
# boundaries would be an unrealistically sharp fuzzy-membership edge, so
# CHL_BAND_RAMP_MIN gives a short linear ramp-up from "barren" and
# CHL_BAND_RAMP_MAX extends the ramp-down out to a still-fairly-turbid
# 0.5 mg/m3 before hitting 0.
CHL_BAND_RAMP_MIN = 0.05
CHL_BAND_IDEAL_MIN = 0.1
CHL_BAND_IDEAL_MAX = 0.3
CHL_BAND_RAMP_MAX = 0.5

# --- v2 Weighted Linear Combination (WLC) weights (must sum to 1.0) ------
# Reuses current_velocity/bathymetry/mld_gradient at v1's exact weights
# (same signals, same validation status -- no reason to re-litigate them
# for v2), and keeps sst_bell/chl_band at essentially v1's sst_gradient/
# chl_gradient weight (0.330 vs 0.329, 0.235 vs 0.235) since they remain
# the two "headline" front/suitability signals. The budget for that comes
# from DROPPING ssha_gradient as its own WLC term (0.141) -- v2 folds SSHA
# into eddy_score instead (structure_layers.py::compute_eddy_score, which
# already requires a co-located positive SSHA bump alongside anticyclonic
# vorticity) rather than double-counting SSHA as both a standalone
# gradient front AND part of the eddy signature.
#
# structure_score (0.08) and eddy_score (0.06) are NEW, deliberately
# CONSERVATIVE pilot weights -- the same reasoning Dallas applied to
# mld_gradient's 0.06 pilot weight (see LAYER_WEIGHTS above): both are
# unvalidated against a real pipeline run. structure_score gets a
# marginally higher weight than eddy_score since Kane's review rated the
# shelf-break/canyon-aggregation mechanism as well-established fisheries
# science (even though these specific coordinates are unverified),
# whereas eddy_score depends on a more involved, freshly-derived vorticity
# sign convention and Kane flagged real-eddy detection as more of a
# phase-2/stretch signal. Revisit both upward once validated against at
# least one real pipeline run with sane, explainable output (same bar set
# for mld_gradient above).
LAYER_WEIGHTS_V2 = {
    "sst_bell": 0.330,
    "chl_band": 0.235,
    "current_velocity": 0.141,
    "bathymetry": 0.094,
    "mld_gradient": 0.060,
    "structure_score": 0.080,
    "eddy_score": 0.060,
}

# --- v2 seasonal final-score multiplier (mirrors MOON_MULTIPLIER_MIN/MAX) -
# Michael's spec for the SEQ/Gold Coast Yellowfin Tuna season: applied as a
# FINAL SCALAR MULTIPLIER on the already-computed 0-100 v2 Bite Score
# (see overlay_v2.py::apply_seasonal_multiplier), mirroring
# overlay.py::apply_moon_phase_multiplier's mechanism -- NOT chained in
# multiplicatively as another WLC raster weight, since a month is a single
# day-level scalar with no per-pixel spatial variation, exactly like moon
# illumination fraction above.
#   - Sep-Nov (9-11): 1.0x, peak season.
#   - Dec-Jan (12, 1): 0.8x.
#   - Feb-Apr (2-4): 0.3x, the seasonal low.
#   - May-Aug (5-8): 0.8x, the winter "barrel run".
# Keyed by calendar month number (1-12) for simple, precise month-boundary
# lookup (e.g. Aug 31 -> 0.8, Sep 1 -> 1.0) via `datetime.month`.
SEASONAL_MULTIPLIER_V2 = {
    1: 0.8,   # January (part of Dec-Jan)
    2: 0.3,   # February (Feb-Apr low)
    3: 0.3,   # March
    4: 0.3,   # April
    5: 0.8,   # May (winter barrel run)
    6: 0.8,   # June
    7: 0.8,   # July
    8: 0.8,   # August
    9: 1.0,   # September (peak season)
    10: 1.0,  # October
    11: 1.0,  # November
    12: 0.8,  # December (part of Dec-Jan)
}

# --- Lenigas wind data source (NOAA CoastWatch ERDDAP, Metop-C ASCAT) -----
# NEW for the "Lenigas" scoring model -- no wind data source existed
# anywhere in this pipeline before this (confirmed via a full-codebase
# search). See .squad/decisions/inbox/ash-lenigas-implementation.md for
# the full live-verification writeup.
#
# Live-tested (Ash, 2026-07-23) two sibling NOAA CoastWatch ERDDAP
# datasets (same public, no-auth server already used for MUR SST /
# VIIRS chlorophyll -- see ERDDAP_BASE_URL/ERDDAP_DATASETS above), both
# real Metop-C ASCAT scatterometer wind products:
#   - erdQCwindproducts1day (daily composite): on the one date tested,
#     the ENTIRE AOI_V2 region came back 100% NaN -- near-coast ASCAT
#     quality-control land-contamination masking evidently covered the
#     whole strip that day. A wider offshore test (lon 150-158 E, same
#     latitudes) confirmed the dataset itself has real, physically sane
#     data (wind speed 1.5-7.79 m/s) -- just not within AOI_V2 that day.
#   - erdQCwindproducts7day (7-day rolling composite, chosen instead):
#     real, usable coverage inside the EXACT AOI_V2 bounds, confirmed
#     across 3 independently-tested dates (2023-10-10, 2026-05-01,
#     "latest") -- consistently ~75-80% finite cells, with sane wind
#     speeds (5.2-11.9 m/s) and directions (0-360 deg) each time. The
#     ~20-25% NaN fraction is the same near-coast QC masking, just
#     narrow enough (thanks to the 7-day averaging pulling in more
#     swaths) to leave most of AOI_V2 with real data.
# Real coverage: 2021-08-31-present, daily-stepped (P1D resolution)
# rolling 7-day (P7D duration) composite, ~5-6 week production lag on
# "latest" (observed: requesting "(last)" on 2026-07-23 returned
# 2026-06-14). 0.333deg (~35km) resolution, 10m height.
LENIGAS_WIND_ERDDAP_DATASET_ID = "erdQCwindproducts7day"
LENIGAS_WIND_ERDDAP_VARIABLES = ("wind_speed", "wind_direction", "wind_u", "wind_v")
LENIGAS_WIND_ALTITUDE_M = 10.0

# Same historical-mislabeling safeguard as
# data_ingestion.py::_MAX_LATEST_FALLBACK_AGE_DAYS, applied to this feed's
# own (much longer, ~5-6 week) normal production lag: beyond this many
# days from the requested date, refuse the "(last)" fallback and raise
# instead, rather than silently substituting a far-off granule for a
# genuine multi-month archive gap.
LENIGAS_WIND_MAX_LATEST_FALLBACK_AGE_DAYS = 45

# --- "Lenigas" scoring model: AOI + scoring parameters --------------------
# A fully SEPARATE bite-score model based on a fisherman's (Lenigas's,
# via a podcast transcript) raw notes -- see
# .squad/decisions/inbox/coordinator-lenigas-directive.md,
# .squad/decisions/inbox/coordinator-lenigas-decisions.md (Michael's 8
# design decisions), .squad/decisions/inbox/kane-lenigas-scoring-spec.md
# (the exact numeric spec these constants implement), and
# .squad/decisions/inbox/ash-lenigas-implementation.md (wind/EAC-axis/
# vorticity-sign modules this model consumes). NEVER "v3" anywhere -- this
# is its own named model, same separation pattern as v1/v2: own config
# section (this one), own normalization/overlay/pipeline modules, own
# output/history/<date>/lenigas/ subfolder. Does not read or modify any
# v1 (AOI/LAYER_WEIGHTS/...) or v2 (AOI_V2/LAYER_WEIGHTS_V2/...) constant
# above.
#
# AOI: real-data-VERIFIED (not assumed) to already be covered by AOI_V2 --
# directly computed a real distance-from-coast raster from the live
# AOI_V2 bathymetry grid (BATHYMETRY_V2_NC_PATH) and confirmed 61,883 real
# sea cells fall within the 60-100km offshore band (real depths there
# range 66-4794m, comfortably spanning the 500-3000m Lenigas depth band
# too), with the grid's own maximum distance-from-coast (~202km) well
# past the 100km band edge -- i.e. the band is NOT clipped at AOI_V2's
# boundary. So AOI_LENIGAS deliberately ALIASES AOI_V2 rather than
# duplicating its values (avoids the two silently drifting out of sync)
# -- no widening was needed, contrary to what the task briefing assumed
# might be necessary.
AOI_LENIGAS = AOI_V2

# Seasonal multiplier (Kane's spec, item 1) -- built from the Lenigas
# transcript's OWN migration story (spawning run arrives Sep-Nov as the
# EAC's warm-water incursion begins; fish are off Fraser Island, north of
# this AOI, Jun-Aug), NOT a copy of SEASONAL_MULTIPLIER_V2's separate
# "winter barrel run" hypothesis (which Lenigas's own account does not
# corroborate for this AOI). Dec/Jan are a judgment-call taper bridging
# the Sep-Nov peak down to the flat Feb-Aug off-season floor, rather than
# a single hard cliff -- see kane-lenigas-scoring-spec.md item 1 for the
# full month-by-month rationale.
SEASONAL_MULTIPLIER_LENIGAS = {
    1: 0.4, 2: 0.3, 3: 0.3, 4: 0.3, 5: 0.3, 6: 0.3,
    7: 0.3, 8: 0.3, 9: 1.0, 10: 1.0, 11: 1.0, 12: 0.6,
}

# SST bell curve (Kane's spec, item 2): peak = 24.5C, the exact midpoint
# of the notes' stated 23-26C band; sigma derived the same way v2's
# SST_BELL_SIGMA_C was (treating the stated band as the curve's FWHM
# around the peak): FWHM = 26-23 = 3.0C, sigma = 3.0 / (2*sqrt(2*ln(2)))
# ~= 1.27C, rounded to 1.3 (same precision convention as v2's 1.7).
SST_BELL_PEAK_C_LENIGAS = 24.5
SST_BELL_SIGMA_C_LENIGAS = 1.3

# Depth suitability (Kane's spec, item 3; Michael's decision #3): ramp up
# 500m->1000m, plateau 1000-1500m, then DECLINE linearly to 0 by 3000m
# (not an indefinite plateau like v1/v2's depth envelopes) -- reuses
# normalization.py::_trapezoidal_membership()'s existing 4-point shape,
# no new membership function needed. The 3000m ramp-max is an explicit
# judgment call (the notes give no "how far past 1500m" figure) -- see
# kane-lenigas-scoring-spec.md item 3 for the full reasoning (this AOI's
# real bathymetry runs to ~4800-4900m abyssal depths, so a gradual,
# 1500m-wide decline span reflects "too deep" as a soft disqualifier, not
# a hard cliff).
DEPTH_LENIGAS_RAMP_MIN_M = 500.0
DEPTH_LENIGAS_IDEAL_MIN_M = 1000.0
DEPTH_LENIGAS_IDEAL_MAX_M = 1500.0
DEPTH_LENIGAS_RAMP_MAX_M = 3000.0

# Distance-offshore-from-coast (Kane's spec, item 4; Michael's decision
# #4: "60-80km" interpreted as distance offshore from the coast): same
# 4-point trapezoidal shape, ramp margins (+-20km either side of the
# 60-80km ideal band) are an explicit judgment call (the notes say
# "usually", signalling a soft preference) -- not derived from any stated
# number. Computed against a real per-pixel distance-from-coast raster
# (scipy.ndimage.distance_transform_edt on the AOI_LENIGAS bathymetry's
# land/sea mask, see pipeline_lenigas.py::compute_distance_from_coast_km),
# reusing the same anisotropic-grid distance-transform technique already
# used for shelf-break proximity in structure_layers.py.
DISTANCE_OFFSHORE_RAMP_MIN_LENIGAS_KM = 40.0
DISTANCE_OFFSHORE_IDEAL_MIN_LENIGAS_KM = 60.0
DISTANCE_OFFSHORE_IDEAL_MAX_LENIGAS_KM = 80.0
DISTANCE_OFFSHORE_RAMP_MAX_LENIGAS_KM = 100.0

# Upwelling/downwelling vorticity-sign scoring (Kane's spec, item 5;
# Michael's decision #5: drop the notes' unit-ambiguous "-10"/"2-4"
# numbers, use vorticity SIGN with magnitude-scaling instead):
#   score = 50 - 50*tanh(zeta / VORTICITY_SCALE_LENIGAS_S)
# Negative zeta (clockwise/SH-cyclonic/upwelling, per
# structure_layers.py::compute_relative_vorticity's verified sign
# convention) -> score -> 100 (favorable). Positive zeta (counter-
# clockwise/SH-anticyclonic/downwelling) -> score -> 0 (unfavorable).
# zeta=0 (neutral) -> score=50.
#
# VORTICITY_SCALE_LENIGAS_S is a judgment call grounded in a real,
# citable order-of-magnitude (not fabricated): typical mesoscale
# relative-vorticity magnitudes in current-bend/frontal settings are
# commonly cited as a fraction of the local Coriolis parameter f (order
# 0.1-0.3x f for a "clearly curving" feature). At this AOI's ~27S
# latitude, f = 2*Omega*sin(27deg) ~= 6.6e-5 s^-1; choosing scale ~= f/10
# ~= 7e-6 s^-1 means a fairly typical mesoscale current bend (~1e-5 s^-1)
# already produces a strongly favorable/unfavorable score without
# requiring an extreme, rare event. Equivalent to the task briefing's
# "VORTICITY_SIGN_SCALE".
VORTICITY_SCALE_LENIGAS_S = 7e-6

# EAC-axis-position scoring zones (Kane's spec, item 7a): a signed
# distance x_km east(+)/west(-) of the traced EAC core-jet axis (see
# eac_axis.py::find_eac_axis_longitude), scored per the notes' "generally
# eastern side of the EAC where it's getting slack on the outside areas"
# -- west of axis is the wrong side, the fast-flow core just east of the
# axis is "right side but not yet slack", the outer "slack" zone 15-40km
# east is the best match, then EAC influence itself fades back toward
# neutral further east. All km breakpoints below are explicit judgment
# calls (the notes give no numeric scale for "outside areas") -- only the
# qualitative shape (west=bad, core=ok, slack=best, far-field=neutral) is
# notes-derived.
EAC_AXIS_WEST_SCORE = 30.0
EAC_AXIS_CORE_MAX_KM = 15.0
EAC_AXIS_CORE_SCORE = 70.0
EAC_AXIS_SLACK_MAX_KM = 40.0
EAC_AXIS_SLACK_SCORE = 100.0
EAC_AXIS_FADE_MAX_KM = 80.0
EAC_AXIS_FADE_SCORE = 50.0

# EAC-convergence scoring (Kane's spec, item 7b): a Gaussian point-
# proximity decay to the nearest detected "current crashes into the EAC"
# convergence point, reusing STRUCTURE_POINT_SIGMA_KM (no reason to invent
# a different decay radius for a mechanistically analogous "current meets
# a fixed-ish structural feature" signal). When zero convergence points
# are detected for a given day (a real, expected possibility -- see
# pipeline_lenigas.py::detect_eac_convergence_point's docstring for the
# honestly-documented v1-of-Lenigas simplification this detector uses),
# the whole layer defaults to a flat neutral 50 rather than 0, per Kane's
# explicit non-punitive-default instruction.
EAC_CONVERGENCE_NEUTRAL_SCORE = 50.0

# Asymmetric moon-phase model (Kane's spec, item 6; Michael's decision
# #6): signed days-from-full-moon (d = (phase_age_days % 28) - 14, using
# moon_phase.py's existing phase_age_days convention where full moon is
# exactly 14.0 on astral's 0-27.99 scale), piecewise-linearly interpolated
# against these anchor points. Peaks a few days BEFORE full moon (d=-3,
# score=100 -- "lead-up to the full moon is good"), troughs sharply ON
# full moon itself (d=0, score=15 -- "bad on day of full moon"), dips at
# both half-moons (d=+-7, score=35 -- "half moon is a little slower"),
# and is explicitly asymmetric around full moon (NOT a mirror image
# either side of d=0) per "a couple of days after is ok" scoring higher
# (55) than the days immediately before full moon taper down to (85 at
# d=-1) -- see kane-lenigas-scoring-spec.md item 6 for the full anchor-
# by-anchor rationale. Baseline anchor score is exactly 50, which maps to
# an exact 1.0x multiplier below -- "far from any described lunar effect"
# is a true neutral no-op.
MOON_PHASE_LENIGAS_ANCHORS_D = [-14, -9, -7, -5, -3, -1, 0, 1, 2, 3, 7, 9, 14]
MOON_PHASE_LENIGAS_ANCHORS_SCORE = [50, 50, 35, 50, 100, 85, 15, 55, 55, 50, 35, 50, 50]

# Overall WLC weights (6 factors, sums to 1.0). Distance-offshore was
# REMOVED: the AOI already confines all scored pixels to the offshore
# fishing ground, so re-penalising inshore pixels redundantly adds no
# discriminative power. Its freed weight (0.09) was redistributed to the
# three most influential tuna-location signals:
#   +0.030 -> eac_axis_position (most critical: slack-zone positioning is
#             the primary where-to-fish signal from the source account)
#   +0.025 -> eac_convergence  (bait/tuna concentration at current crash)
#   +0.025 -> upwelling_downwelling (upwelling drives bait concentration)
#   +0.010 -> sst_bell_lenigas (temperature still relevant; "23-26C")
# SST stays deliberately LOWER-weighted than in v1/v2 (source account
# de-emphasizes exact temperature: "not too much of a thing").
# Wind remains EXCLUDED -- not yet a WLC factor (Kane's scope note).
# Arithmetic check:
#   0.145 + 0.180 + 0.160 + 0.210 + 0.205 + 0.100 = 1.000 (verified)
LAYER_WEIGHTS_LENIGAS = {
    "sst_bell_lenigas":          0.145,  # was 0.135 (+0.010)
    "depth_suitability_lenigas": 0.180,  # unchanged
    "upwelling_downwelling":     0.160,  # was 0.135 (+0.025)
    "eac_axis_position":         0.210,  # was 0.180 (+0.030)
    "eac_convergence":           0.205,  # was 0.180 (+0.025)
    "ssha_hotspot_lenigas":      0.100,  # unchanged
}

# Final scalar multiplier bounds for apply_moon_phase_multiplier_lenigas
# (Kane's spec, item 8: 0.8x-1.2x) -- deliberately mirrors the existing
# MOON_MULTIPLIER_MIN/MAX for consistency with the rest of the project,
# not independently re-derived.
MOON_MULTIPLIER_MIN_LENIGAS = 0.8
MOON_MULTIPLIER_MAX_LENIGAS = 1.2

# Per-date archive subfolder name for the Lenigas pipeline's outputs
# (output/history/<date>/lenigas/), same pattern as v2's "v2" subfolder --
# NEVER "v3".
LENIGAS_OUTPUT_SUBDIR = "lenigas"

# --- SSHA hotspot factor (Kane's FINAL decision) --------------------------
# NEW 7th Lenigas WLC component -- see
# .squad/decisions/inbox/kane-lenigas-ssha-final-decision.md /
# .squad/decisions/inbox/ash-lenigas-ssha-tiers-feasibility.md /
# .squad/decisions/inbox/ripley-lenigas-ssha-hotspot.md. Scores a
# per-date, per-AOI PERCENTILE-RANKED SSHA (zos) anomaly hotspot/boundary
# signal ("the line of zero") -- NOT fixed cm thresholds, since Ash's real
# data showed the re-based anomaly's spread varies up to ~2.5x across
# sampled dates (a fixed-cm envelope would need constant recalibration).
# Raw zos is an ABSOLUTE dynamic-topography field (always positive,
# +32cm to +90cm in this AOI, never zero-centered) -- must be re-based to
# a per-date spatial anomaly first (see
# normalization_lenigas.py::compute_ssha_anomaly_cm_lenigas) before any
# tier scoring is applied, or every cell would silently land in one tier.
#
# Percentile breakpoints used by every seasonal anchor table below (0th
# percentile = that day's most extreme upwelling anomaly, 100th = that
# day's most extreme downwelling anomaly).
SSHA_HOTSPOT_PERCENTILES_LENIGAS = [0, 15, 30, 42, 55, 70, 88, 100]

# Default seasonal table (all months NOT explicitly listed in the winter/
# peak tables below: Jan-May, Sep, Oct). Peak score (100) is deliberately
# biased toward the low-percentile/upwelling side of the zero-crossing,
# monotonically declining toward BOTH tails -- this fixes Kane's own
# previously-flagged inconsistency (a "moderate upwelling" band scoring
# lower than a "light downwelling" band could never recur with this
# single-peaked, non-symmetric anchor shape).
SSHA_HOTSPOT_SCORES_DEFAULT_LENIGAS = [20, 70, 100, 100, 80, 45, 10, 0]

# Winter (Jun, Jul, Aug): SEQ's water column is less stratified in winter,
# so a given SSHA depression corresponds to a WEAKER vertical-nutrient-
# flux response than the same magnitude would produce in summer --
# widens the favorable band toward the extreme upwelling tail. Does NOT
# touch SEASONAL_MULTIPLIER_LENIGAS or the winter-trophy-run question
# (explicitly deferred by Kane, out of scope for this factor).
SSHA_HOTSPOT_SCORES_WINTER_LENIGAS = [55, 85, 100, 100, 75, 35, 5, 0]

# Peak EAC season (Nov, Dec): the EAC is at seasonal-peak strength, so a
# downwelling anomaly compounds on top of an already-thickened warm/
# nutrient-poor surface layer -- tightens downwelling tolerance (pulls
# the unfavorable-side anchors down/left) relative to the default table.
SSHA_HOTSPOT_SCORES_PEAK_LENIGAS = [20, 70, 100, 100, 65, 20, 0, 0]


# --- Giant Trevally (GT) scoring model ------------------------------------
# A fully SEPARATE bite-score model for Giant Trevally (Caranx ignobilis)
# in SE QLD -- NOT a version of the YFT/Lenigas models. GT are an ambush
# reef predator whose habitat is fundamentally different from YFT:
#   - Depth range: 20-150m (reef crests, shelf-edge ledges, drop-offs)
#     vs. YFT 500-3000m (deep offshore pelagic)
#   - EAC position: WESTERN INSHORE edge where the EAC presses against reef
#     structure (the "pressure edge") vs. YFT's EASTERN SLACK ZONE
#   - Moon phase: new moon (dark) is BEST; full moon is WORST (opposite of
#     the fisherman intuition for schooling/feeding pelagics)
#   - Wind: northerly wind concentrates baitfish on reef edges
#
# AOI: same as AOI_LENIGAS = AOI_V2 (the reef systems and shelf edge in
# SE QLD are within this domain; no widening needed).
AOI_GT = AOI_V2

# Per-date archive subfolder (output/history/<date>/gt/)
GT_OUTPUT_SUBDIR = "gt"

# Seasonal multiplier: GT are present year-round in SE QLD but peak during
# the EAC's strongest southward warm-water incursion (Sep-Nov). The EAC
# drives baitfish concentrations into reef pressure-edge zones where GT hunt.
# Feb-Apr = coolest period, weakest EAC, lowest GT activity.
SEASONAL_MULTIPLIER_GT = {
    1: 0.9,   # January: warm, EAC moderately present
    2: 0.6,   # February: post-season taper
    3: 0.6,   # March: cooler water, less EAC
    4: 0.6,   # April: autumn, EAC weakening
    5: 0.7,   # May: winter starting
    6: 0.8,   # June: winter, EAC still runs but weaker
    7: 0.8,   # July: mid-winter
    8: 0.9,   # August: pre-season, EAC building
    9: 1.0,   # September: EAC peak season begins
    10: 1.0,  # October: peak EAC season
    11: 1.0,  # November: peak EAC season
    12: 0.9,  # December: tapering from peak
}

# SST bell curve: GT prefer warm EAC surface water (24-28°C in SE QLD).
# Peak at 26°C -- the upper end of EAC core temperature for this AOI.
# sigma derived via FWHM: treating 24-28°C as the half-maximum window,
# FWHM = 4°C, sigma = 4 / 2.3548 ≈ 1.7°C.
SST_BELL_PEAK_C_GT = 26.0
SST_BELL_SIGMA_C_GT = 1.7

# Depth suitability: GT are a reef-associated species. Suitable depth covers
# GT prime ambush depth: 15-30m reef crests and hard structure edges where
# GT sit and wait for bait pushed past by the EAC pressure edge. Ramp up
# from 5m (too shallow / surf zone), plateau 15-30m (prime), ramp off to
# 60m. Values are positive (depth below sea level), land cells get NaN.
DEPTH_GT_RAMP_MIN_M = 5.0      # too shallow: surf / inshore flats
DEPTH_GT_IDEAL_MIN_M = 15.0    # prime GT reef habitat starts here
DEPTH_GT_IDEAL_MAX_M = 30.0    # top of the prime depth band
DEPTH_GT_RAMP_MAX_M = 60.0     # deeper than 60m: out of prime GT zone

# Bathymetric structure / depth-gradient scoring: GT need hard edges where
# the seafloor changes depth sharply (reef ledges, bommies, shelf steps).
# Score = 100 * tanh(|gradient| / DEPTH_STRUCTURE_GT_SCALE_M_PER_KM) so
# an edge of ~5m/km scores ~0.46 (moderate) and ~15m/km → ~0.91 (excellent).
DEPTH_STRUCTURE_GT_SCALE_M_PER_KM = 5.0

# Vorticity scale for upwelling: same physical mechanism and scale as
# Lenigas (f/10 ≈ 7e-6 s^-1, see VORTICITY_SCALE_LENIGAS_S rationale above).
VORTICITY_SCALE_GT_S = 7e-6

# EAC pressure-edge scoring zones (GT sit on the WESTERN / INSHORE side of
# the EAC axis, NOT the eastern slack zone like YFT). signed_dist_km from
# overlay_lenigas.compute_signed_distance_from_eac_axis_km:
#   d < 0 = west/inshore of axis (GT territory)
#   d > 0 = east/offshore of axis (YFT territory, not GT)
#
# Scoring shape (see overlay_gt.py::score_eac_edge_gt):
#   d > 0 (east of axis):            GT_EAC_OFFSHORE_SCORE  (wrong side)
#   d = 0 (at axis):                 GT_EAC_AXIS_SCORE      (moderate)
#   0 > d > -GT_EAC_INSHORE_OPTIMAL_KM:  linear ramp up to GT_EAC_OPTIMAL_SCORE
#   -optimal > d > -GT_EAC_INSHORE_MAX_KM: linear decline to GT_EAC_FAR_INSHORE_SCORE
#   d ≤ -max_km:                     GT_EAC_FAR_INSHORE_SCORE (EAC fading)
GT_EAC_INSHORE_OPTIMAL_KM = 15.0   # optimal pressure-edge band west of axis
GT_EAC_INSHORE_MAX_KM = 40.0       # EAC influence fades beyond 40km inshore
GT_EAC_AXIS_SCORE = 60.0            # right at axis: moderate
GT_EAC_OPTIMAL_SCORE = 100.0        # in the inshore pressure zone: best
GT_EAC_FAR_INSHORE_SCORE = 35.0     # too far inshore: EAC influence fading
GT_EAC_OFFSHORE_SCORE = 25.0        # east of axis: wrong side for GT

# GT moon phase anchor table: GT are LOW-LIGHT AMBUSH predators.
# New moon (dark) = best; full moon = worst (fish are cautious in bright light).
# User spec: "first couple of days after the new moon, and the last 2 days
# before the full moon are good times. The full moon itself is not ideal."
#
# Uses moon_phase.py's phase_age_days convention:
#   0 = new moon, 7 = first quarter, 14 = full moon, 21 = last quarter
#
# Anchor format: (phase_age_days, score_0_to_100)
# The score is mapped to a multiplier:
#   multiplier = MOON_MULTIPLIER_MIN_GT + (score/100) * (MOON_MULTIPLIER_MAX_GT - MIN)
MOON_PHASE_ANCHORS_GT = [
    (0,  90),  # new moon: excellent (dark, ambush conditions)
    (1,  100), # 1 day after new: BEST
    (2,  95),  # 2 days after new: still excellent
    (7,  55),  # first quarter: moderate
    (12, 85),  # 2 days before full: user says "good"
    (13, 75),  # day before full: good but fading
    (14, 20),  # full moon: BAD (too bright, fish cautious)
    (15, 35),  # day after full: starting to recover
    (21, 55),  # last quarter: moderate
    (26, 80),  # approaching new moon: building again
    (28, 90),  # new moon (wraps to 0): excellent
]
MOON_MULTIPLIER_MIN_GT = 0.5   # full moon: strongly suppress score
MOON_MULTIPLIER_MAX_GT = 1.3   # new moon / dark: boost score

# GT WLC weights (must sum to 1.0).
# EAC pressure edge is the primary driver (GT on western inshore edge).
# Depth structure (hard edges, reef ledges) added as explicit factor.
# Moon phase added as WLC factor (was previously a separate multiplier).
# North wind lowest -- ASCAT lag ~5-6 weeks; redistributed if absent.
# Arithmetic check: 0.20+0.18+0.17+0.15+0.12+0.09+0.05+0.04 = 1.00
LAYER_WEIGHTS_GT = {
    "eac_edge_gt":          0.20,
    "upwelling_gt":         0.18,
    "structure_gt":         0.17,
    "depth_gt":             0.15,
    "sst_gt":               0.12,
    "moon_phase_gt":        0.09,
    "current_gradient_gt":  0.05,
    "north_wind_gt":        0.04,
}


# --- "Outerline Method" (Yellowfin Environmental Hotspot Score) -----------
# A THIRD, fully separate Yellowfin scoring model -- referred to by the
# user as "v3" / the "Outerline Method". Named for its core principle:
# reward being ON THE OUTER LINE / BOUNDARY where multiple favourable
# oceanographic features intersect (thermal fronts, current convergence,
# EAC boundary, FSLE ridges, SLA gradients, upwelling/downwelling
# transitions) -- NOT reward the single strongest/most-extreme value of
# any one feature (warmest water, deepest water, strongest current,
# strongest FSLE, highest SLA). Depth is a MODERATE-WEIGHT FILTER only
# (see DEPTH_SUITABILITY_BREAKPOINTS_OUTERLINE): it must never overwhelm
# a genuinely strong oceanographic hotspot, validated against the real
# 11 Oct 2023 Point Lookout event (yellowfin busting up at ~250m depth --
# see validate_outerline.py). This is a HABITAT SUITABILITY score, not a
# probability of catching/encountering fish -- never described as such
# anywhere in this codebase's UI/output text.
#
# Reuses the same AOI_V2-clipped data sources as v2/Lenigas/GT (verified
# sufficient coverage), and writes to its own SEPARATE
# output/history/<date>/outerline/ subfolder -- no other model's outputs
# are ever touched by an Outerline run.
AOI_OUTERLINE = AOI_V2
OUTERLINE_OUTPUT_SUBDIR = "outerline"

# --- Section 1/2: SST suitability + SST front -----------------------------
# Piecewise-linear membership curve (deg C -> score out of 100), broad and
# forgiving rather than a tight bell curve: 23-26degC is the preferred
# range (matches the real fisherman-notes-derived SST_BELL_PEAK_C_LENIGAS
# = 24.5degC anchor already validated for this exact species/region), but
# suitability never truly collapses to zero across the wider EAC range --
# this is deliberately a much gentler curve than SST_BELL_* (v1/Lenigas/GT)
# since SST *suitability* here is only 8% of the total score; the sharper
# SST *front* factor below carries more weight for the "boundary" signal.
SST_SUITABILITY_BREAKPOINTS_C_OUTERLINE = [19.0, 21.0, 22.0, 23.0, 24.0, 25.0, 26.0, 27.0, 28.0, 30.0]
SST_SUITABILITY_SCORES_OUTERLINE       = [0.0, 15.0, 40.0, 70.0, 92.0, 100.0, 100.0, 60.0, 25.0, 0.0]

# --- Section 3: EAC axis / boundary scoring --------------------------------
# Reuses overlay_lenigas.py::compute_signed_distance_from_eac_axis_km's
# signed east(+)/west(-) km-from-axis field unmodified. Unlike Lenigas's
# axis-position table (which plateaus over a WIDE 15-40km slack zone),
# the Outerline model rewards a much narrower band centred on the EAC's
# outer boundary/edge itself -- a Gaussian bump peaking at
# EAC_BOUNDARY_OFFSET_KM_OUTERLINE km east of the traced core-jet axis,
# per the spec's "reward the boundary, not the core, and not open water
# far from any EAC influence" principle.
EAC_BOUNDARY_OFFSET_KM_OUTERLINE = 12.0
EAC_BOUNDARY_SIGMA_KM_OUTERLINE = 20.0

# --- Section 4/5: current convergence + current interaction ---------------
# Convergence: score = 0.5 - 0.5*tanh(divergence / scale), so NEGATIVE
# divergence (net inflow / convergence, where drifting baitfish/plankton
# concentrate) -> score -> 1.0, positive divergence (dispersal) -> 0.0.
# Same tanh-scaling technique already used by
# overlay_lenigas.py::score_upwelling_downwelling_lenigas, applied here to
# horizontal divergence (du/dx + dv/dy) instead of vertical vorticity.
CURRENT_CONVERGENCE_SCALE_S_OUTERLINE = 7e-6

# Current interaction: normalized gradient magnitude of current SPEED
# (reuses processing.py::velocity_edge_intensity unmodified) -- captures
# shear zones/boundaries where fast core water meets slower surrounding
# water, a genuinely different structural signal from convergence
# (divergence sign) and from EAC boundary (position relative to the axis).
# No extra tunable beyond the existing robust-percentile normalization.

# --- Section 6: SLA / SSHA boundary ----------------------------------------
# Rewards the GRADIENT of sea-surface-height-anomaly (eddy/current edges),
# not the absolute SLA value (which would just re-reward the eddy core) --
# reuses processing.py::spatial_gradient_magnitude + robust_minmax_normalize
# unmodified, same treatment already given to SST/CHL/MLD gradients.

# --- Section 7: upwelling/downwelling TRANSITION ---------------------------
# Deliberately the OPPOSITE shape from Lenigas's upwelling score (which
# rewards one vorticity SIGN outright): Outerline rewards the TRANSITION
# ZONE / boundary between upwelling and downwelling (zeta near zero),
# scoring 1.0 - |tanh(zeta / scale)| -- peaking at the zero-crossing and
# decaying toward 0.0 deep inside either a strongly upwelling or strongly
# downwelling patch. This follows the model's "reward boundaries, not
# extremes" principle even where an existing, differently-shaped scoring
# function already exists for the same underlying vorticity field.
UPWELLING_DOWNWELLING_TRANSITION_SCALE_S_OUTERLINE = 7e-6

# --- Section 8: bathymetry (moderate-weight FILTER only, never dominant) --
# Ramps from 0 in the shallows up to a wide, flat "good" plateau covering
# essentially the entire offshore shelf-break-to-abyssal range (200m to
# 4000m+) -- deliberately NOT a narrow ideal band like v1/Lenigas/GT's
# depth trapezoids, because real catch evidence (11 Oct 2023, ~250m, see
# validate_outerline.py) shows yellowfin holding well short of the deep
# water those models assume is "ideal". Only 5% of the total score, so
# even a large depth mismatch cannot override a genuinely strong
# oceanographic-structure hotspot elsewhere.
DEPTH_SUITABILITY_BREAKPOINTS_M_OUTERLINE = [0.0, 50.0, 100.0, 200.0, 500.0, 1000.0, 2000.0, 4000.0, 6000.0]
DEPTH_SUITABILITY_SCORES_OUTERLINE       = [0.0, 10.0, 35.0, 80.0, 100.0, 100.0, 95.0, 85.0, 70.0]

# --- Section 9: bait concentration proxy -----------------------------------
# Composite of (a) a band-pass chlorophyll suitability score (favours a
# moderate, "green water on the edge of blue" concentration -- neither
# bright-green bloom nor gin-clear open ocean) and (b) the mean of the
# already-computed structural aggregation signals (SST front, current
# convergence, FSLE front) -- baitfish concentrate where productive water
# coincides with physical aggregating structure, not from chlorophyll
# alone.
BAIT_PROXY_CHL_RAMP_MIN_OUTERLINE = 0.05
BAIT_PROXY_CHL_IDEAL_MIN_OUTERLINE = 0.12
BAIT_PROXY_CHL_IDEAL_MAX_OUTERLINE = 0.35
BAIT_PROXY_CHL_RAMP_MAX_OUTERLINE = 0.60
BAIT_PROXY_CHL_WEIGHT_OUTERLINE = 0.4        # vs. 0.6 for the structural-overlap component

# --- Section 10: seasonal suitability (SE QLD yellowfin migration) --------
# A modest (2%) WLC weight, not a multiplier -- deliberately small so it
# nudges but never overrides real-time oceanographic conditions on a given
# day (a fish-favourable ocean structure in an "off" month still scores
# well; the spec explicitly warns against season overriding real data).
SEASON_SUITABILITY_OUTERLINE = {
    1: 0.55, 2: 0.45, 3: 0.45, 4: 0.55, 5: 0.60, 6: 0.75,
    7: 0.80, 8: 0.85, 9: 1.00, 10: 1.00, 11: 0.95, 12: 0.70,
}

# --- Section 11/12: wind & visibility (kept genuinely separate) -----------
# Visibility component: pure sighting/spotting conditions -- best (1.0) in
# a flat calm, decaying linearly with wind speed. Ocean component: a
# neutral baseline (real, direct "wind drives ocean-scale prey aggregation
# in this AOI on the timescale of a single 10m wind snapshot" mechanism is
# NOT established/validated here, so this stays a flat 0.5 rather than
# invent an unverified relationship) -- kept as a separate named
# sub-score anyway so a future, validated ocean-wind mechanism can replace
# just that half without touching the visibility half. Combined 50/50.
WIND_VISIBILITY_CALM_MS_OUTERLINE = 2.0     # <= this speed -> visibility_score = 1.0
WIND_VISIBILITY_MAX_MS_OUTERLINE = 15.0     # >= this speed -> visibility_score = 0.0
WIND_VISIBILITY_OCEAN_BASELINE_OUTERLINE = 0.5
WIND_VISIBILITY_SPLIT_OUTERLINE = 0.5       # weight of visibility_score within the combined value (rest = ocean_score)

# --- Section 13: moon phase (LOW-weight modifier, not a WLC component) ----
# Applied as a narrow-range final multiplier (illumination-fraction based,
# same mechanism as overlay.py::apply_moon_phase_multiplier) AFTER the WLC
# overlay/convergence multiplier -- deliberately a much narrower band than
# v1's 0.8x-1.2x so it can only ever nudge, never dominate, the final
# score, per the spec's explicit "low weighting" instruction for moon.
MOON_MULTIPLIER_MIN_OUTERLINE = 0.95   # full moon / fully illuminated -> slight dampen
MOON_MULTIPLIER_MAX_OUTERLINE = 1.05   # new moon / dark -> slight boost

# --- Section 15: recommended initial component weights (must sum to 1.0) -
# Configurable in Python ONLY -- never hardcoded inline anywhere else in
# the Outerline pipeline. Percentages are the user's own recommended
# starting point (verified to sum to exactly 100%).
WEIGHTS_OUTERLINE = {
    "sst_suitability":       0.08,
    "sst_front":             0.12,
    "eac_boundary":          0.10,
    "current_convergence":   0.15,
    "current_interaction":   0.10,
    "fsle_front":            0.12,
    "sla_boundary":          0.08,
    "upwelling_downwelling": 0.07,
    "bait_proxy":            0.10,
    "bathymetry":            0.05,
    "season":                0.02,
    "wind_visibility":       0.01,
}
assert abs(sum(WEIGHTS_OUTERLINE.values()) - 1.0) < 1e-9, "WEIGHTS_OUTERLINE must sum to 1.0"

# --- Section 16: non-linear feature-convergence multiplier ----------------
# Counts, per pixel, how many of CONVERGENCE_COUNT_COMPONENTS_OUTERLINE
# independently score >= FEATURE_PRESENCE_THRESHOLD_OUTERLINE (out of 100)
# at that pixel, then applies a multiplier from this step table --
# this is the mechanism that rewards genuine INTERSECTIONS of favourable
# features rather than any single strong factor. Steps are
# (min_feature_count, multiplier); the highest matching step wins.
CONVERGENCE_COUNT_COMPONENTS_OUTERLINE = [
    "sst_front", "eac_boundary", "current_convergence", "current_interaction",
    "fsle_front", "sla_boundary", "upwelling_downwelling", "bait_proxy",
]
FEATURE_PRESENCE_THRESHOLD_OUTERLINE = 65.0
CONVERGENCE_MULTIPLIER_STEPS_OUTERLINE = [
    (0, 1.00),
    (3, 1.05),
    (5, 1.15),
    (6, 1.25),
]

# --- Section 17: category grouping (informational only -- NOT a second
# weighting pass; every atomic component above is weighted exactly once
# in WEIGHTS_OUTERLINE. These groupings only drive the sidebar/explanation
# breakdown so related factors aren't presented as if they were
# independent evidence of separate phenomena.) ------------------------------
WEIGHT_CATEGORIES_OUTERLINE = {
    "Thermal structure": ["sst_suitability", "sst_front"],
    "Dynamic structure": ["eac_boundary", "current_convergence", "current_interaction", "fsle_front", "sla_boundary"],
    "Biological productivity": ["bait_proxy"],
    "Habitat": ["bathymetry", "upwelling_downwelling"],
    "Seasonal / weather": ["season", "wind_visibility"],
}

# Plain-English phrases used by overlay_outerline.py::explain_score_outerline()
# for each component, keyed the same as WEIGHTS_OUTERLINE.
EXPLANATION_PHRASES_OUTERLINE = {
    "sst_suitability": "suitable sea surface temperature",
    "sst_front": "a strong SST front",
    "eac_boundary": "the outer boundary of the EAC",
    "current_convergence": "current convergence",
    "current_interaction": "a current shear/interaction zone",
    "fsle_front": "an FSLE ocean-front boundary",
    "sla_boundary": "a sea-level-anomaly (eddy edge) boundary",
    "upwelling_downwelling": "an upwelling/downwelling transition zone",
    "bait_proxy": "a likely bait concentration",
}


