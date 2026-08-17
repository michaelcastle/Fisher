"""
Scalar/simple membership-curve normalizations for the "Outerline Method"
(v3) Yellowfin Environmental Hotspot Score.

NEW, SEPARATE module -- does not import from or modify v1/v2/Lenigas/GT
normalization code; none of their config/output is touched. The genuinely
new *spatial* scoring functions (SST/SLA fronts, EAC boundary, current
convergence/interaction, FSLE, upwelling/downwelling transition, bait
proxy, the WLC overlay itself, and the convergence multiplier) live in
`overlay_outerline.py` instead -- this module only holds the simple
piecewise-linear/scalar membership curves (SST suitability, bathymetry
suitability, season, wind/visibility), following the same
`_trapezoidal_membership`-style convention already used by
`normalization.py`/`normalization_lenigas.py`, but via `np.interp` against
explicit (breakpoint, score) anchor tables since these curves are not
simple trapezoids.

All functions here return values on a [0, 1] scale (never 0-100) --
`overlay_outerline.py::weighted_overlay_outerline` is solely responsible
for scaling the final combined score to 0-100, same division of
responsibility as every other model in this codebase.
"""
import logging
from datetime import datetime

import numpy as np
import xarray as xr

from . import config

logger = logging.getLogger(__name__)


def _piecewise_score(values: np.ndarray, breakpoints: list, scores_0_100: list) -> np.ndarray:
    """
    Piecewise-linear interpolation of `values` against an explicit
    (breakpoint, score) anchor table (`scores_0_100` given out of 100),
    returned on a [0, 1] scale. `np.interp` clamps to the first/last
    anchor score outside the given range (flat extrapolation), which is
    the desired behaviour for both curves this backs (SST suitability,
    bathymetry suitability) -- e.g. water colder than the coldest anchor
    is exactly as unsuitable as the coldest anchor itself, not
    extrapolated further downward.
    """
    finite = np.isfinite(values)
    safe = np.where(finite, values, breakpoints[0])
    scored = np.interp(safe, breakpoints, scores_0_100) / 100.0
    scored = np.where(finite, scored, np.nan)
    return scored


def score_sst_suitability_outerline(sst: xr.DataArray) -> xr.DataArray:
    """
    Broad SST suitability membership curve (Section 1/2 of the Outerline
    spec) -- deliberately gentler/wider than v1/Lenigas/GT's bell curves,
    since this is only an 8% weight here (the sharper `score_sst_front_outerline`
    front factor carries the "boundary" signal instead). See
    `config.SST_SUITABILITY_BREAKPOINTS_C_OUTERLINE` / `..._SCORES_OUTERLINE`.
    """
    values = sst.values.astype("float64")
    score = _piecewise_score(
        values, config.SST_SUITABILITY_BREAKPOINTS_C_OUTERLINE, config.SST_SUITABILITY_SCORES_OUTERLINE
    )
    result = sst.copy(data=score)
    result.name = "sst_suitability_score_outerline"
    return result


def score_bathymetry_outerline(depth: xr.DataArray) -> xr.DataArray:
    """
    Bathymetry as a MODERATE-WEIGHT FILTER only (Section 8): a wide, flat
    "good" plateau from ~200m out through abyssal depths, ramping down
    only in the shallows. See `config.DEPTH_SUITABILITY_BREAKPOINTS_M_OUTERLINE`
    / `..._SCORES_OUTERLINE` and that constant's module-level rationale in
    config.py (validated against the real 11 Oct 2023, ~250m, Point
    Lookout event -- see validate_outerline.py).

    Land (depth <= 0) -> NaN, same convention as normalize_depth() /
    normalize_depth_suitability_lenigas().
    """
    values = depth.values.astype("float64")
    score = _piecewise_score(
        values, config.DEPTH_SUITABILITY_BREAKPOINTS_M_OUTERLINE, config.DEPTH_SUITABILITY_SCORES_OUTERLINE
    )
    score = np.where(values <= 0, np.nan, score)
    result = depth.copy(data=score)
    result.name = "bathymetry_score_outerline"
    return result


def score_season_outerline(target_date: str) -> float:
    """
    Seasonal suitability (Section 10) -- a single scalar [0, 1] value for
    `target_date`'s calendar month (see `config.SEASON_SUITABILITY_OUTERLINE`),
    broadcast uniformly across the AOI by the caller. Deliberately a
    scalar, not a spatial field -- there is no per-cell seasonal signal,
    only a per-date one.
    """
    month = datetime.strptime(target_date, "%Y-%m-%d").month
    return float(config.SEASON_SUITABILITY_OUTERLINE[month])


def score_wind_visibility_outerline(wind_speed: xr.DataArray) -> xr.DataArray:
    """
    Combined wind/visibility score (Sections 11/12), kept as two
    genuinely separate named sub-scores blended together:

      visibility_score: 1.0 at/under a flat calm
      (`config.WIND_VISIBILITY_CALM_MS_OUTERLINE`), decaying linearly to
      0.0 by `config.WIND_VISIBILITY_MAX_MS_OUTERLINE` -- pure
      sighting/spotting conditions.

      ocean_score: a flat neutral baseline
      (`config.WIND_VISIBILITY_OCEAN_BASELINE_OUTERLINE`) -- this
      codebase has no validated mechanism linking a single 10m wind
      snapshot to ocean-scale prey aggregation in this AOI, so this is
      honestly left neutral rather than inventing an unverified
      relationship (see config.py's rationale comment).

    Combined via `config.WIND_VISIBILITY_SPLIT_OUTERLINE` (default 50/50).
    This whole factor is only 1% of the total score.
    """
    speed = wind_speed.values.astype("float64")
    finite = np.isfinite(speed)

    calm = config.WIND_VISIBILITY_CALM_MS_OUTERLINE
    windy = config.WIND_VISIBILITY_MAX_MS_OUTERLINE
    visibility = np.clip(1.0 - (speed - calm) / (windy - calm), 0.0, 1.0)
    visibility[~finite] = np.nan

    ocean = np.where(finite, config.WIND_VISIBILITY_OCEAN_BASELINE_OUTERLINE, np.nan)

    split = config.WIND_VISIBILITY_SPLIT_OUTERLINE
    combined = split * visibility + (1.0 - split) * ocean

    result = wind_speed.copy(data=combined)
    result.name = "wind_visibility_score_outerline"
    return result
