"""
Assets that are identical across every pipeline run/date -- the static
GEBCO bathymetry grid, its derived Depth-suitability score (one of the 5
Bite Score contributing factors, but depends only on the never-changing
bathymetry, not on any daily ocean data), bathymetry depth-contour lines,
and the single unified bathymetry relief map (an AusBathyTopo-based
whole-AOI base at its own native ~250m resolution, plus the 3 real local
surveys -- Moreton Bay Approaches, Sunshine Coast LiDAR, Mudjimba Island --
layered on top at THEIR own native resolutions, see
bathymetry_composite.py and the `relief_map*` entries in RASTER_LAYERS
below) -- are built once here and cached to disk, then served by
webapp.py as standalone static endpoints (fetched by the browser only
when the corresponding layer is switched on) instead of being duplicated
into every date's `bite_score_map.html` (previously ~35MB per date,
almost entirely these same few unchanging images/lines repeated over and
over).

This mirrors the pattern already used for the MBGFC fishing chart (see
mbgfc_chart.py) -- a lightweight placeholder layer is registered in every
generated map page, and the actual pixel/line data is fetched client-side
from the dashboard server the first time that layer is toggled on.
"""
import json
import logging
import os

import numpy as np
from PIL import Image

from . import config
from .ausseabed_bathymetry import (
    RESOLUTION_M as _AUSSEABED_RESOLUTION_M,
    build_moreton_bay_approaches_geotiff,
    build_mudjimba_island_geotiff,
)
from .bathymetry_composite import (
    VISUAL_RESOLUTION_M as _VISUAL_RESOLUTION_M,
    build_composite_bathymetry,
    build_visual_bathymetry_mosaic,
)
from .export import export_geotiff
from .lidar_bathymetry import RESOLUTION_M as _LIDAR_RESOLUTION_M, build_lidar_bathymetry_geotiff
from .normalization import normalize_depth
from .raster_utils import (
    bathymetry_contour_geojson,
    bathymetry_hillshade_to_rgba,
    land_outline_geojson,
    open_score_raster,
    raster_to_rgba,
)

logger = logging.getLogger(__name__)


def get_static_domain_bounds() -> tuple:
    """
    (west, south, east, north) bounds of the static bathymetry grid --
    the same domain every date's Bite Score raster is resampled onto (see
    pipeline.py::align_to_reference()), so this is a date-independent
    stand-in for "the map's overall bounds", used by visualize.py to set
    the initial view and placeholder-layer bounds without needing to open
    any per-date GeoTIFF at template-generation time.
    """
    bathymetry_path = build_static_bathymetry_geotiff()
    _da, _values, bounds = open_score_raster(bathymetry_path)
    return bounds


def build_static_bathymetry_geotiff(force_rebuild: bool = False) -> str:
    """
    Cache the static composite bathymetry grid (identical -- same source
    surveys, same output -- every single pipeline run) once, rather than
    rebuilding an identical `bathymetry.tif` for every date's history
    folder. Used as the input for the depth-contour lines, the relief map,
    and the depth-suitability factor layer below. See
    bathymetry_composite.py: this is GEBCO with the 3 supplementary
    high-resolution surveys (Sunshine Coast LiDAR, AusSeabed Moreton Bay
    Approaches / Mudjimba Island) merged in wherever they cover a cell,
    not raw GEBCO alone.
    """
    path = config.STATIC_BATHYMETRY_TIF_PATH
    if os.path.exists(path) and not force_rebuild:
        return path
    depth = build_composite_bathymetry()
    export_geotiff(depth, output_path=path)
    logger.info("Cached static composite bathymetry to %s", path)
    return path


def build_depth_suitability_geotiff(force_rebuild: bool = False) -> str:
    """
    Cache the "Depth-suitability score" contributing factor (one of the 5
    weighted Bite Score inputs). Depends only on `normalize_depth()`
    applied to the static composite bathymetry grid -- exactly reproducing
    `overlay.weighted_overlay()`'s own `layer_scores["bathymetry"]`
    computation (which uses the depth-suitability grid as its own
    alignment reference, so it's untouched by the reprojection/resampling
    applied to the other 4 daily factors) -- so it never actually changes
    across dates and doesn't need recomputing/re-exporting per pipeline run.
    """
    path = config.DEPTH_SUITABILITY_TIF_PATH
    if os.path.exists(path) and not force_rebuild:
        return path
    depth = build_composite_bathymetry()
    depth_score = normalize_depth(depth)
    scaled = (depth_score * 100.0).clip(min=0, max=100).where(depth.notnull())
    scaled.name = "bathymetry_score"
    export_geotiff(scaled, output_path=path)
    logger.info("Cached depth-suitability factor layer to %s", path)
    return path


def build_visual_relief_geotiff(force_rebuild: bool = False) -> str:
    """
    Cache the whole-AOI bathymetry relief *base* (AusBathyTopo's own
    native ~250m grid, see
    bathymetry_composite.py::build_visual_bathymetry_mosaic()) once -- the
    3 real local surveys (Moreton Bay Approaches, Sunshine Coast LiDAR,
    Mudjimba Island) are layered on top of this base at their own native
    resolutions (see the `relief_map_moreton_bay_approaches`/
    `relief_map_lidar`/`relief_map_mudjimba_island` entries in
    RASTER_LAYERS below), all stacked together under the single
    "Bathymetry relief map" toggle in visualize.py.
    """
    path = config.VISUAL_BATHYMETRY_MOSAIC_TIF_PATH
    if os.path.exists(path) and not force_rebuild:
        return path
    mosaic = build_visual_bathymetry_mosaic()
    export_geotiff(mosaic, output_path=path)
    logger.info("Cached visual bathymetry relief mosaic to %s", path)
    return path


def build_bathymetry_contours_json(force_rebuild: bool = False) -> str:
    """
    Cache the depth-contour (isobath) GeoJSON + label points, derived from
    the static bathymetry grid, as a single JSON asset served directly by
    webapp.py.
    """
    path = config.BATHYMETRY_CONTOURS_JSON_PATH
    if os.path.exists(path) and not force_rebuild:
        return path
    bathymetry_path = build_static_bathymetry_geotiff(force_rebuild=force_rebuild)
    geojson, labels = bathymetry_contour_geojson(bathymetry_path)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"geojson": geojson, "labels": labels}, f)
    logger.info("Cached bathymetry contours to %s", path)
    return path


def build_land_outline_geojson(force_rebuild: bool = False) -> str:
    """
    Cache the land/coastline outline, as a single GeoJSON asset served
    directly by webapp.py. Traced from the fine ~250m AusBathyTopo-based
    visual relief mosaic (see build_visual_relief_geotiff() above), NOT
    the coarser ~450m depth-suitability/scoring grid this used to be
    traced from -- that coarse-grid outline visibly disagreed with the
    real coastline once the (much higher-resolution) relief map was shown
    at the same time (2026-07 bug report: the outline cut across real
    beach/foreshore that the relief map itself correctly renders as
    land). Land here is simply any cell with depth <= 0 (positive-down
    convention -- the same threshold `normalize_depth()` uses to NaN out
    land for the WLC scoring factor), not NaN itself, since the raw
    mosaic keeps real (negative-depth) land elevations rather than
    masking them out.
    """
    path = config.LAND_OUTLINE_JSON_PATH
    if os.path.exists(path) and not force_rebuild:
        return path
    relief_path = build_visual_relief_geotiff(force_rebuild=force_rebuild)
    da, _values, _bounds = open_score_raster(relief_path)
    land_masked = da.where(da > 0)
    geojson = land_outline_geojson(land_masked)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(geojson, f)
    logger.info("Cached land outline to %s", path)
    return path


# Registry of the shared raster-image layers (bathymetry/relief-shading
# rasters, rendered as a single PNG + bounds JSON) -- each entry describes
# how to build/cache its source GeoTIFF and how to convert it to an RGBA
# image, so `build_raster_layer_assets()` below can treat them uniformly.
RASTER_LAYERS = {
    "depth_suitability": {
        "geotiff_fn": build_depth_suitability_geotiff,
        "rgba_fn": lambda values: raster_to_rgba(values),
        "png_path": config.DEPTH_SUITABILITY_PNG_PATH,
        "meta_path": config.DEPTH_SUITABILITY_META_JSON_PATH,
    },
    "relief_map": {
        # The whole-AOI *base* of the single unified "Bathymetry relief
        # map" -- AusBathyTopo's own native ~250m grid (GEBCO fallback
        # merged in only where AusBathyTopo has no coverage, in practice
        # nowhere in this AOI, see build_visual_bathymetry_mosaic()),
        # rendered as literal shaded-relief terrain with a graduated
        # bathymetric colour scale (not a 0-100 score). The 3 entries
        # below layer the real local surveys on top of this base, each at
        # its own native (finer) resolution, all under this same toggle.
        "geotiff_fn": build_visual_relief_geotiff,
        "rgba_fn": lambda values: bathymetry_hillshade_to_rgba(values, _VISUAL_RESOLUTION_M),
        "png_path": config.RELIEF_MAP_PNG_PATH,
        "meta_path": config.RELIEF_MAP_META_JSON_PATH,
    },
    "relief_map_moreton_bay_approaches": {
        # Real 30m multibeam survey covering the offshore Moreton Bay
        # approaches -- layered on top of the relief_map base above at its
        # own native resolution rather than being downsampled into the
        # common grid, so its real detail isn't thrown away.
        "geotiff_fn": build_moreton_bay_approaches_geotiff,
        "rgba_fn": lambda values: bathymetry_hillshade_to_rgba(
            values, _AUSSEABED_RESOLUTION_M["moreton_bay_approaches"]
        ),
        "png_path": config.MORETON_BAY_APPROACHES_PNG_PATH,
        "meta_path": config.MORETON_BAY_APPROACHES_META_JSON_PATH,
    },
    "relief_map_lidar": {
        # Real 10m airborne LiDAR survey of the Sunshine Coast nearshore --
        # same treatment as the Moreton Bay Approaches inset above.
        "geotiff_fn": build_lidar_bathymetry_geotiff,
        "rgba_fn": lambda values: bathymetry_hillshade_to_rgba(values, _LIDAR_RESOLUTION_M),
        "png_path": config.LIDAR_BATHYMETRY_PNG_PATH,
        "meta_path": config.LIDAR_BATHYMETRY_META_JSON_PATH,
    },
    "relief_map_mudjimba_island": {
        # Real 0.5m multibeam survey of a small patch off Mudjimba Island --
        # same treatment as the other 2 insets above.
        "geotiff_fn": build_mudjimba_island_geotiff,
        "rgba_fn": lambda values: bathymetry_hillshade_to_rgba(
            values, _AUSSEABED_RESOLUTION_M["mudjimba_island"]
        ),
        "png_path": config.MUDJIMBA_ISLAND_PNG_PATH,
        "meta_path": config.MUDJIMBA_ISLAND_META_JSON_PATH,
    },
}


def build_raster_layer_assets(key: str, force_rebuild: bool = False) -> tuple:
    """
    Build (if not already cached) and return (png_path, meta_json_path) for
    one of the shared raster layers in `RASTER_LAYERS`. The PNG is the
    already-colour-mapped/hillshaded RGBA image (browser-ready); the JSON
    holds just its lat/lon bounds -- exactly the same split used for the
    MBGFC chart (see mbgfc_chart.py::build_mbgfc_chart_png()).
    """
    if key not in RASTER_LAYERS:
        raise KeyError(f"Unknown static raster layer: {key!r}")
    meta = RASTER_LAYERS[key]
    png_path, meta_path = meta["png_path"], meta["meta_path"]
    if os.path.exists(png_path) and os.path.exists(meta_path) and not force_rebuild:
        return png_path, meta_path

    geotiff_path = meta["geotiff_fn"](force_rebuild=force_rebuild)
    _da, values, bounds = open_score_raster(geotiff_path)
    rgba = meta["rgba_fn"](values)
    rgba_uint8 = (np.clip(rgba, 0.0, 1.0) * 255).astype("uint8")

    os.makedirs(os.path.dirname(png_path) or ".", exist_ok=True)
    Image.fromarray(rgba_uint8, mode="RGBA").save(png_path)

    # min/max of the raw underlying values (a 0-100 score for
    # depth_suitability, or raw positive-down depth in metres for the
    # hillshade layers below it) -- added (2026-07-24, Lambert) so the
    # sidebar's per-layer legend can show a real, live-fetched value range
    # for these static layers too, exactly like every per-date layer's own
    # meta already does (see date_layers.py::build_date_layer_assets()).
    finite_values = values[np.isfinite(values)]
    bounds_meta = {
        "bounds": [[bounds[1], bounds[0]], [bounds[3], bounds[2]]],
        "min": float(finite_values.min()) if finite_values.size else None,
        "max": float(finite_values.max()) if finite_values.size else None,
    }
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(bounds_meta, f)

    logger.info("Cached %s raster layer to %s / %s", key, png_path, meta_path)
    return png_path, meta_path
