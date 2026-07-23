"""
Build a high-resolution static bathymetry/elevation GeoTIFF for the
Sunshine Coast from a locally-supplied 2011 airborne LiDAR survey (raw XYZ
point clouds under data/raw/DP_LIDAR_SunshineCoast/), so it can be shown as
an optional, much higher-resolution alternative to the coarse GEBCO grid
used everywhere else in the pipeline.

The survey only covers a narrow nearshore strip of the Sunshine Coast (not
the full pipeline AOI), so this is rendered as its own selectable map layer
(see visualize.py) rather than being blended into the Bite Score itself.

Point clouds are supplied in GDA94 / MGA Zone 56 (EPSG:28356) easting/
northing metres, height relative to the Australian Height Datum (AHD,
~mean sea level) -- positive = land elevation, negative = underwater depth.
They're gridded here (mean height per cell) onto a fixed-resolution raster
in that native CRS and cached to disk; `visualize.py` reprojects it to
WGS84 on the fly at render time, the same pattern used for every other
raster layer in this project.
"""
import glob
import logging
import os

import numpy as np
import pandas as pd
import rioxarray  # noqa: F401  (registers the .rio accessor)
import xarray as xr

from . import config
from .export import export_geotiff

logger = logging.getLogger(__name__)

_LIDAR_ROOT = os.path.join(config.RAW_DATA_DIR, "DP_LIDAR_SunshineCoast", "DP_LIDAR_SunshineCoast")
_ONSHORE_DIR = os.path.join(_LIDAR_ROOT, "SunshineBathy_LiDAR_xyz", "Classified")
_OFFSHORE_DIR = os.path.join(
    _LIDAR_ROOT, "SunshineBathy_LiDAR_xyz", "Classified_Offshore_AHD_tidal_data_XYZ"
)

# Source point cloud CRS: GDA94 / MGA Zone 56 (covers the Queensland Sunshine
# Coast). GDA94 vs WGS84 differs by ~1m, negligible at this display resolution.
_SOURCE_CRS = "EPSG:28356"

# Fixed grid bounds (metres, GDA94 MGA Zone 56) with generous margin around
# the actual survey extent (measured directly from the raw files: easting
# 502,000.0-523,443.7, northing 7,040,729.8-7,135,978.0) -- avoids a slow
# full pre-scan pass on every build just to (re)compute exact bounds.
_MIN_EASTING = 500_000.0
_MAX_EASTING = 525_000.0
_MIN_NORTHING = 7_035_000.0
_MAX_NORTHING = 7_140_000.0
_RESOLUTION_M = 10.0

# Public alias so other modules (e.g. visualize.py, for hillshade pixel
# spacing) don't need to reach into a "private" name.
RESOLUTION_M = _RESOLUTION_M

_CHUNK_ROWS = 2_000_000


def _xyz_files():
    files = sorted(glob.glob(os.path.join(_ONSHORE_DIR, "*.xyz")))
    # Exclude the merged/decimated "SunshineBathyLiDAR_C2_502_510.xyz"
    # export -- it duplicates points already covered by the individual
    # per-tile "C2_50x.xyz" files above, and would double-count them.
    files = [f for f in files if not os.path.basename(f).startswith("SunshineBathyLiDAR")]
    files += sorted(glob.glob(os.path.join(_OFFSHORE_DIR, "*.xyz")))
    return files


def build_lidar_bathymetry_geotiff(force_rebuild: bool = False) -> str:
    """
    Grid the raw Sunshine Coast LiDAR XYZ point clouds into a single cached
    GeoTIFF (depth in metres, positive-down, same convention as
    `data_ingestion.load_bathymetry()`) and return its path.

    Since this is a static, one-off 2011 survey (not tied to any pipeline
    run date), the result is cached at `config.LIDAR_BATHYMETRY_TIF_PATH`
    and only rebuilt if missing or `force_rebuild=True`.
    """
    output_path = config.LIDAR_BATHYMETRY_TIF_PATH
    if os.path.exists(output_path) and not force_rebuild:
        return output_path

    files = _xyz_files()
    if not files:
        raise FileNotFoundError(
            f"No LiDAR XYZ point cloud files found under {_ONSHORE_DIR} or {_OFFSHORE_DIR}"
        )

    n_cols = int(round((_MAX_EASTING - _MIN_EASTING) / _RESOLUTION_M))
    n_rows = int(round((_MAX_NORTHING - _MIN_NORTHING) / _RESOLUTION_M))

    sum_flat = np.zeros(n_rows * n_cols, dtype=np.float64)
    count_flat = np.zeros(n_rows * n_cols, dtype=np.int64)

    total_points = 0
    dropped_points = 0

    # pandas' C parser handles the ~1.7GB of whitespace-delimited XYZ text
    # far faster than a manual line-by-line parse; chunksize keeps peak
    # memory bounded regardless of how large any individual tile file is.
    for path in files:
        logger.info("Gridding LiDAR tile %s", os.path.basename(path))
        for chunk in pd.read_csv(
            path,
            sep=r"\s+",
            header=None,
            names=["easting", "northing", "z"],
            dtype=np.float64,
            engine="c",
            chunksize=_CHUNK_ROWS,
        ):
            easting = chunk["easting"].to_numpy()
            northing = chunk["northing"].to_numpy()
            z = chunk["z"].to_numpy()
            total_points += len(z)

            in_bounds = (
                (easting >= _MIN_EASTING)
                & (easting < _MAX_EASTING)
                & (northing >= _MIN_NORTHING)
                & (northing < _MAX_NORTHING)
            )
            dropped_points += int((~in_bounds).sum())
            easting, northing, z = easting[in_bounds], northing[in_bounds], z[in_bounds]

            col = ((easting - _MIN_EASTING) / _RESOLUTION_M).astype(np.int64)
            row = ((northing - _MIN_NORTHING) / _RESOLUTION_M).astype(np.int64)
            flat_idx = row * n_cols + col

            sum_flat += np.bincount(flat_idx, weights=z, minlength=n_rows * n_cols)
            count_flat += np.bincount(flat_idx, minlength=n_rows * n_cols)

    if dropped_points:
        logger.warning(
            "%d of %d LiDAR points fell outside the assumed grid bounds and were dropped",
            dropped_points,
            total_points,
        )
    logger.info(
        "Gridded %d LiDAR points into a %dx%d grid at %.0fm resolution",
        total_points,
        n_rows,
        n_cols,
        _RESOLUTION_M,
    )

    with np.errstate(invalid="ignore", divide="ignore"):
        mean_elevation = (sum_flat / count_flat).reshape(n_rows, n_cols)
    mean_elevation[count_flat.reshape(n_rows, n_cols) == 0] = np.nan

    # AHD elevation (positive = land, negative = underwater) -> positive-
    # down depth, matching `load_bathymetry()`'s convention elsewhere.
    depth = -mean_elevation

    easting_coords = _MIN_EASTING + (np.arange(n_cols) + 0.5) * _RESOLUTION_M
    northing_coords = _MIN_NORTHING + (np.arange(n_rows) + 0.5) * _RESOLUTION_M

    da = xr.DataArray(
        depth.astype(np.float32),
        dims=("y", "x"),
        coords={"y": northing_coords, "x": easting_coords},
        name="depth",
    )
    da = da.rio.write_crs(_SOURCE_CRS)
    da = da.rio.write_nodata(np.nan)

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    export_geotiff(da, output_path=output_path)
    return output_path
