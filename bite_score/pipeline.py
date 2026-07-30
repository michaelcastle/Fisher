"""
Core scoring pipeline: takes already-loaded SST / currents / CHL / depth
xarray objects (regardless of whether they came from Copernicus Marine or
a synthetic demo generator) and runs processing -> normalization -> WLC
overlay, returning the final Bite Score DataArray.

Factored out of main.py so the same logic can be exercised in a demo/test
mode without live Copernicus credentials.
"""
import logging
from typing import Dict, Tuple

import xarray as xr

from .normalization import (
    normalize_chl_gradient,
    normalize_current_edges,
    normalize_depth,
    normalize_mld_gradient,
    normalize_sst_gradient,
    normalize_ssha_gradient,
)
from .overlay import weighted_overlay, weighted_overlay_legacy
from .processing import (
    current_velocity_magnitude,
    spatial_gradient_magnitude,
    velocity_edge_intensity,
)

logger = logging.getLogger(__name__)


def compute_bite_score(
    sst: xr.DataArray,
    uo: xr.DataArray,
    vo: xr.DataArray,
    chl: xr.DataArray,
    ssha: xr.DataArray,
    depth: xr.DataArray,
    mld: xr.DataArray = None,
) -> Tuple[xr.DataArray, Dict[str, xr.DataArray]]:
    """
    Run steps 2-4 of the pipeline (gradients -> normalization -> WLC overlay)
    against pre-loaded 2D (lat, lon) fields and return `(bite_score,
    layer_scores)` -- the combined 0-100 Bite Score plus a dict of the
    individual normalized contributing-factor layers (also 0-100, aligned
    to the same grid), so each factor can be inspected/visualized on its
    own.

    `mld` (mixed layer depth / mlotst, see
    data_ingestion.py::fetch_mld) is optional (default None) since its
    Copernicus fetch degrades gracefully on failure in
    main.py::run_pipeline() (unverified dataset-id assumption) -- see
    overlay.py::weighted_overlay's docstring for how the WLC weights
    rebalance when it's absent.
    """
    # 2. Raster processing & gradients
    sst_gradient = spatial_gradient_magnitude(sst)
    chl_gradient = spatial_gradient_magnitude(chl)
    ssha_gradient = spatial_gradient_magnitude(ssha)
    speed = current_velocity_magnitude(uo, vo)
    current_edges = velocity_edge_intensity(speed)

    # 3. Normalization (0.0 - 1.0)
    sst_score = normalize_sst_gradient(sst_gradient)
    # Chlorophyll gradient can be all-NaN when the final fallback dataset
    # (MODIS Aqua R2022SQ "most recent" granule) has full cloud/QC masking
    # over the AOI for a given date. Degrade gracefully -- drop the chl
    # factor and proportionally reweight the remaining layers, exactly as
    # `overlay.py::weighted_overlay` already does for absent MLD.
    try:
        chl_score = normalize_chl_gradient(chl_gradient)
    except ValueError:
        logger.warning(
            "Chlorophyll gradient has no finite values -- omitting chl factor "
            "from WLC and proportionally reweighting remaining layers"
        )
        chl_score = None
    current_score = normalize_current_edges(current_edges)
    ssha_score = normalize_ssha_gradient(ssha_gradient)
    depth_score = normalize_depth(depth)

    mld_score = None
    if mld is not None:
        mld_gradient = spatial_gradient_magnitude(mld)
        mld_score = normalize_mld_gradient(mld_gradient)

    # 4. Weighted overlay (WLC)
    bite_score, layer_scores = weighted_overlay(
        sst_score, chl_score, current_score, ssha_score, depth_score, mld_score=mld_score
    )
    return bite_score, layer_scores


def compute_bite_score_legacy(
    sst: xr.DataArray,
    uo: xr.DataArray,
    vo: xr.DataArray,
    chl: xr.DataArray,
    depth: xr.DataArray,
) -> xr.DataArray:
    """
    Reproduce the original (pre-Gold-Coast-upgrade) scoring pipeline: no
    SSHA layer, SST as the alignment reference grid, nearest-neighbor
    resampling. Lets the old, lower-resolution overlay be generated
    alongside the current one for direct comparison.
    """
    sst_gradient = spatial_gradient_magnitude(sst)
    chl_gradient = spatial_gradient_magnitude(chl)
    speed = current_velocity_magnitude(uo, vo)
    current_edges = velocity_edge_intensity(speed)

    sst_score = normalize_sst_gradient(sst_gradient)
    chl_score = normalize_chl_gradient(chl_gradient)
    current_score = normalize_current_edges(current_edges)
    depth_score = normalize_depth(depth)

    return weighted_overlay_legacy(sst_score, chl_score, current_score, depth_score)
