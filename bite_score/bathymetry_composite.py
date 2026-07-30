"""
Merge the coarse global GEBCO bathymetry grid (~450m/15 arc-second, the
alignment reference grid for the entire pipeline -- see
overlay.py::weighted_overlay()) with the real local high-resolution surveys
already used elsewhere in this project purely as optional visual overlays
(Sunshine Coast LiDAR @10m, AusSeabed Moreton Bay Approaches @30m, AusSeabed
Mudjimba Island @0.5m -- see lidar_bathymetry.py / ausseabed_bathymetry.py).

The result is a single composite depth grid, on the *same* lat/lon grid as
raw GEBCO (so it's a drop-in replacement everywhere `load_bathymetry()` was
previously used, with zero changes needed to `overlay.py`'s alignment
logic), but with far more accurate real-survey depth values substituted in
wherever one of those three surveys actually covers a cell -- GEBCO's own
global grid is built mostly from satellite-altimetry-derived depth
estimates plus sparse ship soundings, so it can be meaningfully wrong
(tens of metres) in exactly the nearshore/reef areas that matter most for
the Bite Score's depth-suitability factor and land/coastline mask, even
though its overall grid resolution is coarse.
"""
import logging
import math

import numpy as np
import rioxarray  # noqa: F401  (registers the .rio accessor)
import xarray as xr
from rasterio.enums import Resampling

from . import config
from .aus_bathytopo import RESOLUTION_M as _AUS_BATHYTOPO_RESOLUTION_M, build_aus_bathytopo_geotiff
from .ausseabed_bathymetry import build_moreton_bay_approaches_geotiff, build_mudjimba_island_geotiff
from .data_ingestion import load_bathymetry
from .lidar_bathymetry import build_lidar_bathymetry_geotiff

logger = logging.getLogger(__name__)

# Approximate metres-per-pixel of the GEBCO/composite grid (15 arc-seconds),
# evaluated at the AOI's mean latitude -- used only for hillshade relief
# shading (see raster_utils.bathymetry_hillshade_to_rgba), where knowing the
# true pixel spacing in real metres (rather than degrees) is needed to
# compute realistic slopes. Averages the lat/lon cell sizes since they
# differ slightly (longitude cells shrink with cos(latitude)) but this
# grid's cells are treated as square for shading purposes, same
# approximation already used elsewhere for this ~450m grid.
_GEBCO_ARCSEC = 15.0
_METRES_PER_DEGREE_LAT = 111_320.0
_mean_lat = (config.AOI["min_lat"] + config.AOI["max_lat"]) / 2.0
_cell_deg = _GEBCO_ARCSEC / 3600.0
_lat_res_m = _cell_deg * _METRES_PER_DEGREE_LAT
_lon_res_m = _cell_deg * _METRES_PER_DEGREE_LAT * math.cos(math.radians(_mean_lat))
RESOLUTION_M = (_lat_res_m + _lon_res_m) / 2.0

# Merged in this order -- each later survey overwrites the composite
# wherever it has valid data, so surveys are listed coarsest-resolution
# first, finest-resolution last, ensuring the most precise data always
# wins any overlap between surveys (not just against the GEBCO base).
# AusBathyTopo 2024 250m (national-scale, real Australian-shelf survey
# compilation) sits between raw GEBCO (~450m) and the 3 small local patch
# surveys -- it covers the *entire* AOI (unlike the 3 small patches), so
# it effectively replaces the GEBCO base almost everywhere, with the 3
# finer local surveys still winning wherever they overlap.
_SURVEY_BUILDERS = [
    ("aus_bathytopo_250m", build_aus_bathytopo_geotiff, 250.0),
    ("moreton_bay_approaches", build_moreton_bay_approaches_geotiff, 30.0),
    ("lidar_sunshine_coast", build_lidar_bathymetry_geotiff, 10.0),
    ("mudjimba_island", build_mudjimba_island_geotiff, 0.5),
]


def _prep_reference(depth: xr.DataArray) -> xr.DataArray:
    """
    Standardize spatial dim names to lat/lon and ensure rioxarray knows the
    spatial dims/CRS -- same normalization `overlay.py::_prep_spatial()`
    applies at scoring time, duplicated here (rather than imported) since
    that helper is a private, internal detail of the overlay module.
    """
    rename_map = {}
    if "latitude" in depth.dims:
        rename_map["latitude"] = "lat"
    if "longitude" in depth.dims:
        rename_map["longitude"] = "lon"
    # Plain rioxarray-opened GeoTIFFs (e.g. AusBathyTopo's own native
    # file, opened directly rather than via load_bathymetry()) use bare
    # x/y dims -- same gotcha as rio.reproject()/reproject_match()'s own
    # dim renaming documented elsewhere in this module.
    if "lat" not in depth.dims and "y" in depth.dims:
        rename_map["y"] = "lat"
    if "lon" not in depth.dims and "x" in depth.dims:
        rename_map["x"] = "lon"
    if rename_map:
        depth = depth.rename(rename_map)
    depth = depth.rio.set_spatial_dims(x_dim="lon", y_dim="lat", inplace=False)
    if depth.rio.crs is None:
        depth = depth.rio.write_crs(config.CRS)
    # rioxarray's spatial-dims cache (set via set_spatial_dims() above)
    # lives on this specific DataArray *object* -- any later xarray op
    # that returns a new object (rename()/assign_coords()/where(), all
    # used elsewhere in this module) silently loses it, and rioxarray's
    # own auto-detection only recognizes the *full* names
    # "latitude"/"longitude" (or "x"/"y"), not the short "lat"/"lon" this
    # whole pipeline standardizes on -- so without this, a later
    # `.rio.reproject_match()` etc. on a downstream copy would raise
    # MissingSpatialDimensionError even though this exact array was
    # already prepped once. Stamping CF `axis`/`standard_name` attrs
    # directly onto the lat/lon coordinate variables (which DO survive
    # rename()/assign_coords()/where()) makes rioxarray's auto-detection
    # succeed again on any later copy, without needing to track down and
    # re-call _prep_reference() after every single intermediate op.
    depth["lat"].attrs.setdefault("axis", "Y")
    depth["lat"].attrs.setdefault("standard_name", "latitude")
    depth["lon"].attrs.setdefault("axis", "X")
    depth["lon"].attrs.setdefault("standard_name", "longitude")
    return depth


def _merge_survey(
    base: xr.DataArray, name: str, survey_path: str, resampling: Resampling
) -> xr.DataArray:
    """
    Reproject one survey GeoTIFF onto `base`'s exact grid and overwrite
    only the cells it actually covers -- shared by both
    build_composite_bathymetry() (merges onto GEBCO's own coarse grid, for
    WLC-scoring alignment) and build_visual_bathymetry_mosaic() (merges
    onto a much finer whole-AOI display grid instead).
    """
    survey = rioxarray.open_rasterio(survey_path, masked=True).squeeze()
    resampled = survey.rio.reproject_match(base, resampling=resampling)
    # reproject_match renames spatial dims to x/y; rename back to lat/lon
    # so cell-wise .where() broadcasts correctly against `base` instead of
    # creating extra dimensions (same gotcha documented in
    # overlay.py::align_to_reference()).
    rename_map = {}
    if "y" in resampled.dims and "lat" in base.dims:
        rename_map["y"] = "lat"
    if "x" in resampled.dims and "lon" in base.dims:
        rename_map["x"] = "lon"
    if rename_map:
        resampled = resampled.rename(rename_map)
    resampled = resampled.assign_coords(lat=base["lat"], lon=base["lon"])

    mask = resampled.notnull()
    n_cells = int(mask.sum())
    if n_cells:
        logger.info("Merged %s (%d cells)", name, n_cells)
        return base.where(~mask, resampled)
    logger.warning("%s reprojected onto the target grid with zero overlapping cells", name)
    return base


def build_composite_bathymetry() -> xr.DataArray:
    """
    Return a depth grid (positive-down metres, NaN over land) on the exact
    same lat/lon grid as raw GEBCO bathymetry, with cells overwritten by
    real local survey data (averaged down onto GEBCO's coarser cell size,
    via area-weighted `Resampling.average` rather than nearest-neighbour)
    wherever one of the supplementary surveys covers them. Real
    multibeam/LiDAR soundings (and the national AusBathyTopo compilation)
    replace GEBCO's satellite-altimetry-derived depth estimates in the
    areas they cover, without changing the shape/size of the reference
    grid the rest of the pipeline resamples onto -- so this is a drop-in
    swap wherever `data_ingestion.load_bathymetry()` was previously called
    directly. This grid stays at GEBCO's own coarse resolution
    deliberately (see build_visual_bathymetry_mosaic() below for a much
    finer whole-AOI grid used only for display, not scoring).
    """
    composite = _prep_reference(load_bathymetry())
    for name, builder, _resolution_m in _SURVEY_BUILDERS:
        composite = _merge_survey(composite, name, builder(), Resampling.average)

    composite = composite.rio.write_crs(config.CRS)
    composite = composite.rio.write_nodata(np.nan)
    composite.name = "depth"
    return composite


# Native pixel resolution (metres) of the whole-AOI *visual* relief base
# built below -- AusBathyTopo's own ~250m grid, deliberately left at its
# real native resolution rather than resampled onto a common finer grid.
# An earlier version of this function bilinear-upsampled AusBathyTopo onto
# a uniform 30m grid (to match the finest of the 3 small local surveys),
# but that just interpolated *between* AusBathyTopo's real ~250m sample
# points -- computing hillshade relief from those fabricated in-between
# pixels made the continental shelf (0-200m depth, where AusBathyTopo is
# the only real data available almost everywhere in this AOI) look
# artificially flat, since the actual depth signal only genuinely changes
# every ~250m. The 3 small local real surveys (Moreton Bay Approaches
# 30m, Sunshine Coast LiDAR 10m, Mudjimba Island 0.5m) are instead kept as
# SEPARATE, native-resolution inset layers layered on top of this base
# (see static_layers.py's `relief_map_moreton_bay_approaches`/
# `relief_map_lidar`/`relief_map_mudjimba_island` entries, and
# visualize.py, which stacks them all under the single "Bathymetry relief
# map" toggle) instead of being downsampled into one common grid, so
# their real fine detail is never thrown away in the areas they cover.
VISUAL_RESOLUTION_M = _AUS_BATHYTOPO_RESOLUTION_M


def build_visual_bathymetry_mosaic() -> xr.DataArray:
    """
    Build the whole-AOI *base* of the single unified "Bathymetry relief
    map" -- AusBathyTopo 2024's own native ~250m grid (a real, Australia-
    wide multibeam/LiDAR/chart compilation, see aus_bathytopo.py), with
    GEBCO's own coarse grid resampled in only as a fallback for any cell
    AusBathyTopo doesn't cover (in practice, none -- AusBathyTopo covers
    this entire AOI). Unlike build_composite_bathymetry() above (which
    downsamples every survey onto GEBCO's own coarse ~450m grid for WLC-
    scoring alignment), this keeps AusBathyTopo at its own real native
    pixel size rather than resampling it onto any other grid, so the
    hillshade relief computed from it (see
    raster_utils.bathymetry_hillshade_to_rgba()) reflects genuine depth
    changes at genuine pixel spacing, not smoothed/interpolated values.
    This is deliberately kept separate from build_composite_bathymetry()
    so the WLC-scoring alignment grid used everywhere else in the
    pipeline is completely unaffected by this display-only base.
    """
    aus_bathytopo_native = _prep_reference(
        rioxarray.open_rasterio(build_aus_bathytopo_geotiff(), masked=True).squeeze()
    )
    reference = _prep_reference(load_bathymetry())
    fallback = reference.rio.reproject_match(aus_bathytopo_native, resampling=Resampling.bilinear)
    # reproject_match() always renames spatial dims to x/y regardless of
    # their original names, so rename back to lat/lon before
    # _prep_reference() (which only knows how to rename
    # latitude/longitude -> lat/lon) -- same gotcha as _merge_survey() above.
    fallback = fallback.rename({"y": "lat", "x": "lon"})
    fallback = fallback.assign_coords(lat=aus_bathytopo_native["lat"], lon=aus_bathytopo_native["lon"])
    # assign_coords() (like rename()) returns a new object that drops the
    # rio accessor's cached spatial-dims state -- re-apply _prep_reference()
    # after it, not before, so the returned array actually has working
    # rio.x_dim/y_dim by the time it's used as reproject_match()'s target.
    fallback = _prep_reference(fallback)

    mosaic = _merge_survey(
        fallback, "aus_bathytopo_250m", build_aus_bathytopo_geotiff(), Resampling.bilinear
    )

    mosaic = mosaic.rio.write_crs(config.CRS)
    mosaic = mosaic.rio.write_nodata(np.nan)
    mosaic.name = "depth"
    return mosaic
