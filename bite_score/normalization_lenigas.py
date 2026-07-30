"""
Normalization / fuzzy-reclassification functions for the "Lenigas" bite-
score model: SST bell-curve suitability, depth suitability (ramp-plateau-
decline), and distance-offshore-from-coast suitability.

This is a NEW, SEPARATE module for the Lenigas scoring model (see
.squad/decisions/inbox/kane-lenigas-scoring-spec.md /
.squad/decisions/inbox/ripley-lenigas-pipeline.md). It reuses two pure,
already-validated functions unmodified rather than duplicating their
logic:
  - `normalization_v2.py::normalize_sst_bell` (generic Gaussian bell-curve
    shape, already parameterized by peak/sigma -- just called here with
    Lenigas's own constants, no new function needed).
  - `normalization.py::_trapezoidal_membership` (generic 4-point ramp-
    plateau-decline fuzzy membership shape, already used by
    `normalize_depth`/`normalize_chl_band` -- confirmed by reading its
    source that it already implements "ramp up, plateau, ramp down to
    zero", i.e. exactly the "decline after the plateau" shape Kane's
    depth spec needs, not just an indefinite plateau).

Does not modify normalization.py/normalization_v2.py themselves; v1/v2
scoring are completely untouched by this module.
"""
import logging

import numpy as np
import xarray as xr
from scipy.stats import rankdata

from . import config
from .normalization import _trapezoidal_membership, normalize_sst_gradient
from .normalization_v2 import normalize_sst_bell

logger = logging.getLogger(__name__)


def normalize_sst_bell_lenigas(
    sst: xr.DataArray,
    sst_gradient: xr.DataArray = None,
    peak_c: float = config.SST_BELL_PEAK_C_LENIGAS,
    sigma_c: float = config.SST_BELL_SIGMA_C_LENIGAS,
    bell_weight: float = config.SST_BELL_COMPONENT_WEIGHT,
    gradient_weight: float = config.SST_GRADIENT_COMPONENT_WEIGHT,
) -> xr.DataArray:
    """
    SST suitability for the Lenigas model: a 50/50 weighted average of
    the absolute-temperature bell curve (peaks at 1.0 at 24.5C, the
    midpoint of the notes' stated 23-26C band, sigma=1.3C) and the
    thermal-front / gradient-strength score (sharpest SST breaks -> 1.0).

    The gradient component captures the fisherman's own instruction --
    "look for the SST breaks" / "best if it's a break on the eastern side
    of the EAC" -- which is a FRONT signal, not an absolute temperature
    signal. The bell curve captures "best temp 26-23C" (absolute
    suitability). Blending both as a weighted average (not a product)
    matches the same Kane-approved pattern used by v2's
    `normalize_sst_bell_v2`: a textbook-optimal temperature reading with
    only an average gradient still scores reasonably, not zeroed out.

    `sst_gradient` is OPTIONAL (default None) -- when absent the function
    falls back to bell-only behaviour, which keeps existing tests valid
    and allows callers that don't have a pre-computed gradient to degrade
    gracefully. The pipeline (`pipeline_lenigas.py`) always passes a
    real gradient.
    """
    bell_score = normalize_sst_bell(sst, peak_c=peak_c, sigma_c=sigma_c)

    if sst_gradient is None:
        bell_score.name = "sst_bell_lenigas_score"
        return bell_score

    gradient_score = normalize_sst_gradient(sst_gradient)
    bell_aligned, gradient_aligned = xr.align(bell_score, gradient_score, join="inner")

    total_weight = bell_weight + gradient_weight
    combined = (
        bell_weight * bell_aligned.fillna(0) + gradient_weight * gradient_aligned.fillna(0)
    ) / total_weight

    nan_mask = bell_aligned.isnull() & gradient_aligned.isnull()
    combined = combined.where(~nan_mask)
    combined.name = "sst_bell_lenigas_score"
    return combined


def normalize_depth_suitability_lenigas(
    depth: xr.DataArray,
    ramp_min: float = config.DEPTH_LENIGAS_RAMP_MIN_M,
    ideal_min: float = config.DEPTH_LENIGAS_IDEAL_MIN_M,
    ideal_max: float = config.DEPTH_LENIGAS_IDEAL_MAX_M,
    ramp_max: float = config.DEPTH_LENIGAS_RAMP_MAX_M,
) -> xr.DataArray:
    """
    Depth suitability for the Lenigas model: 0.0 at/below 500m, ramping
    up to 1.0 by 1000m, a 1000-1500m plateau, then declining linearly back
    to 0.0 by 3000m (Michael's decision #3 / Kane's spec item 3) -- this
    is a genuinely different shape from v1/v2's depth envelopes, which
    both use an indefinite low-suitability tail rather than an explicit
    decline back toward 0 past a ceiling.

    Reuses `normalization.py::_trapezoidal_membership` directly (already
    implements exactly this ramp-up/plateau/ramp-down shape -- confirmed
    by reading its source before reuse, not assumed).

    Land (depth <= 0) and non-finite depth are set to NaN, same
    convention as `normalization.py::normalize_depth`, so the final
    Lenigas Bite Score can mask out land cleanly.
    """
    values = depth.values.astype("float64")
    score = _trapezoidal_membership(values, ramp_min, ideal_min, ideal_max, ramp_max)
    score[~np.isfinite(values)] = np.nan
    score[values <= 0] = np.nan

    result = depth.copy(data=score)
    result.name = "depth_suitability_lenigas_score"
    return result


def normalize_distance_offshore_lenigas(
    distance_km: xr.DataArray,
    ramp_min: float = config.DISTANCE_OFFSHORE_RAMP_MIN_LENIGAS_KM,
    ideal_min: float = config.DISTANCE_OFFSHORE_IDEAL_MIN_LENIGAS_KM,
    ideal_max: float = config.DISTANCE_OFFSHORE_IDEAL_MAX_LENIGAS_KM,
    ramp_max: float = config.DISTANCE_OFFSHORE_RAMP_MAX_LENIGAS_KM,
) -> xr.DataArray:
    """
    Distance-offshore-from-coast suitability for the Lenigas model:
    0.0 at/below 40km, ramping up to 1.0 by 60km, a 60-80km plateau
    ("usually 60km to 80km" per the notes), then ramping back down to 0.0
    by 100km (Michael's decision #4 / Kane's spec item 4).

    `distance_km` should be a real per-pixel distance-from-coast raster
    (see pipeline_lenigas.py::compute_distance_from_coast_km), not raw
    depth. Reuses `normalization.py::_trapezoidal_membership` directly,
    same 4-point shape as the depth/chl-band factors.

    Land (NaN distance, since distance-from-coast has no meaning on land)
    stays NaN.
    """
    values = distance_km.values.astype("float64")
    finite = np.isfinite(values)

    score = _trapezoidal_membership(values, ramp_min, ideal_min, ideal_max, ramp_max)
    score[~finite] = np.nan

    result = distance_km.copy(data=score)
    result.name = "distance_offshore_score"
    return result


def compute_ssha_anomaly_cm_lenigas(zos: xr.DataArray) -> xr.DataArray:
    """
    Per-date, per-AOI spatial SSHA anomaly (cm) for the Lenigas
    "ssha_hotspot" factor -- re-bases the raw `zos` field (Copernicus sea
    surface height above geoid) by subtracting THAT DATE's own spatial
    mean over the domain, then converts metres to cm (Kane's FINAL
    decision, see .squad/decisions/inbox/kane-lenigas-ssha-final-decision.md,
    exactly matching Ash's already-prototyped method in
    ash-lenigas-ssha-tiers-feasibility.md).

    Re-basing is REQUIRED, not optional: raw `zos` is an ABSOLUTE dynamic-
    topography field (real observed range in this AOI is always +32cm to
    +90cm, never crossing zero), not a zero-centered anomaly -- applying
    percentile/tier scoring directly to raw zos would silently fail
    (every cell always landing in the same tier, 100% of the time; see
    Ash's feasibility doc for the confirming real-data investigation).

    `zos` should be a 2D (lat, lon) array already clipped to AOI_LENIGAS
    (AOI_V2), same convention as this pipeline's other Lenigas inputs.
    Non-finite cells stay NaN.
    """
    values = zos.values.astype("float64")
    finite = np.isfinite(values)

    mean_val = np.nanmean(values) if finite.any() else np.nan
    anomaly_cm = (values - mean_val) * 100.0
    anomaly_cm[~finite] = np.nan

    result = zos.copy(data=anomaly_cm)
    result.name = "ssha_anomaly_cm_lenigas"
    return result


def score_ssha_hotspot_lenigas(anomaly_cm: xr.DataArray, month: int) -> xr.DataArray:
    """
    Percentile-based tiered SSHA-hotspot scoring for the Lenigas model
    (Kane's FINAL decision), on a [0, 1] scale.

    For each date, this AOI's own re-based anomaly distribution
    (`compute_ssha_anomaly_cm_lenigas`'s output) is ranked into a
    nonparametric percentile (0 = that day's most extreme upwelling
    anomaly, 100 = that day's most extreme downwelling anomaly, via
    `scipy.stats.rankdata` -- no assumption of normality, no fixed cm
    magnitude, since real spread varies up to ~2.5x across sampled dates
    per Ash's feasibility data), then piecewise-linearly interpolated
    (`np.interp`, same established pattern as `moon_phase.py`'s signed-day
    anchors) between one of 3 seasonal 0-100 score-anchor tables at the
    percentile breakpoints in `config.SSHA_HOTSPOT_PERCENTILES_LENIGAS`.

    The seasonal table is selected by `month` using the same explicit
    month-tuple lookup pattern already used for
    `config.SEASONAL_MULTIPLIER_LENIGAS`/`overlay_lenigas.py`'s seasonal
    multiplier: Jun-Aug -> winter table, Nov-Dec -> peak-season table,
    everything else (Jan-May, Sep, Oct) -> default table.

    A degenerate domain (n<=1 finite cells for this date) returns all-NaN
    rather than a fabricated fallback score, same graceful-degradation
    convention already used elsewhere in this project (e.g. FSLE/MLD
    unavailable-date handling).
    """
    values = anomaly_cm.values.astype("float64")
    finite = np.isfinite(values)
    pct = np.full(values.shape, np.nan, dtype="float64")

    n = int(finite.sum())
    if n > 1:
        ranks = rankdata(values[finite], method="average")
        pct[finite] = 100.0 * (ranks - 1.0) / (n - 1.0)

    if month in (6, 7, 8):
        anchors_score = config.SSHA_HOTSPOT_SCORES_WINTER_LENIGAS
    elif month in (11, 12):
        anchors_score = config.SSHA_HOTSPOT_SCORES_PEAK_LENIGAS
    else:
        anchors_score = config.SSHA_HOTSPOT_SCORES_DEFAULT_LENIGAS

    score_0_100 = np.interp(pct, config.SSHA_HOTSPOT_PERCENTILES_LENIGAS, anchors_score)
    score_0_100[np.isnan(pct)] = np.nan

    result = anomaly_cm.copy(data=score_0_100 / 100.0)
    result.name = "ssha_hotspot_lenigas_score"
    return result
