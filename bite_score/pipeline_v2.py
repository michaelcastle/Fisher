"""
v2 core scoring pipeline: takes already-loaded SST / currents / CHL / SSHA /
depth xarray objects and runs processing -> v2 normalization -> v2 WLC
overlay -> seasonal multiplier, returning the final Bite Score v2
DataArray.

This is a NEW, SEPARATE module for the v2 bite-score model (see
.squad/decisions/inbox/ripley-seq-v2-scoring-model.md), mirroring
pipeline.py's role/structure for v1. It reuses several pure, already-
validated v1 helpers unmodified (processing.py's gradient/velocity
functions, normalization.py's normalize_current_edges/normalize_depth/
normalize_mld_gradient) but does not modify pipeline.py/normalization.py/
overlay.py themselves; v1's pipeline is completely untouched.
"""
import logging
from typing import Dict, Tuple

import xarray as xr

from .normalization import normalize_current_edges, normalize_depth, normalize_mld_gradient
from .normalization_v2 import normalize_chl_band, normalize_sst_bell_v2
from .overlay_v2 import apply_seasonal_multiplier, weighted_overlay_v2
from .processing import (
    current_velocity_magnitude,
    spatial_gradient_magnitude,
    velocity_edge_intensity,
)
from .structure_layers import compute_eddy_score, compute_relative_vorticity, compute_structure_score

logger = logging.getLogger(__name__)


def compute_bite_score_v2(
    sst: xr.DataArray,
    uo: xr.DataArray,
    vo: xr.DataArray,
    chl: xr.DataArray,
    ssha: xr.DataArray,
    depth: xr.DataArray,
    target_date: str,
    mld: xr.DataArray = None,
) -> Tuple[xr.DataArray, Dict[str, xr.DataArray]]:
    """
    Run the v2 gradients -> normalization -> WLC overlay -> seasonal-
    multiplier chain against pre-loaded 2D (lat, lon) fields and return
    `(bite_score_v2, layer_scores)` -- the combined 0-100 v2 Bite Score
    (already seasonally adjusted) plus a dict of the individual normalized
    contributing-factor layers (also 0-100, aligned to the same grid).

    `depth` should come from `data_ingestion.py::load_bathymetry_v2()`
    (the wider AOI_V2-clipped grid), not v1's `load_bathymetry()`.

    `mld` is optional (default None), same graceful-degradation contract
    as v1's `compute_bite_score` -- see overlay_v2.py::weighted_overlay_v2.
    """
    # Structure score: pure function of bathymetry (shelf-break proximity
    # OR named canyon proximity, see structure_layers.py::compute_structure_score).
    structure_score = compute_structure_score(depth)

    # Eddy score: Southern-Hemisphere warm-core (anticyclonic/counter-
    # clockwise) eddy signature, requiring co-located positive vorticity
    # AND positive SSHA (see structure_layers.py::compute_eddy_score).
    vorticity = compute_relative_vorticity(uo, vo)
    eddy_score = compute_eddy_score(vorticity, ssha)

    # SST: bell-curve absolute-temperature suitability combined with the
    # existing gradient/front score as a weighted average (Kane's
    # correction -- see normalization_v2.py::normalize_sst_bell_v2).
    sst_gradient = spatial_gradient_magnitude(sst)
    sst_bell_score = normalize_sst_bell_v2(sst, sst_gradient)

    # Chlorophyll: optimal-band suitability (see
    # normalization_v2.py::normalize_chl_band).
    chl_band_score = normalize_chl_band(chl)

    # Current velocity: reused unmodified from v1.
    speed = current_velocity_magnitude(uo, vo)
    current_edges = velocity_edge_intensity(speed)
    current_score = normalize_current_edges(current_edges)

    # Depth suitability: reused unmodified from v1 (same envelope, applied
    # to the wider v2 bathymetry grid).
    depth_score = normalize_depth(depth)

    mld_score = None
    if mld is not None:
        mld_gradient = spatial_gradient_magnitude(mld)
        mld_score = normalize_mld_gradient(mld_gradient)

    # v2 WLC overlay
    bite_score, layer_scores = weighted_overlay_v2(
        structure_score, sst_bell_score, chl_band_score, eddy_score, current_score, depth_score, mld_score=mld_score
    )

    # Final seasonal scalar multiplier (mirrors v1's moon-phase multiplier
    # mechanism) -- applied last, after the WLC overlay.
    bite_score = apply_seasonal_multiplier(bite_score, target_date)

    return bite_score, layer_scores
