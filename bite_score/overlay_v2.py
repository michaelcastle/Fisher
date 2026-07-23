"""
v2 Weighted Linear Combination (WLC) raster overlay + final seasonal-
multiplier for the SEQ Yellowfin Tuna "v2" bite-score model (structure/
shelf-break scoring, real canyon proximity, bell-curve SST, optimal-band
chlorophyll, vorticity-based eddy detection).

This is a NEW, SEPARATE module for the v2 bite-score model (see
.squad/decisions/inbox/ripley-seq-v2-scoring-model.md). It reuses
overlay.py::align_to_reference unmodified (a pure reprojection helper with
no v1-specific weighting logic), but does not modify overlay.py itself;
v1's `weighted_overlay`/`weighted_overlay_legacy`/`apply_moon_phase_multiplier`
are completely untouched by this module.
"""
import logging
from datetime import datetime
from typing import Dict, Tuple

import numpy as np
import xarray as xr

from . import config
from .overlay import align_to_reference

logger = logging.getLogger(__name__)


def weighted_overlay_v2(
    structure_score: xr.DataArray,
    sst_bell_score: xr.DataArray,
    chl_band_score: xr.DataArray,
    eddy_score: xr.DataArray,
    current_score: xr.DataArray,
    depth_score: xr.DataArray,
    mld_score: xr.DataArray = None,
    weights: Dict[str, float] = config.LAYER_WEIGHTS_V2,
) -> Tuple[xr.DataArray, Dict[str, xr.DataArray]]:
    """
    Combine the v2 normalized (0-1) suitability layers into a single
    "Bite Score v2" raster scaled 0-100:

        Bite Score v2 = 100 * (
            0.330 * SST_bell_gradient_score +
            0.235 * CHL_band_score +
            0.141 * Current_velocity_score +
            0.094 * Bathymetry_score +
            0.060 * MLD_gradient_score +
            0.080 * Structure_score +
            0.060 * Eddy_score
        )

    (weights above are `config.LAYER_WEIGHTS_V2`'s defaults -- see that
    module for the full weight-scheme rationale.)

    Bathymetry (v2's wider-coverage grid, see
    data_ingestion.py::load_bathymetry_v2) is used as the alignment
    *reference* grid, exactly mirroring v1's `overlay.py::weighted_overlay`
    (by far the finest-resolution input, preserving shelf-break/canyon
    detail instead of destroying it by downsampling to a coarser physics
    grid).

    `mld_score` is OPTIONAL (default None), mirroring v1's exact graceful-
    degradation pattern: when absent, `weights["mld_gradient"]` is
    proportionally redistributed across the remaining present layers (the
    same technique `weighted_overlay` already uses) so the combined score
    still spans the full 0-100 range instead of being permanently capped
    below 100 by a "missing" weight.

    Returns `(bite_score, layer_scores)` where `layer_scores` is a dict of
    the individual input layers (six, or seven if `mld_score` was given),
    each aligned to the same grid as `bite_score`, land-masked the same
    way, and scaled to 0-100.
    """
    total_weight = sum(weights.values())
    if not np.isclose(total_weight, 1.0):
        raise ValueError(f"v2 layer weights must sum to 1.0, got {total_weight}")

    if mld_score is not None:
        ref, (structure_aligned, sst_aligned, chl_aligned, eddy_aligned, current_aligned, mld_aligned) = (
            align_to_reference(
                depth_score, structure_score, sst_bell_score, chl_band_score, eddy_score, current_score, mld_score
            )
        )
    else:
        ref, (structure_aligned, sst_aligned, chl_aligned, eddy_aligned, current_aligned) = align_to_reference(
            depth_score, structure_score, sst_bell_score, chl_band_score, eddy_score, current_score
        )
        mld_aligned = None

    # Graceful degradation: if MLD wasn't supplied, drop its weight from
    # the denominator and rescale the remaining weights back up to sum to
    # 1.0, preserving their relative balance -- identical mechanism to
    # overlay.py::weighted_overlay.
    mld_weight = weights.get("mld_gradient", 0.0)
    active_weight = total_weight if mld_aligned is not None else (total_weight - mld_weight)
    rescale = 1.0 / active_weight if active_weight > 0 else 1.0

    combined = (
        weights["structure_score"] * structure_aligned.fillna(0)
        + weights["sst_bell"] * sst_aligned.fillna(0)
        + weights["chl_band"] * chl_aligned.fillna(0)
        + weights["eddy_score"] * eddy_aligned.fillna(0)
        + weights["current_velocity"] * current_aligned.fillna(0)
        + weights["bathymetry"] * ref.fillna(0)
    ) * rescale
    if mld_aligned is not None:
        combined = combined + (mld_weight * rescale) * mld_aligned.fillna(0)

    bite_score = (combined * 100.0).clip(min=0, max=100)
    # Land (where the v2 depth reference grid is NaN) has no meaningful
    # bite probability -- mask it out, same reasoning as v1.
    land_mask = ref.notnull()
    bite_score = bite_score.where(land_mask)
    bite_score.name = "bite_score_v2"
    bite_score.attrs["description"] = "Yellowfin Tuna Bite Probability Score v2 (0-100)"
    bite_score.attrs["weights"] = str(weights)

    def _scaled(layer: xr.DataArray, name: str) -> xr.DataArray:
        out = (layer * 100.0).clip(min=0, max=100).where(land_mask)
        out.name = name
        return out

    layer_scores = {
        "structure": _scaled(structure_aligned, "structure_score"),
        "sst_bell": _scaled(sst_aligned, "sst_bell_score"),
        "chl_band": _scaled(chl_aligned, "chl_band_score"),
        "eddy": _scaled(eddy_aligned, "eddy_score"),
        "current": _scaled(current_aligned, "current_score"),
        "bathymetry": _scaled(ref, "bathymetry_score"),
    }
    if mld_aligned is not None:
        layer_scores["mld"] = _scaled(mld_aligned, "mld_score")

    return bite_score, layer_scores


def apply_seasonal_multiplier(bite_score: xr.DataArray, date: str) -> xr.DataArray:
    """
    Scale an already-computed 0-100 v2 Bite Score raster by a uniform
    seasonal multiplier (`config.SEASONAL_MULTIPLIER_V2`, keyed by calendar
    month), re-clipping to 0-100 afterwards -- mirrors
    overlay.py::apply_moon_phase_multiplier's exact mechanism (a final
    scalar multiplier applied AFTER the WLC overlay, NOT chained in
    multiplicatively as another per-pixel raster weight), per Michael's
    explicit decision that season -- like moon phase -- is a single
    day-level scalar with no meaningful per-pixel spatial variation across
    this AOI.

    `date` is a "YYYY-MM-DD" string (same format as the rest of this
    pipeline's `target_date` convention); only its calendar month is used.

    See config.SEASONAL_MULTIPLIER_V2 for the full Sep-Nov/Dec-Jan/Feb-Apr/
    May-Aug multiplier schedule and rationale.
    """
    dt = datetime.strptime(date, "%Y-%m-%d")
    multiplier = config.SEASONAL_MULTIPLIER_V2[dt.month]

    scaled = (bite_score * multiplier).clip(min=0, max=100)
    scaled.name = bite_score.name
    scaled.attrs = dict(bite_score.attrs)
    scaled.attrs["seasonal_multiplier"] = multiplier
    scaled.attrs["seasonal_multiplier_month"] = dt.month
    return scaled
