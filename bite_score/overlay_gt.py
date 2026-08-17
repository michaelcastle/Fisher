"""
Weighted overlay, moon-phase multiplier, and seasonal multiplier for the
Giant Trevally (GT) bite-score model.

The WLC is the same structure as overlay_lenigas.py:
  1. Align all factor rasters to the bathymetry reference grid
  2. weighted_overlay_gt() → WLC, land-mask, clip to [0, 100]
  3. apply_moon_phase_multiplier_gt() → GT-specific asymmetric lunar model
  4. apply_seasonal_multiplier_gt() → GT seasonal calendar

GT moon model (OPPOSITE direction to YFT/v1/v2 and partially different from
Lenigas):
  - GT are LOW-LIGHT AMBUSH predators; new moon (dark) = best conditions
  - Full moon = worst (fish are cautious in bright light)
  - "First couple of days after the new moon" = best (phase_age_days 1-2)
  - "Last 2 days before the full moon" = good (phase_age_days 12-13)
  - Full moon itself (phase_age_days ~14) = bad

This is fundamentally different from Lenigas (which peaks 3 days before full
moon) and v1/v2 (which use illumination fraction with a monotone inverse).
"""
import logging

import numpy as np
import xarray as xr

from . import config
from .overlay import align_to_reference

logger = logging.getLogger(__name__)


def weighted_overlay_gt(
    sst_score: xr.DataArray,
    upwelling_score: xr.DataArray,
    depth_score: xr.DataArray,
    eac_edge_score: xr.DataArray,
    current_gradient_score: xr.DataArray,
    structure_score: xr.DataArray,
    moon_phase_score: xr.DataArray,
    north_wind_score: xr.DataArray | None = None,
    weights: dict | None = None,
) -> tuple[xr.DataArray, dict]:
    """
    Weighted Linear Combination (WLC) of GT scoring factors.

    Inputs:
      sst_score             [0, 1] DataArray (normalize_sst_gt output)
      upwelling_score       [0, 100] DataArray (score_upwelling_gt output)
      depth_score           [0, 1] DataArray (normalize_depth_gt output)
      eac_edge_score        [0, 100] DataArray (score_eac_edge_gt output)
      current_gradient_score [0, 100] DataArray (score_current_gradient_gt output)
      structure_score       [0, 100] DataArray (score_depth_structure_gt output)
      moon_phase_score      [0, 100] DataArray (score_moon_phase_gt output)
      north_wind_score      [0, 100] DataArray or None (score_north_wind_gt output,
                            may be unavailable due to ASCAT lag / NaN coverage)
      weights               Optional override dict; defaults to config.LAYER_WEIGHTS_GT

    When north_wind_score is None, its weight is proportionally redistributed
    across the remaining factors.

    Returns:
      (bite_score, layer_scores)
        bite_score:   [0, 100] xr.DataArray on the depth grid
        layer_scores: dict of {key: xr.DataArray [0, 100]} for each WLC layer
    """
    if weights is None:
        weights = config.LAYER_WEIGHTS_GT.copy()
    else:
        weights = dict(weights)

    # --- Handle optional north-wind layer -----------------------------------
    if north_wind_score is None:
        logger.warning(
            "GT: north_wind_score unavailable -- redistributing its weight (%s) proportionally",
            weights.get("north_wind_gt", 0.0),
        )
        missing_w = weights.pop("north_wind_gt", 0.0)
        total_remaining = sum(weights.values())
        if total_remaining > 0 and missing_w > 0:
            for k in list(weights):
                weights[k] += weights[k] / total_remaining * missing_w

    # --- Scale [0,1] inputs to [0,100] before alignment --------------------
    sst_100 = sst_score * 100.0
    depth_100 = depth_score * 100.0

    # --- Align all layers to the EAC-edge reference grid ------------------
    others = [sst_100, upwelling_score, depth_100, current_gradient_score,
               structure_score, moon_phase_score]
    if north_wind_score is not None:
        others.append(north_wind_score)

    ref, aligned_list = align_to_reference(eac_edge_score, *others)

    sst_aligned        = aligned_list[0]
    upwelling_aligned  = aligned_list[1]
    depth_aligned      = aligned_list[2]
    grad_aligned       = aligned_list[3]
    structure_aligned  = aligned_list[4]
    moon_aligned       = aligned_list[5]
    wind_aligned       = aligned_list[6] if north_wind_score is not None else None

    # --- WLC ----------------------------------------------------------------
    land_mask = ref.notnull()

    combined = (
        weights["eac_edge_gt"]         * ref.fillna(0)
        + weights["sst_gt"]            * sst_aligned.fillna(0)
        + weights["upwelling_gt"]      * upwelling_aligned.fillna(0)
        + weights["depth_gt"]          * depth_aligned.fillna(0)
        + weights["current_gradient_gt"] * grad_aligned.fillna(0)
        + weights["structure_gt"]      * structure_aligned.fillna(0)
        + weights["moon_phase_gt"]     * moon_aligned.fillna(0)
    )
    if wind_aligned is not None:
        combined = combined + weights.get("north_wind_gt", 0.0) * wind_aligned.fillna(0)

    bite_score = combined.clip(min=0, max=100).where(land_mask)
    bite_score.name = "bite_score_gt"
    bite_score.attrs["description"] = "Giant Trevally Bite Probability Score (0-100)"
    bite_score.attrs["weights"] = str(weights)

    # --- Per-layer output (100-scale, land-masked) --------------------------
    def _masked(layer: xr.DataArray, name: str) -> xr.DataArray:
        out = layer.clip(min=0, max=100).where(land_mask)
        out.name = name
        return out

    layer_scores: dict[str, xr.DataArray] = {
        "eac_edge_gt":          _masked(ref, "eac_edge_gt"),
        "sst_gt":               _masked(sst_aligned, "sst_gt"),
        "upwelling_gt":         _masked(upwelling_aligned, "upwelling_gt"),
        "depth_gt":             _masked(depth_aligned, "depth_gt"),
        "current_gradient_gt":  _masked(grad_aligned, "current_gradient_gt"),
        "structure_gt":         _masked(structure_aligned, "structure_gt"),
        "moon_phase_gt":        _masked(moon_aligned, "moon_phase_gt"),
    }
    if wind_aligned is not None:
        layer_scores["north_wind_gt"] = _masked(wind_aligned, "north_wind_gt")

    return bite_score, layer_scores


def apply_moon_phase_multiplier_gt(
    bite_score: xr.DataArray,
    phase_age_days: float,
    anchors: list | None = None,
    mult_min: float = config.MOON_MULTIPLIER_MIN_GT,
    mult_max: float = config.MOON_MULTIPLIER_MAX_GT,
) -> xr.DataArray:
    """
    GT-specific asymmetric moon-phase multiplier.

    GT are low-light ambush predators. The optimal lunar period is the
    darkness around the new moon -- specifically "the first couple of days
    after the new moon" and "the last 2 days before the full moon". The full
    moon itself is the worst time (too bright, fish become cautious).

    Uses moon_phase.py's `phase_age_days` convention:
      0 = new moon (dark)
      7 = first quarter (half lit, waxing)
     14 = full moon (fully lit)
     21 = last quarter (half lit, waning)
     28 = new moon again

    Anchor table (phase_age_days, score 0-100):
      (0,  90) new moon: excellent
      (1, 100) 1 day after new: BEST
      (2,  95) 2 days after new: still excellent
      (7,  55) first quarter: moderate
      (12, 85) 2 days before full: user says "good" -- bright but pre-peak
      (13, 75) day before full: good but fading
      (14, 20) full moon: BAD (too bright)
      (15, 35) 1 day after full: starting to recover
      (21, 55) last quarter: moderate
      (26, 80) approaching new moon: building
      (28, 90) back to new moon: excellent (wraps to 0)

    The 0-100 score is mapped to a multiplier via:
      multiplier = mult_min + (score / 100) * (mult_max - mult_min)
    so score 100 → 1.3x, score 20 (full moon) → ~0.66x, score 0 → 0.5x.

    The modified bite_score is re-clipped to [0, 100].
    """
    if anchors is None:
        anchors = config.MOON_PHASE_ANCHORS_GT

    # Build anchor arrays for piecewise-linear interpolation
    anchor_days = [a[0] for a in anchors]
    anchor_scores = [a[1] for a in anchors]

    # Normalise phase_age_days to [0, 28)
    d = float(phase_age_days) % 28.0

    moon_score = float(np.interp(d, anchor_days, anchor_scores))
    multiplier = mult_min + (moon_score / 100.0) * (mult_max - mult_min)

    logger.info(
        "GT moon phase: phase_age_days=%.1f  moon_score=%.0f  multiplier=%.3f",
        d,
        moon_score,
        multiplier,
    )

    result = np.clip(bite_score.values * multiplier, 0.0, 100.0)
    out = bite_score.copy(data=result)
    out.name = "bite_score_gt"
    return out


def apply_seasonal_multiplier_gt(
    bite_score: xr.DataArray,
    month: int,
    seasonal_table: dict | None = None,
) -> xr.DataArray:
    """
    GT seasonal calendar multiplier.

    GT are present in SE QLD waters year-round but the EAC's warm-water
    incursion (Sep-Nov) is the peak period: warmer water pushes baitfish
    concentrations into the reef edge zones where GT hunt. The off-season
    (Feb-Apr) is the coolest / weakest EAC period.

    Table (see config.SEASONAL_MULTIPLIER_GT):
      Sep-Nov: 1.0   (peak EAC season)
      Dec, Jan: 0.9  (tapering warm season)
      Aug: 0.9       (late winter, EAC building)
      Jul, Jun: 0.8  (winter)
      May: 0.7       (autumn, EAC weakening)
      Feb-Apr: 0.6   (coolest, weakest EAC)

    Returns bite_score re-clipped to [0, 100].
    """
    if seasonal_table is None:
        seasonal_table = config.SEASONAL_MULTIPLIER_GT

    multiplier = seasonal_table.get(month, 1.0)
    logger.info("GT seasonal multiplier: month=%d  multiplier=%.2f", month, multiplier)

    result = np.clip(bite_score.values * multiplier, 0.0, 100.0)
    out = bite_score.copy(data=result)
    out.name = "bite_score_gt"
    return out
