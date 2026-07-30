"""
Weighted Linear Combination (WLC) raster overlay to produce the final
Yellowfin Tuna Bite Probability Score (0-100).
"""
import logging
from typing import Dict, Tuple

import numpy as np
import rioxarray  # noqa: F401  (registers the .rio accessor)
import xarray as xr
from rasterio.enums import Resampling

from . import config

logger = logging.getLogger(__name__)


def _prep_spatial(da: xr.DataArray) -> xr.DataArray:
    """
    Standardize spatial dim names to lat/lon (Copernicus Marine outputs use
    "latitude"/"longitude"; the demo/bathymetry data uses "lat"/"lon"), then
    ensure rioxarray knows the spatial dims/CRS.
    """
    rename_map = {}
    if "latitude" in da.dims:
        rename_map["latitude"] = "lat"
    if "longitude" in da.dims:
        rename_map["longitude"] = "lon"
    if rename_map:
        da = da.rename(rename_map)

    if "lat" in da.dims and "lon" in da.dims:
        da = da.rio.set_spatial_dims(x_dim="lon", y_dim="lat", inplace=False)
    if da.rio.crs is None:
        da = da.rio.write_crs(config.CRS)
    return da


def align_to_reference(
    reference: xr.DataArray,
    *others: xr.DataArray,
    resampling: Resampling = Resampling.bilinear,
) -> Tuple[xr.DataArray, list]:
    """
    Reproject/resample every input layer onto the same grid as `reference`
    using rioxarray, so all layers can be combined cell-by-cell even though
    they originate from datasets with different native resolutions
    (physics ~0.083deg, biogeochemistry ~0.25deg, bathymetry ~15 arcsec).

    Bilinear resampling (rather than the rioxarray default of nearest-
    neighbor) is used so coarser layers are smoothly interpolated onto a
    finer reference grid instead of producing blocky, stair-stepped output.
    """
    ref = _prep_spatial(reference)

    aligned = []
    for layer in others:
        src = _prep_spatial(layer)
        matched = src.rio.reproject_match(ref, resampling=resampling)
        # reproject_match renames spatial dims to x/y; rename back to the
        # reference's original lat/lon dim names so cell-wise arithmetic
        # broadcasts correctly instead of creating extra dimensions.
        rename_map = {}
        if "y" in matched.dims and "lat" in ref.dims:
            rename_map["y"] = "lat"
        if "x" in matched.dims and "lon" in ref.dims:
            rename_map["x"] = "lon"
        if rename_map:
            matched = matched.rename(rename_map)
        matched = matched.assign_coords(lat=ref["lat"], lon=ref["lon"])
        aligned.append(matched)

    return ref, aligned


def weighted_overlay(
    sst_score: xr.DataArray,
    chl_score: xr.DataArray,
    current_score: xr.DataArray,
    ssha_score: xr.DataArray,
    depth_score: xr.DataArray,
    mld_score: xr.DataArray = None,
    weights: Dict[str, float] = config.LAYER_WEIGHTS,
) -> Tuple[xr.DataArray, Dict[str, xr.DataArray]]:
    """
    Combine the normalized (0-1) suitability layers into a single
    "Bite Score" raster scaled 0-100:

        Bite Score = 100 * (
            0.329 * SST_gradient_score +
            0.235 * CHL_gradient_score +
            0.141 * Current_velocity_score +
            0.141 * SSHA_gradient_score +
            0.094 * Bathymetry_score +
            0.060 * MLD_gradient_score
        )

    (weights above are `config.LAYER_WEIGHTS`'s defaults as of Dallas's
    2026-07-22 pilot-weight sign-off -- MLD's weight was revised down
    from Ripley's original 0.12 proposal to a 0.06 pilot weight pending
    dataset-id verification and real-pipeline validation; see that
    module for the full rationale.)

    Bathymetry is used as the alignment *reference* grid (rather than SST)
    because it is by far the finest-resolution input (~15 arcsec / ~450 m,
    vs. ~9 km for physics and ~27 km for biogeochemistry). Aligning onto it
    preserves full bathymetric detail (shelf breaks, canyons) in the final
    output instead of destroying it by downsampling to a coarser grid.

    `mld_score` (mixed-layer-depth gradient/front score -- see
    normalization.py::normalize_mld_gradient) is OPTIONAL (default None)
    because `main.py::run_pipeline()`'s `fetch_mld()` call degrades
    gracefully on failure (the assumed Copernicus dataset id is unverified
    -- see data_ingestion.py::fetch_mld's docstring). When absent,
    `weights["mld_gradient"]` is proportionally redistributed across the
    remaining present layers (the same technique already used to derive
    `config.LAYER_WEIGHTS_LEGACY` from `config.LAYER_WEIGHTS`) so the
    combined score still spans the full 0-100 range instead of being
    permanently capped below 100 by a "missing" weight.

    Returns `(bite_score, layer_scores)` where `layer_scores` is a dict of
    the individual input layers (five, or six if `mld_score` was given),
    each aligned to the same grid as `bite_score`, land-masked the same
    way, and scaled to 0-100 -- so each contributing factor can be
    inspected/visualized on its own (e.g. as separate selectable map
    layers) rather than only seeing the combined result.
    """
    total_weight = sum(weights.values())
    if not np.isclose(total_weight, 1.0):
        raise ValueError(f"Layer weights must sum to 1.0, got {total_weight}")

    # Build the list of optional layers to align, handling both chl and mld
    # being independently absent. align_to_reference accepts *others so any
    # combination works without duplicating the reprojection logic.
    optional_layers = []
    if chl_score is not None:
        optional_layers.append(chl_score)
    if mld_score is not None:
        optional_layers.append(mld_score)

    ref, aligned_all = align_to_reference(
        depth_score, sst_score, current_score, ssha_score, *optional_layers
    )
    sst_aligned, current_aligned, ssha_aligned = aligned_all[0], aligned_all[1], aligned_all[2]
    idx = 3
    if chl_score is not None:
        chl_aligned = aligned_all[idx]; idx += 1
    else:
        chl_aligned = None
    mld_aligned = aligned_all[idx] if mld_score is not None else None

    # Graceful degradation: drop the weight of any absent factor and rescale
    # the remaining weights proportionally so the score still spans 0-100.
    chl_weight = weights.get("chl_gradient", 0.0)
    mld_weight = weights.get("mld_gradient", 0.0)
    absent_weight = (
        (chl_weight if chl_aligned is None else 0.0)
        + (mld_weight if mld_aligned is None else 0.0)
    )
    active_weight = total_weight - absent_weight
    rescale = 1.0 / active_weight if active_weight > 0 else 1.0

    combined = (
        weights["sst_gradient"] * sst_aligned.fillna(0)
        + (weights["chl_gradient"] * chl_aligned.fillna(0) if chl_aligned is not None else 0.0)
        + weights["current_velocity"] * current_aligned.fillna(0)
        + weights["ssha_gradient"] * ssha_aligned.fillna(0)
        + weights["bathymetry"] * ref.fillna(0)
    ) * rescale
    if mld_aligned is not None:
        combined = combined + (mld_weight * rescale) * mld_aligned.fillna(0)

    bite_score = (combined * 100.0).clip(min=0, max=100)
    # Land (where the depth reference grid is NaN) has no meaningful bite
    # probability -- mask it out to NaN in the final output rather than
    # letting it fall through as a spurious "0% chance" water cell, so land
    # renders as fully transparent / traceable as a real coastline outline.
    land_mask = ref.notnull()
    bite_score = bite_score.where(land_mask)
    bite_score.name = "bite_score"
    bite_score.attrs["description"] = "Yellowfin Tuna Bite Probability Score (0-100)"
    bite_score.attrs["weights"] = str(weights)

    def _scaled(layer: xr.DataArray, name: str) -> xr.DataArray:
        out = (layer * 100.0).clip(min=0, max=100).where(land_mask)
        out.name = name
        return out

    layer_scores = {
        "sst": _scaled(sst_aligned, "sst_score"),
        "current": _scaled(current_aligned, "current_score"),
        "ssha": _scaled(ssha_aligned, "ssha_score"),
        "bathymetry": _scaled(ref, "bathymetry_score"),
    }
    if chl_aligned is not None:
        layer_scores["chl"] = _scaled(chl_aligned, "chl_score")
    if mld_aligned is not None:
        layer_scores["mld"] = _scaled(mld_aligned, "mld_score")

    return bite_score, layer_scores


def apply_moon_phase_multiplier(
    bite_score: xr.DataArray,
    illumination_fraction: float,
    multiplier_min: float = config.MOON_MULTIPLIER_MIN,
    multiplier_max: float = config.MOON_MULTIPLIER_MAX,
) -> xr.DataArray:
    """
    Scale an already-computed 0-100 Bite Score raster by a uniform
    moon-phase multiplier, re-clipping to 0-100 afterwards (a dark-moon
    night can push an already-high score above 100 pre-clip).

    Michael Castle (project owner) decided moon phase should be a UNIFORM
    MULTIPLIER on the final score rather than a 6th WLC raster weight,
    since illumination fraction is a single day-level scalar with no
    meaningful spatial variation across this AOI (see
    moon_phase.py::moon_illumination_fraction's docstring) -- unlike every
    WLC factor in `weighted_overlay` above, which is a genuine per-pixel
    raster.

    Bounds (see config.MOON_MULTIPLIER_MIN/MAX, default 0.8-1.2, i.e.
    +-20%): Ripley's judgment call, not yet confirmed by Michael/Kane (see
    .squad/decisions/inbox/ripley-mld-moon-scoring.md). +-20% is large
    enough to meaningfully separate bright-moon vs. dark-moon nights on
    the final 0-100-bounded map, without a full moon ever crushing an
    otherwise-strong front signal to near-zero (0.8x of 100 is still 80),
    or a new moon inflating a weak signal past a believable ceiling (the
    `.clip(min=0, max=100)` below re-bounds it regardless).

    Directionality: per Kane's rationale (recommendation #2 in
    .squad/decisions/inbox/kane-oceanographic-signals.md), moon
    illumination is "a proxy for nocturnal baitfish vertical migration and
    bite-window timing". The established fisheries-science mechanism is
    that baitfish suppress their nocturnal vertical migration toward the
    surface on bright/moonlit nights (higher predation risk from visual
    predators when illuminated), staying deeper and more dispersed --
    meaning LESS concentrated forage is available to pelagic predators
    like tuna. On dark nights (new moon), baitfish migrate to the surface
    more freely, concentrating forage and improving the bite. So HIGHER
    illumination -> LOWER multiplier, and LOWER illumination -> HIGHER
    multiplier (an inverse relationship):

        multiplier = multiplier_max - illumination_fraction * (multiplier_max - multiplier_min)

    illumination_fraction=0.0 (new moon/dark)  -> multiplier_max (e.g. 1.2x, boost)
    illumination_fraction=1.0 (full moon/bright) -> multiplier_min (e.g. 0.8x, dampen)
    """
    if not 0.0 <= illumination_fraction <= 1.0:
        raise ValueError(
            f"illumination_fraction must be in [0.0, 1.0], got {illumination_fraction}"
        )

    multiplier = multiplier_max - illumination_fraction * (multiplier_max - multiplier_min)
    scaled = (bite_score * multiplier).clip(min=0, max=100)
    scaled.name = bite_score.name
    scaled.attrs = dict(bite_score.attrs)
    scaled.attrs["moon_illumination_fraction"] = illumination_fraction
    scaled.attrs["moon_phase_multiplier"] = multiplier
    return scaled


def weighted_overlay_legacy(
    sst_score: xr.DataArray,
    chl_score: xr.DataArray,
    current_score: xr.DataArray,
    depth_score: xr.DataArray,
    weights: Dict[str, float] = config.LAYER_WEIGHTS_LEGACY,
) -> xr.DataArray:
    """
    Reproduce the original (pre-Gold-Coast-upgrade) 4-layer WLC overlay for
    side-by-side comparison against the current higher-accuracy overlay:
      - No SSHA/eddy-edge layer.
      - SST (not bathymetry) is the alignment reference grid, so the output
        is capped at Copernicus's coarse ~9km physics resolution.
      - Nearest-neighbor resampling (rioxarray's default) instead of
        bilinear, producing blockier, stair-stepped output.
    """
    total_weight = sum(weights.values())
    if not np.isclose(total_weight, 1.0):
        raise ValueError(f"Legacy layer weights must sum to 1.0, got {total_weight}")

    ref, (chl_aligned, current_aligned, depth_aligned) = align_to_reference(
        sst_score, chl_score, current_score, depth_score, resampling=Resampling.nearest
    )

    combined = (
        weights["sst_gradient"] * ref.fillna(0)
        + weights["chl_gradient"] * chl_aligned.fillna(0)
        + weights["current_velocity"] * current_aligned.fillna(0)
        + weights["bathymetry"] * depth_aligned.fillna(0)
    )

    bite_score = (combined * 100.0).clip(min=0, max=100)
    bite_score = bite_score.where(depth_aligned.notnull())
    bite_score.name = "bite_score_legacy"
    bite_score.attrs["description"] = "Yellowfin Tuna Bite Probability Score (legacy, 0-100)"
    bite_score.attrs["weights"] = str(weights)
    return bite_score
