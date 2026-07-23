"""
EAC (East Australian Current) axis detection, and a vorticity-SIGN
upwelling/downwelling classifier, for the "Lenigas" scoring model.

NEW, SEPARATE module. Does not import from or modify v1/v2 pipeline code
(pipeline.py, pipeline_v2.py, overlay.py, overlay_v2.py, config.py's v1/v2
constants); v1/v2 config/output are untouched. Reuses two already-existing
functions UNMODIFIED rather than duplicating their logic:
  - `processing.py::current_velocity_magnitude(u, v)` for the EAC axis's
    speed profile.
  - `structure_layers.py::compute_relative_vorticity(uo, vo)` for the
    upwelling/downwelling classifier's vorticity field.

Both functions here take real, already-ingested Copernicus `uo`/`vo`
current fields (the same fields v2 already fetches -- see
data_ingestion.py::fetch_daily_ocean_data_v2) at `config.AOI_V2`
resolution; neither introduces a new data source.
"""
import logging

import numpy as np
import xarray as xr

from .processing import current_velocity_magnitude
from .structure_layers import _lat_lon_names, compute_relative_vorticity

logger = logging.getLogger(__name__)


def find_eac_axis_longitude(speed: xr.DataArray) -> xr.DataArray:
    """
    Trace the EAC's core jet axis by finding, at EACH latitude row
    independently, the longitude where current speed peaks (argmax of
    speed along the longitude axis).

    This is a per-latitude-band peak-current ridge-following approach,
    not a hardcoded coordinate -- real v2 currents data showed a single,
    clear speed maximum at every latitude row tested (tapering on both
    sides), so this always recomputes the peak from whatever `speed`
    (typically `current_velocity_magnitude`'s output) is passed in, and
    generalizes across dates/AOIs.

    Returns a 1D `xr.DataArray` indexed by latitude, giving the axis
    longitude at each row. A latitude row that is entirely NaN (e.g. an
    all-land row after masking) yields NaN for that row.
    """
    lat_name, lon_name = _lat_lon_names(speed)
    squeeze_dims = [d for d in speed.dims if d not in (lat_name, lon_name)]
    data = speed.squeeze(dim=squeeze_dims) if squeeze_dims else speed
    data = data.astype("float64").transpose(lat_name, lon_name)

    lat_vals = data[lat_name].values
    lon_vals = data[lon_name].values
    values = data.values  # (lat, lon)

    n_lat = values.shape[0]
    axis_lon = np.full(n_lat, np.nan, dtype="float64")
    for i in range(n_lat):
        row = values[i]
        if np.isfinite(row).any():
            axis_lon[i] = lon_vals[np.nanargmax(row)]

    result = xr.DataArray(
        axis_lon, coords={lat_name: lat_vals}, dims=[lat_name], name="eac_axis_lon"
    )
    return result


def classify_east_west_of_axis(grid: xr.DataArray, axis_lon: xr.DataArray) -> xr.DataArray:
    """
    Classify every cell of `grid` as east of the EAC axis (+1.0) or west
    of it (-1.0), by comparing each cell's longitude against the traced
    axis longitude (`find_eac_axis_longitude`'s output) at that cell's
    latitude.

    If `grid`'s latitude coordinate doesn't exactly match `axis_lon`'s,
    the axis is linearly interpolated onto `grid`'s latitude values
    first. Latitude rows outside `axis_lon`'s covered range (or where
    `axis_lon` itself is NaN, e.g. an all-land row) yield NaN, since
    "east/west of an undefined axis" isn't meaningful. NaN cells in
    `grid` also stay NaN.
    """
    lat_name, lon_name = _lat_lon_names(grid)
    squeeze_dims = [d for d in grid.dims if d not in (lat_name, lon_name)]
    data = grid.squeeze(dim=squeeze_dims) if squeeze_dims else grid
    data = data.transpose(lat_name, lon_name)

    lat_vals = data[lat_name].values
    lon_vals = data[lon_name].values

    axis_lat_name = axis_lon.dims[0]
    if np.array_equal(axis_lon[axis_lat_name].values, lat_vals):
        axis_at_row = axis_lon.values
    else:
        axis_at_row = axis_lon.interp({axis_lat_name: lat_vals}).values

    lon_grid = np.broadcast_to(lon_vals, (lat_vals.size, lon_vals.size))
    axis_grid = axis_at_row[:, np.newaxis]

    classification = np.where(lon_grid > axis_grid, 1.0, -1.0)
    classification = np.where(np.isnan(axis_grid), np.nan, classification)
    classification = np.where(~np.isfinite(data.values), np.nan, classification)

    result = xr.DataArray(
        classification, coords=data.coords, dims=data.dims, name="eac_axis_side"
    )
    return result


def compute_eac_axis_classification(uo: xr.DataArray, vo: xr.DataArray) -> xr.DataArray:
    """
    Convenience wrapper: compute current speed from `uo`/`vo` (reusing
    `processing.py::current_velocity_magnitude` unmodified), trace the
    EAC axis longitude at each latitude row, and classify every cell of
    that same `uo`/`vo` grid as east (+1.0) or west (-1.0) of the axis.
    """
    speed = current_velocity_magnitude(uo, vo)
    axis_lon = find_eac_axis_longitude(speed)
    classification = classify_east_west_of_axis(speed, axis_lon)
    classification.name = "eac_axis_side"
    return classification


def classify_upwelling_downwelling(vorticity: xr.DataArray) -> xr.DataArray:
    """
    Classify each grid cell by relative-vorticity SIGN into one of:

      +1.0  upwelling-favorable    (NEGATIVE zeta -- clockwise/cyclonic,
                                    per this project's verified Southern
                                    Hemisphere convention -- see
                                    structure_layers.py::compute_relative_vorticity's
                                    docstring)
      -1.0  downwelling-unfavorable (POSITIVE zeta -- counter-clockwise/
                                    anticyclonic)
       0.0  neutral                (zeta exactly 0.0, e.g. a still/
                                    no-current cell)

    This is a pure SIGN classification, not a magnitude threshold (the
    original podcast notes' numeric thresholds had undeterminable units
    and were explicitly dropped -- see
    .squad/decisions/inbox/coordinator-lenigas-decisions.md). Reuses
    `structure_layers.py::compute_relative_vorticity`'s output directly;
    does not recompute or duplicate its gradient/differencing logic.

    NaN vorticity cells (land/nodata) stay NaN.
    """
    values = vorticity.values
    classification = np.where(np.isfinite(values), 0.0, np.nan)
    classification = np.where(values < 0, 1.0, classification)
    classification = np.where(values > 0, -1.0, classification)

    result = vorticity.copy(data=classification)
    result.name = "upwelling_downwelling_classification"
    return result


def compute_upwelling_downwelling(uo: xr.DataArray, vo: xr.DataArray) -> xr.DataArray:
    """
    Convenience wrapper: compute relative vorticity from `uo`/`vo` via
    `structure_layers.py::compute_relative_vorticity` (unmodified,
    imported not duplicated), then classify by sign via
    `classify_upwelling_downwelling`.
    """
    vorticity = compute_relative_vorticity(uo, vo)
    return classify_upwelling_downwelling(vorticity)
