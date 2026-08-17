"""
Outerline gradients/features -> normalization -> WLC overlay ->
convergence multiplier -> moon-phase-multiplier orchestration for the
"Outerline Method" (v3) Yellowfin Environmental Hotspot Score.

NEW, SEPARATE pipeline module -- see config.py's Outerline section header
comment for the full model rationale. Does not import from or modify
v1/v2/Lenigas/GT pipeline code; their config/output are untouched.
"""
import logging
import os
from typing import Dict, Optional, Tuple

import numpy as np
import rioxarray  # noqa: F401  (registers the .rio accessor)
import xarray as xr

from . import config
from .date_layers import DATE_LAYER_SPECS_OUTERLINE, validate_date_key
from .moon_phase import moon_phase_details
from .normalization_outerline import (
    score_bathymetry_outerline,
    score_season_outerline,
    score_sst_suitability_outerline,
    score_wind_visibility_outerline,
)
from .overlay import align_to_reference, apply_moon_phase_multiplier
from .overlay_outerline import (
    explain_score_outerline,
    score_bait_proxy_outerline,
    score_current_convergence_outerline,
    score_current_interaction_outerline,
    score_eac_boundary_outerline,
    score_fsle_front_outerline,
    score_sla_boundary_outerline,
    score_sst_front_outerline,
    score_upwelling_downwelling_outerline,
    weighted_overlay_outerline,
)

logger = logging.getLogger(__name__)


def compute_hotspot_score_outerline(
    sst: xr.DataArray,
    uo: xr.DataArray,
    vo: xr.DataArray,
    chl: xr.DataArray,
    zos: xr.DataArray,
    depth: xr.DataArray,
    target_date: str,
    fsle: Optional[xr.DataArray] = None,
    wind_speed: Optional[xr.DataArray] = None,
    illumination_fraction: Optional[float] = None,
) -> Tuple[xr.DataArray, Dict[str, xr.DataArray], xr.DataArray]:
    """
    Run the full Outerline gradients -> normalization -> WLC overlay ->
    convergence-multiplier -> moon-phase-multiplier chain against
    pre-loaded 2D (lat, lon) SST / currents / chlorophyll / SSHA /
    bathymetry fields (AOI_OUTERLINE = AOI_V2-clipped) and return
    `(hotspot_score, layer_scores, feature_convergence_count)`.

    `fsle` and `wind_speed` are OPTIONAL (both require data sources that
    can legitimately be unavailable for a given date -- FSLE needs
    forward-forecast days, wind is a lagged ASCAT composite): when
    absent, their WLC weights are proportionally redistributed across the
    remaining present components (see
    `overlay_outerline.py::weighted_overlay_outerline`) rather than
    scoring them as zero/unfavourable.

    `illumination_fraction` is OPTIONAL: if not supplied, it's computed
    internally via `moon_phase.py::moon_phase_details(target_date)` (same
    function every other model already uses), so callers that already
    have the full moon-detail dict for other reasons can pass it through
    instead of triggering a second computation.
    """
    if illumination_fraction is None:
        illumination_fraction = moon_phase_details(target_date)["illumination_fraction"]

    bathymetry_score = score_bathymetry_outerline(depth)

    layers_01: Dict[str, xr.DataArray] = {
        "sst_suitability": score_sst_suitability_outerline(sst),
        "sst_front": score_sst_front_outerline(sst),
        "eac_boundary": score_eac_boundary_outerline(uo, vo, bathymetry_score),
        "current_convergence": score_current_convergence_outerline(uo, vo),
        "current_interaction": score_current_interaction_outerline(uo, vo),
        "sla_boundary": score_sla_boundary_outerline(zos),
        "upwelling_downwelling": score_upwelling_downwelling_outerline(uo, vo),
        "bathymetry": bathymetry_score,
        "season": score_season_outerline(target_date),
    }

    fsle_front_score = None
    if fsle is not None:
        try:
            fsle_front_score = score_fsle_front_outerline(fsle)
            layers_01["fsle_front"] = fsle_front_score
        except Exception:
            logger.warning("Outerline: FSLE front scoring failed; weight redistributed", exc_info=True)

    if wind_speed is not None:
        try:
            layers_01["wind_visibility"] = score_wind_visibility_outerline(wind_speed)
        except Exception:
            logger.warning("Outerline: wind/visibility scoring failed; weight redistributed", exc_info=True)

    # `chl`, the sst_front/current_convergence scores, and (optionally)
    # fsle_front_score each come from a genuinely different native grid
    # (satellite chlorophyll ~833m-4km, MUR SST ~1km, Copernicus currents
    # ~0.083deg, FSLE's own particle-advection grid) -- reproject them all
    # onto `bathymetry_score`'s grid first (same bilinear technique used
    # everywhere else in this codebase) so they can be combined cell-wise
    # without a shape mismatch.
    bait_inputs = [chl, layers_01["sst_front"], layers_01["current_convergence"]]
    if fsle_front_score is not None:
        bait_inputs.append(fsle_front_score)
    _bait_ref, bait_aligned = align_to_reference(bathymetry_score, *bait_inputs)
    chl_aligned, sst_front_aligned, convergence_aligned = bait_aligned[0], bait_aligned[1], bait_aligned[2]
    fsle_aligned = bait_aligned[3] if fsle_front_score is not None else None

    layers_01["bait_proxy"] = score_bait_proxy_outerline(
        chl_aligned, sst_front_aligned, convergence_aligned, fsle_aligned
    )

    hotspot_score, layer_scores, feature_count = weighted_overlay_outerline(layers_01, reference=bathymetry_score)

    hotspot_score = apply_moon_phase_multiplier(
        hotspot_score,
        illumination_fraction,
        multiplier_min=config.MOON_MULTIPLIER_MIN_OUTERLINE,
        multiplier_max=config.MOON_MULTIPLIER_MAX_OUTERLINE,
    )

    return hotspot_score, layer_scores, feature_count


def sample_point_outerline(
    layer_scores: Dict[str, xr.DataArray],
    hotspot_score: xr.DataArray,
    lat: float,
    lon: float,
) -> Dict:
    """
    Sample the hotspot score, every contributing component (0-100), the
    feature-convergence count, and a plain-English explanation string at
    the single nearest grid cell to `(lat, lon)` -- backs both
    validate_outerline.py's historical-event report and (optionally) a
    map "click for details" API endpoint.

    Uses nearest-neighbour selection (`xr.DataArray.sel(..., method="nearest")`)
    -- deliberately not interpolation, since the explanation text must
    describe one real, specific grid cell's actual computed values, not a
    blended/interpolated composite of several cells.
    """
    lat_name, lon_name = ("lat", "lon") if "lat" in hotspot_score.dims else ("latitude", "longitude")

    def _nearest(da: xr.DataArray) -> float:
        sampled = da.sel({lat_name: lat, lon_name: lon}, method="nearest")
        value = float(sampled.values)
        return value if np.isfinite(value) else None

    component_values = {
        key: _nearest(layer) for key, layer in layer_scores.items() if key != "feature_convergence_count"
    }
    feature_count = _nearest(layer_scores["feature_convergence_count"]) or 0.0
    hotspot_value = _nearest(hotspot_score)

    explanation = explain_score_outerline(component_values, feature_count)

    actual_lat = float(hotspot_score.sel({lat_name: lat}, method="nearest")[lat_name].values)
    actual_lon = float(hotspot_score.sel({lon_name: lon}, method="nearest")[lon_name].values)

    return {
        "requested": {"lat": lat, "lon": lon},
        "grid_cell": {"lat": actual_lat, "lon": actual_lon},
        "hotspot_score": hotspot_value,
        "feature_convergence_count": feature_count,
        "components": component_values,
        "explanation": explanation,
    }


def sample_point_outerline_from_date(date: str, lat: float, lon: float) -> Dict:
    """
    Same as `sample_point_outerline` above, but reads directly from that
    date's already-exported GeoTIFFs under
    ``output/history/<date>/outerline/`` (via `date_layers.DATE_LAYER_SPECS_OUTERLINE`)
    instead of requiring in-memory `xr.DataArray`s -- this is what backs
    the map "click for details" API endpoint (webapp.py's
    ``/api/date-layer-outerline/<date>/point``), so a fresh in-memory
    pipeline run is never needed just to answer a click on an
    already-computed day's map.

    Raises `FileNotFoundError` if the Outerline pipeline hasn't been run
    for this date (webapp.py turns that into a 404).
    """
    validate_date_key(date)
    outerline_dir = os.path.join(config.HISTORY_DIR, date, config.OUTERLINE_OUTPUT_SUBDIR)

    hotspot_path = os.path.join(outerline_dir, DATE_LAYER_SPECS_OUTERLINE["hotspot_score_outerline"]["filename"])
    if not os.path.isfile(hotspot_path):
        raise FileNotFoundError(f"No Outerline data for {date!r}")

    def _open(key: str) -> Optional[xr.DataArray]:
        path = os.path.join(outerline_dir, DATE_LAYER_SPECS_OUTERLINE[key]["filename"])
        if not os.path.isfile(path):
            return None
        return rioxarray.open_rasterio(path, masked=True).squeeze()

    hotspot_score = _open("hotspot_score_outerline")
    layer_scores = {
        key: layer
        for key in DATE_LAYER_SPECS_OUTERLINE
        if key != "hotspot_score_outerline" and (layer := _open(key)) is not None
    }

    def _nearest_xy(da: xr.DataArray) -> float:
        sampled = da.sel(x=lon, y=lat, method="nearest")
        value = float(sampled.values)
        return value if np.isfinite(value) else None

    component_values = {key: _nearest_xy(layer) for key, layer in layer_scores.items() if key != "feature_convergence_count"}
    feature_count = (_nearest_xy(layer_scores["feature_convergence_count"]) or 0.0) if "feature_convergence_count" in layer_scores else 0.0
    hotspot_value = _nearest_xy(hotspot_score)

    explanation = explain_score_outerline(component_values, feature_count)

    actual_cell = hotspot_score.sel(x=lon, y=lat, method="nearest")

    return {
        "requested": {"lat": lat, "lon": lon},
        "grid_cell": {"lat": float(actual_cell["y"].values), "lon": float(actual_cell["x"].values)},
        "hotspot_score": hotspot_value,
        "feature_convergence_count": feature_count,
        "components": component_values,
        "explanation": explanation,
    }
