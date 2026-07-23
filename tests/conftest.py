"""
Shared pytest fixtures for the bite_score test suite.

Synthetic fixtures only (no live Copernicus/NOAA calls) -- these mirror
the real pipeline's raster conventions (see data_ingestion.py /
overlay.py) so tests exercise realistic shapes/dims/CRS without needing
network access or credentials:
  - dims named "lat"/"lon" (Copernicus's native "latitude"/"longitude" is
    already renamed by overlay.py::_prep_spatial before this stage)
  - ascending latitude (south -> north), matching
    data_ingestion.py::load_bathymetry()'s `.sortby(lat_name)`
  - CRS EPSG:4326 (config.CRS)
  - AOI bounds taken from config.AOI so fixtures stay in sync with the
    real area of interest if it's ever changed
"""
import numpy as np
import pytest
import rioxarray  # noqa: F401  (registers the .rio accessor)
import xarray as xr

from bite_score import config


@pytest.fixture
def reference_grid() -> xr.DataArray:
    """
    A small synthetic depth/bathymetry-like reference grid, standing in
    for the real composite-bathymetry alignment reference grid
    (bathymetry_composite.py::build_composite_bathymetry(), used as the
    `reference` arg to overlay.py::align_to_reference()). Includes a NaN
    "land" column so land-masking / zero-overlap behavior can be tested.
    """
    lat = np.linspace(config.AOI["min_lat"], config.AOI["max_lat"], 12)
    lon = np.linspace(config.AOI["min_lon"], config.AOI["max_lon"], 10)
    depth = np.tile(np.linspace(5.0, 500.0, lon.size), (lat.size, 1))
    depth[:, 0] = np.nan  # simulate a land column (westernmost)
    da = xr.DataArray(
        depth, coords={"lat": lat, "lon": lon}, dims=["lat", "lon"], name="depth"
    )
    da = da.rio.write_crs(config.CRS)
    da = da.rio.set_spatial_dims(x_dim="lon", y_dim="lat")
    return da


@pytest.fixture
def coarse_raster() -> xr.DataArray:
    """
    A coarser-resolution synthetic raster covering the same AOI bounds as
    `reference_grid` but at lower resolution -- standing in for a daily
    Copernicus physics-family field (e.g. `mlotst`/MLD, or the existing
    sst/currents/ssha fields), which get bilinear-upsampled onto the finer
    bathymetry reference grid in the real pipeline
    (overlay.py::align_to_reference).
    """
    lat = np.linspace(config.AOI["min_lat"], config.AOI["max_lat"], 4)
    lon = np.linspace(config.AOI["min_lon"], config.AOI["max_lon"], 4)
    values = np.random.default_rng(42).uniform(10.0, 80.0, size=(4, 4))
    da = xr.DataArray(
        values, coords={"lat": lat, "lon": lon}, dims=["lat", "lon"], name="mlotst"
    )
    da = da.rio.write_crs(config.CRS)
    da = da.rio.set_spatial_dims(x_dim="lon", y_dim="lat")
    return da
