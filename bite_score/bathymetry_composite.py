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
_SURVEY_BUILDERS = [
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
    if rename_map:
        depth = depth.rename(rename_map)
    depth = depth.rio.set_spatial_dims(x_dim="lon", y_dim="lat", inplace=False)
    if depth.rio.crs is None:
        depth = depth.rio.write_crs(config.CRS)
    return depth


def build_composite_bathymetry() -> xr.DataArray:
    """
    Return a depth grid (positive-down metres, NaN over land) on the exact
    same lat/lon grid as raw GEBCO bathymetry, with cells overwritten by
    real local survey data (averaged down onto GEBCO's coarser cell size,
    via area-weighted `Resampling.average` rather than nearest-neighbour)
    wherever one of the 3 supplementary high-resolution surveys covers
    them. Real multibeam/LiDAR soundings replace GEBCO's satellite-
    altimetry-derived depth estimates in the areas they cover, without
    changing the shape/size of the reference grid the rest of the pipeline
    resamples onto -- so this is a drop-in swap wherever
    `data_ingestion.load_bathymetry()` was previously called directly.
    """
    composite = _prep_reference(load_bathymetry())

    for name, builder, _resolution_m in _SURVEY_BUILDERS:
        survey_path = builder()
        survey = rioxarray.open_rasterio(survey_path, masked=True).squeeze()
        resampled = survey.rio.reproject_match(composite, resampling=Resampling.average)
        # reproject_match renames spatial dims to x/y; rename back to lat/lon
        # so cell-wise .where() broadcasts correctly against `composite`
        # instead of creating extra dimensions (same gotcha documented in
        # overlay.py::align_to_reference()).
        rename_map = {}
        if "y" in resampled.dims and "lat" in composite.dims:
            rename_map["y"] = "lat"
        if "x" in resampled.dims and "lon" in composite.dims:
            rename_map["x"] = "lon"
        if rename_map:
            resampled = resampled.rename(rename_map)
        resampled = resampled.assign_coords(lat=composite["lat"], lon=composite["lon"])

        mask = resampled.notnull()
        n_cells = int(mask.sum())
        if n_cells:
            composite = composite.where(~mask, resampled)
            logger.info("Merged %s into composite bathymetry (%d cells)", name, n_cells)
        else:
            logger.warning(
                "%s reprojected onto the composite bathymetry grid with zero overlapping cells", name
            )

    composite = composite.rio.write_crs(config.CRS)
    composite = composite.rio.write_nodata(np.nan)
    composite.name = "depth"
    return composite
