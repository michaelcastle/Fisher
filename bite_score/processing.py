"""
Raster processing: spatial gradients (thermal / chlorophyll fronts) and
surface current velocity magnitude & edge intensity.
"""
import logging

import numpy as np
import xarray as xr
from scipy.ndimage import gaussian_filter, sobel

logger = logging.getLogger(__name__)

METRES_PER_DEGREE_LAT = 111_320.0


def _lat_lon_names(da: xr.DataArray):
    lat_name = "lat" if "lat" in da.dims else "latitude"
    lon_name = "lon" if "lon" in da.dims else "longitude"
    return lat_name, lon_name


def spatial_gradient_magnitude(da: xr.DataArray, smooth_sigma: float = 1.0) -> xr.DataArray:
    """
    Compute the spatial gradient magnitude ("front intensity") of a 2D field
    using Sobel operators, converted to real-world metre spacing so results
    are comparable in physical units (e.g. degC/m or mg m^-3/m) rather than
    per-pixel units.

    A light Gaussian pre-filter (scipy.ndimage.gaussian_filter) suppresses
    sensor noise so fronts, not speckle, dominate the gradient signal.
    """
    lat_name, lon_name = _lat_lon_names(da)

    data = da.squeeze().astype("float64")
    values = data.values

    nan_mask = ~np.isfinite(values)
    filled = np.where(nan_mask, np.nanmean(values), values) if nan_mask.any() else values

    if smooth_sigma > 0:
        filled = gaussian_filter(filled, sigma=smooth_sigma)

    lat_axis = data.dims.index(lat_name)
    lon_axis = data.dims.index(lon_name)

    # 3x3 Sobel kernel weights sum to 8; normalize so units stay per-pixel.
    grad_lat_px = sobel(filled, axis=lat_axis) / 8.0
    grad_lon_px = sobel(filled, axis=lon_axis) / 8.0

    lat_vals = data[lat_name].values
    lon_vals = data[lon_name].values
    lat_spacing_deg = np.abs(np.mean(np.diff(lat_vals)))
    lon_spacing_deg = np.abs(np.mean(np.diff(lon_vals)))
    mean_lat_rad = np.deg2rad(np.mean(lat_vals))

    dy = lat_spacing_deg * METRES_PER_DEGREE_LAT
    dx = lon_spacing_deg * METRES_PER_DEGREE_LAT * np.cos(mean_lat_rad)

    grad_lat = grad_lat_px / dy
    grad_lon = grad_lon_px / dx

    magnitude = np.sqrt(grad_lat**2 + grad_lon**2)
    magnitude[nan_mask] = np.nan

    result = xr.DataArray(magnitude, coords=data.coords, dims=data.dims, name=f"{da.name}_gradient_mag")
    return result


def current_velocity_magnitude(u: xr.DataArray, v: xr.DataArray) -> xr.DataArray:
    """Compute total surface current speed (m/s) from U/V vector components."""
    u_aligned, v_aligned = xr.align(u.squeeze(), v.squeeze(), join="inner")
    speed = np.sqrt(u_aligned**2 + v_aligned**2)
    speed.name = "current_speed"
    return speed


def velocity_edge_intensity(speed: xr.DataArray) -> xr.DataArray:
    """
    Compute the spatial gradient of current speed, highlighting current
    boundaries and eddy edges rather than raw flow speed - these boundary
    zones concentrate baitfish and are prime pelagic foraging habitat.
    """
    edges = spatial_gradient_magnitude(speed)
    edges.name = "current_edge_intensity"
    return edges
