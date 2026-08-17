"""
Normalization / fuzzy-reclassification functions for the Giant Trevally (GT)
bite-score model.

GT are an ambush reef predator, NOT a deep-water pelagic species like Yellowfin
Tuna. Their habitat overlaps with EAC-influenced reef edges in SE Queensland,
where the southward-flowing EAC presses against coastal reef structure and
creates a "pressure edge" that concentrates baitfish.

Key differences from YFT/Lenigas normalization:
- Depth: 20-150m reef zones (not 500-3000m offshore pelagic)
- SST: peak at 26°C (warmer EAC water, not the cooler tuna range)
- Upwelling: same vorticity-sign mechanism (SH-clockwise = upwelling = bait)
- EAC edge: GT sit on the WESTERN (inshore) side, not the eastern slack zone
- Wind: northerly wind scores well (concentrates baitfish on reef edges)
- Current gradient: speed-change boundaries = feeding ambush spots

All normalization outputs are scaled to [0, 1] (not 0-100 yet -- weighted_overlay_gt
scales to 0-100). Land cells (depth <= 0) are set to NaN using the same convention
as every other pipeline (see normalization.py::normalize_depth).

Reuses the following without modification:
- normalization_v2.normalize_sst_bell (Gaussian bell curve)
- normalization.py::_trapezoidal_membership (4-point ramp-plateau-decline)
- structure_layers.py::compute_relative_vorticity (vorticity field)
"""
import logging

import numpy as np
import xarray as xr

from . import config
from .normalization import _trapezoidal_membership
from .normalization_v2 import normalize_sst_bell
from .structure_layers import compute_relative_vorticity

logger = logging.getLogger(__name__)


def normalize_sst_gt(
    sst: xr.DataArray,
    peak_c: float = config.SST_BELL_PEAK_C_GT,
    sigma_c: float = config.SST_BELL_SIGMA_C_GT,
) -> xr.DataArray:
    """
    SST suitability for GT: Gaussian bell curve peaking at 26°C (warm EAC
    surface water), sigma 1.7°C so the 24-28°C band brackets the FWHM.

    GT are less temperature-fussy than YFT (they tolerate 18-30°C) but
    prefer warm EAC water -- higher SST = stronger EAC incursion = more
    baitfish concentrating at reef pressure edges.

    Returns a [0,1]-scaled DataArray.
    """
    score = normalize_sst_bell(sst, peak_c=peak_c, sigma_c=sigma_c)
    score.name = "sst_gt_score"
    return score


def normalize_depth_gt(
    depth: xr.DataArray,
    ramp_min: float = config.DEPTH_GT_RAMP_MIN_M,
    ideal_min: float = config.DEPTH_GT_IDEAL_MIN_M,
    ideal_max: float = config.DEPTH_GT_IDEAL_MAX_M,
    ramp_max: float = config.DEPTH_GT_RAMP_MAX_M,
) -> xr.DataArray:
    """
    Depth suitability for GT: ramp up 10→20m, plateau 20-150m (reef + shelf
    edge), then decline to 0 at 400m.

    GT are reef-associated predators, not deep-water pelagics. The 20-150m
    band covers:
      - shallow reef crests and heads (20-60m)
      - shelf-edge drop-offs and ledges (60-150m)
      - upper continental slope ambush points where EAC presses the reef

    Land (depth ≤ 0) and non-finite depth → NaN, same as normalize_depth().
    Returns a [0,1]-scaled DataArray.
    """
    values = depth.values.astype("float64")
    score = _trapezoidal_membership(values, ramp_min, ideal_min, ideal_max, ramp_max)
    score[~np.isfinite(values)] = np.nan
    score[values <= 0] = np.nan

    result = depth.copy(data=score)
    result.name = "depth_gt_score"
    return result


def score_upwelling_gt(
    uo: xr.DataArray,
    vo: xr.DataArray,
    scale_s: float = config.VORTICITY_SCALE_GT_S,
) -> xr.DataArray:
    """
    Upwelling suitability for GT using the same vorticity-sign + tanh
    magnitude-scaling mechanism as Lenigas (which shares the same physical
    basis):

        score = 50 - 50 * tanh(zeta / scale_s)

    In the Southern Hemisphere:
      - zeta < 0 (clockwise / SH-cyclonic) → upwelling → baitfish pushed up
                                           → score → 100 (favorable for GT)
      - zeta > 0 (counter-clockwise / SH-anticyclonic) → downwelling
                                           → score → 0 (unfavorable)
      - zeta = 0 → score = 50 (neutral)

    GT benefit from upwelling-driven baitfish concentration at reef edges,
    exactly as described: "looking for areas which are pushing the water up".

    Returns a [0, 100]-scaled DataArray (pre-scaled to match the WLC inputs
    expected by weighted_overlay_gt before the 0-100 final rescaling pass).
    """
    zeta = compute_relative_vorticity(uo, vo)
    vals = zeta.values.astype("float64")
    score = 50.0 - 50.0 * np.tanh(vals / scale_s)
    score[~np.isfinite(vals)] = np.nan

    result = zeta.copy(data=score)
    result.name = "upwelling_gt_score"
    return result


def score_eac_edge_gt(
    signed_dist_km: xr.DataArray,
    inshore_optimal_km: float = config.GT_EAC_INSHORE_OPTIMAL_KM,
    inshore_max_km: float = config.GT_EAC_INSHORE_MAX_KM,
    axis_score: float = config.GT_EAC_AXIS_SCORE,
    optimal_score: float = config.GT_EAC_OPTIMAL_SCORE,
    far_inshore_score: float = config.GT_EAC_FAR_INSHORE_SCORE,
    offshore_score: float = config.GT_EAC_OFFSHORE_SCORE,
) -> xr.DataArray:
    """
    EAC pressure-edge suitability for GT.

    signed_dist_km is the SIGNED distance (km) from the EAC core-jet axis
    returned by overlay_lenigas.compute_signed_distance_from_eac_axis_km:
      - Negative = west/inshore of the axis (GT territory)
      - Positive = east/offshore of the axis (YFT territory, not GT)

    GT sit on the WESTERN (inshore) edge of the EAC where it presses
    against coastal reef structure, creating the "pressure edge" described
    by the user. The optimal zone is approximately 5-25km inshore of the
    EAC core (the "compression zone" where baitfish are trapped between the
    southward current and the reef).

    Scoring shape:
      d > 0 (east/offshore):           offshore_score (25) - wrong side
      d = 0 (right on axis):           axis_score (60) - moderate, it's the core
      0 > d > -inshore_optimal_km:     linearly interpolate from axis_score up to optimal_score (100)
      -inshore_optimal_km ≥ d > -inshore_max_km: linearly decline from optimal_score to far_inshore_score (35)
      d ≤ -inshore_max_km:             far_inshore_score (35) - EAC influence fading

    Returns a [0, 100]-scaled DataArray.
    """
    d = signed_dist_km.values.astype("float64")
    score = np.full_like(d, np.nan)

    finite = np.isfinite(d)

    # East of axis (wrong side for GT)
    east_mask = finite & (d > 0)
    score[east_mask] = offshore_score

    # Right at axis (moderate)
    at_axis = finite & (d == 0)
    score[at_axis] = axis_score

    # Inshore of axis, within optimal band: linear ramp from axis_score to optimal_score
    in_optimal = finite & (d < 0) & (d >= -inshore_optimal_km)
    t = -d[in_optimal] / inshore_optimal_km  # 0=at_axis ... 1=at_optimal_km
    score[in_optimal] = axis_score + t * (optimal_score - axis_score)

    # Beyond optimal km, declining to far_inshore_score
    in_fade = finite & (d < -inshore_optimal_km) & (d > -inshore_max_km)
    t2 = (-d[in_fade] - inshore_optimal_km) / (inshore_max_km - inshore_optimal_km)
    score[in_fade] = optimal_score - t2 * (optimal_score - far_inshore_score)

    # Far inshore (beyond max): flat floor
    far = finite & (d <= -inshore_max_km)
    score[far] = far_inshore_score

    result = signed_dist_km.copy(data=score)
    result.name = "eac_edge_gt_score"
    return result


def score_current_gradient_gt(
    uo: xr.DataArray,
    vo: xr.DataArray,
    lower_pct: float = config.NORMALIZATION_LOWER_PERCENTILE,
    upper_pct: float = config.NORMALIZATION_UPPER_PERCENTILE,
) -> xr.DataArray:
    """
    Current speed-gradient suitability for GT.

    GT feed along boundaries where the current changes speed -- the "edges"
    where fast EAC flow transitions to slower water are prime ambush points
    for baitfish concentration. This is captured by the spatial gradient
    magnitude of the current speed field.

    Normalised to [0, 100] via robust percentile clipping (same technique
    as normalization.py::robust_minmax_normalize), so extreme isolated
    outlier pixels don't compress the entire distribution towards zero.

    Returns a [0, 100]-scaled DataArray.
    """
    from .processing import current_velocity_magnitude, spatial_gradient_magnitude

    speed = current_velocity_magnitude(uo, vo)
    grad = spatial_gradient_magnitude(speed)

    vals = grad.values.astype("float64")
    finite_vals = vals[np.isfinite(vals)]
    if finite_vals.size == 0:
        result = grad.copy(data=np.zeros_like(vals))
        result.name = "current_gradient_gt_score"
        return result

    lo = np.percentile(finite_vals, lower_pct)
    hi = np.percentile(finite_vals, upper_pct)
    if hi <= lo:
        normed = np.zeros_like(vals)
    else:
        normed = np.clip((vals - lo) / (hi - lo), 0.0, 1.0)
    normed[~np.isfinite(vals)] = np.nan

    score = normed * 100.0
    result = grad.copy(data=score)
    result.name = "current_gradient_gt_score"
    return result


def score_north_wind_gt(wind_direction: xr.DataArray) -> xr.DataArray:
    """
    North wind suitability for GT.

    A northerly wind (from the north, blowing southward) concentrates baitfish
    against reef structures and makes them more accessible to GT. The user
    explicitly states "a north wind is generally favorable for fishing".

    Wind direction convention (meteorological): degrees clockwise from north
    where the wind is COMING FROM:
      0° / 360° = wind from north (northerly) → BEST
      90°        = wind from east              → moderate
      180°       = wind from south             → worst
      270°       = wind from west              → moderate

    Score = max(0, cos(wind_dir_rad))^1.5 * 100
    This gives:
      0°  (north wind) → cos(0) = 1.0 → score 100
      90° (east wind)  → cos(π/2) = 0 → score 0
      270° (west wind) → cos(3π/2) = 0 → score 0
      180° (south wind)→ cos(π) = -1 → clamped to 0

    The 1.5 power sharpens the peak slightly around north without making it
    a hard binary (same principle as the bell-curve/tanh shapes elsewhere
    in this codebase -- real data doesn't have perfectly sharp transitions).

    NaN cells (no wind data, ASCAT masked) propagate as NaN.

    Returns a [0, 100]-scaled DataArray.
    """
    dir_vals = wind_direction.values.astype("float64")
    dir_rad = np.deg2rad(dir_vals)
    cos_dir = np.cos(dir_rad)
    score = np.where(np.isfinite(cos_dir), np.maximum(0.0, cos_dir) ** 1.5 * 100.0, np.nan)

    result = wind_direction.copy(data=score)
    result.name = "north_wind_gt_score"
    return result


def score_depth_structure_gt(
    depth: xr.DataArray,
    scale_m_per_km: float = config.DEPTH_STRUCTURE_GT_SCALE_M_PER_KM,
) -> xr.DataArray:
    """
    Bathymetric structure score for GT: how sharp are the depth edges?

    GT are ambush predators that station themselves on hard structural edges
    (reef ledges, bommies, shelf steps, drop-offs) and wait for baitfish
    to be swept past by the EAC.  The spatial gradient of the depth field
    (|∇depth|) captures this: high values = steep changes in seafloor depth
    = prime GT ambush structure.

    Grid cells are ~0.083° ≈ 9.25 km at this latitude; np.gradient gives
    the slope in metres per grid cell, then converted to m/km.

    Score = 100 × tanh(|gradient_m_per_km| / scale_m_per_km)
    so ~5 m/km → ~0.46 (moderate edge), ~15 m/km → ~0.91 (sharp ledge).
    The scale constant is tuned so typical inshore reef bommies and shelf
    steps score well without saturating on the coarser GEBCO grid.

    Land cells (depth ≤ 0) propagate as NaN.
    Returns a [0, 100]-scaled DataArray.
    """
    vals = depth.values.astype("float64")

    # Gradient in units of metres per grid cell; convert to m/km
    # (GEBCO/AusBathyTopo grid ≈ 0.083° ≈ 9.25 km at ~27°S)
    APPROX_CELL_KM = 9.25
    dy, dx = np.gradient(vals)
    magnitude_m_per_km = np.sqrt(dx**2 + dy**2) / APPROX_CELL_KM

    score = 100.0 * np.tanh(magnitude_m_per_km / scale_m_per_km)
    score[~np.isfinite(vals)] = np.nan
    score[vals <= 0] = np.nan

    result = depth.copy(data=score)
    result.name = "structure_gt_score"
    return result


def score_moon_phase_gt(
    depth_ref: xr.DataArray,
    phase_age_days: float,
    anchors: list | None = None,
) -> xr.DataArray:
    """
    Moon phase suitability for GT as a spatially-uniform scoring layer.

    GT are LOW-LIGHT AMBUSH predators: darkness is their advantage.
    The same anchor table used by apply_moon_phase_multiplier_gt is
    reused here, but the result is a 0-100 score (not a multiplier)
    broadcast to the spatial grid so it can be included in the WLC
    and visualised as a map layer.

    Anchor table (phase_age_days, score 0-100):
      (1,  100) 1 day after new moon: BEST (darkest nights)
      (14,  20) full moon: WORST (bright nights, fish cautious)

    phase_age_days is normalised to [0, 28) before interpolation.

    NaN cells (land) in depth_ref propagate as NaN.
    Returns a [0, 100]-scaled DataArray (spatially uniform over ocean).
    """
    if anchors is None:
        anchors = config.MOON_PHASE_ANCHORS_GT

    anchor_days = [a[0] for a in anchors]
    anchor_scores = [a[1] for a in anchors]
    d = float(phase_age_days) % 28.0
    score_value = float(np.interp(d, anchor_days, anchor_scores))

    logger.info(
        "GT moon phase factor: phase_age_days=%.1f → score=%.0f",
        phase_age_days, score_value,
    )

    ocean_mask = np.isfinite(depth_ref.values) & (depth_ref.values > 0)
    score_arr = np.where(ocean_mask, score_value, np.nan)

    result = depth_ref.copy(data=score_arr)
    result.name = "moon_phase_gt_score"
    return result
