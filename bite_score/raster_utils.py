"""
Shared GeoTIFF -> browser-image conversion helpers used by both the
per-date Folium map builder (visualize.py, for layers embedded directly
into that date's HTML) and the shared/static-layer builder (static_layers.py,
for layers that are identical across every date and so are built once,
cached, and served as standalone PNG/JSON assets by webapp.py instead of
being duplicated into every date's page).
"""
import numpy as np
import rasterio.features
import rioxarray  # noqa: F401  (registers the .rio accessor)
from matplotlib.colors import BoundaryNorm, LightSource, ListedColormap
from matplotlib.figure import Figure

import matplotlib


def open_score_raster(geotiff_path: str):
    """
    Open an exported Bite Score (or other single-band) GeoTIFF and return
    (da, image_values, bounds) where `image_values` is guaranteed
    row-0-is-north (the orientation a browser <img>/Leaflet ImageOverlay
    assumes), regardless of how the array happened to be ordered on disk.

    Our pipeline's rasters are built on an ascending-latitude grid (row 0 =
    south), which is geographically valid (rasterio/GDAL read the affine
    transform correctly either way) but is the OPPOSITE of what Leaflet's
    ImageOverlay assumes when stretching a plain image across a lat/lon
    bounding box -- without this flip the heatmap renders mirrored
    north-south. `da` (used for land-outline tracing) is returned
    unflipped, since `rasterio.features.shapes()` reads geo-coordinates
    from the transform directly and is orientation-agnostic.
    """
    da = rioxarray.open_rasterio(geotiff_path, masked=True).squeeze()
    if da.rio.crs.to_epsg() != 4326:
        da = da.rio.reproject("EPSG:4326")

    bounds = da.rio.bounds()  # (minx, miny, maxx, maxy) == (west, south, east, north)
    y_dim = da.dims[-2]
    values = da.values
    if da[y_dim].values[0] < da[y_dim].values[-1]:
        # Ascending latitude (row 0 = south) -> flip so row 0 = north for display.
        values = values[::-1, :]

    return da, values, bounds


def raster_to_rgba(values: np.ndarray, cmap_name: str = "turbo") -> np.ndarray:
    """Convert a 2D score array (0-100, NaN for nodata) into an RGBA image array."""
    normed = np.clip(values / 100.0, 0.0, 1.0)
    colormap = matplotlib.colormaps[cmap_name]
    rgba = colormap(normed)

    # Fully transparent where there is no data (e.g. land / masked cells)
    rgba[..., 3] = np.where(np.isnan(values), 0.0, 0.78)
    return rgba


def fsle_to_rgba(values: np.ndarray, cmap_name: str = "inferno") -> np.ndarray:
    """
    Convert a Finite-Size Lyapunov Exponent field (units 1/day, NaN where
    no front was resolved within the integration window) into an RGBA
    image, rendered as bright filamentary ridges fading to fully
    transparent at low FSLE (open water / eddy interiors) -- it's the
    ridges (fronts), not the absolute value, that are meaningful, so a
    solid-fill heatmap (like the Bite Score layers) would obscure them.

    Normalized against this field's own 95th percentile (rather than a
    fixed constant) since typical FSLE magnitudes vary with how energetic
    the currents are on a given day.
    """
    finite = np.isfinite(values)
    finite_values = values[finite]
    vmax = float(np.nanpercentile(finite_values, 95)) if finite_values.size else 1.0
    vmax = vmax if vmax > 1e-6 else 1.0
    normed = np.clip(np.where(finite, values, 0.0) / vmax, 0.0, 1.0)
    colormap = matplotlib.colormaps[cmap_name]
    rgba = colormap(normed)
    rgba[..., 3] = np.where(finite, normed**1.5 * 0.9, 0.0)
    return rgba


def sla_to_rgba(values: np.ndarray) -> np.ndarray:
    """
    Convert a satellite altimetry Sea Level Anomaly (SLA) field (metres,
    NaN over land/no-data) into an RGBA image using a diverging
    blue-white-red colormap, centred at 0:

        blue  = negative SLA (cold-core eddy, upwelling zone)
        white = neutral (near-average sea level)
        red   = positive SLA (warm-core eddy / EAC spin-off)

    The colour scale is clipped at ±0.4 m -- typical EAC eddy anomalies
    in SE Queensland range from about -0.5 to +0.5 m, so this keeps the
    full dynamic range visible without being blown out by extreme outliers.
    Fully transparent over land / missing data.
    """
    import matplotlib.colors as mcolors
    vmax = 0.40  # metres -- typical EAC eddy amplitude in this AOI
    norm = mcolors.TwoSlopeNorm(vcenter=0.0, vmin=-vmax, vmax=vmax)
    colormap = matplotlib.colormaps["RdBu_r"]  # red=positive/warm, blue=negative/cold
    normed = norm(np.where(np.isfinite(values), values, 0.0))
    rgba = colormap(normed).astype(np.float32)
    rgba[..., 3] = np.where(np.isfinite(values), 0.80, 0.0)
    return rgba


def mld_to_rgba(values: np.ndarray, cmap_name: str = "viridis") -> np.ndarray:
    """
    Convert a raw mixed layer depth field (metres, NaN over land/nodata)
    into an RGBA image. Unlike the 0-100 WLC factor layers, this is Ash's
    raw `mlotst` data (see data_ingestion.py::fetch_mld()) -- not yet
    normalized/scored by Ripley into a gradient/front-strength factor, see
    .squad/decisions/inbox/ash-mld-moonphase.md -- so it's shown on its
    own 2nd-98th percentile-clipped scale rather than assuming a fixed
    0-100 range (same robust-clipping bounds used elsewhere in this
    pipeline, e.g. normalization.py's percentile clipping). Shallower
    (smaller) MLD is rendered brighter since a shoaling mixed layer is the
    meaningful signal here (forage compressed nearer the surface) -- the
    colormap is reversed so low values are bright.
    """
    finite = np.isfinite(values)
    finite_values = values[finite]
    if finite_values.size:
        vmin = float(np.nanpercentile(finite_values, 2))
        vmax = float(np.nanpercentile(finite_values, 98))
    else:
        vmin, vmax = 0.0, 1.0
    if vmax <= vmin:
        vmax = vmin + 1e-6
    normed = np.clip((values - vmin) / (vmax - vmin), 0.0, 1.0)
    colormap = matplotlib.colormaps[f"{cmap_name}_r"]
    rgba = colormap(np.where(finite, normed, 0.0))
    rgba[..., 3] = np.where(finite, 0.78, 0.0)
    return rgba


# Fixed, real-unit (metre) elevation bands for bathymetry_hillshade_to_rgba()
# below -- ascending order, water (negative elevation = depth) first, land
# (positive elevation) last, sharing the single boundary at 0m. Water bands
# are deliberately much finer near the surface (2m steps out to 20m, where
# most nearshore structure/fish-holding depth changes actually happen) and
# progressively coarser at depth, since beyond a few hundred metres further
# depth changes stop being practically meaningful for this app. The first
# and last edges are set far beyond any real elevation in this AOI so every
# real value always falls inside the banded range (BoundaryNorm clips).
_WATER_BREAKS_M = [-100_000, -3000, -2000, -1500, -1000, -700, -500, -300, -200, -150,
                    -100, -75, -50, -35, -20, -10, -5, -2, 0]
_LAND_BREAKS_M = [0, 5, 15, 30, 60, 120, 250, 500, 1000, 2500, 100_000]
_BATHY_TOPO_BOUNDARIES = _WATER_BREAKS_M + _LAND_BREAKS_M[1:]

# Deepest band -> darkest navy, shallowest (just below 0m) -> medium-light
# blue. Starting at Blues(0.25) rather than near-white (0.05) gives the
# hillshade enough base colour to actually show shadow/highlight contrast
# in shallow water -- a base of near-white leaves no room for darkening.
_WATER_COLORS = matplotlib.colormaps["Blues"](
    np.linspace(1.0, 0.25, len(_WATER_BREAKS_M) - 1)
)
# Land: low-lying coastal land (light green) rising to inland high ground
# (dark brown), sampled from the upper (land) half of the "terrain" cmap.
_LAND_COLORS = matplotlib.colormaps["terrain"](
    np.linspace(0.28, 0.95, len(_LAND_BREAKS_M) - 1)
)
_BATHY_TOPO_CMAP = ListedColormap(np.vstack([_WATER_COLORS, _LAND_COLORS]))
_BATHY_TOPO_NORM = BoundaryNorm(_BATHY_TOPO_BOUNDARIES, _BATHY_TOPO_CMAP.N, clip=True)


def bathymetry_hillshade_to_rgba(values: np.ndarray, resolution_m: float) -> np.ndarray:
    """
    Convert a high-resolution bathymetry/elevation grid (stored as
    positive-down depth in metres, NaN outside the surveyed area) into an
    RGBA image using a *banded* bathymetric colour scale -- fixed, real-
    unit (metre) depth bands, light near the surface shading to dark navy
    in deep water (the same convention used on nautical charts), rather
    than a single smooth gradient. A smooth gradient compresses almost the
    entire visually-important shelf/reef depth range (0-200m, where fish
    and structure are) into a narrow sliver of one colour once the grid
    also spans genuinely deep water (this AOI's composite now reaches
    several thousand metres at the shelf edge) -- discrete bands with
    finer steps in shallow water keep those depth *changes* visible at a
    glance, which plain continuous shading does not. Any surveyed land
    above sea level gets its own, separate green/brown elevation bands.

    A hillshade (relief shading), computed directly from this same
    full-resolution grid (no downsampling) at its native `resolution_m`
    pixel spacing, is blended in on top of the banded colours so banks,
    channels and reef structure still read as shaded relief rather than
    flat colour fills.
    """
    elevation = -values  # back to AHD elevation: positive = land, negative = underwater
    finite = np.isfinite(elevation)
    if not finite.any():
        return np.zeros(elevation.shape + (4,))

    elevation_filled = np.where(finite, elevation, 0.0)

    # Step 1 -- base colours from the banded depth/topo scale, using the
    # true (linear) elevation so every depth band stays at the right colour.
    base_rgb = _BATHY_TOPO_CMAP(_BATHY_TOPO_NORM(elevation_filled))[:, :, :3]

    # Step 2 -- hillshade elevation transform: take the cube root of water
    # depth so that small near-surface relief (bommies, ledges, sand banks
    # at 2-20m) generates slopes as prominent in the shading calculation as
    # deep-water canyon walls, making shallow structure genuinely visible.
    # Gradient amplification vs. linear: ~13× at 2m, ~5× at 10m, ~2× at
    # 50m, ~0.1× compression at 2000m -- exactly what we want for a
    # fishing map where the shelf break and shallow reef are what matters.
    # Land stays on the linear scale; no transform needed above sea level.
    _CBRT_SCALE = 100.0  # reference metres -- keeps hillshade numerics stable
    hs_elev = np.where(
        elevation_filled < 0,
        -np.cbrt(np.abs(elevation_filled)) * (_CBRT_SCALE ** (2.0 / 3.0)),
        elevation_filled,
    )

    light = LightSource(azdeg=315, altdeg=45)
    shaded_rgb = light.shade_rgb(
        base_rgb,
        hs_elev,
        vert_exag=12.0,
        dx=resolution_m,
        dy=resolution_m,
        blend_mode="overlay",
    )
    rgba = np.zeros(elevation.shape + (4,), dtype=np.float64)
    rgba[..., :3] = np.clip(shaded_rgb, 0.0, 1.0)
    rgba[..., 3] = np.where(finite, 0.9, 0.0)
    return rgba


def land_outline_geojson(da) -> dict:
    """
    Trace the outline of nodata ("land") cells directly from a raster's own
    mask, so the coastline drawn on the map is pixel-perfectly aligned with
    that raster's transparent areas (rather than drifting out of
    registration the way a separately-sourced coastline dataset might).
    """
    land_mask = np.isnan(da.values).astype("uint8")
    transform = da.rio.transform()

    features = []
    if land_mask.any():
        for geom, _value in rasterio.features.shapes(
            land_mask, mask=land_mask == 1, transform=transform
        ):
            features.append({"type": "Feature", "geometry": geom, "properties": {}})

    return {"type": "FeatureCollection", "features": features}


def _segment_length(seg: np.ndarray) -> float:
    """Approximate planar arc length of a contour segment (lon/lat pairs)."""
    if len(seg) < 2:
        return 0.0
    diffs = np.diff(seg, axis=0)
    return float(np.sum(np.hypot(diffs[:, 0], diffs[:, 1])))


def bathymetry_contour_geojson(
    bathymetry_geotiff_path: str, levels=(20, 50, 100, 200, 500, 1000), max_labels_per_level=5
):
    """
    Derive isobath (depth contour) lines directly from a bathymetry
    GeoTIFF. These give the map real, labeled reference lines scattered
    across the water itself (not just the coastline), making it much
    easier to judge position/scale/coordinates than a heatmap or coastline
    alone can.

    Uses matplotlib's contour path algorithm on the raw depth values
    (metres), keyed to the raster's own lon/lat coordinate arrays -- this
    works regardless of the raster's row ordering (south-up vs. north-up)
    since we pass the actual coordinate values alongside the data, rather
    than assuming a particular row order the way a plain image overlay does.

    Returns `(geojson, labels)` where `labels` is a list of
    `{"lon", "lat", "depth_m"}` points -- one placed at the midpoint of
    each of the longest few segments per depth level (rather than every
    single segment) so permanent on-map depth labels stay legible instead
    of cluttering the map with a label on every tiny contour loop.
    """
    bda = rioxarray.open_rasterio(bathymetry_geotiff_path, masked=True).squeeze()
    y_dim, x_dim = bda.dims[-2], bda.dims[-1]
    lon = bda[x_dim].values
    lat = bda[y_dim].values
    values = bda.values

    # A bare Figure (no pyplot, no GUI backend) is enough to compute contour
    # paths -- we never call draw()/savefig(), so no rendering/backend is
    # ever actually invoked.
    fig = Figure()
    ax = fig.add_subplot(111)
    cs = ax.contour(lon, lat, values, levels=list(levels))

    features = []
    labels = []
    for level, segs in zip(cs.levels, cs.allsegs):
        for seg in segs:
            if len(seg) < 2:
                continue
            features.append(
                {
                    "type": "Feature",
                    "geometry": {"type": "LineString", "coordinates": seg.tolist()},
                    "properties": {"depth_m": float(level)},
                }
            )

        # Label only the longest few segments at this depth level, at their
        # midpoint, so a long isobath doesn't get labeled dozens of times
        # while short/fragmented loops still get skipped entirely.
        longest_segs = sorted(
            (seg for seg in segs if len(seg) >= 2), key=_segment_length, reverse=True
        )[:max_labels_per_level]
        for seg in longest_segs:
            mid = seg[len(seg) // 2]
            labels.append({"lon": float(mid[0]), "lat": float(mid[1]), "depth_m": float(level)})

    return {"type": "FeatureCollection", "features": features}, labels


def sla_contour_geojson(
    sla_geotiff_path: str,
    levels=(-0.3, -0.2, -0.1, 0.0, 0.1, 0.2, 0.3),
    max_labels_per_level=3,
):
    """
    Derive Sea Level Anomaly (SLA) contour lines from an SLA GeoTIFF
    (metres, NaN over land/no-data).

    Returns ``(geojson, labels)`` where each feature has a ``sla_m``
    property (signed metres) and a ``kind`` property of ``"positive"``,
    ``"negative"`` or ``"zero"`` for client-side styling.  Labels are
    placed at the midpoint of the longest few segments per level so the
    map isn't cluttered with a value on every small loop.
    """
    import numpy.ma as ma

    sla_da = rioxarray.open_rasterio(sla_geotiff_path, masked=True).squeeze()
    y_dim, x_dim = sla_da.dims[-2], sla_da.dims[-1]
    lon = sla_da[x_dim].values
    lat = sla_da[y_dim].values
    values = ma.masked_invalid(sla_da.values)

    fig = Figure()
    ax = fig.add_subplot(111)
    cs = ax.contour(lon, lat, values, levels=list(levels))

    features = []
    labels = []
    for level, segs in zip(cs.levels, cs.allsegs):
        if level > 0.001:
            kind = "positive"
        elif level < -0.001:
            kind = "negative"
        else:
            kind = "zero"
        for seg in segs:
            if len(seg) < 2:
                continue
            features.append(
                {
                    "type": "Feature",
                    "geometry": {"type": "LineString", "coordinates": seg.tolist()},
                    "properties": {"sla_m": float(level), "kind": kind},
                }
            )

        longest_segs = sorted(
            (seg for seg in segs if len(seg) >= 2), key=_segment_length, reverse=True
        )[:max_labels_per_level]
        for seg in longest_segs:
            mid = seg[len(seg) // 2]
            labels.append({"lon": float(mid[0]), "lat": float(mid[1]), "sla_m": float(level)})

    return {"type": "FeatureCollection", "features": features}, labels
