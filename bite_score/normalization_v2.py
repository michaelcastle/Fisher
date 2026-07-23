"""
v2 normalization / fuzzy-reclassification functions for the SEQ Yellowfin
Tuna "v2" bite-score model: a Gaussian bell-curve SST suitability combined
with the existing gradient/front score as a weighted average, and a
chlorophyll optimal-band suitability.

This is a NEW, SEPARATE module for the v2 bite-score model (see
.squad/decisions/inbox/kane-seq-v2-validation.md /
.squad/decisions/inbox/ripley-seq-v2-scoring-model.md). It reuses two pure,
already-validated v1 functions unmodified --
normalization.py::normalize_sst_gradient (SST front/gradient scoring) and
normalization.py::_trapezoidal_membership (fuzzy trapezoidal envelope,
already used by normalize_depth) -- but does not modify normalization.py
itself; v1's pipeline is completely untouched by this module.
"""
import logging

import numpy as np
import xarray as xr

from . import config
from .normalization import _trapezoidal_membership, normalize_sst_gradient

logger = logging.getLogger(__name__)


def normalize_sst_bell(
    sst: xr.DataArray,
    peak_c: float = config.SST_BELL_PEAK_C,
    sigma_c: float = config.SST_BELL_SIGMA_C,
) -> xr.DataArray:
    """
    Gaussian bell-curve absolute-temperature suitability:
        score = exp(-(sst - peak_c)**2 / (2 * sigma_c**2))

    Peaks at 1.0 exactly at `peak_c` (22C by default), per Michael's spec.
    `sigma_c` (1.7 by default -- see config.SST_BELL_SIGMA_C's docstring
    for the FWHM derivation) is chosen so the 20-24C "optimal window" reads
    as "at least half-maximum suitability" around the peak, consistent
    with this being a smooth bell curve rather than a flat-topped
    trapezoidal plateau (unlike `normalize_chl_band` below).

    Land / non-finite input is preserved as NaN.
    """
    values = sst.values.astype("float64")
    finite = np.isfinite(values)

    score = np.exp(-((values - peak_c) ** 2) / (2.0 * sigma_c**2))
    score[~finite] = np.nan

    result = sst.copy(data=score)
    result.name = "sst_bell_score"
    return result


def normalize_sst_bell_v2(
    sst: xr.DataArray,
    sst_gradient: xr.DataArray,
    bell_weight: float = config.SST_BELL_COMPONENT_WEIGHT,
    gradient_weight: float = config.SST_GRADIENT_COMPONENT_WEIGHT,
) -> xr.DataArray:
    """
    Combine the bell-curve absolute-temperature suitability
    (`normalize_sst_bell`) with the existing gradient/front-strength score
    (`normalization.py::normalize_sst_gradient`, reused unmodified) as a
    WEIGHTED AVERAGE, per Kane's explicit correction
    (kane-seq-v2-validation.md, item 1c): multiplying two independent
    [0,1] fractional terms would crush the combined score toward zero
    everywhere except where both happen to be simultaneously near-maximal
    -- not what "SST suitability" should mean here. A textbook-optimal
    22C reading with only an average gradient should still score
    reasonably well, not get zeroed out by a product.

    `sst` and `sst_gradient` may already be on slightly different grids
    (the gradient computation can shift coordinate alignment at the
    edges), so they are inner-joined via `xr.align` before combining --
    same defensive pattern already used by
    structure_layers.py::compute_eddy_score for its two inputs.
    """
    bell_score = normalize_sst_bell(sst)
    gradient_score = normalize_sst_gradient(sst_gradient)

    bell_aligned, gradient_aligned = xr.align(bell_score, gradient_score, join="inner")

    total_weight = bell_weight + gradient_weight
    combined = (
        bell_weight * bell_aligned.fillna(0) + gradient_weight * gradient_aligned.fillna(0)
    ) / total_weight

    nan_mask = bell_aligned.isnull() & gradient_aligned.isnull()
    combined = combined.where(~nan_mask)
    combined.name = "sst_bell_gradient_score"
    return combined


def normalize_chl_band(
    chl: xr.DataArray,
    ramp_min: float = config.CHL_BAND_RAMP_MIN,
    ideal_min: float = config.CHL_BAND_IDEAL_MIN,
    ideal_max: float = config.CHL_BAND_IDEAL_MAX,
    ramp_max: float = config.CHL_BAND_RAMP_MAX,
) -> xr.DataArray:
    """
    Chlorophyll optimal-band suitability: 0.1-0.3 mg/m3 -> 1.0 (ideal
    forage-base concentration), <0.1 mg/m3 "barren" -> 0.0, >0.5 mg/m3
    "murky" -> 0.0, per Michael's spec. Reuses the existing
    normalization.py::_trapezoidal_membership() helper (same fuzzy
    envelope shape already used by `normalize_depth`), per Kane's explicit
    recommendation, rather than inventing a new membership function.

    Land / non-finite input is preserved as NaN (chlorophyll has no "land"
    concept of its own, but a non-finite reading -- e.g. a cloud-masked
    satellite pixel -- should stay distinguishable from a real 0.0-scoring
    "barren" measurement).
    """
    values = chl.values.astype("float64")
    finite = np.isfinite(values)

    score = _trapezoidal_membership(values, ramp_min, ideal_min, ideal_max, ramp_max)
    score[~finite] = np.nan

    result = chl.copy(data=score)
    result.name = "chl_band_score"
    return result
