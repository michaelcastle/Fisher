"""
Weighted Linear Combination (WLC) raster overlay + final seasonal/moon-
phase multipliers for the "Lenigas" bite-score model, plus the two
EAC-relative scoring functions (axis position, convergence) that depend
on Ash's `eac_axis.py` primitives.

This is a NEW, SEPARATE module for the Lenigas scoring model (see
.squad/decisions/inbox/kane-lenigas-scoring-spec.md). It reuses several
pure, already-validated functions unmodified rather than duplicating
their logic:
  - `overlay.py::align_to_reference` (generic reprojection helper, no
    v1-specific weighting logic).
  - `structure_layers.py::_lat_lon_names` / `point_gaussian_proximity_score`
    (generic dim-name detection / Gaussian point-proximity scoring,
    already used for v2's named-canyon proximity).
  - `eac_axis.py::find_eac_axis_longitude` (Ash's EAC core-jet axis
    tracer).

Does not modify overlay.py/structure_layers.py/eac_axis.py themselves;
v1/v2 scoring and Ash's Lenigas modules are completely untouched by this
module.
"""
import logging
from datetime import datetime
from typing import Dict, List, Tuple

import numpy as np
import xarray as xr

from . import config
from .overlay import align_to_reference
from .structure_layers import _lat_lon_names, point_gaussian_proximity_score

logger = logging.getLogger(__name__)

METRES_PER_DEGREE_LAT = 111_320.0


def score_upwelling_downwelling_lenigas(
    zeta: xr.DataArray, scale: float = config.VORTICITY_SCALE_LENIGAS_S
) -> xr.DataArray:
    """
    Continuous, magnitude-scaled vorticity-sign score (Kane's spec, item
    5): score = 0.5 - 0.5*tanh(zeta / scale) on a [0, 1] scale (the
    combined WLC overlay below rescales every layer to 0-100 the same
    way v1/v2 already do).

    Negative zeta (clockwise / SH-cyclonic / upwelling, per
    structure_layers.py::compute_relative_vorticity's verified sign
    convention) -> score -> 1.0 (favorable). Positive zeta (counter-
    clockwise / SH-anticyclonic / downwelling) -> score -> 0.0
    (unfavorable). zeta=0 (neutral) -> score=0.5.

    `zeta` should come directly from
    `structure_layers.py::compute_relative_vorticity` (reused unmodified,
    not duplicated) -- this function only classifies its already-computed
    output, same division of responsibility as Ash's
    `eac_axis.py::classify_upwelling_downwelling` (which this function
    supersedes for Lenigas scoring purposes with a continuous version, per
    Kane's spec preferring magnitude-scaling over a flat 3-tier label
    when a continuous zeta is available).
    """
    values = zeta.values.astype("float64")
    finite = np.isfinite(values)

    score = 0.5 - 0.5 * np.tanh(values / scale)
    score[~finite] = np.nan

    result = zeta.copy(data=score)
    result.name = "upwelling_downwelling_score"
    return result


def compute_signed_distance_from_eac_axis_km(
    reference: xr.DataArray, axis_lon: xr.DataArray
) -> xr.DataArray:
    """
    Real per-cell SIGNED distance (km), east(+)/west(-), from the traced
    EAC core-jet axis (`eac_axis.py::find_eac_axis_longitude`'s output),
    computed at each cell's own latitude using the same cos(lat)-
    corrected degrees->km approximation used throughout this codebase
    (e.g. `structure_layers.py::_cell_size_metres`).

    This is a genuinely different (continuous, signed magnitude)
    quantity from `eac_axis.py::classify_east_west_of_axis`'s existing
    +1.0/-1.0 BINARY side classification -- needed here because Kane's
    EAC-axis-position zone table (spec item 7a) requires actual km
    breakpoints (core/slack/fade zones), which a binary side label alone
    cannot express. `axis_lon` is interpolated onto `reference`'s
    latitude if they don't already match, same defensive pattern as
    `classify_east_west_of_axis`.
    """
    lat_name, lon_name = _lat_lon_names(reference)
    squeeze_dims = [d for d in reference.dims if d not in (lat_name, lon_name)]
    data = reference.squeeze(dim=squeeze_dims) if squeeze_dims else reference
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
    lat_rad = np.deg2rad(lat_vals)[:, np.newaxis]

    km_per_deg_lon = (METRES_PER_DEGREE_LAT / 1000.0) * np.cos(lat_rad)
    x_km = (lon_grid - axis_grid) * km_per_deg_lon
    x_km = np.where(np.isnan(axis_grid), np.nan, x_km)
    x_km = np.where(~np.isfinite(data.values), np.nan, x_km)

    result = xr.DataArray(x_km, coords=data.coords, dims=data.dims, name="eac_axis_distance_km")
    return result


def score_eac_axis_position_lenigas(x_km: xr.DataArray) -> xr.DataArray:
    """
    EAC-axis-position zone scoring (Kane's spec, item 7a), on a [0, 1]
    scale (each breakpoint score below is Kane's own 0-100 table value,
    divided by 100 here for consistency with every other Lenigas
    normalization function):

        x_km < 0                 -> 0.30 (west of axis, wrong side)
        0 <= x_km <= 15           -> linear ramp 0.30 -> 0.70 (fast core)
        15 < x_km <= 40           -> 1.00 (slack outer zone, best match)
        40 < x_km <= 80           -> linear decay 1.00 -> 0.50 (fading)
        x_km > 80                 -> 0.50 (far east, neutral)

    Note the deliberate discontinuity at x_km=15 (0.70 -> 1.00) is exactly
    as specified by Kane's table (a real step, not a smoothing artifact).
    """
    values = x_km.values.astype("float64")
    finite = np.isfinite(values)
    score = np.full_like(values, np.nan, dtype="float64")

    west = finite & (values < 0)
    core = finite & (values >= 0) & (values <= config.EAC_AXIS_CORE_MAX_KM)
    slack = finite & (values > config.EAC_AXIS_CORE_MAX_KM) & (values <= config.EAC_AXIS_SLACK_MAX_KM)
    fade = finite & (values > config.EAC_AXIS_SLACK_MAX_KM) & (values <= config.EAC_AXIS_FADE_MAX_KM)
    far = finite & (values > config.EAC_AXIS_FADE_MAX_KM)

    score[west] = config.EAC_AXIS_WEST_SCORE

    core_frac = values[core] / config.EAC_AXIS_CORE_MAX_KM
    score[core] = config.EAC_AXIS_WEST_SCORE + core_frac * (
        config.EAC_AXIS_CORE_SCORE - config.EAC_AXIS_WEST_SCORE
    )

    score[slack] = config.EAC_AXIS_SLACK_SCORE

    fade_frac = (values[fade] - config.EAC_AXIS_SLACK_MAX_KM) / (
        config.EAC_AXIS_FADE_MAX_KM - config.EAC_AXIS_SLACK_MAX_KM
    )
    score[fade] = config.EAC_AXIS_SLACK_SCORE + fade_frac * (
        config.EAC_AXIS_FADE_SCORE - config.EAC_AXIS_SLACK_SCORE
    )

    score[far] = config.EAC_AXIS_FADE_SCORE

    score_01 = score / 100.0
    result = x_km.copy(data=score_01)
    result.name = "eac_axis_position_score"
    return result


def score_eac_convergence_lenigas(
    reference: xr.DataArray,
    convergence_points: List[Tuple[float, float]],
    sigma_km: float = config.STRUCTURE_POINT_SIGMA_KM,
) -> xr.DataArray:
    """
    EAC-convergence Gaussian point-proximity scoring (Kane's spec, item
    7b), on a [0, 1] scale: 1.0 exactly at the nearest detected
    convergence point, decaying smoothly with great-circle distance.
    Reuses `structure_layers.py::point_gaussian_proximity_score` directly
    (already the exact Gaussian-decay formula Kane's spec calls for, and
    already returns a [0, 1] score) -- no new distance-decay math needed.

    `convergence_points` is a list of `(lat, lon)` tuples (see
    `pipeline_lenigas.py::detect_eac_convergence_point` for how these are
    detected -- an honestly-documented v1-of-Lenigas simplification, not
    a validated real-world detector). When EMPTY (a real, expected
    possibility on many days -- convergence points are transient,
    current-direction-dependent features, unlike v2's fixed named-canyon
    coordinates), this returns a flat NEUTRAL 0.5 everywhere `reference`
    is finite (per Kane's explicit non-punitive-default instruction:
    "absence of a detected event on a given day is not evidence the
    location is bad").

    `reference` supplies only the lat/lon coordinates/shape/dims/CRS
    (and, incidentally, its own NaN mask for the neutral-fallback case) --
    pass e.g. the depth-suitability score, which is already NaN over
    land.
    """
    if not convergence_points:
        neutral_value = config.EAC_CONVERGENCE_NEUTRAL_SCORE / 100.0
        values = np.where(np.isfinite(reference.values), neutral_value, np.nan)
        result = reference.copy(data=values)
        result.name = "eac_convergence_score"
        return result

    scores = [
        point_gaussian_proximity_score(reference, lat, lon, sigma_km=sigma_km)
        for lat, lon in convergence_points
    ]
    combined = scores[0]
    for other in scores[1:]:
        combined = xr.DataArray(
            np.fmax(combined.values, other.values), coords=combined.coords, dims=combined.dims
        )
    combined = combined.where(np.isfinite(reference.values))
    combined.name = "eac_convergence_score"
    return combined


def weighted_overlay_lenigas(
    sst_bell_score: xr.DataArray,
    depth_score: xr.DataArray,
    upwelling_downwelling_score: xr.DataArray,
    eac_axis_position_score: xr.DataArray,
    eac_convergence_score: xr.DataArray,
    ssha_hotspot_score: xr.DataArray,
    weights: Dict[str, float] = config.LAYER_WEIGHTS_LENIGAS,
) -> Tuple[xr.DataArray, Dict[str, xr.DataArray]]:
    """
    Combine the six Lenigas normalized (0-1) suitability layers into a
    single "Bite Score Lenigas" raster scaled 0-100:

        Bite Score Lenigas = 100 * (
            0.145 * SST_bell_lenigas_score +
            0.180 * Depth_suitability_lenigas_score +
            0.160 * Upwelling_downwelling_score +
            0.210 * EAC_axis_position_score +
            0.205 * EAC_convergence_score +
            0.100 * SSHA_hotspot_lenigas_score
        )

    Distance-offshore was removed: the AOI already confines all scored
    pixels to offshore fishing grounds. Its freed weight was redistributed
    to the EAC and upwelling factors (see config.LAYER_WEIGHTS_LENIGAS).
    Depth suitability is used as the alignment *reference* grid.
    """
    total_weight = sum(weights.values())
    if not np.isclose(total_weight, 1.0):
        raise ValueError(f"Lenigas layer weights must sum to 1.0, got {total_weight}")

    ref, (
        sst_aligned, upwelling_aligned, axis_aligned, convergence_aligned, ssha_aligned,
    ) = align_to_reference(
        depth_score,
        sst_bell_score,
        upwelling_downwelling_score,
        eac_axis_position_score,
        eac_convergence_score,
        ssha_hotspot_score,
    )

    combined = (
        weights["sst_bell_lenigas"] * sst_aligned.fillna(0)
        + weights["depth_suitability_lenigas"] * ref.fillna(0)
        + weights["upwelling_downwelling"] * upwelling_aligned.fillna(0)
        + weights["eac_axis_position"] * axis_aligned.fillna(0)
        + weights["eac_convergence"] * convergence_aligned.fillna(0)
        + weights["ssha_hotspot_lenigas"] * ssha_aligned.fillna(0)
    )

    bite_score = (combined * 100.0).clip(min=0, max=100)
    # Land (where the depth-suitability reference grid is NaN) has no
    # meaningful bite probability -- mask it out, same reasoning as v1/v2.
    land_mask = ref.notnull()
    bite_score = bite_score.where(land_mask)
    bite_score.name = "bite_score_lenigas"
    bite_score.attrs["description"] = "Yellowfin Tuna Bite Probability Score - Lenigas model (0-100)"
    bite_score.attrs["weights"] = str(weights)

    def _scaled(layer: xr.DataArray, name: str) -> xr.DataArray:
        out = (layer * 100.0).clip(min=0, max=100).where(land_mask)
        out.name = name
        return out

    layer_scores = {
        "sst_bell_lenigas": _scaled(sst_aligned, "sst_bell_lenigas_score"),
        "depth_suitability_lenigas": _scaled(ref, "depth_suitability_lenigas_score"),
        "upwelling_downwelling": _scaled(upwelling_aligned, "upwelling_downwelling_score"),
        "eac_axis_position": _scaled(axis_aligned, "eac_axis_position_score"),
        "eac_convergence": _scaled(convergence_aligned, "eac_convergence_score"),
        "ssha_hotspot_lenigas": _scaled(ssha_aligned, "ssha_hotspot_lenigas_score"),
    }

    return bite_score, layer_scores


def apply_seasonal_multiplier_lenigas(bite_score: xr.DataArray, date: str) -> xr.DataArray:
    """
    Scale an already-computed 0-100 Lenigas Bite Score raster by a
    uniform seasonal multiplier (`config.SEASONAL_MULTIPLIER_LENIGAS`,
    keyed by calendar month), re-clipping to 0-100 afterwards -- mirrors
    `overlay_v2.py::apply_seasonal_multiplier`'s exact mechanism (a final
    scalar multiplier applied AFTER the WLC overlay).

    `date` is a "YYYY-MM-DD" string; only its calendar month is used.
    """
    dt = datetime.strptime(date, "%Y-%m-%d")
    multiplier = config.SEASONAL_MULTIPLIER_LENIGAS[dt.month]

    scaled = (bite_score * multiplier).clip(min=0, max=100)
    scaled.name = bite_score.name
    scaled.attrs = dict(bite_score.attrs)
    scaled.attrs["seasonal_multiplier"] = multiplier
    scaled.attrs["seasonal_multiplier_month"] = dt.month
    return scaled


def apply_moon_phase_multiplier_lenigas(bite_score: xr.DataArray, phase_age_days: float) -> xr.DataArray:
    """
    Scale an already-computed 0-100 Lenigas Bite Score raster by the
    NEW asymmetric signed-days-from-full-moon multiplier (Kane's spec,
    item 6 / Michael's decision #6) -- a genuinely different model from
    the existing illumination-fraction-based
    `overlay.py::apply_moon_phase_multiplier`, applied AFTER the WLC
    overlay and the seasonal multiplier, same final-scalar-multiplier
    mechanism.

    `phase_age_days` is astral's raw 0..27.99 lunar-cycle position (see
    `moon_phase.py::moon_phase_details`'s `phase_age_days`, where full
    moon is exactly 14.0) -- converted here to signed days-from-full-moon
    `d` in [-14, +14), piecewise-linearly interpolated against Kane's
    anchor table (`config.MOON_PHASE_LENIGAS_ANCHORS_D/SCORE`) to get a
    0-100 "moon score", then mapped to a 0.8x-1.2x multiplier via:

        multiplier = MOON_MULTIPLIER_MIN_LENIGAS + (moon_score/100) *
                     (MOON_MULTIPLIER_MAX_LENIGAS - MOON_MULTIPLIER_MIN_LENIGAS)

    A moon_score of exactly 50 (the anchor table's baseline value) maps
    to an exact 1.0x multiplier -- "far from any described lunar effect"
    is a true neutral no-op, by design (see kane-lenigas-scoring-spec.md
    item 6/8).
    """
    d = (phase_age_days % 28.0) - 14.0
    moon_score = float(
        np.interp(d, config.MOON_PHASE_LENIGAS_ANCHORS_D, config.MOON_PHASE_LENIGAS_ANCHORS_SCORE)
    )
    multiplier = config.MOON_MULTIPLIER_MIN_LENIGAS + (moon_score / 100.0) * (
        config.MOON_MULTIPLIER_MAX_LENIGAS - config.MOON_MULTIPLIER_MIN_LENIGAS
    )

    scaled = (bite_score * multiplier).clip(min=0, max=100)
    scaled.name = bite_score.name
    scaled.attrs = dict(bite_score.attrs)
    scaled.attrs["moon_phase_multiplier_lenigas"] = multiplier
    scaled.attrs["moon_phase_signed_days_from_full_lenigas"] = d
    return scaled
