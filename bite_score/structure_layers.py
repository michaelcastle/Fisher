"""
v2 structure-scoring primitives: shelf-break (100-200m contour) distance
scoring, named canyon/seamount Gaussian proximity scoring, and a
vorticity-based Southern-Hemisphere warm-core (anticyclonic/
counterclockwise) eddy detector.

This is a NEW, SEPARATE module for the v2 bite-score model -- see
.squad/decisions/inbox/ash-seq-v2-structure-layers.md. It does not import
from or modify overlay.py/normalization.py's v1 scoring functions; v1's
pipeline is completely untouched by this module.

Coordinate/units conventions follow the rest of this codebase:
  - depth: positive-down metres, land/nodata = NaN (see
    normalization.py::normalize_depth).
  - lat/lon: EPSG:4326 degrees, dims named "lat"/"lon" (or
    "latitude"/"longitude", detected via `_lat_lon_names`).
  - longitude spacing is corrected by cos(latitude) when converting
    degrees to real metres, exactly as in processing.py and
    bathymetry_composite.py.
"""
import logging

import numpy as np
import xarray as xr
from scipy.ndimage import distance_transform_edt

from . import config

logger = logging.getLogger(__name__)

METRES_PER_DEGREE_LAT = 111_320.0


def _lat_lon_names(da: xr.DataArray) -> tuple:
    lat_name = "lat" if "lat" in da.dims else "latitude"
    lon_name = "lon" if "lon" in da.dims else "longitude"
    return lat_name, lon_name


def _cell_size_metres(da: xr.DataArray, lat_name: str, lon_name: str) -> tuple:
    """
    Return (dy_metres, dx_metres) -- the grid's approximate per-cell size
    in real-world metres, evaluated at the grid's mean latitude. Same
    single-scalar-per-grid approximation already used for this ~450m
    bathymetry grid in bathymetry_composite.py::RESOLUTION_M (cells
    treated as locally square/uniform rather than recomputing cos(lat)
    row-by-row), which is accurate enough at this AOI's scale and keeps
    `distance_transform_edt`'s `sampling` argument a simple 2-tuple.
    """
    lat_vals = da[lat_name].values
    lon_vals = da[lon_name].values
    lat_spacing_deg = np.abs(np.mean(np.diff(lat_vals)))
    lon_spacing_deg = np.abs(np.mean(np.diff(lon_vals)))
    mean_lat_rad = np.deg2rad(np.mean(lat_vals))

    dy = lat_spacing_deg * METRES_PER_DEGREE_LAT
    dx = lon_spacing_deg * METRES_PER_DEGREE_LAT * np.cos(mean_lat_rad)
    return dy, dx


def shelf_break_distance_score(
    depth: xr.DataArray,
    min_depth_m: float = config.SHELF_BREAK_MIN_DEPTH_M,
    max_depth_m: float = config.SHELF_BREAK_MAX_DEPTH_M,
    inside_km: float = config.SHELF_BREAK_INSIDE_KM,
    outside_km: float = config.SHELF_BREAK_OUTSIDE_KM,
) -> xr.DataArray:
    """
    Score proximity to the continental shelf-break (the min_depth_m -
    max_depth_m contour band, 100-200m by default): 1.0 on the contour
    band itself, ramping down to 0.0 by `inside_km` on the shallower
    (shoreward) side and by `outside_km` on the deeper (seaward) side.

    The band is intentionally scored asymmetrically (a much tighter
    5km falloff shoreward vs. a wider 20km falloff seaward, per Michael's
    spec) since the shelf-break's current-acceleration/upwelling effect on
    baitfish aggregation is understood to extend further into deeper water
    than back up onto the shelf itself.

    Uses `scipy.ndimage.distance_transform_edt` (Euclidean distance
    transform) with its `sampling` argument set to this grid's real-world
    per-cell (dy, dx) metre spacing, so the returned distances are true
    metres rather than raw pixel counts -- this correctly accounts for
    anisotropic (non-square) cells without a separate manual pixel->metre
    conversion step.

    Land / nodata (non-finite depth) is preserved as NaN.
    """
    lat_name, lon_name = _lat_lon_names(depth)
    dy, dx = _cell_size_metres(depth, lat_name, lon_name)

    values = depth.values.astype("float64")
    finite = np.isfinite(values)

    band = finite & (values >= min_depth_m) & (values <= max_depth_m)
    shallow_side = finite & (values < min_depth_m)
    deep_side = finite & (values > max_depth_m)

    if band.any():
        dist_to_band_m = distance_transform_edt(~band, sampling=(dy, dx))
    else:
        # No band cells at all in this grid (e.g. a small synthetic test
        # grid, or a real tile that happens to miss the contour entirely)
        # -- every finite cell is "infinitely" far from the band.
        dist_to_band_m = np.full(values.shape, np.inf)

    score = np.zeros_like(values, dtype="float64")
    score[band] = 1.0

    inside_m = inside_km * 1000.0
    outside_m = outside_km * 1000.0

    score[shallow_side] = np.clip(1.0 - dist_to_band_m[shallow_side] / inside_m, 0.0, 1.0)
    score[deep_side] = np.clip(1.0 - dist_to_band_m[deep_side] / outside_m, 0.0, 1.0)

    score[~finite] = np.nan

    result = depth.copy(data=score)
    result.name = "shelf_break_score"
    return result


def _haversine_distance_km(
    lat1: np.ndarray, lon1: np.ndarray, lat2: float, lon2: float
) -> np.ndarray:
    """
    Great-circle distance (km) from every point in `lat1`/`lon1` (degrees)
    to the single point `(lat2, lon2)` (degrees), via the standard
    haversine formula. Used for the named canyon/seamount proximity
    scoring below, where a genuine great-circle distance was explicitly
    requested (rather than this codebase's usual cos(lat)-scaled planar
    approximation used for short-range gradients in processing.py/
    fsle.py, which is equivalent at this AOI's scale but less exact for a
    named single-point radius).
    """
    r_km = 6371.0088
    phi1 = np.deg2rad(lat1)
    phi2 = np.deg2rad(lat2)
    dphi = np.deg2rad(lat2 - lat1)
    dlambda = np.deg2rad(lon2 - lon1)

    a = np.sin(dphi / 2.0) ** 2 + np.cos(phi1) * np.cos(phi2) * np.sin(dlambda / 2.0) ** 2
    c = 2.0 * np.arcsin(np.clip(np.sqrt(a), 0.0, 1.0))
    return r_km * c


def _latlon_meshgrid(da: xr.DataArray, lat_name: str, lon_name: str) -> tuple:
    """Return 2D (lat_grid, lon_grid) arrays broadcast to `da`'s shape/dim order."""
    lat_vals = da[lat_name].values
    lon_vals = da[lon_name].values
    if da.dims.index(lat_name) < da.dims.index(lon_name):
        lat_grid, lon_grid = np.meshgrid(lat_vals, lon_vals, indexing="ij")
    else:
        lon_grid, lat_grid = np.meshgrid(lon_vals, lat_vals, indexing="ij")
    return lat_grid, lon_grid


def point_gaussian_proximity_score(
    grid: xr.DataArray,
    point_lat: float,
    point_lon: float,
    sigma_km: float = config.STRUCTURE_POINT_SIGMA_KM,
) -> xr.DataArray:
    """
    Gaussian distance-decay proximity score to a single named point
    feature: `exp(-distance_km**2 / (2 * sigma_km**2))`, 1.0 exactly at
    the point, decaying smoothly with great-circle distance.

    `grid` supplies only the lat/lon coordinates/shape/dims/CRS to score
    against (its data values are ignored) -- pass e.g. the depth/reference
    grid.

    `sigma_km` is a tunable, unvalidated "influence radius" (see
    config.STRUCTURE_POINT_SIGMA_KM) -- NOT derived from any
    feature-specific survey data.
    """
    lat_name, lon_name = _lat_lon_names(grid)
    lat_grid, lon_grid = _latlon_meshgrid(grid, lat_name, lon_name)

    dist_km = _haversine_distance_km(lat_grid, lon_grid, point_lat, point_lon)
    score = np.exp(-(dist_km**2) / (2.0 * sigma_km**2))

    result = xr.DataArray(score, coords=grid.coords, dims=grid.dims, name="point_proximity_score")
    return result


def named_feature_proximity_score(
    grid: xr.DataArray,
    features: dict = config.STRUCTURE_FEATURES_V2,
    sigma_km: float = config.STRUCTURE_POINT_SIGMA_KM,
) -> xr.DataArray:
    """
    Combine the Gaussian proximity score to every named point feature
    (Tweed Canyon, Noosa Canyon, Queensland Seamount by default) via an
    element-wise maximum: a cell scores highly if it is close to ANY one
    named feature, rather than requiring closeness to all of them (which
    would be geographically impossible, since the 3 features are tens of
    km apart) or averaging (which would needlessly dilute a cell that is
    genuinely right next to just one canyon).
    """
    scores = [
        point_gaussian_proximity_score(grid, pt["lat"], pt["lon"], sigma_km=sigma_km)
        for pt in features.values()
    ]
    combined = scores[0]
    for other in scores[1:]:
        combined = np.maximum(combined, other)
    combined.name = "named_feature_proximity_score"
    return combined


def compute_structure_score(
    depth: xr.DataArray,
    features: dict = config.STRUCTURE_FEATURES_V2,
    sigma_km: float = config.STRUCTURE_POINT_SIGMA_KM,
    min_depth_m: float = config.SHELF_BREAK_MIN_DEPTH_M,
    max_depth_m: float = config.SHELF_BREAK_MAX_DEPTH_M,
    inside_km: float = config.SHELF_BREAK_INSIDE_KM,
    outside_km: float = config.SHELF_BREAK_OUTSIDE_KM,
) -> xr.DataArray:
    """
    Combine `shelf_break_distance_score` and `named_feature_proximity_score`
    into a single 0-1 "structure_score", via element-wise maximum.

    Max (rather than a weighted average or product) is used because these
    are two INDEPENDENT/ALTERNATIVE structural cues, not two conditions
    that must both hold at once: a cell can be excellent structure either
    because it sits right on the shelf-break contour (even if it's far
    from any named canyon/seamount), or because it's right next to a named
    canyon (even mid-shelf, away from the 100-200m band). Requiring both
    (e.g. via a product) would incorrectly zero out cells that only have
    one kind of structure nearby -- this is the same "don't multiplicatively
    chain independent fractional terms" concern Kane raised for v1's WLC
    factors (see kane-seq-v2-validation.md), applied here to combining two
    structure sub-scores instead of combining structure with an unrelated
    oceanographic factor.
    """
    shelf_score = shelf_break_distance_score(
        depth,
        min_depth_m=min_depth_m,
        max_depth_m=max_depth_m,
        inside_km=inside_km,
        outside_km=outside_km,
    )
    point_score = named_feature_proximity_score(depth, features=features, sigma_km=sigma_km)

    shelf_vals = shelf_score.values
    point_vals = point_score.values
    combined = np.fmax(shelf_vals, point_vals)
    # fmax treats NaN as "missing" (ignores it in favour of the other
    # operand), but a land/nodata cell should stay NaN in both inputs
    # anyway since shelf_break_distance_score already NaNs land -- guard
    # explicitly so a stray NaN in one input doesn't get silently filled
    # by the other.
    combined[np.isnan(shelf_vals) & np.isnan(point_vals)] = np.nan

    result = depth.copy(data=combined)
    result.name = "structure_score"
    return result


def compute_relative_vorticity(uo: xr.DataArray, vo: xr.DataArray) -> xr.DataArray:
    """
    Compute relative vorticity zeta = dv/dx - du/dy (units: 1/s), the
    vertical component of curl(velocity), from surface current U/V
    components on a lat/lon grid.

    Sign convention -- VERIFIED against independent sources (not guessed),
    see .squad/decisions/inbox/ash-seq-v2-structure-layers.md for the full
    derivation and citations. IMPORTANT CORRECTION vs. the task's initial
    framing (and vs. this team's own earlier, unverified assumption in
    ash-seq-v2-feasibility.md / kane-seq-v2-validation.md): those docs
    assumed Southern Hemisphere warm-core/anticyclonic eddies rotate
    CLOCKWISE. That assumption is WRONG. The verified facts are:

      1. In a standard East-North-Up frame (x=east, y=north, viewed
         map-style from above -- exactly this lat/lon grid once both dims
         are sorted ascending), zeta > 0 is COUNTER-clockwise rotation and
         zeta < 0 is CLOCKWISE rotation. This is a purely geometric fact
         and does NOT flip between hemispheres (confirmed both by direct
         derivation from solid-body rotation u=-omega*y, v=omega*x, and by
         Wikipedia's Vorticity article: "Vorticity is positive when --
         looking down onto the Earth's surface -- the wind turns
         counterclockwise").
      2. What DOES flip between hemispheres is which rotation SENSE is
         called "anticyclonic": anticyclonic rotation is CLOCKWISE in the
         Northern Hemisphere but COUNTER-CLOCKWISE in the Southern
         Hemisphere (Wikipedia's "Anticyclonic rotation" article, and the
         Vorticity article's "the nomenclature is reversed in the
         Southern Hemisphere" -- both explicit, citable statements).
      3. Warm-core ocean eddies are anticyclonic (well-established
         oceanography, e.g. the East Australian Current's own warm-core
         eddies -- see Wikipedia's "East Australian Current" article).

    Combining 1-3: in the Southern Hemisphere (this AOI), a warm-core
    anticyclonic eddy is COUNTER-CLOCKWISE, i.e. POSITIVE zeta -- the
    OPPOSITE sign from what the task briefing assumed. See
    `compute_eddy_score`, which is written to use this corrected,
    verified convention (positive zeta), not the task's original
    "clockwise" framing.

    U/V are first sorted ascending on both lat and lon (regardless of
    their input order) so this sign convention holds regardless of how
    the source data happens to be oriented.
    """
    lat_name, lon_name = _lat_lon_names(uo)

    u = uo.squeeze().astype("float64").sortby(lat_name).sortby(lon_name)
    v = vo.squeeze().astype("float64").sortby(lat_name).sortby(lon_name)

    dy, dx = _cell_size_metres(u, lat_name, lon_name)

    lat_axis = u.dims.index(lat_name)
    lon_axis = u.dims.index(lon_name)

    # Central differences (not Sobel) -- we need the true signed partial
    # derivative, not a noise-suppressed edge-magnitude estimate.
    dv_dx = np.gradient(v.values, axis=lon_axis) / dx
    du_dy = np.gradient(u.values, axis=lat_axis) / dy

    zeta = dv_dx - du_dy
    nan_mask = ~np.isfinite(u.values) | ~np.isfinite(v.values)
    zeta[nan_mask] = np.nan

    result = xr.DataArray(zeta, coords=u.coords, dims=u.dims, name="relative_vorticity")
    return result


def _normalize_nonnegative(values: np.ndarray) -> np.ndarray:
    """
    Scale a non-negative-with-zeros array to [0, 1] by the 98th percentile
    of its strictly-positive values (percentile-clipped, same robustness
    rationale as normalization.py::robust_minmax_normalize, but anchored
    at a hard 0 floor rather than the data's own minimum, since 0 here is
    a meaningful "no signal" floor, not an arbitrary data minimum).
    NaN is preserved; an all-zero/all-NaN input returns all zeros/NaN.
    """
    result = np.zeros_like(values, dtype="float64")
    nan_mask = ~np.isfinite(values)
    positive = values[~nan_mask & (values > 0)]
    if positive.size > 0:
        hi = np.percentile(positive, config.NORMALIZATION_UPPER_PERCENTILE)
        if hi <= 0:
            hi = positive.max()
        result = np.clip(values / hi, 0.0, 1.0)
    result[nan_mask] = np.nan
    return result


def compute_eddy_score(vorticity: xr.DataArray, ssha: xr.DataArray) -> xr.DataArray:
    """
    Score a real warm-core Southern-Hemisphere eddy signature (0-1) by
    requiring BOTH anticyclonic rotation AND a co-located positive
    sea-surface-height anomaly (warm-core signature), rather than scoring
    on either signal alone.

    IMPORTANT: per `compute_relative_vorticity`'s verified (not guessed)
    sign-convention derivation, anticyclonic (warm-core) rotation in the
    Southern Hemisphere is COUNTER-clockwise, i.e. POSITIVE zeta -- this
    is the OPPOSITE sign from the task's original "clockwise" framing
    (which this analysis found to be an incorrect, unverified assumption
    shared by the task briefing and this team's own earlier decision
    docs). This function therefore gates on POSITIVE vorticity, not
    negative.

    Unlike `compute_structure_score` above (where max() was used because
    its two sub-scores are independent/alternative cues), a product IS
    the right combination here: vorticity sign alone can't distinguish a
    real warm-core eddy from other anticyclonic shear/noise, and a
    positive SSHA bump alone can't distinguish an eddy from a slow-varying
    regional sea-level trend -- a genuine warm-core eddy requires both
    conditions to hold at the SAME location simultaneously, which is
    exactly what an element-wise product of two independently-normalized
    [0,1] non-negative-only scores enforces (anywhere either signal is
    absent/wrong-signed, that factor is 0, correctly zeroing the product).

    Cyclonic (negative zeta) rotation and/or negative SSHA contribute 0,
    not a penalty -- this only ever scores presence of a positive
    (anticyclonic + warm-core) signature, never anti-scores its absence.
    """
    vort_aligned, ssha_aligned = xr.align(vorticity, ssha, join="inner")

    anticyclonic_strength = np.clip(vort_aligned.values, 0.0, None)
    warm_core_strength = np.clip(ssha_aligned.values, 0.0, None)

    anticyclonic_score = _normalize_nonnegative(anticyclonic_strength)
    warm_core_score = _normalize_nonnegative(warm_core_strength)

    eddy = anticyclonic_score * warm_core_score

    result = xr.DataArray(eddy, coords=vort_aligned.coords, dims=vort_aligned.dims, name="eddy_score")
    return result
