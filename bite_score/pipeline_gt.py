"""
Giant Trevally (GT) core scoring pipeline: takes already-loaded SST /
currents / bathymetry xarray objects and runs the GT normalization chain ->
GT WLC overlay -> seasonal multiplier -> moon-phase multiplier, returning
the final GT Bite Score DataArray.

GT are an ambush reef predator, NOT a deep-water pelagic species like Yellowfin
Tuna. Their behaviour on the EAC differs fundamentally from YFT:
  - YFT follow the EAC's EASTERN SLACK ZONE (15-40km offshore)
  - GT ambush from the EAC's WESTERN INSHORE EDGE (5-25km inshore of EAC axis)
    where the southward current presses against coastal reef structure

This module mirrors pipeline_lenigas.py's role/structure, providing the
`compute_bite_score_gt()` function called by `main.py::run_pipeline_gt()`.

Data sources reused from Lenigas (no new ERDDAP products needed):
  - AOI: AOI_LENIGAS = AOI_V2 (same coverage, GT reef zone is within it)
  - Bathymetry: load_bathymetry_v2() (same GEBCO_v2 grid)
  - SST: load_erddap_layer_v2("sst", date) with Copernicus fallback
  - Currents: fetch_daily_ocean_data_v2() → uo / vo
  - Wind: fetch_wind_data_lenigas() → wind_direction (ASCAT 7-day composite)
  - Moon: moon_phase_details() (same astronomical calculation)

Does not modify pipeline.py / pipeline_v2.py / pipeline_lenigas.py or any
of the modules they depend on.
"""
import logging
from datetime import datetime
from typing import Dict, Tuple

import xarray as xr

from .eac_axis import find_eac_axis_longitude
from .moon_phase import moon_phase_details
from .normalization_gt import (
    normalize_depth_gt,
    normalize_sst_gt,
    score_current_gradient_gt,
    score_depth_structure_gt,
    score_eac_edge_gt,
    score_moon_phase_gt,
    score_north_wind_gt,
    score_upwelling_gt,
)
from .overlay_gt import (
    apply_seasonal_multiplier_gt,
    weighted_overlay_gt,
)
from .overlay_lenigas import compute_signed_distance_from_eac_axis_km
from .processing import current_velocity_magnitude

logger = logging.getLogger(__name__)


def compute_bite_score_gt(
    sst: xr.DataArray,
    uo: xr.DataArray,
    vo: xr.DataArray,
    depth: xr.DataArray,
    target_date: str,
    wind_direction: xr.DataArray | None = None,
    phase_age_days: float | None = None,
) -> Tuple[xr.DataArray, Dict[str, xr.DataArray]]:
    """
    Run the GT normalization -> WLC overlay -> seasonal-multiplier ->
    moon-phase-multiplier chain against pre-loaded 2D (lat, lon) SST /
    currents / bathymetry fields and return ``(bite_score_gt, layer_scores)``.

    Parameters
    ----------
    sst : xr.DataArray
        Sea surface temperature (°C), AOI_LENIGAS-clipped.
    uo : xr.DataArray
        Eastward current velocity (m/s), AOI_LENIGAS-clipped.
    vo : xr.DataArray
        Northward current velocity (m/s), AOI_LENIGAS-clipped.
    depth : xr.DataArray
        Bathymetry (m, positive = below sea level), AOI_LENIGAS-clipped.
    target_date : str
        ISO date string ``"YYYY-MM-DD"``.
    wind_direction : xr.DataArray or None
        Wind direction in degrees (meteorological, 0=from N, 90=from E),
        from ``data_ingestion_lenigas.py::fetch_wind_data_lenigas()``.
        Defaults to None; when None, ``north_wind_gt`` weight is redistributed
        proportionally to the other 5 factors (graceful degradation).
    phase_age_days : float or None
        Astral moon phase position (0-27.99, 0=new moon, 14=full moon).
        When None, computed internally via ``moon_phase_details(target_date)``.

    Returns
    -------
    (bite_score_gt, layer_scores)
        bite_score_gt : xr.DataArray [0, 100] -- final GT bite score after
            WLC + seasonal + moon multipliers applied.
        layer_scores : dict of {key: xr.DataArray [0, 100]} for the 5 or 6
            WLC layers (north_wind_gt absent when wind_direction is None).
    """
    if phase_age_days is None:
        phase_age_days = moon_phase_details(target_date)["phase_age_days"]

    target_month = datetime.strptime(target_date, "%Y-%m-%d").month

    # --- Factor 1: SST bell curve (peak 26°C, sigma 1.7°C) ----------------
    sst_score = normalize_sst_gt(sst)

    # --- Factor 2: Upwelling (SH-clockwise vorticity = bait-concentrating) -
    upwelling_score = score_upwelling_gt(uo, vo)

    # --- Factor 3: Depth suitability (prime reef zone 15-30m) --------------
    depth_score = normalize_depth_gt(depth)

    # --- Factor 4: EAC pressure edge (GT on WESTERN inshore side of axis) --
    speed = current_velocity_magnitude(uo, vo)
    axis_lon = find_eac_axis_longitude(speed)
    signed_dist_km = compute_signed_distance_from_eac_axis_km(depth_score, axis_lon)
    eac_edge_score = score_eac_edge_gt(signed_dist_km)

    # --- Factor 5: Current speed gradient (feeding-edge ambush spots) ------
    current_gradient_score = score_current_gradient_gt(uo, vo)

    # --- Factor 6: Depth structure (hard edges, reef ledges, drop-offs) ----
    structure_score = score_depth_structure_gt(depth)

    # --- Factor 7: Moon phase (new moon = best, full moon = worst) ---------
    moon_phase_score = score_moon_phase_gt(depth, phase_age_days)

    # --- Factor 8: North wind (optional, may be None) ----------------------
    north_wind_score = None
    if wind_direction is not None:
        north_wind_score = score_north_wind_gt(wind_direction)

    # --- WLC overlay -------------------------------------------------------
    bite_score, layer_scores = weighted_overlay_gt(
        sst_score=sst_score,
        upwelling_score=upwelling_score,
        depth_score=depth_score,
        eac_edge_score=eac_edge_score,
        current_gradient_score=current_gradient_score,
        structure_score=structure_score,
        moon_phase_score=moon_phase_score,
        north_wind_score=north_wind_score,
    )

    # --- Seasonal multiplier (GT season: Sep-Nov peak in SE QLD) -----------
    bite_score = apply_seasonal_multiplier_gt(bite_score, target_month)

    # Moon phase is now a WLC factor (score_moon_phase_gt above), not a
    # post-hoc multiplier -- the separate apply_moon_phase_multiplier_gt
    # call has been removed to avoid double-counting.

    return bite_score, layer_scores
