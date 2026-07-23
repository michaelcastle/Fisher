"""
Normalization / fuzzy reclassification of processed layers onto a common
0.0 - 1.0 suitability scale for Yellowfin Tuna habitat.
"""
import logging

import numpy as np
import xarray as xr

from . import config

logger = logging.getLogger(__name__)


def robust_minmax_normalize(
    da: xr.DataArray,
    lower_percentile: float = config.NORMALIZATION_LOWER_PERCENTILE,
    upper_percentile: float = config.NORMALIZATION_UPPER_PERCENTILE,
) -> xr.DataArray:
    """
    Percentile-clipped min-max normalization to [0, 1].

    Robust to a small number of outlier spikes (e.g. cloud-contaminated
    pixels) that would otherwise dominate a naive min/max scaling and wash
    out the rest of the suitability signal.
    """
    values = da.values.astype("float64")
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        raise ValueError(f"No finite values to normalize in {da.name}")

    lo, hi = np.percentile(finite, [lower_percentile, upper_percentile])
    if hi <= lo:
        hi = lo + 1e-9

    normalized = np.clip((values - lo) / (hi - lo), 0.0, 1.0)
    normalized[~np.isfinite(values)] = np.nan

    result = da.copy(data=normalized)
    result.name = f"{da.name}_score"
    return result


def normalize_sst_gradient(sst_gradient: xr.DataArray) -> xr.DataArray:
    """Sharpest thermal fronts -> 1.0 (Yellowfin key on temperature breaks)."""
    return robust_minmax_normalize(sst_gradient)


def normalize_chl_gradient(chl_gradient: xr.DataArray) -> xr.DataArray:
    """Sharpest chlorophyll / water-colour fronts -> 1.0 (blue/green boundary)."""
    return robust_minmax_normalize(chl_gradient)


def normalize_current_edges(current_edge_intensity: xr.DataArray) -> xr.DataArray:
    """Moderate-to-high velocity edges / eddy boundaries -> 1.0."""
    return robust_minmax_normalize(current_edge_intensity)


def normalize_ssha_gradient(ssha_gradient: xr.DataArray) -> xr.DataArray:
    """
    Sharpest sea-surface-height-anomaly gradients -> 1.0. SSHA fronts mark
    eddy edges and current boundaries (often more cleanly than raw current
    velocity, since geostrophic shear is directly proportional to the SSH
    slope), which concentrate baitfish and pelagic foraging activity.
    """
    return robust_minmax_normalize(ssha_gradient)


def normalize_mld_gradient(mld_gradient: xr.DataArray) -> xr.DataArray:
    """
    Sharpest mixed-layer-depth (mlotst) gradients -> 1.0.

    Following Kane's mechanism (shoaling MLD compresses forage into a thin
    surface layer, especially meaningful near an existing thermal/
    chlorophyll front -- see
    .squad/decisions/inbox/kane-oceanographic-signals.md), this scores the
    MLD *gradient* (a shoaling front/edge), reusing the exact same
    gradient-magnitude + robust-percentile-normalization approach already
    used for sst/chl/ssha above (see
    processing.py::spatial_gradient_magnitude), rather than inventing a
    new absolute-depth suitability envelope (like normalize_depth's
    trapezoid) that would need separately-tuned, unvalidated thresholds.
    A sharp MLD transition zone marks the *edge* of a shoaling event,
    which is exactly where Kane's mechanism says forage gets concentrated
    against another front -- consistent with how every other front-style
    factor in this pipeline is already treated.
    """
    return robust_minmax_normalize(mld_gradient)


def _trapezoidal_membership(
    values: np.ndarray, ramp_min: float, ideal_min: float, ideal_max: float, ramp_max: float
) -> np.ndarray:
    """
    Fuzzy trapezoidal membership function:
        0 below ramp_min, rising linearly to 1 at ideal_min,
        1 (plateau) between ideal_min and ideal_max,
        falling linearly to 0 at ramp_max, 0 beyond.
    """
    score = np.zeros_like(values, dtype="float64")

    rising = (values >= ramp_min) & (values < ideal_min)
    score[rising] = (values[rising] - ramp_min) / (ideal_min - ramp_min)

    plateau = (values >= ideal_min) & (values <= ideal_max)
    score[plateau] = 1.0

    falling = (values > ideal_max) & (values <= ramp_max)
    score[falling] = (ramp_max - values[falling]) / (ramp_max - ideal_max)

    return np.clip(score, 0.0, 1.0)


def normalize_depth(
    depth: xr.DataArray,
    ideal_min: float = config.DEPTH_IDEAL_MIN,
    ideal_max: float = config.DEPTH_IDEAL_MAX,
    ramp_min: float = config.DEPTH_RAMP_MIN,
    ramp_max: float = config.DEPTH_RAMP_MAX,
) -> xr.DataArray:
    """
    Depth suitability: 100m-600m -> 1.0 (the continental shelf-break /
    drop-off zone favoured by pelagic gamefish like Yellowfin Tuna),
    shallow flats or abyssal depths -> 0.0.

    Land (depth <= 0, i.e. above sea level) is set to NaN rather than 0.0,
    so it stays distinguishable from a real (but low-suitability) ocean
    cell -- this NaN mask is what lets the final Bite Score raster mask out
    land cleanly instead of scoring them as "0% chance of a bite" water.
    """
    values = depth.values.astype("float64")
    score = _trapezoidal_membership(values, ramp_min, ideal_min, ideal_max, ramp_max)
    score[~np.isfinite(values)] = np.nan
    score[values <= 0] = np.nan

    result = depth.copy(data=score)
    result.name = "depth_score"
    return result
