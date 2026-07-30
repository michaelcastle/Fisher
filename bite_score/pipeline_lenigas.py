"""
"Lenigas" core scoring pipeline: takes already-loaded SST / currents /
bathymetry xarray objects and runs distance-from-coast derivation ->
Lenigas normalization -> Lenigas WLC overlay -> seasonal multiplier ->
moon-phase multiplier, returning the final Bite Score Lenigas DataArray.

This is a NEW, SEPARATE module for the "Lenigas" bite-score model (see
.squad/decisions/inbox/kane-lenigas-scoring-spec.md /
.squad/decisions/inbox/ripley-lenigas-pipeline.md), mirroring
pipeline_v2.py's role/structure. It reuses several pure, already-
validated functions unmodified rather than duplicating their logic:
  - `structure_layers.py::compute_relative_vorticity` (vorticity field),
    `_lat_lon_names`/`_cell_size_metres` (grid dim/spacing helpers).
  - `processing.py::current_velocity_magnitude` (current speed).
  - `eac_axis.py::find_eac_axis_longitude` (Ash's EAC core-jet axis
    tracer).
  - `moon_phase.py::moon_phase_details` (phase_age_days).

Does not modify pipeline.py/pipeline_v2.py/structure_layers.py/
eac_axis.py/moon_phase.py themselves; v1/v2 pipelines and Ash's Lenigas
modules are completely untouched by this module.
"""
import logging
from datetime import datetime
from typing import Dict, List, Tuple

import numpy as np
import xarray as xr
from scipy.ndimage import distance_transform_edt

from .eac_axis import find_eac_axis_longitude
from .moon_phase import moon_phase_details
from .normalization_lenigas import (
    compute_ssha_anomaly_cm_lenigas,
    normalize_depth_suitability_lenigas,
    normalize_distance_offshore_lenigas,
    normalize_sst_bell_lenigas,
    score_ssha_hotspot_lenigas,
)
from .overlay_lenigas import (
    apply_moon_phase_multiplier_lenigas,
    apply_seasonal_multiplier_lenigas,
    compute_signed_distance_from_eac_axis_km,
    score_eac_axis_position_lenigas,
    score_eac_convergence_lenigas,
    score_upwelling_downwelling_lenigas,
    weighted_overlay_lenigas,
)
from .processing import current_velocity_magnitude, spatial_gradient_magnitude
from .structure_layers import _cell_size_metres, _lat_lon_names, compute_relative_vorticity

logger = logging.getLogger(__name__)


def compute_distance_from_coast_km(depth: xr.DataArray) -> xr.DataArray:
    """
    Real per-pixel distance-from-coast (km) raster for the Lenigas
    model's distance-offshore factor, derived directly from the AOI's
    own bathymetry land/sea mask (depth <= 0 or non-finite = land) via
    `scipy.ndimage.distance_transform_edt`, using the grid's true
    anisotropic (cos(lat)-corrected) per-cell metre spacing as the
    `sampling` argument -- the SAME technique already used for shelf-
    break-distance scoring in
    `structure_layers.py::shelf_break_distance_score` (reused via
    `structure_layers._lat_lon_names`/`_cell_size_metres`, not
    duplicated), just applied to a land/sea mask instead of a depth-band
    mask. No new/invented coastline data source -- this coastline is
    fully derivable from the bathymetry grid already loaded for this
    pipeline (same principle already established in this project by
    `visualize.py`'s NaN-mask-derived land outline).

    Sea cells get their real Euclidean distance (in km) to the nearest
    land cell; land cells are set to NaN (distance-from-coast has no
    meaning standing on land).
    """
    lat_name, lon_name = _lat_lon_names(depth)
    dy, dx = _cell_size_metres(depth, lat_name, lon_name)

    values = depth.values.astype("float64")
    finite = np.isfinite(values)
    land_mask = ~finite | (values <= 0)
    sea_mask = ~land_mask

    dist_m = distance_transform_edt(sea_mask, sampling=(dy, dx))
    dist_km = dist_m / 1000.0
    dist_km[land_mask] = np.nan

    result = depth.copy(data=dist_km)
    result.name = "distance_from_coast_km"
    return result


def detect_eac_convergence_point(uo: xr.DataArray, vo: xr.DataArray) -> List[Tuple[float, float]]:
    """
    v1-of-Lenigas SIMPLIFICATION -- honestly documented, NOT a validated
    real-world convergence-point detector (no such detector exists
    anywhere else in this codebase or in Ash's Lenigas implementation).
    Approximates the notes' "current goes from the east to west and
    crashes into/is a focal point onto the EAC" (Kane's spec item 7b) as
    the single latitude row where the along-axis EASTWARD current
    component (u) is most strongly NEGATIVE (i.e. the strongest local
    WESTWARD flow), sampled AT the EAC's own traced core-jet axis
    longitude (`eac_axis.py::find_eac_axis_longitude`, reused
    unmodified) -- a real, if deliberately crude, proxy for "a focal
    point onto the EAC", not a fabricated feature location.

    Returns a list of `(lat, lon)` tuples: EMPTY if no latitude row has
    any westward (u < 0) flow at the axis at all -- a real, expected
    outcome on many days (along-axis flow is often southward/eastward,
    not westward-converging), NOT an error condition. Never returns more
    than one point in this first Lenigas build (only the single
    strongest convergence signal) -- multi-point detection is flagged as
    future work.
    """
    speed = current_velocity_magnitude(uo, vo)
    axis_lon = find_eac_axis_longitude(speed)

    lat_name, lon_name = _lat_lon_names(uo)
    u = uo.squeeze().astype("float64")
    squeeze_dims = [d for d in u.dims if d not in (lat_name, lon_name)]
    if squeeze_dims:
        u = u.squeeze(dim=squeeze_dims)
    u = u.transpose(lat_name, lon_name)

    lat_vals = u[lat_name].values
    lon_vals = u[lon_name].values
    u_vals = u.values

    axis_lat_name = axis_lon.dims[0]
    if np.array_equal(axis_lon[axis_lat_name].values, lat_vals):
        axis_at_row = axis_lon.values
    else:
        axis_at_row = axis_lon.interp({axis_lat_name: lat_vals}).values

    # np.interp requires increasing x -- sort lon once, reused per row.
    order = np.argsort(lon_vals)
    lon_sorted = lon_vals[order]

    u_at_axis = np.full(lat_vals.size, np.nan)
    for i in range(lat_vals.size):
        if not np.isfinite(axis_at_row[i]):
            continue
        row_sorted = u_vals[i][order]
        if not np.isfinite(row_sorted).any():
            continue
        safe_row = np.where(np.isfinite(row_sorted), row_sorted, 0.0)
        u_at_axis[i] = np.interp(axis_at_row[i], lon_sorted, safe_row)

    if not np.isfinite(u_at_axis).any():
        return []

    strongest_idx = int(np.nanargmin(u_at_axis))
    if u_at_axis[strongest_idx] >= 0:
        # No genuinely westward flow anywhere along the axis today --
        # a real, expected "no convergence detected" outcome.
        return []

    return [(float(lat_vals[strongest_idx]), float(axis_at_row[strongest_idx]))]


def compute_bite_score_lenigas(
    sst: xr.DataArray,
    uo: xr.DataArray,
    vo: xr.DataArray,
    depth: xr.DataArray,
    zos: xr.DataArray,
    target_date: str,
    phase_age_days: float = None,
) -> Tuple[xr.DataArray, Dict[str, xr.DataArray]]:
    """
    Run the Lenigas gradients -> normalization -> WLC overlay ->
    seasonal-multiplier -> moon-phase-multiplier chain against pre-
    loaded 2D (lat, lon) SST / currents / bathymetry / SSHA fields
    (AOI_LENIGAS-clipped, i.e. `data_ingestion.py::load_bathymetry_v2()`'s
    output, reused unmodified -- AOI_LENIGAS aliases AOI_V2, verified
    sufficient coverage, see config.py) and return `(bite_score_lenigas,
    layer_scores)`.

    `zos` (raw sea surface height, Copernicus `COPERNICUS_DATASETS["ssha"]`,
    same field v1's `ssha_gradient` and v2's eddy score already consume)
    feeds the NEW `ssha_hotspot_lenigas` factor (Kane's FINAL decision,
    see .squad/decisions/inbox/kane-lenigas-ssha-final-decision.md):
    re-based to a per-date spatial anomaly
    (`normalization_lenigas.py::compute_ssha_anomaly_cm_lenigas`), then
    percentile-tier scored for `target_date`'s calendar month
    (`normalization_lenigas.py::score_ssha_hotspot_lenigas`).

    `phase_age_days` (astral's raw 0..27.99 lunar-cycle position) is
    OPTIONAL: if not supplied, it's computed internally via
    `moon_phase.py::moon_phase_details(target_date)` (the same function
    v1's pipeline already uses), so callers that already have the full
    moon-detail dict for other reasons (e.g.
    `main.py::run_pipeline_lenigas`, which also writes a
    `moon_phase.json` side-file) can pass it through instead of
    triggering a second computation.

    Wind data (`data_ingestion_lenigas.py::fetch_wind_data_lenigas`) is
    deliberately NOT a parameter here -- per Kane's explicit scope note
    (kane-lenigas-scoring-spec.md item 8), wind is not yet part of the
    Lenigas WLC weights for this first build; `main.py::run_pipeline_lenigas`
    fetches/reports on it separately for validation/diagnostic purposes
    only.
    """
    if phase_age_days is None:
        phase_age_days = moon_phase_details(target_date)["phase_age_days"]

    target_month = datetime.strptime(target_date, "%Y-%m-%d").month

    distance_km = compute_distance_from_coast_km(depth)

    sst_gradient = spatial_gradient_magnitude(sst)
    sst_bell_score = normalize_sst_bell_lenigas(sst, sst_gradient=sst_gradient)
    depth_score = normalize_depth_suitability_lenigas(depth)
    distance_score = normalize_distance_offshore_lenigas(distance_km)

    zeta = compute_relative_vorticity(uo, vo)
    upwelling_score = score_upwelling_downwelling_lenigas(zeta)

    ssha_anomaly_cm = compute_ssha_anomaly_cm_lenigas(zos)
    ssha_hotspot_score = score_ssha_hotspot_lenigas(ssha_anomaly_cm, target_month)

    speed = current_velocity_magnitude(uo, vo)
    axis_lon = find_eac_axis_longitude(speed)
    x_km = compute_signed_distance_from_eac_axis_km(depth_score, axis_lon)
    eac_axis_score = score_eac_axis_position_lenigas(x_km)

    convergence_points = detect_eac_convergence_point(uo, vo)
    eac_convergence_score = score_eac_convergence_lenigas(depth_score, convergence_points)
    if not convergence_points:
        logger.info(
            "No EAC convergence point detected for %s (no westward flow along the "
            "traced axis) -- eac_convergence scored as flat neutral 50",
            target_date,
        )

    bite_score, layer_scores = weighted_overlay_lenigas(
        sst_bell_score, depth_score, distance_score, upwelling_score, eac_axis_score,
        eac_convergence_score, ssha_hotspot_score,
    )

    bite_score = apply_seasonal_multiplier_lenigas(bite_score, target_date)
    bite_score = apply_moon_phase_multiplier_lenigas(bite_score, phase_age_days)

    return bite_score, layer_scores
