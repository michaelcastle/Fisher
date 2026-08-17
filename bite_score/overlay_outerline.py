"""
Spatial scoring functions + Weighted Linear Combination (WLC) overlay for
the "Outerline Method" (v3) Yellowfin Environmental Hotspot Score.

Core principle (see config.py's Outerline section header comment and the
full spec this implements): reward CO-LOCATION / INTERSECTION of multiple
favourable oceanographic features (thermal fronts, current convergence,
EAC boundary, FSLE ridges, SLA gradients, upwelling/downwelling
transitions) rather than the single most extreme value of any one
feature. This is a HABITAT SUITABILITY score, not a probability of
encountering/catching fish -- never described as the latter anywhere in
this codebase's output/UI text.

NEW, SEPARATE module. Reuses several already-validated, generic
functions UNMODIFIED rather than duplicating their logic:
  - `processing.py::spatial_gradient_magnitude` / `current_velocity_magnitude`
    / `velocity_edge_intensity`
  - `normalization.py::robust_minmax_normalize`
  - `structure_layers.py::_lat_lon_names` / `_cell_size_metres` /
    `compute_relative_vorticity`
  - `eac_axis.py::find_eac_axis_longitude`
  - `overlay_lenigas.py::compute_signed_distance_from_eac_axis_km` (a
    generic signed-distance-from-EAC-axis utility, not Lenigas-specific
    scoring logic)
  - `overlay.py::align_to_reference` (generic reprojection helper)

Does not modify any of those modules; v1/v2/Lenigas/GT scoring and output
are completely untouched.
"""
import logging
from typing import Dict, List, Tuple

import numpy as np
import xarray as xr

from . import config
from .eac_axis import find_eac_axis_longitude
from .normalization import robust_minmax_normalize
from .overlay import align_to_reference
from .overlay_lenigas import compute_signed_distance_from_eac_axis_km
from .processing import current_velocity_magnitude, spatial_gradient_magnitude, velocity_edge_intensity
from .structure_layers import _cell_size_metres, _lat_lon_names, compute_relative_vorticity

logger = logging.getLogger(__name__)


# --- Section 3: EAC boundary -----------------------------------------------
def score_eac_boundary_outerline(
    uo: xr.DataArray,
    vo: xr.DataArray,
    reference: xr.DataArray,
    offset_km: float = config.EAC_BOUNDARY_OFFSET_KM_OUTERLINE,
    sigma_km: float = config.EAC_BOUNDARY_SIGMA_KM_OUTERLINE,
) -> xr.DataArray:
    """
    Score proximity to the EAC's OUTER BOUNDARY/EDGE (a Gaussian bump
    centred `offset_km` east of the traced core-jet axis), NOT the point
    of strongest flow (the axis itself, x_km=0) and not open water far
    from any EAC influence. `reference` supplies the alignment grid
    (pass e.g. bathymetry-suitability, already NaN over land).
    """
    speed = current_velocity_magnitude(uo, vo)
    axis_lon = find_eac_axis_longitude(speed)
    x_km = compute_signed_distance_from_eac_axis_km(reference, axis_lon)

    values = x_km.values.astype("float64")
    score = np.exp(-((values - offset_km) ** 2) / (2.0 * sigma_km**2))
    score[~np.isfinite(values)] = np.nan

    result = x_km.copy(data=score)
    result.name = "eac_boundary_score_outerline"
    return result


# --- Section 4: current convergence -----------------------------------------
def _current_divergence(uo: xr.DataArray, vo: xr.DataArray) -> xr.DataArray:
    """
    Horizontal divergence div = du/dx + dv/dy (units: 1/s) on a lat/lon
    grid. Same central-difference + real-metre-spacing technique as
    `structure_layers.py::compute_relative_vorticity` (reused verbatim,
    just a different combination of the same partial derivatives) --
    NEGATIVE divergence marks convergence (net inflow), where drifting
    plankton/baitfish concentrate.
    """
    lat_name, lon_name = _lat_lon_names(uo)
    u = uo.squeeze().astype("float64").sortby(lat_name).sortby(lon_name)
    v = vo.squeeze().astype("float64").sortby(lat_name).sortby(lon_name)

    dy, dx = _cell_size_metres(u, lat_name, lon_name)
    lat_axis = u.dims.index(lat_name)
    lon_axis = u.dims.index(lon_name)

    du_dx = np.gradient(u.values, axis=lon_axis) / dx
    dv_dy = np.gradient(v.values, axis=lat_axis) / dy

    divergence = du_dx + dv_dy
    nan_mask = ~np.isfinite(u.values) | ~np.isfinite(v.values)
    divergence[nan_mask] = np.nan

    result = xr.DataArray(divergence, coords=u.coords, dims=u.dims, name="current_divergence")
    return result


def score_current_convergence_outerline(
    uo: xr.DataArray, vo: xr.DataArray, scale: float = config.CURRENT_CONVERGENCE_SCALE_S_OUTERLINE
) -> xr.DataArray:
    """
    Continuous convergence score (Section 4): score = 0.5 - 0.5*tanh(div/scale).
    Negative divergence (convergence) -> 1.0; positive (dispersal) -> 0.0;
    neutral -> 0.5. Same tanh-scaling technique already used by
    `overlay_lenigas.py::score_upwelling_downwelling_lenigas`.
    """
    divergence = _current_divergence(uo, vo)
    values = divergence.values.astype("float64")
    score = 0.5 - 0.5 * np.tanh(values / scale)
    score[~np.isfinite(values)] = np.nan

    result = divergence.copy(data=score)
    result.name = "current_convergence_score_outerline"
    return result


# --- Section 5: current interaction / shear ---------------------------------
def score_current_interaction_outerline(uo: xr.DataArray, vo: xr.DataArray) -> xr.DataArray:
    """
    Current-speed shear/edge score (Section 5): normalized gradient
    magnitude of current speed (reuses `processing.py::velocity_edge_intensity`
    unmodified) -- highlights zones where fast core water meets slower
    surrounding water. A genuinely different structural signal from
    `score_current_convergence_outerline` (divergence SIGN) and from
    `score_eac_boundary_outerline` (position relative to the axis).
    """
    speed = current_velocity_magnitude(uo, vo)
    edges = velocity_edge_intensity(speed)
    score = robust_minmax_normalize(edges)
    score.name = "current_interaction_score_outerline"
    return score


# --- Section 2: SST front ---------------------------------------------------
def score_sst_front_outerline(sst: xr.DataArray) -> xr.DataArray:
    """Sharpest thermal fronts -> 1.0 (Section 2). Reuses the same gradient
    + robust-percentile-normalization technique as v1's sst_gradient."""
    gradient = spatial_gradient_magnitude(sst)
    score = robust_minmax_normalize(gradient)
    score.name = "sst_front_score_outerline"
    return score


# --- Section 6: SLA / SSHA boundary -----------------------------------------
def score_sla_boundary_outerline(zos: xr.DataArray) -> xr.DataArray:
    """Sharpest SLA/SSHA gradients -> 1.0 (Section 6) -- rewards the eddy/
    current EDGE, not the absolute SLA value (which would just re-reward
    the eddy core, the opposite of this model's philosophy)."""
    gradient = spatial_gradient_magnitude(zos)
    score = robust_minmax_normalize(gradient)
    score.name = "sla_boundary_score_outerline"
    return score


# --- Section 7: upwelling/downwelling TRANSITION -----------------------------
def score_upwelling_downwelling_outerline(
    uo: xr.DataArray, vo: xr.DataArray, scale: float = config.UPWELLING_DOWNWELLING_TRANSITION_SCALE_S_OUTERLINE
) -> xr.DataArray:
    """
    Rewards the TRANSITION ZONE between upwelling and downwelling (zeta
    near zero) -- score = 1.0 - |tanh(zeta/scale)|, peaking at the
    zero-crossing/boundary and decaying toward 0.0 deep inside either a
    strongly upwelling or strongly downwelling patch. Deliberately the
    OPPOSITE shape from Lenigas's upwelling score (which rewards one
    vorticity sign outright, see overlay_lenigas.py::score_upwelling_downwelling_lenigas)
    -- follows this model's "reward boundaries, not extremes" principle.
    """
    zeta = compute_relative_vorticity(uo, vo)
    values = zeta.values.astype("float64")
    score = 1.0 - np.abs(np.tanh(values / scale))
    score[~np.isfinite(values)] = np.nan

    result = zeta.copy(data=score)
    result.name = "upwelling_downwelling_score_outerline"
    return result


# --- Section 5 (independent diagnostic): FSLE front --------------------------
def score_fsle_front_outerline(fsle: xr.DataArray) -> xr.DataArray:
    """
    FSLE ridge/front strength -> 1.0 (Section 5). FSLE (units 1/day) is
    already a front-intensity diagnostic by construction (see fsle.py) --
    simply robust-percentile-normalized here, same treatment as every
    other gradient-style factor.
    """
    score = robust_minmax_normalize(fsle)
    score.name = "fsle_front_score_outerline"
    return score


# --- Section 9: bait concentration proxy ------------------------------------
def score_bait_proxy_outerline(
    chl: xr.DataArray,
    sst_front_score: xr.DataArray,
    current_convergence_score: xr.DataArray,
    fsle_front_score: xr.DataArray = None,
) -> xr.DataArray:
    """
    Composite bait-concentration proxy (Section 9): a band-pass
    chlorophyll suitability score (favours moderate "green-on-blue-edge"
    water, not a bright bloom or gin-clear open ocean) blended with the
    mean of the already-computed structural aggregation signals (SST
    front, current convergence, and FSLE front when available) --
    baitfish concentrate where productive water coincides with physical
    aggregating structure, not from chlorophyll alone.

    All three/four inputs are expected already reprojected onto the same
    grid (see `weighted_overlay_outerline`, which aligns everything
    before calling this).
    """
    chl_values = chl.values.astype("float64")
    finite = np.isfinite(chl_values)
    safe = np.where(finite, chl_values, config.BAIT_PROXY_CHL_RAMP_MIN_OUTERLINE)

    ramp_min = config.BAIT_PROXY_CHL_RAMP_MIN_OUTERLINE
    ideal_min = config.BAIT_PROXY_CHL_IDEAL_MIN_OUTERLINE
    ideal_max = config.BAIT_PROXY_CHL_IDEAL_MAX_OUTERLINE
    ramp_max = config.BAIT_PROXY_CHL_RAMP_MAX_OUTERLINE

    chl_score = np.zeros_like(safe, dtype="float64")
    rising = (safe >= ramp_min) & (safe < ideal_min)
    chl_score[rising] = (safe[rising] - ramp_min) / (ideal_min - ramp_min)
    plateau = (safe >= ideal_min) & (safe <= ideal_max)
    chl_score[plateau] = 1.0
    falling = (safe > ideal_max) & (safe <= ramp_max)
    chl_score[falling] = (ramp_max - safe[falling]) / (ramp_max - ideal_max)
    chl_score = np.clip(chl_score, 0.0, 1.0)
    chl_score[~finite] = np.nan

    structure_layers = [sst_front_score.values, current_convergence_score.values]
    if fsle_front_score is not None:
        structure_layers.append(fsle_front_score.values)
    structure_stack = np.stack(structure_layers, axis=0)
    structure_score = np.nanmean(structure_stack, axis=0)

    weight = config.BAIT_PROXY_CHL_WEIGHT_OUTERLINE
    combined = weight * chl_score + (1.0 - weight) * structure_score
    combined = np.clip(combined, 0.0, 1.0)
    combined[~finite] = np.nan

    result = chl.copy(data=combined)
    result.name = "bait_proxy_score_outerline"
    return result


def weighted_overlay_outerline(
    layer_scores_01: Dict[str, xr.DataArray],
    reference: xr.DataArray,
    weights: Dict[str, float] = None,
) -> Tuple[xr.DataArray, Dict[str, xr.DataArray], xr.DataArray]:
    """
    Combine the Outerline model's normalized (0-1) layers into a final
    0-100 "Yellowfin Environmental Hotspot Score" raster.

    `layer_scores_01` must be keyed exactly like `config.WEIGHTS_OUTERLINE`
    (a subset is fine -- e.g. `fsle_front` and/or `wind_visibility` may be
    legitimately absent for a given date; their weight is proportionally
    redistributed across the remaining present components, same
    "proportional-rescale" technique documented throughout config.py).
    `season` may be passed as either a scalar float or a 0-1 DataArray.

    Mechanism (see config.py's Outerline section for full rationale):
      1. All spatial layers are reprojected onto `reference`'s grid via
         `align_to_reference` (bilinear).
      2. combined_linear = sum(weight_i * layer_i) over present components.
      3. feature_count = per-pixel count of `config.CONVERGENCE_COUNT_COMPONENTS_OUTERLINE`
         members scoring >= `config.FEATURE_PRESENCE_THRESHOLD_OUTERLINE`
         (out of 100) -- this is what rewards genuine INTERSECTIONS of
         favourable features (Section 16), not merely a high weighted sum.
      4. convergence_multiplier = the highest-matching step in
         `config.CONVERGENCE_MULTIPLIER_STEPS_OUTERLINE` for that pixel's
         feature_count.
      5. final = clip(100 * combined_linear * convergence_multiplier, 0, 100).

    Returns (hotspot_score, layer_scores_0_100, feature_count) -- the
    caller (pipeline_outerline.py) applies the moon-phase multiplier
    afterwards, same "final scalar multiplier applied after WLC" pattern
    used by every other model in this codebase.
    """
    if weights is None:
        weights = config.WEIGHTS_OUTERLINE

    present_keys = [k for k in weights if k in layer_scores_01]
    missing = sorted(set(weights) - set(present_keys))
    if missing:
        logger.info("Outerline: components unavailable today, weights redistributed: %s", missing)

    present_weight_sum = sum(weights[k] for k in present_keys)
    if present_weight_sum <= 0:
        raise ValueError("No Outerline components available to score with")
    active_weights = {k: weights[k] / present_weight_sum for k in present_keys}

    # `season` may be a bare scalar (no spatial variation) -- broadcast it
    # onto `reference`'s grid before alignment so align_to_reference always
    # receives real DataArrays.
    prepared = dict(layer_scores_01)
    if "season" in prepared and not isinstance(prepared["season"], xr.DataArray):
        season_value = float(prepared["season"])
        prepared["season"] = xr.full_like(reference, season_value, dtype="float64")

    ordered_keys = present_keys
    ref, aligned = align_to_reference(reference, *(prepared[k] for k in ordered_keys))
    aligned_by_key = dict(zip(ordered_keys, aligned))

    land_mask = ref.notnull()

    combined = xr.zeros_like(ref, dtype="float64")
    for key in ordered_keys:
        combined = combined + active_weights[key] * aligned_by_key[key].fillna(0)

    def _scaled(layer: xr.DataArray, name: str) -> xr.DataArray:
        out = (layer * 100.0).clip(min=0, max=100).where(land_mask)
        out.name = name
        return out

    layer_scores_0_100 = {key: _scaled(aligned_by_key[key], f"{key}_score_outerline") for key in ordered_keys}

    # Feature-convergence count: only over the components explicitly
    # designated for this purpose (config.CONVERGENCE_COUNT_COMPONENTS_OUTERLINE),
    # each compared to FEATURE_PRESENCE_THRESHOLD_OUTERLINE independently.
    count_keys = [k for k in config.CONVERGENCE_COUNT_COMPONENTS_OUTERLINE if k in layer_scores_0_100]
    if count_keys:
        stack = np.stack([layer_scores_0_100[k].values for k in count_keys], axis=0)
        present_mask = np.isfinite(stack)
        favourable = present_mask & (stack >= config.FEATURE_PRESENCE_THRESHOLD_OUTERLINE)
        feature_count_values = favourable.sum(axis=0).astype("float64")
    else:
        feature_count_values = np.zeros(ref.shape, dtype="float64")

    steps = sorted(config.CONVERGENCE_MULTIPLIER_STEPS_OUTERLINE)
    multiplier_values = np.full(ref.shape, steps[0][1], dtype="float64")
    for min_count, multiplier in steps:
        multiplier_values = np.where(feature_count_values >= min_count, multiplier, multiplier_values)

    hotspot_score = (combined.values * 100.0) * multiplier_values
    hotspot_score = np.clip(hotspot_score, 0.0, 100.0)
    hotspot_score = np.where(land_mask.values, hotspot_score, np.nan)

    hotspot_da = ref.copy(data=hotspot_score)
    hotspot_da.name = "hotspot_score_outerline"
    hotspot_da.attrs["description"] = "Yellowfin Environmental Hotspot Score - Outerline Method (0-100)"
    hotspot_da.attrs["weights"] = str(active_weights)

    feature_count_da = ref.copy(data=np.where(land_mask.values, feature_count_values, np.nan))
    feature_count_da.name = "feature_convergence_count_outerline"

    layer_scores_0_100["feature_convergence_count"] = feature_count_da

    return hotspot_da, layer_scores_0_100, feature_count_da


def explain_score_outerline(component_values_0_100: Dict[str, float], feature_count: float) -> str:
    """
    Build a plain-English explanation string (Section 18) from a single
    pixel's already-sampled component values (out of 100), e.g.:

        "High score because suitable SST overlaps a strong SST front,
        an FSLE ocean-front boundary and current convergence on the
        outer boundary of the EAC. 4 favourable features co-locate here
        (convergence multiplier 1.05x)."

    `component_values_0_100` should be keyed like
    `config.CONVERGENCE_COUNT_COMPONENTS_OUTERLINE` (a subset is fine --
    components unavailable for this date are simply omitted from the
    explanation, never guessed at).
    """
    threshold = config.FEATURE_PRESENCE_THRESHOLD_OUTERLINE
    present_phrases = [
        config.EXPLANATION_PHRASES_OUTERLINE[key]
        for key in config.CONVERGENCE_COUNT_COMPONENTS_OUTERLINE
        if key in component_values_0_100
        and component_values_0_100[key] is not None
        and component_values_0_100[key] >= threshold
    ]

    steps = sorted(config.CONVERGENCE_MULTIPLIER_STEPS_OUTERLINE)
    multiplier = steps[0][1]
    for min_count, step_multiplier in steps:
        if feature_count >= min_count:
            multiplier = step_multiplier

    if not present_phrases:
        return (
            "Low-to-moderate score: no individual factor here reaches the "
            f"favourable threshold ({threshold:.0f}/100) at this location today."
        )

    if len(present_phrases) == 1:
        feature_clause = present_phrases[0]
    else:
        feature_clause = ", ".join(present_phrases[:-1]) + " and " + present_phrases[-1]

    return (
        f"Elevated score because this location has {feature_clause}. "
        f"{int(feature_count)} favourable feature(s) co-locate here "
        f"(convergence multiplier {multiplier:.2f}x)."
    )
