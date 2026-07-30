"""
Visualization helpers: render the exported Bite Score GeoTIFF as an
interactive web map (Folium) over Moreton Island / the Sunshine Coast, plus
an alternative Plotly Densitymapbox rendering.
"""
import logging
import json

import folium
import numpy as np
import rioxarray  # noqa: F401  (registers the .rio accessor, used by build_plotly_map)
from branca.colormap import LinearColormap

from . import config
from .static_layers import get_static_domain_bounds

logger = logging.getLogger(__name__)

# Reference point used to frame the initial map view
MAP_CENTER = (-26.85, 153.35)

# Turbo colormap sample stops, used for the on-map legend.
_LEGEND_COLORS = [
    "#30123b", "#4145ab", "#4675ed", "#39a2fc", "#1bcfd4",
    "#24eca6", "#61fc6c", "#a4fc3b", "#d1e834", "#f3c63a",
    "#fe9b2d", "#f36315", "#d93807", "#b11901", "#7a0403",
]

# Metadata for the five individual contributing-factor layers that feed the
# WLC overlay (see overlay.py::weighted_overlay / config.LAYER_WEIGHTS),
# used to render them as their own selectable map layers plus the "How It's
# Calculated" explanation section. Order matches how they're weighted.
_CONTRIBUTING_LAYERS = [
    {
        "key": "sst",
        "weight_key": "sst_gradient",
        "label": "SST thermal-front score",
        "icon": "thermostat",
        "description": (
            "Sharpest sea-surface-temperature gradients (thermal fronts), "
            "where Yellowfin Tuna often forage along temperature breaks. "
            "Source: NASA MUR satellite SST (~1km)."
        ),
    },
    {
        "key": "chl",
        "weight_key": "chl_gradient",
        "label": "Chlorophyll-front score",
        "icon": "grass",
        "description": (
            "Sharpest chlorophyll / water-colour gradients marking blue-"
            "water/green-water boundaries where baitfish concentrate. "
            "Source: NOAA VIIRS satellite chlorophyll-a (~4km)."
        ),
    },
    {
        "key": "current",
        "weight_key": "current_velocity",
        "label": "Current-edge score",
        "icon": "waves",
        "description": (
            "Intensity of surface current-velocity edges / eddy "
            "boundaries. Source: Copernicus Marine surface current "
            "vectors (~9km)."
        ),
    },
    {
        "key": "ssha",
        "weight_key": "ssha_gradient",
        "label": "SSHA / eddy-front score",
        "icon": "water",
        "description": (
            "Sharpest sea-surface-height-anomaly gradients, marking eddy "
            "edges via geostrophic shear -- often a cleaner eddy signal "
            "than current velocity alone. Source: Copernicus Marine SSHA "
            "(~9km)."
        ),
    },
    {
        "key": "mld",
        # NOTE: "mld_gradient" is not yet in config.LAYER_WEIGHTS -- Ripley
        # owns wiring this into the WLC formula (see
        # .squad/decisions/inbox/ash-mld-moonphase.md). Until then this
        # shows as a 0% factor (config.LAYER_WEIGHTS.get(..., 0) below),
        # matching every other "weight pulled live from config" row here --
        # no placeholder number is hardcoded, so this becomes accurate
        # automatically once Ripley adds the real weight.
        "weight_key": "mld_gradient",
        "label": "MLD front score",
        "icon": "layers",
        "description": (
            "Shoaling (shallower) mixed layer depth compresses baitfish "
            "and forage species closer to the surface -- a signal that "
            "matters most where it coincides with the thermal or "
            "chlorophyll fronts already scored above. Source: Copernicus "
            "Marine mixed layer depth (mlotst, ~9km)."
        ),
    },
    {
        "key": "bathymetry",
        "weight_key": "bathymetry",
        "label": "Depth-suitability score",
        "icon": "terrain",
        "description": (
            "Fuzzy suitability envelope peaking at the continental "
            "shelf-break / drop-off (favoured by pelagic gamefish). Land "
            "is masked out entirely. Source: composite bathymetry -- GEBCO "
            "(~450m) with real local multibeam/LiDAR surveys merged in "
            "nearshore, wherever available."
        ),
    },
]

# Metadata for the v2 ("Beta") model's contributing factors (see
# overlay_v2.py::weighted_overlay_v2 / config.LAYER_WEIGHTS_V2 and
# .squad/decisions/inbox/ripley-seq-v2-scoring-model.md). This is a
# SEPARATE, experimental scoring model -- different inputs, different
# weights, not yet validated against v1's track record -- so every v2
# layer/label below is clearly suffixed "(v2 Beta)" and never reuses or
# overwrites any of the v1 entries/keys above. Order matches
# config.LAYER_WEIGHTS_V2's weighting (heaviest first).
_CONTRIBUTING_LAYERS_V2 = [
    {
        "key": "sst_bell",
        "weight_key": "sst_bell",
        "label": "SST bell-curve score",
        "icon": "thermostat",
        "description": (
            "How close sea-surface temperature (blended with its local "
            "gradient) sits to Yellowfin Tuna's preferred range, scored as "
            "a bell curve rather than v1's pure thermal-front-gradient "
            "approach -- peaks away from fronts too, not just on them."
        ),
    },
    {
        "key": "chl_band",
        "weight_key": "chl_band",
        "label": "Chlorophyll optimal-band score",
        "icon": "grass",
        "description": (
            "Chlorophyll concentration scored against an optimal "
            "productivity band (too little = clear/oligotrophic water, "
            "too much = turbid/coastal water), rather than v1's pure "
            "chlorophyll-gradient/front approach."
        ),
    },
    {
        "key": "current",
        "weight_key": "current_velocity",
        "label": "Current-edge score (v2 recomputed)",
        "icon": "waves",
        "description": (
            "Surface current-velocity edge intensity, recomputed on v2's "
            "wider AOI_V2 grid alongside the other v2 factors."
        ),
    },
    {
        "key": "bathymetry",
        "weight_key": "bathymetry",
        "label": "Depth-suitability score (v2 recomputed)",
        "icon": "terrain",
        "description": (
            "Same depth-suitability envelope concept as v1, recomputed on "
            "v2's own wider-coverage bathymetry grid (data/gebco_seq_v2.nc)."
        ),
    },
    {
        "key": "mld",
        "weight_key": "mld_gradient",
        "label": "MLD gradient score (v2)",
        "icon": "layers",
        "description": (
            "Mixed-layer-depth gradient, normalized into a real 0-100 WLC "
            "factor (unlike v1's raw-metres MLD diagnostic layer)."
        ),
    },
    {
        "key": "structure",
        "weight_key": "structure_score",
        "label": "Structure proximity score",
        "icon": "hub",
        "description": (
            "Proximity to named seafloor structure (shelf break, canyons) "
            "-- a genuinely NEW v2 factor with no v1 equivalent. See "
            "config.STRUCTURE_FEATURES_V2 / structure_layers.py."
        ),
    },
    {
        "key": "eddy",
        "weight_key": "eddy_score",
        "label": "Eddy detection score",
        "icon": "cyclone",
        "description": (
            "Real vorticity-based warm-core eddy detection (from surface "
            "current shear), rather than v1's SSHA-gradient proxy -- "
            "another genuinely NEW v2 factor with no v1 equivalent."
        ),
    },
]

# Metadata for the "Lenigas" model's contributing factors -- a SECOND,
# INDEPENDENT experimental scoring model (see
# overlay_lenigas.py::weighted_overlay_lenigas / config.LAYER_WEIGHTS_LENIGAS
# and .squad/decisions/inbox/ripley-lenigas-pipeline.md), named after the
# real SEQ fisherman podcast account whose informally-described conditions
# it's built from -- distinct from both v1 (validated track record) and v2
# (oceanographic-structure/eddy model). NEVER called "v3" anywhere. Order
# matches config.LAYER_WEIGHTS_LENIGAS's weighting (heaviest first); wind
# speed is listed last with weight_key=None since it's fetched/reported for
# validation but deliberately NOT part of the WLC weights yet (informational
# only -- see config.py's comment above LAYER_WEIGHTS_LENIGAS).
_CONTRIBUTING_LAYERS_LENIGAS = [
    {
        "key": "eac_axis_position",
        "weight_key": "eac_axis_position",
        "label": "EAC axis-position score",
        "icon": "alt_route",
        "description": (
            "5-zone score based on signed distance from the East "
            "Australian Current's traced core-jet axis -- the podcast's "
            "account of fishing relative to 'the current line' turned "
            "into a continuous km-based score."
        ),
    },
    {
        "key": "eac_convergence",
        "weight_key": "eac_convergence",
        "label": "EAC convergence-point score",
        "icon": "join_inner",
        "description": (
            "Proximity to a single detected point where westward-flowing "
            "water most strongly meets the EAC's core-jet axis -- an "
            "honestly-documented v1-of-Lenigas simplification (falls back "
            "to a flat neutral 50 on days with no detected convergence)."
        ),
    },
    {
        "key": "depth_suitability",
        "weight_key": "depth_suitability_lenigas",
        "label": "Depth-suitability score (Lenigas)",
        "icon": "terrain",
        "description": (
            "A separate depth-suitability ramp/envelope tuned to this "
            "model's own preferred depth band, recomputed on the same "
            "AOI_V2 bathymetry grid as v2's depth-suitability factor."
        ),
    },
    {
        "key": "upwelling_downwelling",
        "weight_key": "upwelling_downwelling",
        "label": "Upwelling/downwelling score",
        "icon": "swap_vert",
        "description": (
            "Continuous tanh-scaled score from relative vorticity sign -- "
            "upwelling (nutrient-rich water rising) scores higher than "
            "downwelling, per the podcast's account of upwelling zones "
            "fishing better."
        ),
    },
    {
        "key": "sst_bell",
        "weight_key": "sst_bell_lenigas",
        "label": "SST bell-curve score (Lenigas)",
        "icon": "thermostat",
        "description": (
            "A clean Gaussian bell-curve fit around this model's own "
            "preferred sea-surface temperature, without v2's added "
            "gradient/front blending -- SST is this model's "
            "lowest-weighted factor, per the source account's own "
            "de-emphasis of exact temperature."
        ),
    },
    {
        "key": "distance_offshore",
        "weight_key": "distance_offshore",
        "label": "Distance-offshore score",
        "icon": "sailing",
        "description": (
            "Ramped suitability envelope over real distance-from-coast "
            "(computed from the AOI_V2 land/sea mask), peaking at the "
            "offshore band the source account describes fishing, rather "
            "than v1/v2's shelf-break-proximity framing."
        ),
    },
    {
        "key": "ssha_hotspot",
        "weight_key": "ssha_hotspot_lenigas",
        "label": "SSHA hotspot score (Lenigas)",
        "icon": "waves",
        "description": (
            "Percentile-tiered score from a per-date, re-based sea "
            "surface height anomaly (zos) -- a hotspot/boundary signal "
            "distinct from upwelling/downwelling's current-shear-derived "
            "vorticity, using seasonal anchor tables that peak at the "
            "30th percentile (upwelling-biased)."
        ),
    },
    {
        "key": "wind_speed",
        "weight_key": None,
        "label": "Wind speed",
        "icon": "air",
        "description": (
            "Real wind speed, fetched and reported for validation "
            "purposes but NOT yet part of the WLC weights below -- shown "
            "here only as an informational raw layer (own percentile-"
            "clipped scale, not a 0-100 score) until a wind-suitability "
            "curve is specified as follow-up work."
        ),
    },
]

def build_folium_map(output_html: str = "bite_score_map.html") -> folium.Map:
    """
    Load the Bite Score GeoTIFF and render it as a polished, user-friendly
    interactive map centred on Moreton Island / the Sunshine Coast:
      - a crisp land outline traced from the raster's own nodata mask, so
        the coastline stays visible under the heatmap,
      - switchable basemaps (light / streets / satellite),
      - an on-map colour legend,
      - a live opacity slider so the heatmap never has to fully hide the map,
      - an "Update Data" button + date picker that (when the page is served
        via `python -m bite_score.webapp`) re-runs the pipeline for the
        chosen date and reloads the map when done,
      - a "View historical data" dropdown (populated from `/api/history`
        when served via the webapp) to switch to a previously-processed
        day's stored map almost instantly, without re-running the pipeline,
      - a second toggleable "legacy" overlay (the original, lower-
        resolution SST-referenced scoring) for direct comparison against
        the current, more accurate overlay,
      - the four daily normalized contributing-factor layers
        (SST/chlorophyll/current/SSHA gradients) as their own
        selectable/toggleable overlays, plus a "How It's Calculated"
        explanation of the scoring methodology,
      - a Finite-Size Lyapunov Exponent (FSLE) diagnostic layer
        highlighting ocean fronts / Lagrangian Coherent Structures, plus a
        "How FSLE Is Calculated" explanation (not available for every
        date -- requires several days of forecast current data).
      - a handful of *shared, static* layers that never change across dates
        (depth-contour isobaths, the Depth-suitability factor, and a
        single unified high-resolution bathymetry relief map merging
        AusBathyTopo, the Sunshine Coast LiDAR survey, and the AusSeabed
        Moreton Bay Approaches / Mudjimba Island surveys onto one grid),
        plus the land/coastline outline -- fetched from the dashboard
        server's static `/api/static-layer/*`, `/api/bathymetry/contours`
        and `/api/bathymetry/land-outline` endpoints, built once and
        reused by every date's map (see `bsqLoadRasterLayer()` /
        `bsqLoadContours()` / `bsqLoadLandOutline()` JS below).
      - a georeferenced Moreton Bay Game Fish Club nautical chart overlay
        (reefs/banks/grounds) plus its FAD/SFAD/wave-buoy coordinates as
        point markers -- fetched the same on-demand way, from the
        dashboard server's static `/api/mbgfc/*` endpoints.

    Unlike every layer above, this function itself no longer reads *any*
    per-date GeoTIFF, so the resulting page is 100% identical regardless
    of which date the user is looking at -- the per-date Bite Score
    heatmap, legacy heatmap, four contributing factors, and FSLE are ALSO
    only lightweight placeholders here, fetched client-side from
    `/api/date-layer/<date>/<key>/*` (see `bsqLoadDateLayer()` JS below),
    with `<date>` resolved in the browser (from the `/history/<date>` URL
    path, or `/api/latest-date` for "/"). That's what lets a single
    generated `output_html` (rather than one per date) serve every day's
    data -- see date_layers.py for the per-date asset cache and
    webapp.py for the endpoints.
    """
    # The domain (and therefore land mask) is identical for every date --
    # each day's Bite Score raster is resampled onto this same static
    # bathymetry grid (see pipeline.py::align_to_reference()) -- so these
    # bounds are a date-independent stand-in for "the map's overall
    # extent", used only for the initial view and as a starting bounding
    # box for placeholder layers (corrected via `setBounds()` once each
    # layer's real per-date/per-layer meta is fetched).
    bounds = get_static_domain_bounds()

    fmap = folium.Map(location=MAP_CENTER, zoom_start=9, tiles=None, control_scale=True)

    fonts_html = """
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&family=JetBrains+Mono:wght@500&display=swap" rel="stylesheet">
    <link href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:wght,FILL@100..700,0..1&display=block" rel="stylesheet">
    """
    fmap.get_root().header.add_child(folium.Element(fonts_html))

    # Every overlay below gets its own dedicated Leaflet pane (rather than
    # sharing the default 'overlayPane'), purely so its stacking order (in
    # front of / behind other overlays) can be controlled independently by
    # setting that pane's CSS z-index -- which is exactly what the sidebar
    # drag-and-drop layer reordering does (see bsqEnableLayerReorder() /
    # applyDrawOrder() below). Panes are created in top-of-list order with
    # descending z-index, so the initial stacking (before any dragging)
    # already matches "top of Layers list = drawn frontmost".
    _pane_z = [500]
    _pane_vars = {}

    def _add_pane(label: str) -> str:
        pane = folium.map.CustomPane(
            f"bsqPane{len(_pane_vars)}", z_index=_pane_z[0], pointer_events=True
        )
        _pane_z[0] -= 1
        pane.add_to(fmap)
        _pane_vars[label] = pane.get_name()
        return pane.name

    # Kept as named variables (rather than the previous throwaway
    # `folium.TileLayer(...).add_to(fmap)` one-liners) so their JS `var`
    # identifiers (see `light_var`/`streets_var`/`satellite_var` below) can
    # be referenced directly by the compact basemap switcher control
    # (2026-07-25, Lambert -- see bsqSwitchBasemap() JS below), which
    # drives these 3 base layers itself instead of relying on Folium's own
    # (now removed from the sidebar) basemap radio buttons.
    light_layer = folium.TileLayer("CartoDB positron", name="Light basemap", show=True)
    light_layer.add_to(fmap)
    streets_layer = folium.TileLayer("OpenStreetMap", name="Streets basemap", show=False)
    streets_layer.add_to(fmap)
    satellite_layer = folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Tiles &copy; Esri &mdash; Esri, Maxar, Earthstar Geographics",
        name="Satellite basemap",
        show=False,
    )
    satellite_layer.add_to(fmap)

    # Georeferenced Moreton Bay Game Fish Club nautical chart (reefs, banks
    # and named fishing grounds) + its FAD/SFAD/wave-buoy coordinates.
    # Unlike every other layer here, no pixel/point data is embedded into
    # this page at all -- a lightweight *placeholder* overlay/group is
    # registered with Folium's LayerControl (so the layer exists, is
    # selectable, and keeps whatever on/off state the user picks) and the
    # actual chart image + marker list are fetched client-side from the
    # dashboard server's static `/api/mbgfc/*` endpoints (see the
    # `bsqLoadMbgfc()` JS below). That decouples this layer entirely from
    # the per-date pipeline: it's always available on every date's map,
    # past or future, without ever needing that date's HTML rebuilt.
    # FADs/buoys and waypoints are created first (highest z-index) so they
    # always render in front of the chart image and relief map even when
    # those raster layers are enabled underneath them.
    mbgfc_locations_pane = _add_pane("MBGFC FADs, SFADs & wave buoys")
    mbgfc_locations_layer = folium.FeatureGroup(name="MBGFC FADs, SFADs & wave buoys", show=False)
    mbgfc_locations_layer.add_to(fmap)

    # Fishing waypoints: Light Tackle Grounds and Heavy Tackle Marks
    # supplied by the user. Loaded lazily from /api/waypoints on first
    # toggle, same decoupled pattern as the MBGFC locations layer above.
    waypoints_pane = _add_pane("Fishing waypoints (Light & Heavy Tackle)")
    waypoints_layer = folium.FeatureGroup(name="Fishing waypoints (Light & Heavy Tackle)", show=False)
    waypoints_layer.add_to(fmap)

    # MBGFC chart image: below the dots/waypoints so markers stay visible
    # even when the chart scan is enabled.
    mbgfc_chart_pane = _add_pane("MBGFC fishing chart (georeferenced)")
    mbgfc_chart_layer = folium.raster_layers.ImageOverlay(
        image=np.zeros((1, 1, 4)),
        bounds=[[bounds[1], bounds[0]], [bounds[3], bounds[2]]],
        opacity=0.85,
        name="MBGFC fishing chart (georeferenced)",
        interactive=True,
        cross_origin=False,
        show=False,
        pane=mbgfc_chart_pane,
    )
    mbgfc_chart_layer.add_to(fmap)

    # Land/coastline outline: like the bathymetry contours below, this is
    # derived purely from the static bathymetry grid (identical every
    # date), so it's a lightweight placeholder FeatureGroup here; the real
    # GeoJSON is fetched from `/api/bathymetry/land-outline` (see
    # `bsqLoadLandOutline()` JS below), loaded directly at page load since
    # it's shown by default.
    land_outline_pane = _add_pane("Land outline")
    land_outline_group = folium.FeatureGroup(name="Land outline", show=True)
    land_outline_group.add_to(fmap)

    # Depth-contour (isobath) lines + labels: identical on every date
    # (derived from the static GEBCO grid, not any daily data), so -- like
    # the MBGFC chart above -- this is a lightweight placeholder
    # FeatureGroup here; the actual GeoJSON + labels are fetched from
    # `/api/bathymetry/contours` (see `bsqLoadContours()` JS below), loaded
    # directly at page load since it's shown by default.
    contour_pane = _add_pane("Bathymetry contours (depth reference)")
    contour_group = folium.FeatureGroup(name="Bathymetry contours (depth reference)", show=True)
    contour_group.add_to(fmap)

    # Independent diagnostic layer (not one of the five weighted factors):
    # ocean fronts / Lagrangian Coherent Structures revealed by a Finite-
    # Size Lyapunov Exponent field (see fsle.py). Not available for every
    # date (requires several days of forecast current data beyond it), so
    # this placeholder simply fails gracefully (a console warning) if
    # toggled on for a date where it wasn't computed.
    fsle_pane = _add_pane("Ocean fronts (FSLE)")
    fsle_layer = folium.raster_layers.ImageOverlay(
        image=np.zeros((1, 1, 4)),
        bounds=[[bounds[1], bounds[0]], [bounds[3], bounds[2]]],
        opacity=0.9,
        name="Ocean fronts (FSLE)",
        interactive=True,
        cross_origin=False,
        show=False,
        pane=fsle_pane,
    )
    fsle_layer.add_to(fmap)

    # Satellite altimetry Sea Level Anomaly (SLA): independent visual
    # reference layer revealing warm-core / cold-core eddies and EAC
    # meander structure. Diverging blue/white/red colormap, centred at 0.
    # Sourced from NOAA CoastWatch ERDDAP (nesdisSSH1day, 0.25deg daily).
    # Not available for every date -- same graceful-degradation pattern
    # as FSLE (a console warning if toggled on for a missing date).
    sla_pane = _add_pane("Sea level anomaly (altimetry)")
    sla_layer = folium.raster_layers.ImageOverlay(
        image=np.zeros((1, 1, 4)),
        bounds=[[bounds[1], bounds[0]], [bounds[3], bounds[2]]],
        opacity=0.85,
        name="Sea level anomaly (altimetry)",
        interactive=True,
        cross_origin=False,
        show=False,
        pane=sla_pane,
    )
    sla_layer.add_to(fmap)

    # SLA contour lines (per-date GeoJSON): isolines at ±0.1/0.2/0.3 m
    # and the zero line, coloured red for warm-core eddies (positive SLA)
    # and blue for cold-core / upwelling (negative SLA).  Loaded lazily
    # via /api/date-layer/<date>/sla_contours/contours.json on overlayadd.
    sla_contour_pane = _add_pane("Sea level anomaly contours")
    sla_contour_group = folium.FeatureGroup(name="Sea level anomaly contours", show=False)
    sla_contour_group.add_to(fmap)

    # The Bite Score heatmap itself: shown by default, so it's loaded
    # directly at page load (see `bsqResolveDateAndLoad()` JS below) rather
    # than waiting for an "overlayadd" toggle event.
    heatmap_pane = _add_pane("Bite Score heatmap (current, high-res)")
    heatmap_layer = folium.raster_layers.ImageOverlay(
        image=np.zeros((1, 1, 4)),
        bounds=[[bounds[1], bounds[0]], [bounds[3], bounds[2]]],
        opacity=0.78,
        name="Bite Score heatmap (current, high-res)",
        interactive=True,
        cross_origin=False,
        pane=heatmap_pane,
    )
    heatmap_layer.add_to(fmap)

    legacy_pane = _add_pane("Bite Score heatmap (legacy, coarse - for comparison)")
    legacy_layer = folium.raster_layers.ImageOverlay(
        image=np.zeros((1, 1, 4)),
        bounds=[[bounds[1], bounds[0]], [bounds[3], bounds[2]]],
        opacity=0.78,
        name="Bite Score heatmap (legacy, coarse - for comparison)",
        interactive=True,
        cross_origin=False,
        show=False,
        pane=legacy_pane,
    )
    legacy_layer.add_to(fmap)

    # ---- Sidebar Layers-list grouping (2026-07-23, Lambert) ----
    # The layers below are deliberately CREATED in group order (Reference
    # charts -> Ocean & environmental context -> Bite Score v1 -> Bite
    # Score v2 -> High-res bathymetry surveys) purely so they land
    # contiguously in Folium's LayerControl overlays list -- this is what
    # lets `bsqInsertLayerGroupHeaders()` (JS below) insert one static
    # divider row before the first layer of each group by matching that
    # layer's label text. No layer keys/names/weights changed, only the
    # order these `_add_pane()`/`ImageOverlay`/`FeatureGroup` calls run in.
    # `bsqEnableLayerReorder()`'s drag-and-drop and per-date lazy loading
    # (`bsqLoadDateLayer()`/`bsqLoadRasterLayer()`) key off each layer's
    # label text, not creation order, so both keep working unmodified.

    # The 5 daily normalized contributing-factor layers (each 0-100, same
    # colour scale as the main heatmap) that were combined to produce the
    # v1 Bite Score, so the user can inspect any one factor on its own.
    # Hidden by default (show=False) -- toggle on via the Layers list to
    # fetch it for the currently-resolved date. The 6th factor (Depth-
    # suitability, just below) is handled separately, since unlike these it
    # never changes across dates and so is a shared/static layer instead.
    factor_vars = {}
    for meta in _CONTRIBUTING_LAYERS:
        if meta["key"] == "bathymetry":
            continue
        weight_pct = config.LAYER_WEIGHTS.get(meta["weight_key"], 0) * 100
        # Weight is intentionally NOT baked into this label string (see
        # .squad/decisions/inbox/lambert-layer-ui-declutter.md) -- it's
        # rendered as its own pill next to the row instead (see
        # `_layer_ui`/`bsqEnhanceLayerRows()` below), so the raw checkbox
        # text stays short and scannable.
        factor_name = f"Factor: {meta['label']}"
        factor_pane = _add_pane(factor_name)
        factor_layer = folium.raster_layers.ImageOverlay(
            image=np.zeros((1, 1, 4)),
            bounds=[[bounds[1], bounds[0]], [bounds[3], bounds[2]]],
            opacity=0.78,
            name=factor_name,
            interactive=True,
            cross_origin=False,
            show=False,
            pane=factor_pane,
        )
        factor_layer.add_to(fmap)
        factor_vars[meta["key"]] = (factor_name, factor_layer)

    # 6th v1 factor: Depth-suitability. Unlike the other 5, this is a pure
    # function of the static local GEBCO/composite bathymetry grid (see
    # bathymetry_composite.py) with zero dependency on any daily ocean
    # data, so it's a shared/static layer whose pixels are fetched once
    # from `/api/static-layer/depth_suitability/*` (see
    # `bsqLoadRasterLayer()` JS below) and reused by every date's map,
    # rather than being re-rendered per date like the 5 factors above.
    # Grouped here (rather than with the other static bathymetry survey
    # layers further below) since it's conceptually one of the v1 WLC
    # factors, per the sidebar grouping described above.
    weight_pct = config.LAYER_WEIGHTS.get("bathymetry", 0) * 100
    depth_suitability_name = "Factor: Depth-suitability score"
    depth_suitability_pane = _add_pane(depth_suitability_name)
    depth_suitability_layer = folium.raster_layers.ImageOverlay(
        image=np.zeros((1, 1, 4)),
        bounds=[[bounds[1], bounds[0]], [bounds[3], bounds[2]]],
        opacity=0.78,
        name=depth_suitability_name,
        interactive=True,
        cross_origin=False,
        show=False,
        pane=depth_suitability_pane,
    )
    depth_suitability_layer.add_to(fmap)

    # v2 ("Beta") experimental Bite Score heatmap -- a SEPARATE scoring
    # model (structure proximity, real eddy detection, seasonal
    # multiplier; see .squad/decisions/inbox/ripley-seq-v2-scoring-model.md)
    # rendered as its own toggleable overlay for direct comparison against
    # v1's main heatmap above, exactly mirroring the "legacy" layer's
    # pattern (own pane, hidden by default, fetched on demand). v1's
    # heatmap/legacy/factor layers above are completely untouched by this
    # block -- v2 only ever reads from that date's SEPARATE
    # output/history/<date>/v2/ subfolder (see date_layers.py::
    # DATE_LAYER_SPECS_V2 / build_date_layer_assets_v2()), so a date with
    # v1 data but no v2 run simply 404s when this layer is toggled on
    # (handled gracefully client-side -- see bsqLoadDateLayer() and
    # bsqCheckV2Availability() JS below -- never a crash or blank/broken
    # tile).
    v2_heatmap_pane = _add_pane("Bite Score heatmap v2 (Beta - structure/eddy model)")
    v2_heatmap_layer = folium.raster_layers.ImageOverlay(
        image=np.zeros((1, 1, 4)),
        bounds=[[bounds[1], bounds[0]], [bounds[3], bounds[2]]],
        opacity=0.78,
        name="Bite Score heatmap v2 (Beta - structure/eddy model)",
        interactive=True,
        cross_origin=False,
        show=False,
        pane=v2_heatmap_pane,
    )
    v2_heatmap_layer.add_to(fmap)

    # v2's own 7 contributing factors (see _CONTRIBUTING_LAYERS_V2 above),
    # same lazy placeholder-overlay treatment as v1's factor loop above.
    factor_vars_v2 = {}
    for meta in _CONTRIBUTING_LAYERS_V2:
        weight_pct = config.LAYER_WEIGHTS_V2.get(meta["weight_key"], 0) * 100
        factor_name_v2 = f"Factor (v2 Beta): {meta['label']}"
        factor_pane_v2 = _add_pane(factor_name_v2)
        factor_layer_v2 = folium.raster_layers.ImageOverlay(
            image=np.zeros((1, 1, 4)),
            bounds=[[bounds[1], bounds[0]], [bounds[3], bounds[2]]],
            opacity=0.78,
            name=factor_name_v2,
            interactive=True,
            cross_origin=False,
            show=False,
            pane=factor_pane_v2,
        )
        factor_layer_v2.add_to(fmap)
        factor_vars_v2[meta["key"]] = (factor_name_v2, factor_layer_v2)

    # "Lenigas" experimental Bite Score heatmap -- a SECOND, INDEPENDENT
    # scoring model built from a real SEQ fisherman podcast account (EAC
    # axis position/convergence, distance offshore, upwelling/downwelling,
    # its own SST bell curve and depth-suitability ramp; see
    # .squad/decisions/inbox/ripley-lenigas-pipeline.md), rendered as its
    # own toggleable overlay for direct comparison against v1's and v2's
    # heatmaps above, exactly mirroring the v2 ("Beta") layer's pattern
    # immediately above (own pane, hidden by default, fetched on demand).
    # v1/v2's heatmap/legacy/factor layers above are completely untouched
    # by this block -- Lenigas only ever reads from that date's SEPARATE
    # output/history/<date>/lenigas/ subfolder (see date_layers.py::
    # DATE_LAYER_SPECS_LENIGAS / build_date_layer_assets_lenigas()), so a
    # date with v1/v2 data but no Lenigas run simply 404s when this layer
    # is toggled on (handled gracefully client-side -- see
    # bsqLoadDateLayer() and bsqCheckLenigasAvailability() JS below --
    # never a crash or blank/broken tile). Always "Lenigas", never "v3".
    lenigas_heatmap_pane = _add_pane("Bite Score heatmap Lenigas (SEQ fisherman model)")
    lenigas_heatmap_layer = folium.raster_layers.ImageOverlay(
        image=np.zeros((1, 1, 4)),
        bounds=[[bounds[1], bounds[0]], [bounds[3], bounds[2]]],
        opacity=0.78,
        name="Bite Score heatmap Lenigas (SEQ fisherman model)",
        interactive=True,
        cross_origin=False,
        show=False,
        pane=lenigas_heatmap_pane,
    )
    lenigas_heatmap_layer.add_to(fmap)

    # Lenigas's own 7 WLC contributing factors plus the informational-only
    # wind speed layer (see _CONTRIBUTING_LAYERS_LENIGAS above), same lazy
    # placeholder-overlay treatment as v1/v2's factor loops above. Wind
    # speed has no weight_key (not part of the WLC weights), so its label
    # omits a "% weight" suffix rather than showing a misleading 0%.
    factor_vars_lenigas = {}
    for meta in _CONTRIBUTING_LAYERS_LENIGAS:
        factor_name_lenigas = f"Factor (Lenigas): {meta['label']}"
        factor_pane_lenigas = _add_pane(factor_name_lenigas)
        factor_layer_lenigas = folium.raster_layers.ImageOverlay(
            image=np.zeros((1, 1, 4)),
            bounds=[[bounds[1], bounds[0]], [bounds[3], bounds[2]]],
            opacity=0.78,
            name=factor_name_lenigas,
            interactive=True,
            cross_origin=False,
            show=False,
            pane=factor_pane_lenigas,
        )
        factor_layer_lenigas.add_to(fmap)
        factor_vars_lenigas[meta["key"]] = (factor_name_lenigas, factor_layer_lenigas)

    # The remaining layer never changes across dates (it's derived purely
    # from the static GEBCO/composite bathymetry grid plus the local
    # LiDAR/AusSeabed/AusBathyTopo surveys -- none of which depend on any
    # daily ocean data). Rather than re-rendering and re-embedding
    # identical images into every date's page, these are lightweight
    # placeholder ImageOverlays whose actual pixels/bounds are fetched on
    # demand from `/api/static-layer/<key>/*` the first time this group is
    # switched on (see `bsqLoadRasterLayer()` JS below) -- built once,
    # cached, and reused by every date's map.
    #
    # This single "Bathymetry relief map" toggle is a FeatureGroup (like
    # "Land outline"/"Bathymetry contours" below) bundling 4 image layers
    # instead of one: a whole-AOI AusBathyTopo-based base at its own
    # native ~250m resolution, plus the 3 real local surveys (Moreton Bay
    # Approaches 30m, Sunshine Coast LiDAR 10m, Mudjimba Island 0.5m)
    # stacked on top, each rendered at ITS OWN native resolution rather
    # than being downsampled onto one common grid (an earlier version of
    # this consolidation did that, at a fixed ~30m, which threw away the
    # LiDAR/Mudjimba surveys' real finer detail and made the AusBathyTopo
    # base look artificially flat everywhere it was upsampled -- see
    # bathymetry_composite.py::build_visual_bathymetry_mosaic()). Panes
    # are created finest-survey-first so they get the highest z-index and
    # so draw on top of the coarser layers below them wherever they
    # overlap.
    relief_map_mudjimba_pane = _add_pane("Bathymetry relief map (Mudjimba Island inset)")
    relief_map_lidar_pane = _add_pane("Bathymetry relief map (LiDAR inset)")
    relief_map_mba_pane = _add_pane("Bathymetry relief map (Moreton Bay Approaches inset)")
    relief_map_pane = _add_pane("Bathymetry relief map")
    relief_map_group = folium.FeatureGroup(name="Bathymetry relief map", show=False)
    relief_map_group.add_to(fmap)

    relief_map_layer = folium.raster_layers.ImageOverlay(
        image=np.zeros((1, 1, 4)),
        bounds=[[bounds[1], bounds[0]], [bounds[3], bounds[2]]],
        opacity=0.9,
        interactive=True,
        cross_origin=False,
        pane=relief_map_pane,
    )
    relief_map_layer.add_to(relief_map_group)

    relief_map_mba_layer = folium.raster_layers.ImageOverlay(
        image=np.zeros((1, 1, 4)),
        bounds=[[bounds[1], bounds[0]], [bounds[3], bounds[2]]],
        opacity=0.9,
        interactive=True,
        cross_origin=False,
        pane=relief_map_mba_pane,
    )
    relief_map_mba_layer.add_to(relief_map_group)

    relief_map_lidar_layer = folium.raster_layers.ImageOverlay(
        image=np.zeros((1, 1, 4)),
        bounds=[[bounds[1], bounds[0]], [bounds[3], bounds[2]]],
        opacity=0.9,
        interactive=True,
        cross_origin=False,
        pane=relief_map_lidar_pane,
    )
    relief_map_lidar_layer.add_to(relief_map_group)

    relief_map_mudjimba_layer = folium.raster_layers.ImageOverlay(
        image=np.zeros((1, 1, 4)),
        bounds=[[bounds[1], bounds[0]], [bounds[3], bounds[2]]],
        opacity=0.9,
        interactive=True,
        cross_origin=False,
        pane=relief_map_mudjimba_pane,
    )
    relief_map_mudjimba_layer.add_to(relief_map_group)


    legend = LinearColormap(
        colors=_LEGEND_COLORS,
        vmin=0,
        vmax=100,
        caption="Yellowfin Tuna Bite Score (0-100)",
        text_color="#c4c6cf",
    )
    legend.add_to(fmap)


    folium.LayerControl(collapsed=False).add_to(fmap)

    # Folium declares each layer as a top-level `var <name> = ...` inside its
    # own <script> tag, so later <script> blocks in the same page (like our
    # control panel below) can reference it by name once it has loaded.
    heatmap_var = heatmap_layer.get_name()
    legacy_var = legacy_layer.get_name()
    mbgfc_chart_var = mbgfc_chart_layer.get_name()
    mbgfc_locations_var = mbgfc_locations_layer.get_name()
    waypoints_var = waypoints_layer.get_name()
    land_outline_group_var = land_outline_group.get_name()
    contour_group_var = contour_group.get_name()
    depth_suitability_var = depth_suitability_layer.get_name()
    relief_map_var = relief_map_layer.get_name()
    relief_map_mba_var = relief_map_mba_layer.get_name()
    relief_map_lidar_var = relief_map_lidar_layer.get_name()
    relief_map_mudjimba_var = relief_map_mudjimba_layer.get_name()
    fsle_var = fsle_layer.get_name()
    sla_var = sla_layer.get_name()
    sla_contour_group_var = sla_contour_group.get_name()
    v2_heatmap_var = v2_heatmap_layer.get_name()
    lenigas_heatmap_var = lenigas_heatmap_layer.get_name()
    light_var = light_layer.get_name()
    streets_var = streets_layer.get_name()
    satellite_var = satellite_layer.get_name()
    map_var = fmap.get_name()

    # Per-date layers (see date_layers.py) keyed by their Layers-list label
    # -> (API key, JS variable name) -- used to build the generic
    # `bsqDateLayerByName` lookup below, so a single `bsqLoadDateLayer()`
    # function (rather than a long if/else chain) can handle the Bite
    # Score heatmap, legacy heatmap, four contributing factors, and FSLE.
    # v2 ("Beta") entries use a "v2/"-prefixed API key (e.g. "v2/bite_score_v2")
    # so `bsqLoadDateLayer()` can route them to the SEPARATE
    # `/api/date-layer-v2/` endpoint instead of v1's `/api/date-layer/` --
    # see that function's JS below. This is purely additive: every v1 key
    # above is unprefixed and behaves exactly as before. Lenigas entries
    # likewise use a "lenigas/"-prefixed API key (e.g.
    # "lenigas/bite_score_lenigas") routing to the SEPARATE
    # `/api/date-layer-lenigas/` endpoint -- also purely additive.
    _date_layer_by_name = {
        "Bite Score heatmap (current, high-res)": ("bite_score", heatmap_var),
        "Bite Score heatmap (legacy, coarse - for comparison)": ("legacy", legacy_var),
        "Ocean fronts (FSLE)": ("fsle", fsle_var),
        "Sea level anomaly (altimetry)": ("sla", sla_var),
        "Bite Score heatmap v2 (Beta - structure/eddy model)": ("v2/bite_score_v2", v2_heatmap_var),
        "Bite Score heatmap Lenigas (SEQ fisherman model)": ("lenigas/bite_score_lenigas", lenigas_heatmap_var),
    }
    for key, (factor_name, factor_layer) in factor_vars.items():
        _date_layer_by_name[factor_name] = (key, factor_layer.get_name())
    for key, (factor_name_v2, factor_layer_v2) in factor_vars_v2.items():
        _date_layer_by_name[factor_name_v2] = (f"v2/{key}", factor_layer_v2.get_name())
    for key, (factor_name_lenigas, factor_layer_lenigas) in factor_vars_lenigas.items():
        _date_layer_by_name[factor_name_lenigas] = (f"lenigas/{key}", factor_layer_lenigas.get_name())

    # ---- Per-layer legends + info icons (2026-07-24, Lambert) ----
    # `_layer_ui` maps every selectable overlay's exact Layers-list label
    # to {"info": <reused description text>, "legend": {...}} -- consumed
    # client-side by `bsqEnhanceLayerRows()` (JS below) to render an info
    # icon + a compact mini colour-scale legend next to each layer's
    # checkbox, without hand-writing per-layer HTML: every "info" string
    # below is lifted straight from the existing `_CONTRIBUTING_LAYERS*`
    # descriptions or the existing accordion copy elsewhere in this file
    # (see each entry's comment), never new fisheries-science claims.
    # "legend" kinds:
    #   "score"      -- 0-100 normalized WLC factor/composite (Turbo scale,
    #                    same as the main on-map legend above).
    #   "raw"        -- a real-unit informational layer that is NOT 0-100
    #                    normalized (v1's raw-metres MLD diagnostic, and
    #                    Lenigas's informational wind-speed layer).
    #   "diverging"  -- literal bathymetry/relief elevation (metres,
    #                    positive = underwater depth, negative = land).
    #   "diagnostic" -- FSLE (own percentile-normalized scale, 1/day).
    #   "none"       -- vector/reference layers with no numeric scale
    #                    (still get an info icon, just no legend bar).
    _bathymetry_desc = next(m["description"] for m in _CONTRIBUTING_LAYERS if m["key"] == "bathymetry")
    # "role": "factor" | "composite" (2026-07-23, Lambert) -- lets
    # `bsqEnhanceLayerRows()` (JS below) style each model's main heatmap
    # row distinctly (bolder/larger) and visually indent/nest its own
    # contributing-factor rows underneath it in the Layers list, without
    # guessing the relationship from label text. "weight_pct"/
    # "informational" (factor rows only) are rendered as a small pill next
    # to the row instead of being baked into the raw label string above.
    _layer_ui = {}
    for meta in _CONTRIBUTING_LAYERS:
        if meta["key"] == "bathymetry":
            continue
        factor_name, _layer = factor_vars[meta["key"]]
        legend_kind = {"kind": "raw", "unit": "m"} if meta["key"] == "mld" else {"kind": "score"}
        factor_weight_pct = config.LAYER_WEIGHTS.get(meta["weight_key"], 0) * 100
        _layer_ui[factor_name] = {
            "info": meta["description"], "legend": legend_kind,
            "role": "factor", "weight_pct": round(factor_weight_pct),
        }
    depth_weight_pct = config.LAYER_WEIGHTS.get("bathymetry", 0) * 100
    _layer_ui[depth_suitability_name] = {
        "info": _bathymetry_desc, "legend": {"kind": "score"},
        "role": "factor", "weight_pct": round(depth_weight_pct),
    }
    for meta in _CONTRIBUTING_LAYERS_V2:
        factor_name_v2, _layer = factor_vars_v2[meta["key"]]
        factor_weight_pct_v2 = config.LAYER_WEIGHTS_V2.get(meta["weight_key"], 0) * 100
        _layer_ui[factor_name_v2] = {
            "info": meta["description"], "legend": {"kind": "score"},
            "role": "factor", "weight_pct": round(factor_weight_pct_v2),
        }
    for meta in _CONTRIBUTING_LAYERS_LENIGAS:
        factor_name_lenigas, _layer = factor_vars_lenigas[meta["key"]]
        legend_kind = {"kind": "raw", "unit": "m/s"} if meta["key"] == "wind_speed" else {"kind": "score"}
        _ui_entry = {"info": meta["description"], "legend": legend_kind, "role": "factor"}
        if meta["weight_key"] is None:
            _ui_entry["informational"] = True
        else:
            _ui_entry["weight_pct"] = round(config.LAYER_WEIGHTS_LENIGAS.get(meta["weight_key"], 0) * 100)
        _layer_ui[factor_name_lenigas] = _ui_entry

    _layer_ui["Bite Score heatmap (current, high-res)"] = {
        "info": (
            "The final Yellowfin Tuna Bite Score (0-100): a Weighted Linear "
            "Combination of the six factors below (SST thermal fronts, "
            "chlorophyll fronts, current edges, SSHA/eddy fronts, MLD "
            "fronts and depth suitability), all resampled onto the fine "
            "bathymetry grid before blending."
        ),
        "legend": {"kind": "score"},
        "role": "composite",
    }
    _layer_ui["Bite Score heatmap (legacy, coarse - for comparison)"] = {
        "info": (
            "The original, lower-resolution scoring approach (SST as the "
            "alignment reference, nearest-neighbour resampling, no SSHA/MLD "
            "factors) -- kept only for direct comparison against the "
            "current, more accurate overlay above."
        ),
        "legend": {"kind": "score"},
        "role": "composite",
    }
    _layer_ui["Ocean fronts (FSLE)"] = {
        "info": (
            "A Finite-Size Lyapunov Exponent (FSLE) field highlighting the "
            "thin, filamentary ocean fronts where converging surface "
            "currents concentrate drifting plankton and baitfish -- an "
            "independent diagnostic layer, not one of the six weighted "
            "Bite Score factors. Shown on its own 95th-percentile-clipped "
            "scale (units 1/day), not 0-100."
        ),
        "legend": {"kind": "diagnostic", "unit": "1/day"},
    }
    _layer_ui["Sea level anomaly (altimetry)"] = {
        "info": (
            "Satellite altimetry Sea Level Anomaly (SLA) from multi-mission "
            "radar altimeters (Jason-3, Sentinel-3, CryoSat-2 and others). "
            "Red = positive SLA (warm-core EAC eddy, elevated sea surface), "
            "blue = negative SLA (cold-core eddy or upwelling zone). "
            "An independent reference layer -- not a Bite Score factor. "
            "Not available for every date (2017-present archive, ~3-day latency)."
        ),
        "legend": {"kind": "diverging_sla", "unit": "m"},
    }
    _layer_ui["Sea level anomaly contours"] = {
        "info": (
            "Contour lines of the Sea Level Anomaly field at ±0.1, ±0.2 and "
            "±0.3 m, plus the zero-crossing (grey dashed). "
            "Red lines = positive SLA (warm-core EAC eddies / ridge structures); "
            "blue lines = negative SLA (cold-core eddies or upwelling zones). "
            "Thicker lines indicate stronger anomalies. "
            "Helps trace eddy boundaries that can be hard to read from the heatmap alone. "
            "Not available for dates without an SLA layer."
        ),
    }
    _layer_ui["Bite Score heatmap v2 (Beta - structure/eddy model)"] = {
        "info": (
            "A separate, experimental scoring model -- seafloor-structure "
            "proximity, real vorticity-based eddy detection, bell-curve "
            "SST, optimal-band chlorophyll and a seasonal multiplier. Not "
            "validated against catch data the way v1 has been -- treat it "
            "as a second opinion, not a replacement for v1."
        ),
        "legend": {"kind": "score"},
        "role": "composite",
    }
    _layer_ui["Bite Score heatmap Lenigas (SEQ fisherman model)"] = {
        "info": (
            "A second, independent, experimental scoring model built from "
            "a real SEQ fisherman podcast account's informally-described "
            "conditions (EAC axis position/convergence, distance offshore, "
            "upwelling/downwelling, its own SST bell curve and depth-"
            "suitability ramp). Not validated against catch data -- an "
            "informal third opinion, not a replacement for v1 or v2."
        ),
        "legend": {"kind": "score"},
        "role": "composite",
    }
    _layer_ui["Bathymetry relief map"] = {
        "info": (
            "A single, unified shaded-relief view of every real bathymetry "
            "source this project has. A whole-of-AOI base is Geoscience "
            "Australia's AusBathyTopo 2024, kept at its own native ~250m "
            "resolution (not upsampled -- that used to make the shelf look "
            "artificially flat), with GEBCO (~450m) only as a last-resort "
            "fallback. AusSeabed's Moreton Bay Approaches (30m) and "
            "Mudjimba Island (0.5m) multibeam surveys, plus the Sunshine "
            "Coast LiDAR survey (10m), are layered on top at THEIR own "
            "native resolutions wherever they cover the AOI, so the "
            "sharpest real detail is always shown, not averaged away onto "
            "one common grid. Colour bands are fixed real-metre depth/"
            "elevation steps (finer near the surface) rather than a smooth "
            "gradient, so depth changes stay visible at a glance. Legend "
            "shows raw depth in metres (negative values = land)."
        ),
        "legend": {"kind": "diverging", "unit": "m"},
    }
    _layer_ui["Bathymetry contours (depth reference)"] = {
        "info": (
            "Isobath (depth contour) lines derived from the static "
            "composite bathymetry grid and labelled in metres -- a fixed "
            "reference for judging position/scale, identical on every "
            "date."
        ),
        "legend": {"kind": "none"},
    }
    _layer_ui["Land outline"] = {
        "info": (
            "The coastline, traced directly from the Depth-suitability "
            "score raster's own land (nodata) mask -- pixel-perfectly "
            "aligned with every other layer on this map."
        ),
        "legend": {"kind": "none"},
    }
    _layer_ui["MBGFC fishing chart (georeferenced)"] = {
        "info": (
            "A scanned Moreton Bay Game Fish Club nautical chart showing "
            "named reefs, banks and fishing grounds from Noosa to the "
            "Gold Coast, georeferenced using its own printed lat/lon grid. "
            "Reference only, not for navigation."
        ),
        "legend": {"kind": "none"},
    }
    _layer_ui["MBGFC FADs, SFADs & wave buoys"] = {
        "info": (
            "Exact FAD/SFAD/wave-buoy coordinates and depths, parsed "
            "directly from the MBGFC chart's own text table (not "
            "estimated from the scanned image)."
        ),
        "legend": {"kind": "none"},
    }
    _layer_ui_json = json.dumps(_layer_ui)

    # Reverse lookups (label -> API key) so the JS loaders below can find
    # the right mini-legend row to update with a layer's live min/max once
    # its meta is fetched -- built from the SAME `_date_layer_by_name` dict
    # above (per-date layers) plus a small static one (RASTER_LAYERS keys),
    # so there's exactly one source of truth for every key<->label pairing.
    _key_to_label = {key: label for label, (key, _var) in _date_layer_by_name.items()}
    _key_to_label_json = json.dumps(_key_to_label)
    _static_key_to_label = {
        "depth_suitability": depth_suitability_name,
        "relief_map": "Bathymetry relief map",
        "relief_map_moreton_bay_approaches": "Bathymetry relief map",
        "relief_map_lidar": "Bathymetry relief map",
        "relief_map_mudjimba_island": "Bathymetry relief map",
    }
    _static_key_to_label_json = json.dumps(_static_key_to_label)

    # JS lookup from each overlay's Layers-list label to its dedicated pane
    # variable (see _add_pane() above) -- lets bsqEnableLayerReorder() set
    # `pane.style.zIndex` directly to match list order, regardless of
    # whether the underlying layer is a raster ImageOverlay or a vector
    # GeoJson/FeatureGroup. Built as a *function* (called from inside the
    # DOMContentLoaded handler below) rather than a top-level `var ... =`
    # assignment, since Folium declares each `pane_xxx` variable in its own
    # <script> tag that's emitted later in the document -- referencing them
    # eagerly here (before that later script has run) would throw a
    # ReferenceError. By DOMContentLoaded time every script tag in the page
    # has already executed, so all `pane_xxx` globals are guaranteed to exist.
    pane_map_entries = ",\n          ".join(
        f"{json.dumps(label)}: {var_name}" for label, var_name in _pane_vars.items()
    )
    pane_map_js = (
        f"function bsqInitLayerPanes() {{\n"
        f"        bsqLayerPanes = {{\n          {pane_map_entries}\n        }};\n"
        f"      }}"
    )
    # Same eager-vs-later-script-tag issue as the pane lookup above, since
    # this references each per-date layer's own `var image_overlay_xxx`
    # identifier -- wrapped in a function, called from DOMContentLoaded.
    date_layer_map_entries = ",\n          ".join(
        f"{json.dumps(name)}: {{key: {json.dumps(key)}, layer: {var_name}}}"
        for name, (key, var_name) in _date_layer_by_name.items()
    )
    date_layer_map_js = (
        f"function bsqInitDateLayers() {{\n"
        f"        bsqDateLayerByName = {{\n          {date_layer_map_entries}\n        }};\n"
        f"      }}"
    )
    mbgfc_locations_pane_json = json.dumps(mbgfc_locations_pane)
    waypoints_pane_json = json.dumps(waypoints_pane)
    land_outline_pane_json = json.dumps(land_outline_pane)
    contour_pane_json = json.dumps(contour_pane)
    sla_contour_pane_json = json.dumps(sla_contour_pane)
    depth_suitability_name_json = json.dumps(depth_suitability_name)

    legacy_slider_html = """
        <div id="bsq-opacity-row">
          <label for="bsq-opacity-legacy">Legacy overlay opacity <span class="bsq-hint">(enable it in the layer list first)</span></label>
          <input type="range" id="bsq-opacity-legacy" min="0" max="1" step="0.05" value="0.78"
                 oninput="bsqSetLegacyOpacity(this.value)">
        </div>
        """

    legacy_js = f"""
      function bsqSetLegacyOpacity(v) {{
        try {{ {legacy_var}.setOpacity(parseFloat(v)); }} catch (e) {{}}
      }}
        """

    # "How It's Calculated" explanation: built from the same config weights
    # that actually drive the WLC overlay, so this stays accurate if the
    # weights are ever re-tuned rather than describing a hardcoded formula.
    methodology_rows = []
    for meta in _CONTRIBUTING_LAYERS:
        weight_pct = config.LAYER_WEIGHTS.get(meta["weight_key"], 0) * 100
        methodology_rows.append(
            f"""
            <div class="bsq-factor-row">
              <div class="bsq-factor-head">
                <span class="material-symbols-outlined">{meta['icon']}</span>
                <span class="bsq-factor-label">{meta['label']}</span>
                <span class="bsq-factor-weight">{weight_pct:.0f}%</span>
              </div>
              <p class="bsq-factor-desc">{meta['description']}</p>
            </div>
            """
        )
    methodology_html = "".join(methodology_rows)

    # "Mixed Layer Depth (MLD) Front" explanation: describes the newest
    # Copernicus-sourced factor layer (see _CONTRIBUTING_LAYERS above and
    # date_layers.py's "mld" entry). Unlike the 4 longer-established
    # factors (SST/chl/current/SSHA), Ripley hasn't finished wiring this
    # into config.LAYER_WEIGHTS/overlay.py yet (see
    # .squad/decisions/inbox/ash-mld-moonphase.md), so this section gets
    # its own accordion with an explicit "not yet scored" caveat rather
    # than being folded silently into methodology_html's 0%-weight row.
    # Same per-date availability caveat as FSLE below -- the Copernicus
    # mlotst fetch degrades gracefully (skipped, not fatal) if it fails or
    # the assumed dataset id turns out to be wrong for a given date.
    mld_availability_html = (
        '<p class="bsq-sub">Toggle on <strong>&ldquo;Factor: MLD front '
        'score&rdquo;</strong> in the Layers list above. Not available for '
        'every date -- the Copernicus mixed layer depth fetch degrades '
        'gracefully (skipped, with a warning) if it fails for that date, '
        'the same as FSLE below.</p>'
        '<p class="bsq-sub"><strong>Reading it:</strong> this layer shows '
        'the raw <code>mlotst</code> depth field (metres, see its own mini '
        'legend once toggled on) -- not the normalized 0-100 gradient/'
        'front-strength value that actually feeds the weight above, which '
        'isn&rsquo;t currently exported as its own visual layer.</p>'
    )

    mld_section_html = f"""
      <div class="bsq-section">
        <div class="bsq-accordion-header" id="bsq-mld-toggle">
          <h3><span class="material-symbols-outlined">layers</span>Mixed Layer Depth (MLD) Front</h3>
          <span class="material-symbols-outlined bsq-chevron">expand_more</span>
        </div>
        <div class="bsq-accordion-body" id="bsq-mld-body">
          <p class="bsq-sub">A shoaling (shallower) mixed layer compresses baitfish and forage species closer to the surface, within easier reach of surface-feeding tuna -- particularly meaningful where it coincides with the thermal/chlorophyll fronts already scored above.</p>
          <div class="bsq-factor-row">
            <div class="bsq-factor-head">
              <span class="material-symbols-outlined">travel_explore</span>
              <span class="bsq-factor-label">Data source</span>
            </div>
            <p class="bsq-factor-desc">Copernicus Marine mixed layer thickness (<code>mlotst</code>), the same physics product family already used for SSHA/currents above.</p>
          </div>
          <div class="bsq-factor-row">
            <div class="bsq-factor-head">
              <span class="material-symbols-outlined">grid_on</span>
              <span class="bsq-factor-label">Method</span>
            </div>
            <p class="bsq-factor-desc">Displayed here as the raw depth field (metres) on its own percentile-clipped scale, brighter where the mixed layer is shallower. Ripley is still wiring this into a gradient/front-strength score alongside the other four WLC factors above.</p>
          </div>
          <div class="bsq-factor-row">
            <div class="bsq-factor-head">
              <span class="material-symbols-outlined">colorize</span>
              <span class="bsq-factor-label">Reading it</span>
            </div>
            <p class="bsq-factor-desc">Brighter areas are a shallower (shoaled) mixed layer; darker areas are deeper mixing -- look for bright patches lining up with the SST/chlorophyll front layers above.</p>
          </div>
          {mld_availability_html}
        </div>
      </div>
    """

    # "How FSLE Is Calculated" explanation: a separate, independent
    # diagnostic layer (not part of the WLC formula above), so it gets its
    # own accordion rather than being folded into methodology_html.
    # Availability depends on which date is resolved client-side (it
    # requires several forecast days beyond that date, not always
    # available e.g. for far-past historical dates), so -- unlike the old
    # per-date-generated-HTML version -- this can't be decided here at
    # template-generation time; toggling it on for an unavailable date
    # simply fails gracefully (a console warning), same as any other
    # missing per-date/static layer.
    fsle_availability_html = (
        '<p class="bsq-sub">Toggle on <strong>&ldquo;Ocean fronts (FSLE)&rdquo;</strong> '
        'in the Layers list above. Not available for every date -- it requires several '
        'days of forecast surface-current data beyond the selected date, which '
        'isn&rsquo;t always available (e.g. for far-past historical dates).</p>'
    )

    fsle_section_html = f"""
      <div class="bsq-section">
        <div class="bsq-accordion-header" id="bsq-fsle-toggle">
          <h3><span class="material-symbols-outlined">air</span>Ocean Fronts (FSLE)</h3>
          <span class="material-symbols-outlined bsq-chevron">expand_more</span>
        </div>
        <div class="bsq-accordion-body" id="bsq-fsle-body">
          <p class="bsq-sub">A Finite-Size Lyapunov Exponent (FSLE) highlights the thin, filamentary ocean fronts where converging surface currents concentrate drifting plankton and baitfish -- a Lagrangian signal invisible in any single day's current snapshot.</p>
          <div class="bsq-factor-row">
            <div class="bsq-factor-head">
              <span class="material-symbols-outlined">travel_explore</span>
              <span class="bsq-factor-label">Data source</span>
            </div>
            <p class="bsq-factor-desc">Free daily surface current vectors (u/v) from the Copernicus Marine Data Store, including several forecast days beyond the selected date.</p>
          </div>
          <div class="bsq-factor-row">
            <div class="bsq-factor-head">
              <span class="material-symbols-outlined">scatter_plot</span>
              <span class="bsq-factor-label">Method</span>
            </div>
            <p class="bsq-factor-desc">A dense grid of virtual particle pairs is advected forward through the current field with a 4th-order Runge-Kutta integrator. Each pair's separation is tracked until it grows from an initial distance &delta;&#8320; to a final threshold &delta;<sub>f</sub>, taking time &tau;.</p>
          </div>
          <div class="bsq-factor-row">
            <div class="bsq-factor-head">
              <span class="material-symbols-outlined">functions</span>
              <span class="bsq-factor-label">Formula</span>
            </div>
            <p class="bsq-factor-desc">&lambda; = (1&frasl;&tau;) &middot; ln(&delta;<sub>f</sub> &frasl; &delta;&#8320;), in units of 1/day. Brighter ridges mean faster separation, i.e. sharper convergence fronts.</p>
          </div>
          {fsle_availability_html}
        </div>
      </div>
    """

    sla_section_html = """
      <div class="bsq-section">
        <div class="bsq-accordion-header" id="bsq-sla-toggle">
          <h3><span class="material-symbols-outlined">water</span>Sea Level Anomaly (Altimetry)</h3>
          <span class="material-symbols-outlined bsq-chevron">expand_more</span>
        </div>
        <div class="bsq-accordion-body" id="bsq-sla-body">
          <p class="bsq-sub">Satellite radar altimetry measures the sea surface height relative to a long-term mean, revealing warm-core and cold-core eddies, EAC meanders, and upwelling zones -- features that concentrate baitfish and pelagic species.</p>
          <div class="bsq-factor-row">
            <div class="bsq-factor-head">
              <span class="material-symbols-outlined">satellite_alt</span>
              <span class="bsq-factor-label">Data source</span>
            </div>
            <p class="bsq-factor-desc">NOAA CoastWatch ERDDAP &mdash; <em>nesdisSSH1day</em>: multi-satellite merged altimetry product from the RADS database (Jason-3, Sentinel-3A, CryoSat-2, SARAL/AltiKa). 0.25&deg; daily global grid, archive from 2017 onward. Approx. 3-day near-real-time latency.</p>
          </div>
          <div class="bsq-factor-row">
            <div class="bsq-factor-head">
              <span class="material-symbols-outlined">palette</span>
              <span class="bsq-factor-label">Colour scale</span>
            </div>
            <p class="bsq-factor-desc"><strong style="color:#d73027">Red</strong> = positive SLA (sea surface elevated above mean &mdash; warm-core EAC eddy or southward EAC jet). <strong style="color:#4575b4">Blue</strong> = negative SLA (sea surface below mean &mdash; cold-core eddy or coastal upwelling). Scale clipped at &plusmn;0.4 m to suit typical EAC anomaly amplitudes.</p>
          </div>
          <div class="bsq-factor-row">
            <div class="bsq-factor-head">
              <span class="material-symbols-outlined">info</span>
              <span class="bsq-factor-label">How to use</span>
            </div>
            <p class="bsq-factor-desc">Strong positive SLA cells (red) indicate warm-core eddies that spin off the EAC and can concentrate juvenile tuna and baitfish at their edges. The sharpest edges and saddle-points between eddies of opposite sign are often the most productive fishing zones. Use this layer alongside the FSLE overlay to confirm which fronts are associated with real eddy structure.</p>
          </div>
          <p class="bsq-sub">Toggle on <strong>&ldquo;Sea level anomaly (altimetry)&rdquo;</strong> in the Layers list above. Not available for every date &mdash; archive begins 2017-02-13, and there may be gaps during satellite outages or processing delays.</p>
        </div>
      </div>
    """

    # "v2 Bite Score (Beta)" explanation: a SEPARATE, EXPERIMENTAL scoring
    # model (structure proximity, real vorticity-based eddy detection,
    # bell-curve SST, optimal-band chlorophyll, seasonal multiplier -- see
    # .squad/decisions/inbox/ripley-seq-v2-scoring-model.md), clearly
    # called out here so nobody mistakes it for v1's validated Bite Score
    # above. The `#bsq-v2-status` paragraph below is a LIVE readout (see
    # bsqCheckV2Availability() JS), not a static claim, since whether v2
    # has actually been run for the currently-viewed date can only be
    # known client-side.
    v2_methodology_rows = []
    for meta in _CONTRIBUTING_LAYERS_V2:
        weight_pct = config.LAYER_WEIGHTS_V2.get(meta["weight_key"], 0) * 100
        v2_methodology_rows.append(
            f"""
            <div class="bsq-factor-row">
              <div class="bsq-factor-head">
                <span class="material-symbols-outlined">{meta['icon']}</span>
                <span class="bsq-factor-label">{meta['label']}</span>
                <span class="bsq-factor-weight">{weight_pct:.0f}%</span>
              </div>
              <p class="bsq-factor-desc">{meta['description']}</p>
            </div>
            """
        )
    v2_methodology_html = "".join(v2_methodology_rows)

    v2_section_html = f"""
      <div class="bsq-section">
        <div class="bsq-accordion-header" id="bsq-v2-toggle">
          <h3><span class="material-symbols-outlined">science</span>v2 Bite Score (Beta)<span class="bsq-beta-pill">BETA</span></h3>
          <span class="material-symbols-outlined bsq-chevron">expand_more</span>
        </div>
        <div class="bsq-accordion-body" id="bsq-v2-body">
          <p class="bsq-sub"><strong>This is a separate, experimental scoring model</strong> -- not a refinement of the Bite Score above. It combines seafloor-structure proximity (shelf break + named canyons), real vorticity-based warm-core eddy detection, a bell-curve SST fit, an optimal-band chlorophyll fit, and a seasonal multiplier, using different weights and different inputs than v1. It has <strong>not</strong> been validated against catch data the way v1's model has -- treat it as a second opinion to compare against v1, not a replacement for it.</p>
          <p class="bsq-v2-status" id="bsq-v2-status">Checking v2 (Beta) availability...</p>
          <div class="bsq-factor-row">
            <div class="bsq-factor-head">
              <span class="material-symbols-outlined">toggle_on</span>
              <span class="bsq-factor-label">Viewing it</span>
            </div>
            <p class="bsq-factor-desc">Toggle on <strong>&ldquo;Bite Score heatmap v2 (Beta - structure/eddy model)&rdquo;</strong> in the Layers list above (near the top, alongside the v1 and legacy heatmaps) to compare it directly against v1's heatmap. Its 7 individual contributing factors are also available lower down in the Layers list, each labelled <strong>&ldquo;Factor (v2 Beta): ...&rdquo;</strong>.</p>
          </div>
          {v2_methodology_html}
          <div class="bsq-factor-row">
            <div class="bsq-factor-head">
              <span class="material-symbols-outlined">calendar_month</span>
              <span class="bsq-factor-label">Seasonal multiplier</span>
            </div>
            <p class="bsq-factor-desc">The combined score above is further scaled by a calendar-month multiplier: &times;1.0 Sep&ndash;Nov (peak season), &times;0.8 Dec&ndash;Jan and May&ndash;Aug (winter &ldquo;barrel run&rdquo;), &times;0.3 Feb&ndash;Apr (seasonal low).</p>
          </div>
          <p class="bsq-sub">Only available for a small number of test dates so far -- if it hasn&rsquo;t been run for the date you&rsquo;re viewing, the status above will say so and the heatmap toggle simply stays blank (v1&rsquo;s heatmap is completely unaffected either way).</p>
        </div>
      </div>
    """

    # "Lenigas Bite Score" explanation: a SECOND, INDEPENDENT, EXPERIMENTAL
    # scoring model built from a real SEQ fisherman podcast account (EAC
    # axis position/convergence, distance offshore, upwelling/downwelling,
    # its own SST bell curve and depth-suitability ramp -- see
    # .squad/decisions/inbox/ripley-lenigas-pipeline.md), clearly called
    # out here so nobody mistakes it for v1's validated Bite Score or v2's
    # oceanographic-structure model above. The `#bsq-lenigas-status`
    # paragraph below is a LIVE readout (see bsqCheckLenigasAvailability()
    # JS), not a static claim, since whether Lenigas has actually been run
    # for the currently-viewed date can only be known client-side. Always
    # "Lenigas", never "v3".
    lenigas_methodology_rows = []
    for meta in _CONTRIBUTING_LAYERS_LENIGAS:
        if meta["weight_key"] is None:
            weight_html = ""
        else:
            weight_pct = config.LAYER_WEIGHTS_LENIGAS.get(meta["weight_key"], 0) * 100
            weight_html = f'<span class="bsq-factor-weight">{weight_pct:.0f}%</span>'
        lenigas_methodology_rows.append(
            f"""
            <div class="bsq-factor-row">
              <div class="bsq-factor-head">
                <span class="material-symbols-outlined">{meta['icon']}</span>
                <span class="bsq-factor-label">{meta['label']}</span>
                {weight_html}
              </div>
              <p class="bsq-factor-desc">{meta['description']}</p>
            </div>
            """
        )
    lenigas_methodology_html = "".join(lenigas_methodology_rows)

    lenigas_section_html = f"""
      <div class="bsq-section">
        <div class="bsq-accordion-header" id="bsq-lenigas-toggle">
          <h3><span class="material-symbols-outlined">record_voice_over</span>Lenigas Bite Score<span class="bsq-beta-pill">EXPERIMENTAL</span></h3>
          <span class="material-symbols-outlined bsq-chevron">expand_more</span>
        </div>
        <div class="bsq-accordion-body" id="bsq-lenigas-body">
          <p class="bsq-sub"><strong>This is a second, independent, experimental scoring model</strong> -- built from a real SEQ fisherman podcast account's informally-described conditions, not a refinement of v1 or v2 above. It combines EAC axis-position and convergence-point scores, a distance-offshore ramp, an upwelling/downwelling vorticity score, its own SST bell curve and depth-suitability ramp, using different weights and different inputs than either v1 or v2. It has <strong>not</strong> been validated against catch data -- treat it as an informal, experimental third opinion, not a replacement for v1 or v2.</p>
          <p class="bsq-lenigas-status" id="bsq-lenigas-status">Checking Lenigas availability...</p>
          <div class="bsq-factor-row">
            <div class="bsq-factor-head">
              <span class="material-symbols-outlined">toggle_on</span>
              <span class="bsq-factor-label">Viewing it</span>
            </div>
            <p class="bsq-factor-desc">Toggle on <strong>&ldquo;Bite Score heatmap Lenigas (SEQ fisherman model)&rdquo;</strong> in the Layers list above (alongside the v1, legacy and v2 heatmaps) to compare it directly against them. Its 6 individual WLC factors plus an informational wind-speed layer are also available lower down in the Layers list, each labelled <strong>&ldquo;Factor (Lenigas): ...&rdquo;</strong>.</p>
          </div>
          {lenigas_methodology_html}
          <p class="bsq-sub">Only available for a small number of test dates so far -- if it hasn&rsquo;t been run for the date you&rsquo;re viewing, the status above will say so and the heatmap toggle simply stays blank (v1's and v2's heatmaps are completely unaffected either way).</p>
        </div>
      </div>
    """

    # "Bathymetry Relief Map" explanation: describes the single unified
    # shaded-relief toggle, which is really 4 stacked image layers -- a
    # whole-AOI AusBathyTopo-based base at its own native ~250m
    # resolution, plus the 3 real local surveys (Moreton Bay Approaches,
    # Mudjimba Island, Sunshine Coast LiDAR) layered on top at THEIR OWN
    # native resolutions -- bundled under one toggle instead of the 4
    # separate top-level layers this used to be.
    relief_map_availability_html = (
        '<p class="bsq-sub">Toggle on <strong>&ldquo;Bathymetry relief '
        'map&rdquo;</strong> in the Layers list above. Loaded on demand from '
        'the local dashboard server (<code>python -m bite_score.webapp</code>) the '
        'first time it&rsquo;s switched on.</p>'
    )

    relief_map_section_html = f"""
      <div class="bsq-section">
        <div class="bsq-accordion-header" id="bsq-relief-toggle">
          <h3><span class="material-symbols-outlined">terrain</span>Bathymetry Relief Map</h3>
          <span class="material-symbols-outlined bsq-chevron">expand_more</span>
        </div>
        <div class="bsq-accordion-body" id="bsq-relief-body">
          <p class="bsq-sub">A single shaded-relief (hillshade) view of the sea floor across the whole map area -- one toggle, but really 4 image layers stacked together so every real survey shows at its own best resolution, not averaged down onto one common grid.</p>
          <div class="bsq-factor-row">
            <div class="bsq-factor-head">
              <span class="material-symbols-outlined">public</span>
              <span class="bsq-factor-label">Data source</span>
            </div>
            <p class="bsq-factor-desc">Geoscience Australia&rsquo;s AusBathyTopo 2024 grid (250m, whole-of-AOI) as the base, with the AusSeabed Moreton Bay Approaches (30m) and Mudjimba Island (0.5m) multibeam surveys and the Sunshine Coast LiDAR survey (10m) layered on top wherever each one covers the AOI -- GEBCO (~450m) is used only as a last-resort fallback outside all of those.</p>
          </div>
          <div class="bsq-factor-row">
            <div class="bsq-factor-head">
              <span class="material-symbols-outlined">grid_on</span>
              <span class="bsq-factor-label">Method</span>
            </div>
            <p class="bsq-factor-desc">Each source is kept at ITS OWN native pixel resolution rather than being resampled onto one shared grid -- so the small local surveys never lose real detail, and the whole-AOI base isn&rsquo;t artificially smoothed by being upsampled onto a finer grid than it actually has data for. Rendered with fixed real-metre depth/elevation colour bands (finer near the surface) rather than a smooth gradient, so depth changes stay visible even across a range spanning land down to the deep continental slope.</p>
          </div>
          <div class="bsq-factor-row">
            <div class="bsq-factor-head">
              <span class="material-symbols-outlined">colorize</span>
              <span class="bsq-factor-label">Reading it</span>
            </div>
            <p class="bsq-factor-desc">Blue shades are underwater depth (darker = deeper); green/brown shades are land. Look for visibly sharper, crisper detail over the Sunshine Coast, Moreton Bay approaches and Mudjimba Island -- the areas backed by the finest real survey data, now shown at their true native resolution.</p>
          </div>
          {relief_map_availability_html}
        </div>
      </div>
    """

    # "MBGFC Fishing Chart" explanation: describes the georeferenced
    # nautical chart + coordinate table, both sourced from the same static
    # PDF one-pager (not tied to any pipeline run date). The layer itself
    # is always registered above; its actual content is fetched from the
    # dashboard server when toggled on, so it only "works" when the page
    # is served via `python -m bite_score.webapp` (same requirement as the
    # "Update Data" button and "Historical Data" list above).
    mbgfc_availability_html = (
        '<p class="bsq-sub">Toggle on <strong>&ldquo;MBGFC fishing chart&rdquo;</strong> '
        'and <strong>&ldquo;MBGFC FADs, SFADs &amp; wave buoys&rdquo;</strong> in the '
        'Layers list above. Loaded on demand from the local dashboard server '
        '(<code>python -m bite_score.webapp</code>) the first time either is switched '
        'on, so this layer is always available on every date&rsquo;s map without '
        'needing to be regenerated.</p>'
    )

    mbgfc_section_html = f"""
      <div class="bsq-section">
        <div class="bsq-accordion-header" id="bsq-mbgfc-toggle">
          <h3><span class="material-symbols-outlined">map</span>MBGFC Fishing Chart</h3>
          <span class="material-symbols-outlined bsq-chevron">expand_more</span>
        </div>
        <div class="bsq-accordion-body" id="bsq-mbgfc-body">
          <p class="bsq-sub">A scanned nautical chart published by the Moreton Bay Game Fish Club, showing named reefs, banks and fishing grounds from Noosa to the Gold Coast, georeferenced onto the map using its own printed lat/lon grid.</p>
          <div class="bsq-factor-row">
            <div class="bsq-factor-head">
              <span class="material-symbols-outlined">description</span>
              <span class="bsq-factor-label">Data source</span>
            </div>
            <p class="bsq-factor-desc">MBGFC "Fishing Locations & Info" one-pager PDF (mbgfc.com.au) -- a scanned chart image plus a text table of exact FAD/SFAD/wave-buoy coordinates and depths.</p>
          </div>
          <div class="bsq-factor-row">
            <div class="bsq-factor-head">
              <span class="material-symbols-outlined">grid_on</span>
              <span class="bsq-factor-label">Method</span>
            </div>
            <p class="bsq-factor-desc">The chart's own printed degree gridlines (153&ndash;155&deg;E, 26&ndash;28&deg;S) were located pixel-by-pixel and used to fit a linear lon/lat transform; the FAD/SFAD/wave-buoy markers are parsed directly from the PDF's text table, not estimated from the image.</p>
          </div>
          <div class="bsq-factor-row">
            <div class="bsq-factor-head">
              <span class="material-symbols-outlined">warning</span>
              <span class="bsq-factor-label">Caveat</span>
            </div>
            <p class="bsq-factor-desc">Reference only, not for navigation -- print/scan registration may introduce small (sub-100m scale) positional error in the chart image itself.</p>
          </div>
          {mbgfc_availability_html}
        </div>
      </div>
    """

    # Mini colour-scale gradients for the per-layer legend bars added by
    # `bsqEnhanceLayerRows()` below -- one per `_layer_ui` "legend.kind",
    # each a CSS-ready comma-joined hex-colour list. "score" reuses the
    # exact same Turbo stops as the main on-map legend above (visual
    # consistency); "raw" approximates the reversed-viridis colormap
    # `mld_to_rgba()` actually renders with; "diverging" approximates the
    # "terrain" colormap `bathymetry_hillshade_to_rgba()` renders with;
    # "diagnostic" approximates the "inferno" colormap `fsle_to_rgba()`
    # renders with. These are indicative UI swatches only -- the real map
    # layers still use matplotlib's actual colormaps, not these CSS stops.
    _score_gradient_css = ", ".join(_LEGEND_COLORS)
    _raw_gradient_css = ", ".join(
        ["#fde725", "#b5de2b", "#6ece58", "#35b779", "#1f9e89", "#26828e", "#31688e", "#3e4a89", "#482878", "#440154"]
    )
    _diverging_gradient_css = ", ".join(
        ["#26456e", "#1f78b4", "#5ab4d6", "#a6d9c8", "#8bc47a", "#c9a86a", "#e8dcc4"]
    )
    _diagnostic_gradient_css = ", ".join(
        ["#000004", "#1b0c41", "#4a0c6b", "#781c6d", "#a52c60", "#cf4446", "#ed6925", "#fb9b06", "#f7d03c", "#fcffa4"]
    )
    # Blue/white/red diverging gradient for the SLA layer, matching RdBu_r colormap
    # (negative SLA = blue/cold, zero = white, positive SLA = red/warm).
    _sla_gradient_css = ", ".join(
        ["#4575b4", "#74add1", "#abd9e9", "#e0f3f8", "#ffffff", "#fee090", "#fdae61", "#f46d43", "#d73027"]
    )

    control_html = f"""
    <style>
      html, body {{
        margin: 0; padding: 0; height: 100%; background: #0b1326;
        color: #dae2fd; font-family: 'Inter', -apple-system, Segoe UI, Roboto, Arial, sans-serif;
        overflow: hidden;
      }}

      /* The map fills the whole viewport to the right of the sidebar --
         no floating header/panel/drawer sits on top of it any more, so
         the coastline, bathymetry and heatmap stay fully visible.
         invalidateSize() is called after load to make Leaflet recompute
         tile layout for the new container size. */
      #{map_var} {{
        position: fixed !important;
        top: 0 !important;
        left: 320px !important;
        right: 0 !important;
        bottom: 54px !important;
        width: auto !important;
        height: auto !important;
      }}

      /* ---- Date timeline bar ---- */
      .bsq-timeline {{
        position: fixed; bottom: 0; left: 320px; right: 0; height: 54px;
        background: #0b1326; border-top: 1px solid rgba(142,145,152,0.18);
        z-index: 999; display: flex; align-items: center;
        padding: 0 20px 0 16px; box-sizing: border-box; user-select: none;
      }}
      .bsq-tl-track-wrap {{
        position: relative; flex: 1; height: 100%; display: flex; align-items: center;
      }}
      .bsq-tl-track {{
        position: absolute; left: 0; right: 0; top: 50%; height: 2px;
        background: rgba(142,145,152,0.22); border-radius: 1px;
        transform: translateY(-50%);
      }}
      .bsq-tl-year-tick {{
        position: absolute; bottom: calc(50% + 4px);
        width: 1px; height: 6px; background: rgba(142,145,152,0.35);
      }}
      .bsq-tl-year-label {{
        position: absolute; bottom: calc(50% + 12px);
        transform: translateX(-50%);
        font-size: 9px; color: #8e9198; letter-spacing: 0.04em;
        white-space: nowrap; pointer-events: none;
      }}
      .bsq-tl-dot {{
        position: absolute; top: 50%; transform: translate(-50%, -50%);
        width: 8px; height: 8px; border-radius: 50%;
        background: rgba(99,247,255,0.35); border: 1.5px solid rgba(99,247,255,0.5);
        cursor: pointer; transition: background 0.15s, transform 0.15s;
        z-index: 1;
      }}
      .bsq-tl-dot:hover {{
        background: rgba(99,247,255,0.7); transform: translate(-50%, -50%) scale(1.5);
        z-index: 3;
      }}
      .bsq-tl-dot.current {{
        background: #63f7ff; border-color: #63f7ff;
        width: 12px; height: 12px; z-index: 2;
        box-shadow: 0 0 8px rgba(99,247,255,0.6);
      }}
      .bsq-tl-dot.current:hover {{
        transform: translate(-50%, -50%) scale(1.3);
      }}
      .bsq-tl-label-current {{
        position: absolute; top: calc(50% + 9px);
        transform: translateX(-50%);
        font-size: 9px; font-weight: 700; color: #63f7ff;
        white-space: nowrap; pointer-events: none; letter-spacing: 0.03em;
      }}
      .bsq-tl-tooltip {{
        position: fixed; padding: 4px 8px; background: #1a2440;
        border: 1px solid rgba(99,247,255,0.4); border-radius: 5px;
        font-size: 11px; color: #dae2fd; pointer-events: none;
        white-space: nowrap; z-index: 2000; display: none;
      }}
      .bsq-tl-latest-btn {{
        flex-shrink: 0; margin-left: 10px;
        display: flex; align-items: center; gap: 4px;
        font-size: 11px; color: #63f7ff; cursor: pointer; opacity: 0.75;
        border: 1px solid rgba(99,247,255,0.3); border-radius: 5px;
        padding: 3px 8px; background: transparent; transition: opacity 0.15s;
        white-space: nowrap;
      }}
      .bsq-tl-latest-btn:hover {{ opacity: 1; }}
      .bsq-tl-latest-btn .material-symbols-outlined {{ font-size: 13px; }}
      .bsq-tl-zoom-label {{
        flex-shrink: 0; font-size: 10px; color: #8e9198; margin-right: 8px;
        white-space: nowrap; cursor: pointer; display: none; transition: color 0.15s;
      }}
      .bsq-tl-zoom-label.visible {{ display: block; }}
      .bsq-tl-zoom-label:hover {{ color: #63f7ff; }}
      .bsq-tl-track-wrap {{ cursor: ew-resize; }}
      .bsq-tl-track-wrap.dragging {{ cursor: grabbing; }}

      .bsq-sidebar {{
        position: fixed; top: 0; left: 0; bottom: 0; width: 320px;
        background: #0b1326; border-right: 1px solid rgba(142,145,152,0.15);
        display: flex; flex-direction: column; overflow-y: auto;
        z-index: 1000; box-sizing: border-box;
      }}
      .bsq-sidebar::-webkit-scrollbar {{ width: 6px; }}
      .bsq-sidebar::-webkit-scrollbar-thumb {{ background: rgba(142,145,152,0.3); border-radius: 3px; }}

      .bsq-brand {{
        padding: 20px; border-bottom: 1px solid rgba(142,145,152,0.15);
        display: flex; align-items: center; justify-content: space-between; gap: 8px;
        flex-shrink: 0;
      }}
      .bsq-brand h1 {{ margin: 0; font-size: 18px; font-weight: 800; color: #afc8f0; letter-spacing: -0.01em; }}
      .bsq-brand p {{ margin: 3px 0 0; font-size: 10px; letter-spacing: 0.06em; text-transform: uppercase; color: #8e9198; }}
      .bsq-recenter {{
        flex-shrink: 0; width: 32px; height: 32px; border-radius: 8px;
        border: 1px solid rgba(142,145,152,0.25); background: rgba(34,42,61,0.6);
        color: #63f7ff; cursor: pointer; display: flex; align-items: center; justify-content: center;
      }}
      .bsq-recenter:hover {{ background: rgba(34,42,61,0.95); }}
      .bsq-recenter .material-symbols-outlined {{ font-size: 18px; }}

      .bsq-section {{ padding: 16px 20px; border-bottom: 1px solid rgba(142,145,152,0.12); }}
      .bsq-section:last-of-type {{ border-bottom: none; }}
      .bsq-section h3 {{
        margin: 0 0 4px 0; font-size: 12px; font-weight: 700; color: #63f7ff;
        text-transform: uppercase; letter-spacing: 0.06em;
        display: flex; align-items: center; gap: 6px;
      }}
      .bsq-section h3 .material-symbols-outlined {{ font-size: 15px; }}
      .bsq-section .bsq-sub {{ margin: 0 0 10px 0; font-size: 11.5px; color: #8e9198; line-height: 1.4; }}
      .bsq-section label {{
        display: block; font-size: 11.5px; color: #c4c6cf; margin-top: 10px; margin-bottom: 4px;
        text-transform: uppercase; letter-spacing: 0.03em;
      }}
      .bsq-section label:first-of-type {{ margin-top: 0; }}
      .bsq-hint {{ font-weight: 400; text-transform: none; letter-spacing: normal; color: #8e9198; }}
      .bsq-section input[type="date"] {{
        width: 100%; box-sizing: border-box; padding: 6px 8px;
        font-size: 13px; border: 1px solid rgba(142,145,152,0.35); border-radius: 6px;
        background: #171f33; color: #dae2fd; font-family: 'JetBrains Mono', monospace;
      }}
      .bsq-section input[type="range"] {{ width: 100%; accent-color: #63f7ff; }}
      #bsq-opacity-row {{ margin-top: 14px; }}

      .bsq-stat-row {{ display: flex; gap: 12px; margin-bottom: 4px; }}
      .bsq-stat {{ flex: 1; background: rgba(34,42,61,0.5); border-radius: 8px; padding: 8px 10px; }}
      .bsq-stat-label {{ display: block; font-size: 9.5px; text-transform: uppercase; letter-spacing: 0.05em; color: #8e9198; }}
      .bsq-stat-value {{ font-family: 'JetBrains Mono', monospace; font-size: 14px; color: #63f7ff; font-weight: 500; }}
      a.bsq-stat {{ text-decoration: none; display: block; transition: background 0.15s; cursor: pointer; }}
      a.bsq-stat:hover {{ background: rgba(99,247,255,0.12); }}
      a.bsq-stat .bsq-stat-label .material-symbols-outlined {{ font-size: 12px; color: #63f7ff; margin-left: 2px; }}

      #bsq-update-btn {{
        width: 100%; margin-top: 12px; padding: 9px 0;
        background: #63f7ff; color: #003739; border: none; border-radius: 8px;
        font-size: 13px; font-weight: 700; cursor: pointer; transition: transform .1s ease;
      }}
      #bsq-update-btn:hover {{ transform: scale(1.02); }}
      #bsq-update-btn:active {{ transform: scale(0.97); }}
      #bsq-update-btn:disabled {{ background: rgba(99,247,255,0.35); color: rgba(0,55,57,0.6); cursor: default; transform: none; }}
      #bsq-status {{ margin-top: 8px; font-size: 11.5px; color: #c4c6cf; min-height: 16px; line-height: 1.4; }}

      /* Collapsible history list -- it lives inline in the sidebar instead
         of a separate overlay drawer, so it never covers the map. */
      .bsq-accordion-header {{ display: flex; align-items: center; justify-content: space-between; cursor: pointer; user-select: none; }}
      .bsq-accordion-header h3 {{ margin-bottom: 0; }}
      .bsq-chevron {{ transition: transform .15s ease; font-size: 18px !important; color: #8e9198; }}
      .bsq-accordion-header.open .bsq-chevron {{ transform: rotate(180deg); }}
      .bsq-accordion-body {{ display: none; margin-top: 10px; }}
      .bsq-accordion-body.open {{ display: block; }}
      .bsq-history-item {{
        display: flex; align-items: center; gap: 8px;
        padding: 9px 10px; margin-bottom: 6px; border-radius: 8px; cursor: pointer;
        background: rgba(34,42,61,0.5); border: 1px solid transparent;
        font-family: 'JetBrains Mono', monospace; font-size: 12.5px; color: #dae2fd;
        transition: background .12s, border-color .12s;
      }}
      .bsq-history-item:hover {{ background: rgba(34,42,61,0.9); border-color: rgba(99,247,255,0.3); }}
      .bsq-history-item.current {{ background: rgba(0,31,63,0.6); border-color: #63f7ff; color: #63f7ff; font-weight: 700; }}
      .bsq-history-item .material-symbols-outlined {{ font-size: 16px; opacity: 0.7; }}

      /* "How It's Calculated" methodology breakdown -- one row per
         contributing factor, weight pulled straight from the same config
         values that drive the real WLC overlay. */
      .bsq-factor-row {{ padding: 10px 0; border-top: 1px solid rgba(142,145,152,0.12); }}
      .bsq-factor-row:first-child {{ border-top: none; padding-top: 0; }}
      .bsq-factor-head {{ display: flex; align-items: center; gap: 6px; }}
      .bsq-factor-head .material-symbols-outlined {{ font-size: 16px; color: #63f7ff; }}
      .bsq-factor-label {{ font-size: 12.5px; font-weight: 600; color: #dae2fd; flex: 1; }}
      .bsq-factor-weight {{
        font-family: 'JetBrains Mono', monospace; font-size: 11.5px; font-weight: 700;
        color: #003739; background: #63f7ff; border-radius: 5px; padding: 1px 6px;
      }}
      .bsq-factor-desc {{ margin: 4px 0 0; font-size: 11.5px; color: #8e9198; line-height: 1.45; }}
      .bsq-history-empty {{ font-size: 12px; color: #8e9198; padding: 4px 0; }}

      /* Per-layer info icon + mini legend (2026-07-24, Lambert) -- added
         next to every selectable overlay's checkbox in the Layers list
         (see bsqEnhanceLayerRows() below), so users don't have to hunt
         through the accordions further down to know what a layer means
         or what colour scale/value range it's showing. */
      .bsq-info-icon {{
        background: none; border: none; cursor: pointer; padding: 0 0 0 4px;
        margin: 0; font-size: 12px; line-height: 1; flex-shrink: 0; opacity: 0.8;
      }}
      .bsq-info-icon:hover {{ opacity: 1; }}
      /* Sits directly next to the info icon (2026-07-25, Lambert -- previously
         forced full-width/onto its own line via width:100%/flex-basis:100%,
         which wasted a whole extra row per layer). The parent
         `.bsq-layer-content-col` is still `flex-wrap: wrap`, so this only
         drops to its own line when the row genuinely doesn't have room
         (e.g. a long label + weight pill in the narrow 320px sidebar). */
      .bsq-mini-legend {{
        display: flex; align-items: center; gap: 4px; flex-shrink: 0;
        margin: 0; font-family: 'JetBrains Mono', monospace;
        font-size: 10px; color: #8e9198; cursor: default;
      }}
      .bsq-legend-bar {{
        display: inline-block; width: 46px; height: 8px; border-radius: 3px;
        border: 1px solid rgba(142,145,152,0.35); flex-shrink: 0;
      }}
      .bsq-legend-score .bsq-legend-bar {{ background: linear-gradient(to right, {_score_gradient_css}); }}
      .bsq-legend-raw .bsq-legend-bar {{ background: linear-gradient(to right, {_raw_gradient_css}); }}
      .bsq-legend-diverging .bsq-legend-bar {{ background: linear-gradient(to right, {_diverging_gradient_css}); }}
      .bsq-legend-diagnostic .bsq-legend-bar {{ background: linear-gradient(to right, {_diagnostic_gradient_css}); }}
      .bsq-legend-diverging_sla .bsq-legend-bar {{ background: linear-gradient(to right, {_sla_gradient_css}); }}
      .bsq-legend-range {{ white-space: nowrap; }}

      /* Composite-vs-factor visual hierarchy within each Bite Score group
         (2026-07-23, Lambert) -- the model's main heatmap row is styled
         bolder/larger, its own contributing-factor rows are indented
         underneath it, so the "answer vs ingredient" relationship reads
         at a glance instead of 25+ flat, visually-identical rows. Roles
         come from `_layer_ui[label].role` (see build_folium_map() above)
         and are applied by bsqEnhanceLayerRows() (JS below). `!important`
         needed on color to win over this list's own
         `#bsq-layers-slot .leaflet-control-layers-overlays label {{ color: ... !important }}`
         rule above. */
      #bsq-layers-slot .leaflet-control-layers-overlays label.bsq-layer-composite .bsq-layer-content-col {{
        font-weight: 800; font-size: 13.5px;
      }}
      #bsq-layers-slot .leaflet-control-layers-overlays label.bsq-layer-composite span:last-child {{
        color: #63f7ff !important;
      }}
      #bsq-layers-slot .leaflet-control-layers-overlays label.bsq-layer-factor .bsq-layer-content-col {{
        margin-left: 14px; font-size: 12px;
      }}
      #bsq-layers-slot .leaflet-control-layers-overlays label.bsq-layer-factor span:last-child {{
        color: #c4c6cf !important;
      }}

      /* Weight/informational pill next to each factor row (2026-07-23,
         Lambert) -- reuses the exact same visual language as
         .bsq-factor-weight in the "How It's Calculated" section below,
         so the weight is scannable at a glance instead of being buried in
         parenthetical label text ("...(33% weight)"). */
      .bsq-layer-weight-pill {{
        font-family: 'JetBrains Mono', monospace; font-size: 10.5px; font-weight: 700;
        color: #003739; background: #63f7ff; border-radius: 5px; padding: 1px 6px;
        flex-shrink: 0;
      }}
      .bsq-layer-weight-pill.bsq-layer-informational-pill {{
        background: rgba(142,145,152,0.4); color: #dae2fd;
      }}

      /* Single shared popover reused for every layer's info icon (rather
         than one per layer), positioned via JS next to whichever icon
         was clicked/hovered. Dismissed by clicking elsewhere, Escape, or
         its own close button -- never a full modal/overlay. */
      #bsq-info-popover {{
        display: none; position: fixed; z-index: 5000; max-width: 270px;
        background: #171f33; border: 1px solid rgba(99,247,255,0.35);
        border-radius: 10px; padding: 12px 16px 12px 14px;
        box-shadow: 0 8px 24px rgba(0,0,0,0.45);
      }}
      #bsq-info-popover-title {{ font-size: 12.5px; font-weight: 700; color: #63f7ff; margin-bottom: 6px; padding-right: 14px; }}
      #bsq-info-popover-body {{ font-size: 11.5px; color: #c4c6cf; line-height: 1.45; }}
      #bsq-info-popover-close {{
        position: absolute; top: 8px; right: 8px; background: none; border: none;
        color: #8e9198; cursor: pointer; font-size: 15px; line-height: 1; padding: 2px;
      }}
      #bsq-info-popover-close:hover {{ color: #dae2fd; }}

      .bsq-sidebar-footer {{ padding: 16px 20px; font-size: 11px; color: #8e9198; line-height: 1.5; flex-shrink: 0; }}

      /* The native Leaflet layer-control and colour legend are reparented
         (via JS below) out of their floating corners on the map and into
         these sidebar slots, so everything lives in one coherent panel
         instead of scattering separate boxes across the map. */
      #bsq-layers-slot .leaflet-control-layers,
      #bsq-legend-slot .legend.leaflet-control {{
        position: static !important; float: none !important; margin: 0 !important;
        background: transparent !important; border: none !important; box-shadow: none !important;
        width: 100% !important; box-sizing: border-box; color: #dae2fd;
      }}
      #bsq-layers-slot .leaflet-control-layers-list label,
      #bsq-layers-slot .leaflet-control-layers span,
      #bsq-layers-slot .leaflet-control-layers-base label,
      #bsq-layers-slot .leaflet-control-layers-overlays label {{ color: #dae2fd !important; font-size: 13px; }}
      #bsq-layers-slot .leaflet-control-layers-separator {{ border-top: 1px solid rgba(142,145,152,0.25) !important; margin: 8px 0 !important; }}

      /* Drag-and-drop reordering of the overlay checklist (see
         bsqEnableLayerReorder() below) -- draw order on the map follows
         list order, top item drawn frontmost, so dragging a layer to the
         top of this list brings it visually to the front. */
      #bsq-layers-slot .leaflet-control-layers-overlays label {{
        display: flex !important; align-items: flex-start; gap: 0;
        padding: 2px 4px; border-radius: 6px; cursor: grab;
        border-top: 2px solid transparent; border-bottom: 2px solid transparent;
        transition: background .1s;
      }}
      #bsq-layers-slot .leaflet-control-layers-overlays label:hover {{ background: rgba(99,247,255,0.08); }}

      /* Fixed-width leading "control column" (drag handle + checkbox),
         IDENTICAL for every row regardless of nesting depth or role
         (composite/factor/plain static) -- built client-side by
         bsqEnhanceLayerRows() (JS below), which moves the checkbox out of
         Leaflet's own wrapper span into this dedicated column, and
         everything else (label text, weight pill, info icon, legend)
         into a sibling `.bsq-layer-content-col`. This is what keeps every
         checkbox in the list aligned to the same x-position: any
         indentation/role styling (see .bsq-layer-composite/-factor rules
         below) is applied only to `.bsq-layer-content-col`, never to
         this column or the row itself (2026-07-23, Lambert). */
      #bsq-layers-slot .leaflet-control-layers-overlays .bsq-layer-control-col {{
        display: flex; align-items: center; justify-content: flex-start; gap: 3px;
        flex: 0 0 36px; width: 36px; min-height: 18px; flex-shrink: 0;
      }}
      #bsq-layers-slot .leaflet-control-layers-overlays .bsq-layer-control-col::before {{
        font-family: 'Material Symbols Outlined'; content: "drag_indicator";
        font-size: 15px; color: #8e9198; flex-shrink: 0;
      }}
      #bsq-layers-slot .leaflet-control-layers-overlays .bsq-layer-control-col input[type=checkbox] {{
        width: 16px; height: 16px; margin: 0; flex-shrink: 0; cursor: pointer;
      }}
      /* Free-flowing content column -- label text, weight pill, info icon
         and mini legend (immediately after the info icon, 2026-07-25) all
         live here, NOT snapped to fixed sub-columns, so short labels stay
         compact and only the control column above is rigid; `flex-wrap`
         lets the legend drop to its own line only when a row is too
         narrow to fit everything on one line. */
      #bsq-layers-slot .leaflet-control-layers-overlays .bsq-layer-content-col {{
        display: flex; align-items: center; flex-wrap: wrap; gap: 6px;
        flex: 1 1 auto; min-width: 0; padding: 2px 0; line-height: 1.3;
      }}
      #bsq-layers-slot .leaflet-control-layers-overlays label.bsq-dragging {{ opacity: 0.35; cursor: grabbing; }}
      #bsq-layers-slot .leaflet-control-layers-overlays label.bsq-drag-over-top {{ border-top-color: #63f7ff; }}
      #bsq-layers-slot .leaflet-control-layers-overlays label.bsq-drag-over-bottom {{ border-bottom-color: #63f7ff; }}
      /* Collapsible per-model group headers (2026-07-23, Lambert) --
         upgraded from a static divider to a real expand/collapse row
         (visual language matches the existing .bsq-accordion-header
         chevron pattern used elsewhere in this sidebar), inserted by
         bsqInsertLayerGroupHeaders() (JS below). Still a plain <div>, not
         a <label>, so it's never draggable and never selected by
         bsqEnableLayerReorder()'s ":scope > label" queries -- drag-
         reorder and per-date lazy-load "overlayadd" listeners stay
         completely unaffected. Collapsing a group only hides its member
         rows via CSS (a class toggle, display:none), never unchecks or
         removes them, so an already-toggled-on layer keeps rendering on
         the map even while its group is collapsed. */
      #bsq-layers-slot .leaflet-control-layers-overlays .bsq-layer-group-header {{
        display: flex !important; align-items: center; justify-content: space-between;
        cursor: pointer; user-select: none;
        font-size: 10px; font-weight: 700; letter-spacing: 0.06em;
        text-transform: uppercase; color: #8e9198;
        padding: 10px 4px 4px; margin-top: 6px;
        border-top: 1px solid rgba(142,145,152,0.25);
      }}
      #bsq-layers-slot .leaflet-control-layers-overlays .bsq-layer-group-header:first-child {{
        margin-top: 0; border-top: none; padding-top: 2px;
      }}
      #bsq-layers-slot .leaflet-control-layers-overlays .bsq-layer-group-header:hover {{ color: #dae2fd; }}
      #bsq-layers-slot .leaflet-control-layers-overlays .bsq-layer-group-header .bsq-chevron {{
        font-size: 15px !important; color: #8e9198; transition: transform .15s ease;
      }}
      #bsq-layers-slot .leaflet-control-layers-overlays .bsq-layer-group-header.open .bsq-chevron {{
        transform: rotate(180deg);
      }}
      /* Hides a collapsed group's member rows -- needs !important to win
         over this same list's own `label {{ display: flex !important }}`
         rule just below. */
      #bsq-layers-slot .leaflet-control-layers-overlays label.bsq-group-collapsed {{
        display: none !important;
      }}
      #bsq-legend-slot .legend svg {{ width: 100%; height: auto; }}
      #bsq-legend-slot .legend.leaflet-control svg .domain,
      #bsq-legend-slot .legend.leaflet-control svg line {{ stroke: #8e9198 !important; }}
      #bsq-legend-slot .legend.leaflet-control text {{ fill: #c4c6cf !important; }}

      /* Permanent isobath depth labels on the map itself -- a small pill
         that stays legible over any basemap (light/streets/satellite)
         without needing to hover for the tooltip. */
      .bsq-depth-label {{
        position: absolute;
        left: 0; top: 0;
        width: max-content;
        transform: translate(-50%, -50%);
        color: #0b5394;
        font-family: 'JetBrains Mono', monospace;
        font-size: 10.5px;
        font-weight: 700;
        white-space: nowrap;
        pointer-events: none;
        text-shadow:
          -1px -1px 2px rgba(255,255,255,0.9),
          1px -1px 2px rgba(255,255,255,0.9),
          -1px 1px 2px rgba(255,255,255,0.9),
          1px 1px 2px rgba(255,255,255,0.9);
      }}

      /* SLA contour value labels -- styled like depth labels but with
         red/blue colouring to match the contour line colour. */
      .bsq-sla-label {{
        position: absolute;
        left: 0; top: 0;
        width: max-content;
        transform: translate(-50%, -50%);
        font-family: 'JetBrains Mono', monospace;
        font-size: 10.5px;
        font-weight: 700;
        white-space: nowrap;
        pointer-events: none;
        text-shadow:
          -1px -1px 2px rgba(255,255,255,0.9),
           1px -1px 2px rgba(255,255,255,0.9),
          -1px  1px 2px rgba(255,255,255,0.9),
           1px  1px 2px rgba(255,255,255,0.9);
      }}
      .bsq-sla-label--pos {{ color: #c0392b; }}
      .bsq-sla-label--neg {{ color: #1a5276; }}
      .bsq-sla-label--zero {{ color: #666666; }}

      .bsq-waypoint-label {{
        position: absolute;
        left: 8px; top: -5px;
        width: max-content;
        color: #1a1a2e;
        font-family: 'Inter', sans-serif;
        font-size: 10px;
        font-weight: 600;
        white-space: nowrap;
        pointer-events: none;
        text-shadow:
          -1px -1px 2px rgba(255,255,255,0.95),
          1px -1px 2px rgba(255,255,255,0.95),
          -1px 1px 2px rgba(255,255,255,0.95),
          1px 1px 2px rgba(255,255,255,0.95);
      }}

      /* The zoom control and attribution stay on the map itself -- small
         and unobtrusive, standard Leaflet UX -- but restyled dark to match. */
      .leaflet-control-zoom a, .leaflet-control-attribution {{
        background: rgba(23,31,51,0.88) !important;
        color: #dae2fd !important;
        border-color: rgba(142,145,152,0.25) !important;
      }}
      .leaflet-control-attribution {{ font-size: 10.5px !important; }}
      .leaflet-control-attribution a {{ color: #63f7ff !important; }}
      .leaflet-bar a {{
        background: rgba(23,31,51,0.88) !important;
        border-bottom: 1px solid rgba(142,145,152,0.2) !important;
        color: #63f7ff !important;
      }}
      .leaflet-bar a:hover {{ background: rgba(34,42,61,0.95) !important; }}

      /* Compact bottom-left map control (2026-07-25, Lambert) -- basemap
         switcher + quick reference-chart toggles, moved off the sidebar
         and onto the map itself (matching Leaflet's own zoom-control
         corner-widget convention/visual treatment above), positioned in
         Leaflet's "bottomleft" corner so it never overlaps the zoom
         control (topleft) or attribution (bottomright). Built as a plain
         Leaflet Control (see bsqBuildMapControls() JS below), reusing the
         `.leaflet-bar`/`a` dark styling above rather than duplicating it,
         just relaxing the anchors' fixed 26x26 sizing so a short text
         label can sit next to each icon. */
      .bsq-map-controls {{ display: flex; flex-direction: column; }}
      .bsq-map-controls a.bsq-basemap-btn,
      .bsq-map-controls a.bsq-refchart-btn {{
        display: flex !important; align-items: center; gap: 6px;
        width: auto !important; height: auto !important; line-height: 1.3 !important;
        padding: 6px 10px; font-size: 11.5px; font-family: 'JetBrains Mono', monospace;
        white-space: nowrap; text-decoration: none;
      }}
      .bsq-map-controls a .material-symbols-outlined {{ font-size: 15px; }}
      .bsq-map-controls a.active {{ background: #63f7ff !important; color: #003739 !important; font-weight: 700; }}
      .bsq-map-controls-divider {{ border-top: 1px solid rgba(142,145,152,0.25); }}

      @media (max-width: 820px) {{
        .bsq-sidebar {{ width: 100%; height: 42vh; bottom: auto; border-right: none; border-bottom: 1px solid rgba(142,145,152,0.15); }}
        #{map_var} {{ left: 0 !important; top: 42vh !important; bottom: 54px !important; }}
        .bsq-timeline {{ left: 0; }}
      }}
    </style>

    <div class="bsq-timeline" id="bsq-timeline">
      <span class="bsq-tl-zoom-label" id="bsq-tl-zoom-label" title="Click to reset zoom"></span>
      <div class="bsq-tl-track-wrap" id="bsq-tl-track-wrap">
        <div class="bsq-tl-track"></div>
      </div>
      <button class="bsq-tl-latest-btn" id="bsq-tl-latest-btn" title="Jump to latest date">
        <span class="material-symbols-outlined">bolt</span>Latest
      </button>
    </div>
    <div class="bsq-tl-tooltip" id="bsq-tl-tooltip"></div>

    <nav class="bsq-sidebar">
      <div class="bsq-brand">
        <div>
          <h1>Yellowfin Tuna</h1>
          <p>Bite Score Intelligence</p>
        </div>
        <button class="bsq-recenter" id="bsq-recenter" title="Recenter map on data">
          <span class="material-symbols-outlined">my_location</span>
        </button>
      </div>

      <div class="bsq-section">
        <h3><span class="material-symbols-outlined">calendar_today</span>Data date: <span id="bsq-date-label">Loading&hellip;</span></h3>
        <div class="bsq-stat-row">
          <div class="bsq-stat">
            <span class="bsq-stat-label">Score range</span>
            <span class="bsq-stat-value" id="bsq-score-range">&ndash;</span>
          </div>
          <a class="bsq-stat" id="bsq-moon-stat" href="#" title="View full Moon &amp; Tides details" style="display: none;">
            <span class="bsq-stat-label">&#127769; Moon illumination <span class="material-symbols-outlined">arrow_forward</span></span>
            <span class="bsq-stat-value" id="bsq-moon-value">&ndash;</span>
          </a>
        </div>
        <label for="bsq-date">Update data for date</label>
        <input type="date" id="bsq-date" value="{config.DEFAULT_TARGET_DATE}">
        <button id="bsq-update-btn" onclick="bsqUpdateData()">Update Data</button>
        <div id="bsq-status"></div>
      </div>

      <div class="bsq-section">
        <h3><span class="material-symbols-outlined">opacity</span>Opacity</h3>
        <label for="bsq-opacity">Heatmap opacity</label>
        <input type="range" id="bsq-opacity" min="0" max="1" step="0.05" value="0.78"
               oninput="bsqSetOpacity(this.value)">
        {legacy_slider_html}
      </div>

      <div class="bsq-section">
        <h3><span class="material-symbols-outlined">layers</span>Layers</h3>
        <div id="bsq-layers-slot"></div>
      </div>

      <div class="bsq-section">
        <h3><span class="material-symbols-outlined">palette</span>Legend</h3>
        <div id="bsq-legend-slot"></div>
      </div>

      <div class="bsq-section">
        <div class="bsq-accordion-header" id="bsq-methodology-toggle">
          <h3><span class="material-symbols-outlined">school</span>How It's Calculated</h3>
          <span class="material-symbols-outlined bsq-chevron">expand_more</span>
        </div>
        <div class="bsq-accordion-body" id="bsq-methodology-body">
          <p class="bsq-sub">The Bite Score (0&ndash;100) blends six normalized ocean-condition layers using a fixed Weighted Linear Combination. Each factor is also available as its own toggleable layer above.</p>
          {methodology_html}
          <p class="bsq-sub" style="margin-top: 10px;">All layers are resampled onto the fine bathymetry grid (bilinear) before blending, so coarser satellite/model fields don't destroy the fine shelf-break detail.</p>
        </div>
      </div>

      {mld_section_html}

      {fsle_section_html}

      {sla_section_html}

      {v2_section_html}

      {lenigas_section_html}

      {relief_map_section_html}

      {mbgfc_section_html}

      <div class="bsq-section">
        <div class="bsq-accordion-header" id="bsq-history-toggle">
          <h3><span class="material-symbols-outlined">history</span>Historical Data</h3>
          <span class="material-symbols-outlined bsq-chevron">expand_more</span>
        </div>
        <div class="bsq-accordion-body" id="bsq-history-body">
          <p class="bsq-sub">Previously processed days stored in the output history folder. Select one to switch instantly (no pipeline re-run).</p>
          <div id="bsq-history-list">
            <div class="bsq-history-empty">Loading...</div>
          </div>
        </div>
      </div>

      <div class="bsq-sidebar-footer">
        SE Queensland &middot; Noosa &rarr; Gold Coast
      </div>
    </nav>

    <div id="bsq-info-popover" role="dialog" aria-label="Layer information">
      <button type="button" id="bsq-info-popover-close" aria-label="Close">&times;</button>
      <div id="bsq-info-popover-title"></div>
      <div id="bsq-info-popover-body"></div>
    </div>

    <script>
      // Reused description/legend metadata for every selectable overlay
      // (see the `_layer_ui` build block in build_folium_map() above),
      // keyed by exact Layers-list label text -- pure data, no forward
      // reference to any Folium-declared identifier, so (unlike
      // bsqLayerPanes/bsqDateLayerByName below) this can be a plain
      // top-level assignment rather than a function called from
      // DOMContentLoaded.
      var bsqLayerUI = {_layer_ui_json};
      var bsqKeyToLabel = {_key_to_label_json};
      var bsqStaticKeyToLabel = {_static_key_to_label_json};

      function bsqSetOpacity(v) {{
        try {{ {heatmap_var}.setOpacity(parseFloat(v)); }} catch (e) {{}}
      }}
      {legacy_js}

      // Every overlay lives in its own dedicated Leaflet pane (see
      // _add_pane() in visualize.py), so drag-and-drop reordering of the
      // overlay checklist just needs to update each pane's CSS z-index to
      // match list order -- works uniformly whether the layer underneath
      // is a raster ImageOverlay or a vector GeoJson/FeatureGroup, and
      // avoids relying on per-layer-type Leaflet methods (setZIndex only
      // exists on some layer types; bringToFront doesn't reorder relative
      // to layers of a different type sharing the default pane). Purely a
      // runtime/session convenience -- order isn't persisted across reloads.
      var bsqLayerPanes = null;
      {pane_map_js}

      // Visual grouping of the Layers-list overlays (see the sidebar-
      // grouping comment block in build_folium_map() above, which creates
      // each group's layers contiguously so they land together in
      // Folium's rendered overlays list). bsqInsertLayerGroupHeaders()
      // (below) inserts one collapsible header row (a plain <div>, not a
      // <label>) before the first layer of each group, matched by that
      // layer's exact label text -- so this keeps working even if group
      // membership shifts, as long as the trigger layer's name string
      // below stays in sync with visualize.py. Header rows are plain
      // <div>s (never draggable, and never matched by
      // bsqEnableLayerReorder()'s ":scope > label" queries), so drag-and-
      // drop reordering and per-date lazy-loading are completely
      // unaffected by this.
      var bsqLayerGroupStarts = {{
        "MBGFC fishing chart (georeferenced)": "Reference charts",
        "Land outline": "Ocean & environmental context",
        "Bite Score heatmap (current, high-res)": "Bite Score \u2014 v1 (current model)",
        "Bite Score heatmap v2 (Beta - structure/eddy model)": "Bite Score \u2014 v2 (Beta model)",
        "Bite Score heatmap Lenigas (SEQ fisherman model)": "Bite Score \u2014 Lenigas (SEQ fisherman model)",
        "Bathymetry relief map": "High-res bathymetry surveys"
      }};

      // Inserts a collapsible header before each group's first layer and
      // wires up click-to-toggle -- rows stay exactly where they are in
      // the DOM (siblings of the header, direct children of `container`,
      // same as before this feature), only a CSS class
      // (`bsq-group-collapsed`) hides/shows them, so nothing here changes
      // how bsqEnableLayerReorder()/bsqEnhanceLayerRows()'s own
      // ":scope > label" queries or the per-date lazy-load "overlayadd"
      // listener behave. A group starts OPEN if it already contains a
      // checked/active layer on page load (e.g. v1's main heatmap, or the
      // always-on land outline/contours) -- so collapsing never silently
      // hides something the user (or the default state) already switched
      // on -- and starts CLOSED otherwise (Reference charts, v2 Beta,
      // Lenigas, and the high-res bathymetry surveys are all off by
      // default), decluttering the initial view.
      function bsqInsertLayerGroupHeaders() {{
        var container = document.querySelector("#bsq-layers-slot .leaflet-control-layers-overlays");
        if (!container) return;
        var rows = Array.prototype.slice.call(container.querySelectorAll(":scope > label"));
        var headers = [];
        var currentHeader = null;
        rows.forEach(function (row) {{
          var span = row.querySelector("span:last-child");
          var name = span ? span.textContent.trim() : null;
          var groupLabel = name ? bsqLayerGroupStarts[name] : null;
          if (groupLabel) {{
            var header = document.createElement("div");
            header.className = "bsq-layer-group-header";
            var title = document.createElement("span");
            title.textContent = groupLabel;
            var chevron = document.createElement("span");
            chevron.className = "material-symbols-outlined bsq-chevron";
            chevron.textContent = "expand_more";
            header.appendChild(title);
            header.appendChild(chevron);
            header.bsqRows = [];
            header.addEventListener("click", function () {{
              var opening = !header.classList.contains("open");
              header.classList.toggle("open", opening);
              header.bsqRows.forEach(function (r) {{ r.classList.toggle("bsq-group-collapsed", !opening); }});
            }});
            container.insertBefore(header, row);
            headers.push(header);
            currentHeader = header;
          }}
          if (currentHeader) {{ currentHeader.bsqRows.push(row); }}
        }});
        headers.forEach(function (header) {{
          var hasChecked = header.bsqRows.some(function (r) {{
            var input = r.querySelector("input[type=checkbox]");
            return !!(input && input.checked);
          }});
          header.classList.toggle("open", hasChecked);
          header.bsqRows.forEach(function (r) {{ r.classList.toggle("bsq-group-collapsed", !hasChecked); }});
        }});
      }}

      // Adds a small info icon + (where applicable) a mini colour-scale
      // legend to every overlay row that has an entry in `bsqLayerUI`
      // (built server-side in build_folium_map() above) -- covers every
      // selectable layer generically, so no per-layer HTML had to be
      // hand-written for this. Both are appended INSIDE the row's own
      // <label> (after its checkbox + text span), which -- being a plain
      // <button>/<div>, not another <label>/<input> -- doesn't interfere
      // with bsqEnableLayerReorder()'s ":scope > label" queries or the
      // per-date lazy-load "overlayadd" listener, which both key off
      // row.querySelector("span:last-child") -- an existing, untouched
      // element that stays exactly where it already was.
      var bsqPopoverPinnedLabel = null;
      function bsqEnhanceLayerRows() {{
        var container = document.querySelector("#bsq-layers-slot .leaflet-control-layers-overlays");
        if (!container) return;
        var rows = Array.prototype.slice.call(container.querySelectorAll(":scope > label"));
        rows.forEach(function (row) {{
          var span = row.querySelector("span:last-child");
          var name = span ? span.textContent.trim() : null;
          var ui = name ? bsqLayerUI[name] : null;

          // Split every row (not just ones with a bsqLayerUI entry, so
          // even a plain/unregistered overlay still lines up) into a
          // fixed-width leading control column (drag handle + checkbox)
          // and a free-flowing content column holding everything else --
          // this is what keeps every checkbox in the whole list aligned
          // to the same x-position regardless of role/nesting (2026-07-23,
          // Lambert). The checkbox is simply relocated (not cloned), so
          // its native <label>-wraps-<input> click-to-toggle behavior and
          // the row's own draggable/dragstart|dragover|drop listeners
          // (already attached to `row` itself by bsqEnableLayerReorder(),
          // which always runs before this) are completely unaffected.
          var input = row.querySelector("input[type=checkbox]");
          if (!input) return;
          var controlCol = document.createElement("div");
          controlCol.className = "bsq-layer-control-col";
          controlCol.appendChild(input);
          var contentCol = document.createElement("div");
          contentCol.className = "bsq-layer-content-col";
          while (row.firstChild) {{ contentCol.appendChild(row.firstChild); }}
          row.appendChild(controlCol);
          row.appendChild(contentCol);

          if (!ui) return;

          // Visual hierarchy (2026-07-23, Lambert): bold/larger for a
          // model's composite heatmap row, indented for its own
          // contributing-factor rows underneath -- see the `role` field
          // built into `_layer_ui` in build_folium_map() above. Applied to
          // the row (for the `span:last-child` colour rules) as well as
          // (via CSS) the content column, never the control column, so
          // factor-row indentation never moves the checkbox.
          if (ui.role === "composite") {{ row.classList.add("bsq-layer-composite"); }}
          if (ui.role === "factor") {{ row.classList.add("bsq-layer-factor"); }}

          // Weight/informational pill (2026-07-23, Lambert) -- replaces
          // the old baked-in "(33% weight)" / "(informational only)"
          // parenthetical text that used to live in the raw label string,
          // reusing the same visual language as the .bsq-factor-weight
          // pill already used in the "How It's Calculated" section below.
          if (ui.informational) {{
            var infoPill = document.createElement("span");
            infoPill.className = "bsq-layer-weight-pill bsq-layer-informational-pill";
            infoPill.textContent = "Info only";
            contentCol.appendChild(infoPill);
          }} else if (typeof ui.weight_pct === "number") {{
            var weightPill = document.createElement("span");
            weightPill.className = "bsq-layer-weight-pill";
            weightPill.textContent = ui.weight_pct + "%";
            contentCol.appendChild(weightPill);
          }}

          var icon = document.createElement("button");
          icon.type = "button";
          icon.className = "bsq-info-icon";
          icon.setAttribute("aria-label", "About this layer");
          icon.setAttribute("title", "About this layer");
          icon.textContent = "\\u2139\\uFE0F";
          // Nested interactive elements inside a <label> would otherwise
          // also toggle that label's checkbox on click (label-forwarding)
          // -- stopping propagation here keeps the info icon from
          // silently switching the layer on/off every time it's opened.
          icon.addEventListener("mousedown", function (e) {{ e.stopPropagation(); }});
          icon.addEventListener("click", function (e) {{
            e.preventDefault();
            e.stopPropagation();
            bsqToggleInfoPopover(name, icon);
          }});
          icon.addEventListener("mouseenter", function () {{ bsqShowInfoPopover(name, icon); }});
          icon.addEventListener("mouseleave", function () {{
            if (bsqPopoverPinnedLabel !== name) {{ bsqHideInfoPopover(); }}
          }});
          contentCol.appendChild(icon);

          if (ui.legend && ui.legend.kind !== "none") {{
            var legendRow = document.createElement("div");
            legendRow.className = "bsq-mini-legend bsq-legend-" + ui.legend.kind;
            legendRow.setAttribute("data-legend-label", name);
            var bar = document.createElement("span");
            bar.className = "bsq-legend-bar";
            var rangeEl = document.createElement("span");
            rangeEl.className = "bsq-legend-range";
            rangeEl.textContent = ui.legend.kind === "score" ? "0\\u2013100" : "\\u2013";
            legendRow.appendChild(bar);
            legendRow.appendChild(rangeEl);
            contentCol.appendChild(legendRow);
          }}
        }});
      }}

      // Fills in a layer's mini-legend range with its real, live-fetched
      // min/max (see bsqLoadDateLayer()/bsqLoadRasterLayer() below) --
      // replaces the generic "0-100" / "-" placeholder text set by
      // bsqEnhanceLayerRows() above once that layer's actual data has
      // been loaded, so every legend shows today's real numbers rather
      // than a stale/hardcoded range.
      function bsqUpdateLegendRange(label, min, max) {{
        if (!label || min === null || min === undefined || max === null || max === undefined) return;
        var rows = document.querySelectorAll(".bsq-mini-legend");
        for (var i = 0; i < rows.length; i++) {{
          if (rows[i].getAttribute("data-legend-label") !== label) continue;
          var el = rows[i].querySelector(".bsq-legend-range");
          if (!el) return;
          var ui = bsqLayerUI[label];
          var unit = (ui && ui.legend && ui.legend.unit) ? (" " + ui.legend.unit) : "";
          var fmt = function (v) {{ return (Math.round(v * 10) / 10).toString(); }};
          el.textContent = fmt(min) + unit + "\\u2013" + fmt(max) + unit;
          return;
        }}
      }}

      // Single popover shared by every info icon (rather than one per
      // layer) -- repositioned via JS to sit next to whichever icon was
      // just clicked/hovered. Clicking an icon "pins" it open (stays open
      // until dismissed via the close button, Escape, or clicking
      // elsewhere); hovering shows it only while the mouse stays over the
      // icon, matching the "click OR hover" requirement without needing
      // two separate UI elements.
      function bsqShowInfoPopover(label, anchorEl) {{
        var pop = document.getElementById("bsq-info-popover");
        var ui = bsqLayerUI[label];
        if (!pop || !ui) return;
        var titleText = label
          .replace(/^Factor( \\(Lenigas\\)| \\(v2 Beta\\))?: /, "")
          .replace(/ \\([^)]*% weight\\)$/, "")
          .replace(/ \\(informational only\\)$/, "");
        document.getElementById("bsq-info-popover-title").textContent = titleText;
        document.getElementById("bsq-info-popover-body").textContent = ui.info;
        pop.setAttribute("data-label", label);
        pop.style.display = "block";
        var rect = anchorEl.getBoundingClientRect();
        var popRect = pop.getBoundingClientRect();
        var left = Math.max(8, Math.min(rect.left, window.innerWidth - popRect.width - 12));
        var top = rect.bottom + 6;
        if (top + popRect.height > window.innerHeight) {{ top = Math.max(8, rect.top - popRect.height - 6); }}
        pop.style.left = left + "px";
        pop.style.top = top + "px";
      }}
      function bsqHideInfoPopover() {{
        var pop = document.getElementById("bsq-info-popover");
        if (pop) {{ pop.style.display = "none"; }}
        bsqPopoverPinnedLabel = null;
      }}
      function bsqToggleInfoPopover(label, anchorEl) {{
        var pop = document.getElementById("bsq-info-popover");
        if (bsqPopoverPinnedLabel === label && pop && pop.style.display === "block") {{
          bsqHideInfoPopover();
          return;
        }}
        bsqShowInfoPopover(label, anchorEl);
        bsqPopoverPinnedLabel = label;
      }}

      // Lookup from each per-date layer's Layers-list label to its API
      // key + JS ImageOverlay variable (see date_layers.py / webapp.py's
      // `/api/date-layer/*` endpoints), used by the "overlayadd" listener
      // below to fetch it for whichever date is currently resolved
      // (bsqCurrentDate, set by bsqResolveDateAndLoad()). Same eager-vs-
      // later-script-tag reasoning as bsqLayerPanes above.
      var bsqDateLayerByName = null;
      {date_layer_map_js}

      function bsqEnableLayerReorder() {{
        var container = document.querySelector("#bsq-layers-slot .leaflet-control-layers-overlays");
        if (!container) return;
        var rows = Array.prototype.slice.call(container.querySelectorAll(":scope > label"));
        var dragged = null;

        function applyDrawOrder() {{
          // Bottom-of-list rows are processed first so each subsequent
          // (higher, more "front") row ends up with a higher z-index than
          // everything below it.
          var current = Array.prototype.slice.call(container.querySelectorAll(":scope > label")).reverse();
          var zIndex = 401;
          current.forEach(function (row) {{
            var span = row.querySelector("span:last-child");
            var name = span ? span.textContent.trim() : null;
            var pane = name ? bsqLayerPanes[name] : null;
            if (!pane) return;
            try {{ pane.style.zIndex = zIndex; }} catch (e) {{}}
            zIndex += 1;
          }});
        }}

        rows.forEach(function (row) {{
          row.setAttribute("draggable", "true");

          row.addEventListener("dragstart", function (e) {{
            dragged = row;
            row.classList.add("bsq-dragging");
            e.dataTransfer.effectAllowed = "move";
          }});

          row.addEventListener("dragend", function () {{
            row.classList.remove("bsq-dragging");
            rows.forEach(function (r) {{ r.classList.remove("bsq-drag-over-top", "bsq-drag-over-bottom"); }});
          }});

          row.addEventListener("dragover", function (e) {{
            e.preventDefault();
            if (!dragged || dragged === row) return;
            var rect = row.getBoundingClientRect();
            var before = (e.clientY - rect.top) < rect.height / 2;
            row.classList.toggle("bsq-drag-over-top", before);
            row.classList.toggle("bsq-drag-over-bottom", !before);
          }});

          row.addEventListener("dragleave", function () {{
            row.classList.remove("bsq-drag-over-top", "bsq-drag-over-bottom");
          }});

          row.addEventListener("drop", function (e) {{
            e.preventDefault();
            row.classList.remove("bsq-drag-over-top", "bsq-drag-over-bottom");
            if (!dragged || dragged === row) return;
            var rect = row.getBoundingClientRect();
            var before = (e.clientY - rect.top) < rect.height / 2;
            container.insertBefore(dragged, before ? row : row.nextSibling);
            applyDrawOrder();
          }});
        }});
      }}

      // Persist the checked overlay set across full-page navigations
      // (Part 1, 2026-07-25, Lambert) -- switching historical dates loads
      // a brand-new copy of this same static HTML (see bsqResolveDateAndLoad()
      // above), which otherwise resets every layer back to its Folium-
      // authored default every time. Keyed/versioned ("_v1") so a future
      // change to this format can start fresh instead of trying to
      // interpret stale saved data. Only the overlay checklist is
      // persisted here -- basemap choice has its own separate key (see
      // bsqSwitchBasemap() below), and is unaffected by this.
      var BSQ_LAYER_SELECTION_KEY = "bsqLayerSelection_v1";
      // Guard flag: suppresses bsqSaveLayerSelection() during restore so
      // intermediate click() calls don't overwrite the intended saved state
      // before the restore loop finishes.
      var bsqRestoringLayerSelection = false;

      function bsqGetCheckedLayerNames() {{
        var container = document.querySelector("#bsq-layers-slot .leaflet-control-layers-overlays");
        var names = [];
        if (!container) return names;
        Array.prototype.forEach.call(container.querySelectorAll(":scope > label"), function (row) {{
          var input = row.querySelector("input[type=checkbox]");
          var span = row.querySelector("span:last-child");
          if (input && input.checked && span) {{ names.push(span.textContent.trim()); }}
        }});
        return names;
      }}

      function bsqSaveLayerSelection() {{
        if (bsqRestoringLayerSelection) return;
        try {{
          localStorage.setItem(BSQ_LAYER_SELECTION_KEY, JSON.stringify(bsqGetCheckedLayerNames()));
        }} catch (e) {{}}
      }}

      // Full restore: turns ON saved-checked layers that aren't currently
      // checked, and turns OFF default-on layers that weren't in the saved
      // state -- via genuine `input.click()` calls so Leaflet's own
      // Control.Layers handler runs (firing "overlayadd"/"overlayremove")
      // and per-date lazy-loads are triggered correctly. If there is no
      // saved state at all, nothing is changed (first visit uses Folium
      // defaults). A saved name no longer present in the current overlay
      // list (e.g. a renamed layer) is silently ignored. Must run before
      // bsqInsertLayerGroupHeaders() below, so restored layers' groups are
      // correctly computed as open. bsqRestoringLayerSelection is set for
      // the duration to prevent the intermediate click()s from overwriting
      // the intended saved state in localStorage.
      function bsqRestoreLayerSelection() {{
        var container = document.querySelector("#bsq-layers-slot .leaflet-control-layers-overlays");
        if (!container) return;
        var raw;
        try {{ raw = localStorage.getItem(BSQ_LAYER_SELECTION_KEY); }} catch (e) {{ return; }}
        if (!raw) return;
        var saved;
        try {{ saved = JSON.parse(raw); }} catch (e) {{ return; }}
        if (!Array.isArray(saved)) return;
        var savedSet = {{}};
        saved.forEach(function (name) {{ savedSet[name] = true; }});
        var toCheck = [], toUncheck = [];
        Array.prototype.forEach.call(container.querySelectorAll(":scope > label"), function (row) {{
          var input = row.querySelector("input[type=checkbox]");
          var span = row.querySelector("span:last-child");
          if (!input || !span) return;
          var name = span.textContent.trim();
          if (savedSet[name] && !input.checked) {{ toCheck.push(input); }}
          else if (!savedSet[name] && input.checked) {{ toUncheck.push(input); }}
        }});
        bsqRestoringLayerSelection = true;
        try {{
          toCheck.forEach(function (inp) {{ inp.click(); }});
          toUncheck.forEach(function (inp) {{ inp.click(); }});
        }} finally {{
          bsqRestoringLayerSelection = false;
        }}
      }}

      // Compact bottom-left map control (Parts 3 & 4, 2026-07-25, Lambert):
      // a basemap switcher (replacing the sidebar's old basemap radios,
      // now removed -- see the DOMContentLoaded reparenting code above)
      // plus 2 quick-access reference-chart toggles, styled like Leaflet's
      // own zoom control (reuses the `.leaflet-bar`/`a` dark theme above).
      // `bsqBasemapLayers` is built by a function (called from
      // DOMContentLoaded), not a top-level `var ... =`, for the same
      // eager-vs-later-script-tag reason as bsqLayerPanes/bsqDateLayerByName
      // above -- Folium declares each `tile_layer_xxx` identifier in its
      // own <script> tag emitted later in the document.
      var bsqBasemapLayers = null;
      function bsqInitBasemapLayers() {{
        bsqBasemapLayers = {{light: {light_var}, streets: {streets_var}, satellite: {satellite_var}}};
      }}
      var bsqActiveBasemapKey = "light";
      var BSQ_BASEMAP_KEY = "bsqBasemap_v1";

      function bsqSwitchBasemap(key) {{
        if (!bsqBasemapLayers[key] || key === bsqActiveBasemapKey) return;
        Object.keys(bsqBasemapLayers).forEach(function (k) {{
          if (k !== key) {{ try {{ {map_var}.removeLayer(bsqBasemapLayers[k]); }} catch (e) {{}} }}
        }});
        try {{ {map_var}.addLayer(bsqBasemapLayers[key]); }} catch (e) {{}}
        bsqActiveBasemapKey = key;
        try {{ localStorage.setItem(BSQ_BASEMAP_KEY, key); }} catch (e) {{}}
        document.querySelectorAll(".bsq-basemap-btn").forEach(function (btn) {{
          btn.classList.toggle("active", btn.getAttribute("data-basemap") === key);
        }});
      }}

      // Reference-chart toggles proxy a real `.click()` on the matching
      // sidebar checkbox (rather than driving the MBGFC layers directly),
      // so the sidebar Layers list stays the single source of truth --
      // toggling either place fires the same native "overlayadd"/
      // "overlayremove" events, which bsqSyncRefChartButtons() (below)
      // already listens for to keep both in sync.
      function bsqFindOverlayRow(name) {{
        var container = document.querySelector("#bsq-layers-slot .leaflet-control-layers-overlays");
        if (!container) return null;
        var rows = container.querySelectorAll(":scope > label");
        for (var i = 0; i < rows.length; i++) {{
          var span = rows[i].querySelector("span:last-child");
          if (span && span.textContent.trim() === name) return rows[i];
        }}
        return null;
      }}

      function bsqToggleRefChartLayer(name) {{
        var row = bsqFindOverlayRow(name);
        var input = row ? row.querySelector("input[type=checkbox]") : null;
        if (input) {{ input.click(); }}
      }}

      function bsqSyncRefChartButtons() {{
        document.querySelectorAll(".bsq-refchart-btn").forEach(function (btn) {{
          var name = btn.getAttribute("data-refchart-name");
          var row = bsqFindOverlayRow(name);
          var input = row ? row.querySelector("input[type=checkbox]") : null;
          btn.classList.toggle("active", !!(input && input.checked));
        }});
      }}

      function bsqBuildMapControls() {{
        var BsqMapControls = L.Control.extend({{
          options: {{position: "bottomleft"}},
          onAdd: function () {{
            var container = L.DomUtil.create("div", "leaflet-bar bsq-map-controls");
            L.DomEvent.disableClickPropagation(container);
            L.DomEvent.disableScrollPropagation(container);

            [
              {{key: "light", label: "Light", icon: "light_mode"}},
              {{key: "streets", label: "Streets", icon: "map"}},
              {{key: "satellite", label: "Satellite", icon: "satellite_alt"}}
            ].forEach(function (bm) {{
              var a = document.createElement("a");
              a.href = "#";
              a.className = "bsq-basemap-btn" + (bm.key === bsqActiveBasemapKey ? " active" : "");
              a.setAttribute("data-basemap", bm.key);
              a.title = bm.label + " basemap";
              a.innerHTML = '<span class="material-symbols-outlined">' + bm.icon + '</span>' + bm.label;
              a.addEventListener("click", function (e) {{ e.preventDefault(); bsqSwitchBasemap(bm.key); }});
              container.appendChild(a);
            }});

            var divider = document.createElement("div");
            divider.className = "bsq-map-controls-divider";
            container.appendChild(divider);

            [
              {{name: "MBGFC FADs, SFADs & wave buoys", label: "FADs/buoys", icon: "anchor"}},
              {{name: "MBGFC fishing chart (georeferenced)", label: "Fishing chart", icon: "map"}}
            ].forEach(function (rc) {{
              var a = document.createElement("a");
              a.href = "#";
              a.className = "bsq-refchart-btn";
              a.setAttribute("data-refchart-name", rc.name);
              a.title = "Toggle " + rc.label;
              a.innerHTML = '<span class="material-symbols-outlined">' + rc.icon + '</span>' + rc.label;
              a.addEventListener("click", function (e) {{ e.preventDefault(); bsqToggleRefChartLayer(rc.name); }});
              container.appendChild(a);
            }});

            return container;
          }}
        }});
        {map_var}.addControl(new BsqMapControls());
        bsqSyncRefChartButtons();
      }}

      document.addEventListener("DOMContentLoaded", function () {{
        // The sidebar takes up part of the viewport width, so re-fit the
        // view to the actual data bounds afterwards (rather than relying
        // on the original fixed zoom_start) to keep the coastline and
        // bathymetry contours fully in view instead of being cropped.
        try {{
          {map_var}.invalidateSize();
          {map_var}.fitBounds([[{bounds[1]}, {bounds[0]}], [{bounds[3]}, {bounds[2]}]]);
        }} catch (e) {{}}

        // Reparent the native Leaflet layer-control and colour legend from
        // their floating map corners into the sidebar, so nothing sits on
        // top of the map -- everything lives in one coherent side panel.
        var layersCtrl = document.querySelector(".leaflet-control-layers");
        if (layersCtrl) {{
          // Basemap radios relocated to the new bottom-left map control
          // (Part 3, 2026-07-25, Lambert -- see bsqBuildMapControls() /
          // bsqSwitchBasemap() below) -- remove Folium's own base-layers
          // section (and its divider) so it no longer appears in the
          // sidebar's Layers list at all.
          var baseSection = layersCtrl.querySelector(".leaflet-control-layers-base");
          if (baseSection) {{ baseSection.remove(); }}
          var baseSeparator = layersCtrl.querySelector(".leaflet-control-layers-separator");
          if (baseSeparator) {{ baseSeparator.remove(); }}
          document.getElementById("bsq-layers-slot").appendChild(layersCtrl);
        }}
        var legendCtrl = document.querySelector(".legend.leaflet-control");
        if (legendCtrl) {{ document.getElementById("bsq-legend-slot").appendChild(legendCtrl); }}

        // Restore any previously-saved basemap choice as early as possible
        // (2026-07-23, Lambert -- bugfix) -- switching basemap calls
        // map.removeLayer()/addLayer() on the *base* tile layers, which
        // Leaflet's own Control.Layers listens for (via each layer's own
        // "add"/"remove" events) and reacts to by fully rebuilding its
        // "_overlaysList" DOM from scratch. Doing this restore here, before
        // bsqInsertLayerGroupHeaders()/bsqEnableLayerReorder()/
        // bsqEnhanceLayerRows() below run, means that native rebuild
        // happens on the plain, not-yet-enhanced list -- so nothing is lost.
        // Previously this restore happened inside bsqBuildMapControls(),
        // called LAST, which silently wiped every info icon, mini-legend,
        // group header and drag-reorder attribute right back off every
        // row whenever the saved basemap wasn't the "light" default.
        bsqInitBasemapLayers();
        try {{
          var savedBasemap = localStorage.getItem(BSQ_BASEMAP_KEY);
          if (savedBasemap) {{ bsqSwitchBasemap(savedBasemap); }}
        }} catch (e) {{}}

        bsqInitLayerPanes();

        // These layers carry no data of their own on this page -- fetch
        // them from the dashboard server the first time each is switched
        // on in the layer list, so they stay available on every date's
        // map without ever needing that date regenerated. Registered here
        // (moved up from further below, 2026-07-25, Lambert) so it's
        // already listening before bsqRestoreLayerSelection() below
        // programmatically re-checks any saved layer -- a restored layer
        // triggers its lazy load exactly like a real user click would.
        {map_var}.on("overlayadd", function (e) {{
          if (e.name === "MBGFC fishing chart (georeferenced)" || e.name === "MBGFC FADs, SFADs & wave buoys") {{
            bsqLoadMbgfc();
          }} else if (e.name === "Fishing waypoints (Light & Heavy Tackle)") {{
            bsqLoadWaypoints();
          }} else if (e.name === {depth_suitability_name_json}) {{
            bsqLoadRasterLayer("depth_suitability", {depth_suitability_var});
          }} else if (e.name === "Bathymetry relief map") {{
            bsqLoadRasterLayer("relief_map", {relief_map_var});
            bsqLoadRasterLayer("relief_map_moreton_bay_approaches", {relief_map_mba_var});
            bsqLoadRasterLayer("relief_map_lidar", {relief_map_lidar_var});
            bsqLoadRasterLayer("relief_map_mudjimba_island", {relief_map_mudjimba_var});
          }} else if (e.name === "Bathymetry contours (depth reference)") {{
            bsqLoadContours();
          }} else if (e.name === "Land outline") {{
            bsqLoadLandOutline();
          }} else if (e.name === "Sea level anomaly contours") {{
            if (bsqCurrentDate) bsqLoadSlaContours(bsqCurrentDate);
          }} else if (bsqDateLayerByName && bsqDateLayerByName[e.name]) {{
            var entry = bsqDateLayerByName[e.name];
            bsqLoadDateLayer(entry.key, entry.layer, entry.key === "bite_score");
          }}
        }});

        // Persist which overlays are checked across full-page navigations
        // (Part 1, 2026-07-25, Lambert -- switching historical dates is a
        // real navigation to /history/<date>, which otherwise reloads this
        // same static HTML with every layer back at its Folium-authored
        // default). Saves the full set of currently-checked layer names on
        // every toggle (whether from this Layers list or the new bottom-
        // left reference-chart buttons -- both ultimately fire the same
        // native "overlayadd"/"overlayremove" map events), then restores
        // exact saved state (turning ON non-default layers and turning OFF
        // default-on layers the user unchecked) before
        // bsqInsertLayerGroupHeaders() below computes each group's initial
        // open/closed state, so a restored layer's group starts open too.
        // Also keeps the bottom-left reference-chart buttons' active state
        // in sync with the sidebar checkboxes.
        {map_var}.on("overlayadd overlayremove", function () {{
          bsqSaveLayerSelection();
          bsqSyncRefChartButtons();
        }});
        // bsqInitDateLayers() must run before bsqRestoreLayerSelection() so
        // that bsqDateLayerByName is populated when restored layer clicks fire
        // "overlayadd". bsqCurrentDate is seeded from the URL path here (for
        // /history/<date> navigations) so bsqLoadDateLayer() won't bail out
        // with an early "if (!bsqCurrentDate) return" during restore; the root
        // "/" case is handled by bsqLoadRestoredDateLayers() called from
        // bsqResolveDateAndLoad() after the async fetch completes.
        bsqInitDateLayers();
        if (bsqDateFromPath) {{ bsqCurrentDate = bsqDateFromPath; }}
        bsqRestoreLayerSelection();

        bsqInsertLayerGroupHeaders();
        bsqEnableLayerReorder();
        bsqEnhanceLayerRows();
        bsqBuildMapControls();

        document.getElementById("bsq-info-popover-close").addEventListener("click", bsqHideInfoPopover);
        document.addEventListener("click", function (e) {{
          var pop = document.getElementById("bsq-info-popover");
          if (!pop || pop.style.display !== "block") return;
          if (pop.contains(e.target) || e.target.classList.contains("bsq-info-icon")) return;
          bsqHideInfoPopover();
        }});
        document.addEventListener("keydown", function (e) {{
          if (e.key === "Escape") {{ bsqHideInfoPopover(); }}
        }});

        document.getElementById("bsq-recenter").addEventListener("click", function () {{
          try {{ {map_var}.fitBounds([[{bounds[1]}, {bounds[0]}], [{bounds[3]}, {bounds[2]}]]); }} catch (e) {{}}
        }});

        document.getElementById("bsq-history-toggle").addEventListener("click", function () {{
          var opening = !document.getElementById("bsq-history-body").classList.contains("open");
          document.getElementById("bsq-history-body").classList.toggle("open", opening);
          this.classList.toggle("open", opening);
        }});

        document.getElementById("bsq-methodology-toggle").addEventListener("click", function () {{
          var opening = !document.getElementById("bsq-methodology-body").classList.contains("open");
          document.getElementById("bsq-methodology-body").classList.toggle("open", opening);
          this.classList.toggle("open", opening);
        }});

        document.getElementById("bsq-mld-toggle").addEventListener("click", function () {{
          var opening = !document.getElementById("bsq-mld-body").classList.contains("open");
          document.getElementById("bsq-mld-body").classList.toggle("open", opening);
          this.classList.toggle("open", opening);
        }});

        document.getElementById("bsq-fsle-toggle").addEventListener("click", function () {{
          var opening = !document.getElementById("bsq-fsle-body").classList.contains("open");
          document.getElementById("bsq-fsle-body").classList.toggle("open", opening);
          this.classList.toggle("open", opening);
        }});

        document.getElementById("bsq-relief-toggle").addEventListener("click", function () {{
          var opening = !document.getElementById("bsq-relief-body").classList.contains("open");
          document.getElementById("bsq-relief-body").classList.toggle("open", opening);
          this.classList.toggle("open", opening);
        }});

        document.getElementById("bsq-mbgfc-toggle").addEventListener("click", function () {{
          var opening = !document.getElementById("bsq-mbgfc-body").classList.contains("open");
          document.getElementById("bsq-mbgfc-body").classList.toggle("open", opening);
          this.classList.toggle("open", opening);
        }});

        // These layers carry no data of their own on this page -- fetch
        // them from the dashboard server the first time each is switched
        // on in the layer list, so they stay available on every date's
        // map without ever needing that date regenerated. (Registered
        // earlier above, alongside bsqRestoreLayerSelection() -- see the
        // 2026-07-25, Lambert comment there.)

        bsqLoadContours();
        bsqLoadLandOutline();
        bsqResolveDateAndLoad();
        bsqLoadHistory();
      }});

      // Which date this page should show: parsed directly from the URL
      // path for an archived day (/history/<date>), resolved from
      // `/api/latest-date` otherwise (the "/" root route). Known
      // synchronously wherever possible (bsqDateFromPath) so the
      // Historical Data list below can mark the current entry without
      // waiting on a network round-trip.
      var bsqDateFromPathMatch = location.pathname.match(/^\\/history\\/([^/]+)\\/?$/);
      var bsqDateFromPath = bsqDateFromPathMatch ? decodeURIComponent(bsqDateFromPathMatch[1]) : null;
      var bsqCurrentDate = null;

      async function bsqResolveDateAndLoad() {{
        var date = bsqDateFromPath;
        if (!date) {{
          try {{
            var resp = await fetch("/api/latest-date", {{cache: "no-store"}});
            var data = await resp.json();
            date = data.date;
          }} catch (e) {{}}
        }}
        bsqCurrentDate = date;

        var labelEl = document.getElementById("bsq-date-label");
        var dateInput = document.getElementById("bsq-date");
        if (labelEl) {{ labelEl.textContent = date || "no data yet"; }}
        if (dateInput && date) {{ dateInput.value = date; }}

        if (!date) {{
          document.getElementById("bsq-status").textContent = "No processed data yet -- pick a date and click Update Data.";
          return;
        }}

        // The heatmap (and legacy heatmap/factors/FSLE, once toggled on)
        // fetch from /api/date-layer/<date>/<key>/* -- see
        // bsqLoadDateLayer() below. The heatmap itself is shown by
        // default, so it's loaded directly here rather than waiting for
        // an "overlayadd" event.
        bsqLoadDateLayer("bite_score", {heatmap_var}, true);
        // Load any date layers that were restored (checked) before
        // bsqCurrentDate was available -- covers layers turned on via
        // bsqRestoreLayerSelection() when bsqCurrentDate was still null
        // (root "/" route where the date is fetched async).
        bsqLoadRestoredDateLayers();
        bsqMaybeLoadSlaContours();
        bsqLoadMoonPhase();
        bsqCheckV2Availability();
        bsqCheckLenigasAvailability();
      }}

      // Scan checked overlay rows and load any date layer whose data hasn't
      // been fetched yet -- used by bsqResolveDateAndLoad() above to catch
      // layers that were restored before bsqCurrentDate was known.
      function bsqLoadRestoredDateLayers() {{
        if (!bsqDateLayerByName || !bsqCurrentDate) return;
        var container = document.querySelector("#bsq-layers-slot .leaflet-control-layers-overlays");
        if (!container) return;
        Array.prototype.forEach.call(container.querySelectorAll(":scope > label"), function (row) {{
          var input = row.querySelector("input[type=checkbox]");
          var span = row.querySelector("span:last-child");
          if (!input || !input.checked || !span) return;
          var entry = bsqDateLayerByName[span.textContent.trim()];
          if (entry) {{ bsqLoadDateLayer(entry.key, entry.layer, entry.key === "bite_score"); }}
        }});
      }}

      // Generic loader for the per-date layers (Bite Score heatmap,
      // legacy heatmap, the four contributing factors, FSLE, and v2
      // "Beta"'s heatmap + 7 contributing factors): each is cached
      // server-side per date (see date_layers.py) but still fetched
      // lazily here rather than embedded into this page, so the exact
      // same template works for every date. `updateStats` additionally
      // refreshes the "Score range" sidebar stat from the fetched meta
      // (only meaningful for the main heatmap). A "v2/"-prefixed key
      // (e.g. "v2/bite_score_v2", see `_date_layer_by_name` in
      // build_folium_map()) routes to the SEPARATE `/api/date-layer-v2/`
      // endpoint instead of v1's `/api/date-layer/` -- v1 keys (no
      // prefix) behave EXACTLY as before, so this is purely additive.
      // Same treatment for a "lenigas/"-prefixed key, routing to the
      // SEPARATE `/api/date-layer-lenigas/` endpoint instead.
      var bsqLoadedDateLayers = {{}};
      function bsqLoadDateLayer(key, layerVar, updateStats) {{
        if (!bsqCurrentDate) return;
        var cacheKey = key + "@" + bsqCurrentDate;
        if (bsqLoadedDateLayers[cacheKey]) return;
        bsqLoadedDateLayers[cacheKey] = true;
        var isV2 = key.indexOf("v2/") === 0;
        var isLenigas = key.indexOf("lenigas/") === 0;
        var apiKey = isV2 ? key.slice(3) : (isLenigas ? key.slice(8) : key);
        var base = (isV2 ? "/api/date-layer-v2/" : (isLenigas ? "/api/date-layer-lenigas/" : "/api/date-layer/")) + bsqCurrentDate + "/" + apiKey;
        fetch(base + "/meta", {{cache: "no-store"}})
          .then(function (r) {{ if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); }})
          .then(function (meta) {{
            layerVar.setUrl(base + "/chart.png");
            layerVar.setBounds(meta.bounds);
            if (updateStats && meta.min !== null && meta.max !== null && meta.min !== undefined) {{
              var el = document.getElementById("bsq-score-range");
              if (el) {{ el.textContent = Math.round(meta.min) + "\\u2013" + Math.round(meta.max); }}
            }}
            bsqUpdateLegendRange(bsqKeyToLabel[key], meta.min, meta.max);
          }})
          .catch(function (e) {{
            console.warn("Date layer '" + key + "' unavailable for " + bsqCurrentDate, e);
            // Toggling on a v2/Lenigas layer for a date it hasn't been run
            // for is expected (not every date has a v2/Lenigas run yet,
            // since both are experimental) -- surface it in that model's
            // sidebar status text too, rather than only a console warning,
            // so it's obvious in the UI why the layer just stayed blank
            // instead of appearing.
            if (isV2) {{ bsqSetV2Status(false); }}
            if (isLenigas) {{ bsqSetLenigasStatus(false); }}
          }});
      }}

      // v2 ("Beta") availability check for the CURRENTLY resolved date --
      // runs independently of whether the user has toggled the v2
      // heatmap/factor layers on, so the sidebar's "v2 Bite Score (Beta)"
      // section always shows an accurate, honest "available" / "not
      // available for this date" message up front (never a blank/broken
      // layer with no explanation). Deliberately checks only the
      // combined "bite_score_v2" key (not every factor) -- Ripley's v2
      // pipeline always writes that file first, so its presence/absence
      // is a reliable proxy for "was v2 run for this date at all".
      function bsqSetV2Status(available) {{
        var statusEl = document.getElementById("bsq-v2-status");
        if (!statusEl || !bsqCurrentDate) return;
        if (available) {{
          statusEl.textContent = "v2 (Beta) data is available for " + bsqCurrentDate + " -- toggle \\u201cBite Score heatmap v2 (Beta - structure/eddy model)\\u201d on in the Layers list above to view it.";
          statusEl.className = "bsq-v2-status bsq-v2-available";
        }} else {{
          statusEl.textContent = "v2 (Beta) has not been run for " + bsqCurrentDate + " yet. This experimental model is only available for a handful of test dates so far -- v1's Bite Score heatmap above is unaffected and remains this date's validated result.";
          statusEl.className = "bsq-v2-status bsq-v2-unavailable";
        }}
      }}
      function bsqCheckV2Availability() {{
        var statusEl = document.getElementById("bsq-v2-status");
        if (!bsqCurrentDate || !statusEl) return;
        statusEl.textContent = "Checking v2 (Beta) availability for " + bsqCurrentDate + "...";
        statusEl.className = "bsq-v2-status";
        fetch("/api/date-layer-v2/" + bsqCurrentDate + "/bite_score_v2/meta", {{cache: "no-store"}})
          .then(function (r) {{ if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); }})
          .then(function () {{ bsqSetV2Status(true); }})
          .catch(function () {{ bsqSetV2Status(false); }});
      }}

      // Lenigas availability check for the CURRENTLY resolved date --
      // exactly mirrors bsqCheckV2Availability() above, but for the
      // SEPARATE, independent Lenigas model, so the sidebar's "Lenigas
      // Bite Score" section always shows an accurate, honest "available"
      // / "not available for this date" message up front (never a
      // blank/broken layer with no explanation). Deliberately checks only
      // the combined "bite_score_lenigas" key (not every factor) --
      // Ripley's Lenigas pipeline always writes that file first, so its
      // presence/absence is a reliable proxy for "was Lenigas run for
      // this date at all". Always "Lenigas", never "v3".
      function bsqSetLenigasStatus(available) {{
        var statusEl = document.getElementById("bsq-lenigas-status");
        if (!statusEl || !bsqCurrentDate) return;
        if (available) {{
          statusEl.textContent = "Lenigas data is available for " + bsqCurrentDate + " -- toggle \\u201cBite Score heatmap Lenigas (SEQ fisherman model)\\u201d on in the Layers list above to view it.";
          statusEl.className = "bsq-lenigas-status bsq-lenigas-available";
        }} else {{
          statusEl.textContent = "Lenigas has not been run for " + bsqCurrentDate + " yet. This experimental model is only available for a handful of test dates so far -- v1's and v2's Bite Score heatmaps above are unaffected.";
          statusEl.className = "bsq-lenigas-status bsq-lenigas-unavailable";
        }}
      }}
      function bsqCheckLenigasAvailability() {{
        var statusEl = document.getElementById("bsq-lenigas-status");
        if (!bsqCurrentDate || !statusEl) return;
        statusEl.textContent = "Checking Lenigas availability for " + bsqCurrentDate + "...";
        statusEl.className = "bsq-lenigas-status";
        fetch("/api/date-layer-lenigas/" + bsqCurrentDate + "/bite_score_lenigas/meta", {{cache: "no-store"}})
          .then(function (r) {{ if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); }})
          .then(function () {{ bsqSetLenigasStatus(true); }})
          .catch(function () {{ bsqSetLenigasStatus(false); }});
      }}

      // Day-level (non-spatial) moon illumination readout -- unlike every
      // other per-date layer above, moon phase is a single scalar with no
      // spatial variation, so there's no image/bounds to load, just a
      // small JSON side-file (see main.py's `moon_phase.json` write and
      // webapp.py's /api/moon-phase/<date> route). The multiplier shown
      // here is recomputed client-side from the raw illumination_fraction
      // using the EXACT SAME formula as overlay.py::apply_moon_phase_multiplier
      // (multiplier = MOON_MULTIPLIER_MAX - illum * (MOON_MULTIPLIER_MAX - MOON_MULTIPLIER_MIN),
      // currently 1.2 - illum * 0.4) -- if that formula or the 0.8/1.2
      // bounds ever change in overlay.py/config.py, this literal must be
      // updated to match or the displayed multiplier will silently drift
      // out of sync with the real scoring.
      function bsqLoadMoonPhase() {{
        var statEl = document.getElementById("bsq-moon-stat");
        var valueEl = document.getElementById("bsq-moon-value");
        if (!bsqCurrentDate || !statEl || !valueEl) return;
        // Links to Lambert's standalone "Moon & Tides" detail page
        // (/moon/<date>, see moon_tide_page.py/webapp.py) for the same
        // date currently shown on this map -- set eagerly (not inside the
        // fetch .then below) so the link target is correct even if the
        // fetch itself fails; the stat box just stays hidden in that case.
        statEl.href = "/moon/" + bsqCurrentDate;
        fetch("/api/moon-phase/" + bsqCurrentDate, {{cache: "no-store"}})
          .then(function (r) {{ if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); }})
          .then(function (data) {{
            var illum = data.illumination_fraction;
            if (typeof illum !== "number") throw new Error("missing illumination_fraction");
            var multiplier = 1.2 - illum * 0.4;
            valueEl.textContent = Math.round(illum * 100) + "% (bite score \\u00d7" + multiplier.toFixed(2) + ")";
            statEl.style.display = "";
          }})
          .catch(function (e) {{
            // Graceful degradation: historical dates archived before this
            // feature existed (or any date the pipeline hasn't processed)
            // simply have no moon_phase.json -- omit the readout entirely
            // rather than showing a broken/fabricated value, matching the
            // "not available for this date" convention used elsewhere
            // (e.g. FSLE/MLD sidebar sections) in this dashboard.
            console.warn("Moon phase unavailable for " + bsqCurrentDate, e);
            statEl.style.display = "none";
          }});
      }}

      // Land/coastline outline: static vector data (derived from the
      // bathymetry grid's own nodata mask), shown by default, so loaded
      // directly at page load rather than waiting for an overlayadd event.
      var bsqLandOutlineLoaded = false;
      function bsqLoadLandOutline() {{
        if (bsqLandOutlineLoaded) return;
        bsqLandOutlineLoaded = true;
        fetch("/api/bathymetry/land-outline", {{cache: "no-store"}})
          .then(function (r) {{ return r.json(); }})
          .then(function (geojson) {{
            L.geoJSON(geojson, {{
              style: function () {{ return {{fillColor: "none", fillOpacity: 0, color: "#20232a", weight: 1.6}}; }},
              pane: {land_outline_pane_json},
            }}).addTo({land_outline_group_var});
          }})
          .catch(function (e) {{ console.warn("Land outline unavailable (is python -m bite_score.webapp running?)", e); }});
      }}

      async function bsqLoadHistory() {{
        var listEl = document.getElementById("bsq-history-list");
        try {{
          var resp = await fetch("/api/history", {{cache: "no-store"}});
          var data = await resp.json();
          var dates = data.dates || [];
          listEl.innerHTML = "";

          var latestItem = document.createElement("div");
          latestItem.className = "bsq-history-item" + (!bsqDateFromPath ? " current" : "");
          latestItem.innerHTML = '<span class="material-symbols-outlined">bolt</span><span>Latest (most recent run)</span>';
          latestItem.addEventListener("click", function () {{ window.location.href = "/"; }});
          listEl.appendChild(latestItem);

          if (dates.length === 0) {{
            var empty = document.createElement("div");
            empty.className = "bsq-history-empty";
            empty.textContent = "No archived dates found yet.";
            listEl.appendChild(empty);
          }}

          dates.forEach(function (d) {{
            var item = document.createElement("div");
            item.className = "bsq-history-item" + (d === bsqDateFromPath ? " current" : "");
            item.innerHTML = '<span class="material-symbols-outlined">calendar_month</span><span>' + d + '</span>';
            item.addEventListener("click", function () {{ window.location.href = "/history/" + d; }});
            listEl.appendChild(item);
          }});

          // Auto-expand the history section when viewing an archived date,
          // so it's immediately obvious which day is showing and how to
          // get back to "Latest".
          if (bsqDateFromPath) {{
            document.getElementById("bsq-history-body").classList.add("open");
            document.getElementById("bsq-history-toggle").classList.add("open");
          }}

          bsqBuildTimeline(dates);
        }} catch (e) {{
          // No dashboard server running (e.g. this HTML was opened directly
          // as a file) -- explain why the list can't be populated.
          listEl.innerHTML = '<div class="bsq-history-empty">Can\\'t reach history server. Run: python -m bite_score.webapp</div>';
        }}
      }}

      // Timeline bar -- zoom/pan state
      var bsqTlAllDates = null;
      var bsqTlAllTimestamps = null;
      var bsqTlViewMin = null;
      var bsqTlViewMax = null;
      var bsqTlTotalMin = null;
      var bsqTlTotalMax = null;
      var bsqTlDragState = null; // {{startX, startViewMin, startViewMax, moved}}
      var BSQ_TL_VIEW_KEY = "bsqTlView_v1";

      // Timeline bar along the bottom of the map. Dates are positioned
      // proportionally by their calendar timestamp (to scale). Supports
      // mouse-wheel zoom (centred on the cursor), click-drag panning, and
      // double-click to reset to the full range.
      function bsqBuildTimeline(dates) {{
        var wrap = document.getElementById("bsq-tl-track-wrap");
        if (!wrap || !dates || dates.length === 0) return;

        bsqTlAllDates = dates.slice();
        bsqTlAllTimestamps = dates.map(function (d) {{ return new Date(d).getTime(); }});
        bsqTlTotalMin = Math.min.apply(null, bsqTlAllTimestamps);
        bsqTlTotalMax = Math.max.apply(null, bsqTlAllTimestamps);
        // Pad 3% right so the newest dot isn't flush against the edge
        var pad = (bsqTlTotalMax - bsqTlTotalMin || 1) * 0.03;
        bsqTlTotalMax += pad;
        bsqTlViewMin = bsqTlTotalMin;
        bsqTlViewMax = bsqTlTotalMax;

        // Restore saved zoom window from localStorage (preserved across
        // date navigation). Clamp to the current total range in case new
        // dates have been added outside the saved window.
        try {{
          var savedView = JSON.parse(localStorage.getItem(BSQ_TL_VIEW_KEY) || "null");
          if (savedView && typeof savedView.min === "number" && typeof savedView.max === "number") {{
            var sMin = Math.max(savedView.min, bsqTlTotalMin);
            var sMax = Math.min(savedView.max, bsqTlTotalMax);
            if (sMax - sMin > 14 * 86400000) {{
              bsqTlViewMin = sMin;
              bsqTlViewMax = sMax;
            }}
          }}
        }} catch (e) {{}}

        // Attach interaction handlers once
        if (!wrap._bsqTlBound) {{
          wrap._bsqTlBound = true;
          wrap.addEventListener("wheel", bsqTlOnWheel, {{passive: false}});
          wrap.addEventListener("mousedown", bsqTlOnMouseDown);
          document.addEventListener("mousemove", bsqTlOnMouseMove);
          document.addEventListener("mouseup", bsqTlOnMouseUp);
          wrap.addEventListener("dblclick", bsqTlResetZoom);
        }}

        // Latest button
        var latestBtn = document.getElementById("bsq-tl-latest-btn");
        if (latestBtn && !latestBtn._bsqTlBound) {{
          if (!bsqDateFromPath) {{
            latestBtn.style.opacity = "0.35";
            latestBtn.style.cursor = "default";
            latestBtn.style.pointerEvents = "none";
          }} else {{
            latestBtn._bsqTlBound = true;
            latestBtn.addEventListener("click", function () {{ window.location.href = "/"; }});
          }}
        }}

        // Zoom reset label
        var zoomLabel = document.getElementById("bsq-tl-zoom-label");
        if (zoomLabel && !zoomLabel._bsqTlBound) {{
          zoomLabel._bsqTlBound = true;
          zoomLabel.addEventListener("click", bsqTlResetZoom);
        }}

        bsqTlRender();
      }}

      // Re-draws all dots/ticks for the current view window.
      function bsqTlRender() {{
        var wrap = document.getElementById("bsq-tl-track-wrap");
        if (!wrap || !bsqTlAllDates) return;
        var tooltip = document.getElementById("bsq-tl-tooltip");

        // Clear previous renderable elements
        Array.prototype.forEach.call(
          wrap.querySelectorAll(".bsq-tl-dot,.bsq-tl-year-tick,.bsq-tl-year-label,.bsq-tl-label-current"),
          function (el) {{ el.remove(); }}
        );

        var viewRange = bsqTlViewMax - bsqTlViewMin;
        function toPercent(t) {{ return ((t - bsqTlViewMin) / viewRange) * 100; }}
        var MS_DAY = 86400000;

        // Year lines
        var yr = new Date(bsqTlViewMin).getUTCFullYear();
        while (true) {{
          var tYr = Date.UTC(yr, 0, 1);
          if (tYr > bsqTlViewMax) break;
          if (tYr >= bsqTlViewMin) {{
            var pct = toPercent(tYr);
            var ytick = document.createElement("div");
            ytick.className = "bsq-tl-year-tick";
            ytick.style.left = pct + "%";
            wrap.appendChild(ytick);
            var ylbl = document.createElement("div");
            ylbl.className = "bsq-tl-year-label";
            ylbl.style.left = pct + "%";
            ylbl.textContent = yr;
            wrap.appendChild(ylbl);
          }}
          yr++;
        }}

        // Month sub-ticks when view is < 180 days
        if (viewRange < 180 * MS_DAY) {{
          var d0 = new Date(bsqTlViewMin);
          var mo0 = d0.getUTCFullYear() * 12 + d0.getUTCMonth();
          var MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
          for (var mi = 0; mi < 25; mi++) {{
            var abs = mo0 + mi;
            var moYr = Math.floor(abs / 12), moMo = abs % 12;
            var tM = Date.UTC(moYr, moMo, 1);
            if (tM <= bsqTlViewMin) continue;
            if (tM > bsqTlViewMax) break;
            var pctM = toPercent(tM);
            var mtick = document.createElement("div");
            mtick.className = "bsq-tl-year-tick";
            mtick.style.left = pctM + "%";
            mtick.style.height = "4px";
            mtick.style.opacity = "0.5";
            wrap.appendChild(mtick);
            var mlbl = document.createElement("div");
            mlbl.className = "bsq-tl-year-label";
            mlbl.style.left = pctM + "%";
            mlbl.style.opacity = "0.7";
            mlbl.textContent = MONTHS[moMo];
            wrap.appendChild(mlbl);
          }}
        }}

        // Dots
        var currentDate = bsqCurrentDate || bsqDateFromPath;
        bsqTlAllDates.forEach(function (d, i) {{
          var ts = bsqTlAllTimestamps[i];
          if (ts < bsqTlViewMin || ts > bsqTlViewMax) return;
          var pct = toPercent(ts);
          var isCurrent = (d === currentDate);
          var dot = document.createElement("div");
          dot.className = "bsq-tl-dot" + (isCurrent ? " current" : "");
          dot.style.left = pct + "%";

          if (tooltip) {{
            dot.addEventListener("mouseenter", function (ev) {{
              tooltip.textContent = d;
              tooltip.style.display = "block";
              bsqTlPositionTooltip(ev);
            }});
            dot.addEventListener("mousemove", bsqTlPositionTooltip);
            dot.addEventListener("mouseleave", function () {{ tooltip.style.display = "none"; }});
          }}

          if (!isCurrent) {{
            dot.addEventListener("click", function () {{
              // Ignore if this mousedown→up was a drag
              if (bsqTlDragState && bsqTlDragState.moved) return;
              window.location.href = "/history/" + d;
            }});
          }}

          wrap.appendChild(dot);

          if (isCurrent) {{
            var clbl = document.createElement("div");
            clbl.className = "bsq-tl-label-current";
            clbl.style.left = pct + "%";
            clbl.textContent = d;
            wrap.appendChild(clbl);
          }}
        }});

        // Zoom range label
        var zoomLabel = document.getElementById("bsq-tl-zoom-label");
        if (zoomLabel) {{
          var isFullRange = (bsqTlViewMin <= bsqTlTotalMin + 1000 && bsqTlViewMax >= bsqTlTotalMax - 1000);
          if (isFullRange) {{
            zoomLabel.textContent = "";
            zoomLabel.classList.remove("visible");
          }} else {{
            var MONTHS2 = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
            function fmtT(t) {{ var dt = new Date(t); return MONTHS2[dt.getUTCMonth()] + " " + dt.getUTCFullYear(); }}
            zoomLabel.textContent = fmtT(bsqTlViewMin) + " \u2013 " + fmtT(bsqTlViewMax) + " \u00d7";
            zoomLabel.classList.add("visible");
          }}
        }}

        // Persist view to localStorage so navigating to another date
        // restores the same zoom window.
        try {{ localStorage.setItem(BSQ_TL_VIEW_KEY, JSON.stringify({{min: bsqTlViewMin, max: bsqTlViewMax}})); }} catch (e) {{}}
      }}

      function bsqTlOnWheel(ev) {{
        ev.preventDefault();
        var wrap = document.getElementById("bsq-tl-track-wrap");
        if (!wrap) return;
        var rect = wrap.getBoundingClientRect();
        var frac = Math.max(0, Math.min((ev.clientX - rect.left) / rect.width, 1));
        var viewRange = bsqTlViewMax - bsqTlViewMin;
        var factor = ev.deltaY < 0 ? 0.6 : 1.65; // wheel-up = zoom in
        var MS_DAY = 86400000;
        var newRange = Math.min(
          Math.max(viewRange * factor, 14 * MS_DAY),
          bsqTlTotalMax - bsqTlTotalMin
        );
        var pivotT = bsqTlViewMin + frac * viewRange;
        var newMin = pivotT - frac * newRange;
        var newMax = pivotT + (1 - frac) * newRange;
        if (newMin < bsqTlTotalMin) {{ newMax += bsqTlTotalMin - newMin; newMin = bsqTlTotalMin; }}
        if (newMax > bsqTlTotalMax) {{ newMin -= newMax - bsqTlTotalMax; newMax = bsqTlTotalMax; }}
        bsqTlViewMin = Math.max(newMin, bsqTlTotalMin);
        bsqTlViewMax = newMax;
        bsqTlRender();
      }}

      function bsqTlOnMouseDown(ev) {{
        if (ev.button !== 0) return;
        bsqTlDragState = {{startX: ev.clientX, startViewMin: bsqTlViewMin, startViewMax: bsqTlViewMax, moved: false}};
        var wrap = document.getElementById("bsq-tl-track-wrap");
        if (wrap) {{ wrap.classList.add("dragging"); }}
      }}

      function bsqTlOnMouseMove(ev) {{
        if (!bsqTlDragState) return;
        var dx = ev.clientX - bsqTlDragState.startX;
        if (Math.abs(dx) > 4) {{ bsqTlDragState.moved = true; }}
        if (!bsqTlDragState.moved) return;
        var wrap = document.getElementById("bsq-tl-track-wrap");
        if (!wrap) return;
        var rect = wrap.getBoundingClientRect();
        var viewRange = bsqTlDragState.startViewMax - bsqTlDragState.startViewMin;
        var dt = -(dx / rect.width) * viewRange;
        var newMin = bsqTlDragState.startViewMin + dt;
        var newMax = bsqTlDragState.startViewMax + dt;
        if (newMin < bsqTlTotalMin) {{ newMax += bsqTlTotalMin - newMin; newMin = bsqTlTotalMin; }}
        if (newMax > bsqTlTotalMax) {{ newMin -= newMax - bsqTlTotalMax; newMax = bsqTlTotalMax; }}
        bsqTlViewMin = Math.max(newMin, bsqTlTotalMin);
        bsqTlViewMax = newMax;
        bsqTlRender();
      }}

      function bsqTlOnMouseUp() {{
        if (!bsqTlDragState) return;
        var wrap = document.getElementById("bsq-tl-track-wrap");
        if (wrap) {{ wrap.classList.remove("dragging"); }}
        // Keep moved flag alive briefly so click handlers can check it
        var prev = bsqTlDragState;
        bsqTlDragState = null;
        if (prev.moved) {{ setTimeout(function () {{}}, 0); }}
      }}

      function bsqTlResetZoom() {{
        if (bsqTlTotalMin === null) return;
        bsqTlViewMin = bsqTlTotalMin;
        bsqTlViewMax = bsqTlTotalMax;
        bsqTlRender();
      }}

      function bsqTlPositionTooltip(ev) {{
        var tooltip = document.getElementById("bsq-tl-tooltip");
        if (!tooltip) return;
        var x = ev.clientX + 12, y = ev.clientY - 32;
        if (x + 120 > window.innerWidth) {{ x = ev.clientX - 124; }}
        tooltip.style.left = x + "px";
        tooltip.style.top = y + "px";
      }}

      // Fetches the MBGFC chart image/bounds and FAD/SFAD/wave-buoy marker
      // list from the dashboard server the first time either layer is
      // switched on (see the "overlayadd" listener above), rather than on
      // every page load -- keeps this static-file page lightweight and
      // avoids a network request when the user never looks at this layer.
      var bsqMbgfcLoaded = false;
      function bsqLoadMbgfc() {{
        if (bsqMbgfcLoaded) return;
        bsqMbgfcLoaded = true;

        fetch("/api/mbgfc/meta", {{cache: "no-store"}})
          .then(function (r) {{ return r.json(); }})
          .then(function (meta) {{
            {mbgfc_chart_var}.setUrl("/api/mbgfc/chart.png");
            {mbgfc_chart_var}.setBounds(meta.bounds);
          }})
          .catch(function (e) {{ console.warn("MBGFC chart unavailable (is python -m bite_score.webapp running?)", e); }});

        var categoryStyle = {{
          wave_buoy: {{color: "#1f6feb", label: "Wave Buoy"}},
          fad: {{color: "#f0883e", label: "FAD"}},
          sfad: {{color: "#8957e5", label: "SFAD (shelf)"}},
          other: {{color: "#8e9198", label: "Location"}},
        }};
        fetch("/api/mbgfc/locations", {{cache: "no-store"}})
          .then(function (r) {{ return r.json(); }})
          .then(function (data) {{
            (data.locations || []).forEach(function (loc) {{
              var style = categoryStyle[loc.category] || categoryStyle.other;
              var depthTxt = (loc.depth_m === null || loc.depth_m === undefined) ? "unknown" : (Math.round(loc.depth_m) + " m");
              var marker = L.circleMarker([loc.lat, loc.lon], {{
                radius: 5, color: style.color, fillColor: style.color, fillOpacity: 0.9, weight: 1.5,
                pane: {mbgfc_locations_pane_json},
              }});
              marker.bindTooltip(loc.name);
              marker.bindPopup(
                "<b>" + loc.name + "</b><br>" + style.label + "<br>" +
                loc.lat.toFixed(4) + ", " + loc.lon.toFixed(4) + "<br>Depth: " + depthTxt
              );
              marker.addTo({mbgfc_locations_var});
            }});
          }})
          .catch(function (e) {{ console.warn("MBGFC locations unavailable (is python -m bite_score.webapp running?)", e); }});
      }}

      // Fishing waypoints: Light Tackle Grounds (green) and Heavy Tackle
      // Marks (red). Loaded lazily the first time the layer is toggled on,
      // same pattern as bsqLoadMbgfc() above.
      var bsqWaypointsLoaded = false;
      function bsqLoadWaypoints() {{
        if (bsqWaypointsLoaded) return;
        bsqWaypointsLoaded = true;

        var categoryStyle = {{
          light_tackle: {{color: "#2ea043", fillColor: "#2ea043", label: "Light Tackle Grounds"}},
          heavy_tackle: {{color: "#e53e3e", fillColor: "#e53e3e", label: "Heavy Tackle Marks"}},
        }};
        fetch("/api/waypoints", {{cache: "no-store"}})
          .then(function (r) {{ return r.json(); }})
          .then(function (data) {{
            (data.waypoints || []).forEach(function (wp) {{
              var style = categoryStyle[wp.category] || categoryStyle.light_tackle;
              var marker = L.circleMarker([wp.lat, wp.lon], {{
                radius: 5, color: style.color, fillColor: style.fillColor,
                fillOpacity: 0.85, weight: 1.5,
                pane: {waypoints_pane_json},
              }});
              marker.bindPopup(
                "<b>" + wp.name + "</b><br>" + style.label + "<br>" +
                wp.lat.toFixed(4) + "\u00b0S, " + wp.lon.toFixed(4) + "\u00b0E"
              );
              marker.addTo({waypoints_var});
              // Text label floating to the right of the dot
              L.marker([wp.lat, wp.lon], {{
                icon: L.divIcon({{
                  iconSize: [0, 0],
                  iconAnchor: [0, 0],
                  html: '<div class="bsq-waypoint-label" style="color:' + style.color + '">' + wp.name + '</div>',
                }}),
                interactive: false,
                pane: {waypoints_pane_json},
              }}).addTo({waypoints_var});
            }});
            // Reef lines: polylines with an endpoint-circle at each end and
            // a label at the midpoint of each line.
            (data.reef_lines || []).forEach(function (rl) {{
              var reefColor = "#e67e00";
              L.polyline(rl.coords, {{
                color: reefColor, weight: 2.5, opacity: 0.9,
                dashArray: "6 4",
                pane: {waypoints_pane_json},
              }}).bindTooltip(rl.name)
                .bindPopup("<b>" + rl.name + "</b><br>" + rl.description)
                .addTo({waypoints_var});
              // Small circle at each endpoint
              rl.coords.forEach(function (c) {{
                L.circleMarker(c, {{
                  radius: 4, color: reefColor, fillColor: reefColor,
                  fillOpacity: 0.85, weight: 1.5,
                  pane: {waypoints_pane_json},
                }}).addTo({waypoints_var});
              }});
              // Label at the midpoint
              L.marker([rl.label_lat, rl.label_lon], {{
                icon: L.divIcon({{
                  iconSize: [0, 0],
                  iconAnchor: [0, 0],
                  html: '<div class="bsq-waypoint-label" style="color:' + reefColor + '">' + rl.name + '</div>',
                }}),
                interactive: false,
                pane: {waypoints_pane_json},
              }}).addTo({waypoints_var});
            }});
          }})
          .catch(function (e) {{ console.warn("Fishing waypoints unavailable (is python -m bite_score.webapp running?)", e); }});
      }}
      // Generic loader for the shared/static raster layers (Depth-
      // suitability factor, LiDAR, Moreton Bay Approaches, Mudjimba
      // Island): each is built once by the dashboard server and cached
      // to disk, so fetching it here (rather than embedding it into this
      // page) means every date's map reuses the exact same PNG instead of
      // re-rendering and re-storing an identical image per date.
      var bsqLoadedRasterLayers = {{}};
      function bsqLoadRasterLayer(key, layerVar) {{
        if (bsqLoadedRasterLayers[key]) return;
        bsqLoadedRasterLayers[key] = true;
        fetch("/api/static-layer/" + key + "/meta", {{cache: "no-store"}})
          .then(function (r) {{ return r.json(); }})
          .then(function (meta) {{
            layerVar.setUrl("/api/static-layer/" + key + "/chart.png");
            layerVar.setBounds(meta.bounds);
            bsqUpdateLegendRange(bsqStaticKeyToLabel[key], meta.min, meta.max);
          }})
          .catch(function (e) {{ console.warn("Static layer '" + key + "' unavailable (is python -m bite_score.webapp running?)", e); }});
      }}

      // Bathymetry contours are vector data (isobath lines + depth
      // labels), not an image, so they get their own loader that fills in
      // the placeholder FeatureGroup created above rather than swapping
      // an ImageOverlay's URL/bounds.
      var bsqContoursLoaded = false;
      function bsqLoadContours() {{
        if (bsqContoursLoaded) return;
        bsqContoursLoaded = true;
        fetch("/api/bathymetry/contours", {{cache: "no-store"}})
          .then(function (r) {{ return r.json(); }})
          .then(function (data) {{
            L.geoJSON(data.geojson, {{
              style: function () {{ return {{color: "#0b5394", weight: 1, opacity: 0.6, dashArray: "4,3"}}; }},
              pane: {contour_pane_json},
              onEachFeature: function (feature, layer) {{
                if (feature.properties && feature.properties.depth_m !== undefined) {{
                  layer.bindTooltip("Depth (m): " + feature.properties.depth_m);
                }}
              }},
            }}).addTo({contour_group_var});

            (data.labels || []).forEach(function (label) {{
              L.marker([label.lat, label.lon], {{
                icon: L.divIcon({{
                  iconSize: [0, 0],
                  iconAnchor: [0, 0],
                  html: '<div class="bsq-depth-label">' + Math.round(label.depth_m) + ' m</div>',
                }}),
                interactive: false,
              }}).addTo({contour_group_var});
            }});
          }})
          .catch(function (e) {{ console.warn("Bathymetry contours unavailable (is python -m bite_score.webapp running?)", e); }});
      }}

      // Per-date SLA contour lines (GeoJSON).  Called from overlayadd and
      // from bsqResolveDateAndLoad() (the async root-path case where the
      // layer was pre-checked via layer-restore before bsqCurrentDate was
      // known).  Caches the loaded GeoJSON layer by date so re-toggling
      // or navigating to the same date doesn't re-fetch.
      var bsqSlaContoursDate = null;   // date whose contours are in the group
      var bsqSlaContoursLayer = null;  // the L.geoJSON layer currently in the group
      function bsqLoadSlaContours(date) {{
        if (!date) return;
        if (bsqSlaContoursDate === date) return;  // already current
        // Remove old contours from the group
        if (bsqSlaContoursLayer) {{
          {sla_contour_group_var}.removeLayer(bsqSlaContoursLayer);
          bsqSlaContoursLayer = null;
        }}
        bsqSlaContoursDate = date;  // mark optimistically so rapid switches don't double-fetch
        fetch("/api/date-layer/" + date + "/sla_contours/contours.json", {{cache: "no-store"}})
          .then(function (r) {{ return r.json(); }})
          .then(function (data) {{
            // Color scale: red for positive, blue for negative, grey dashed for zero
            var newLayer = L.geoJSON(data.geojson, {{
              style: function (feature) {{
                var sla = feature.properties ? (feature.properties.sla_m || 0) : 0;
                var kind = feature.properties ? (feature.properties.kind || "zero") : "zero";
                var color = kind === "positive" ? "#c0392b"
                          : kind === "negative" ? "#1a5276"
                          : "#777777";
                var weight = Math.max(1, Math.min(3, Math.round(Math.abs(sla) * 12)));
                var dashArray = kind === "zero" ? "5,4" : null;
                return {{color: color, weight: weight, opacity: 0.80, dashArray: dashArray}};
              }},
              pane: {sla_contour_pane_json},
              onEachFeature: function (feature, layer) {{
                if (feature.properties && feature.properties.sla_m !== undefined) {{
                  var val = feature.properties.sla_m;
                  var sign = val > 0.001 ? "+" : "";
                  layer.bindTooltip("SLA: " + sign + val.toFixed(2) + " m");
                }}
              }},
            }});
            newLayer.addTo({sla_contour_group_var});
            bsqSlaContoursLayer = newLayer;

            // Value labels at mid-points of the longest segments
            (data.labels || []).forEach(function (label) {{
              var val = label.sla_m;
              var sign = val > 0.001 ? "+" : "";
              var kind = val > 0.001 ? "pos" : (val < -0.001 ? "neg" : "zero");
              L.marker([label.lat, label.lon], {{
                icon: L.divIcon({{
                  iconSize: [0, 0],
                  iconAnchor: [0, 0],
                  html: '<div class="bsq-sla-label bsq-sla-label--' + kind + '">'
                        + sign + val.toFixed(2) + ' m</div>',
                }}),
                interactive: false,
                pane: {sla_contour_pane_json},
              }}).addTo({sla_contour_group_var});
            }});
          }})
          .catch(function (e) {{ console.warn("SLA contours unavailable for " + date, e); }});
      }}

      // Check if SLA contours layer checkbox is currently checked and, if
      // so, ensure its data is loaded for the given date.  Called from
      // bsqResolveDateAndLoad() to handle the case where the layer was
      // restored before bsqCurrentDate was available (root "/" route).
      function bsqMaybeLoadSlaContours() {{
        if (!bsqCurrentDate) return;
        var container = document.querySelector("#bsq-layers-slot .leaflet-control-layers-overlays");
        if (!container) return;
        Array.prototype.forEach.call(container.querySelectorAll(":scope > label"), function (row) {{
          var input = row.querySelector("input[type=checkbox]");
          var span = row.querySelector("span:last-child");
          if (!input || !input.checked || !span) return;
          if (span.textContent.trim() === "Sea level anomaly contours") {{
            bsqLoadSlaContours(bsqCurrentDate);
          }}
        }});
      }}

      async function bsqPollStatus() {{
        var statusEl = document.getElementById("bsq-status");
        var btn = document.getElementById("bsq-update-btn");
        try {{
          var resp = await fetch("/api/status", {{cache: "no-store"}});
          var data = await resp.json();
          if (data.state === "running") {{
            statusEl.textContent = data.message || "Updating...";
            setTimeout(bsqPollStatus, 2000);
          }} else if (data.state === "done") {{
            statusEl.textContent = "Done! Reloading map...";
            setTimeout(function () {{ window.location.reload(); }}, 1200);
          }} else if (data.state === "error") {{
            statusEl.textContent = "Update failed: " + (data.message || "unknown error");
            btn.disabled = false;
          }} else {{
            btn.disabled = false;
          }}
        }} catch (e) {{
          setTimeout(bsqPollStatus, 3000);
        }}
      }}

      async function bsqUpdateData() {{
        var dateVal = document.getElementById("bsq-date").value;
        var btn = document.getElementById("bsq-update-btn");
        var statusEl = document.getElementById("bsq-status");
        btn.disabled = true;
        statusEl.textContent = "Starting update...";
        try {{
          var resp = await fetch("/api/update", {{
            method: "POST",
            headers: {{"Content-Type": "application/json"}},
            body: JSON.stringify({{date: dateVal}})
          }});
          if (!resp.ok) {{
            var body = await resp.json().catch(function () {{ return {{}}; }});
            statusEl.textContent = body.message || ("Server error: " + resp.status);
            btn.disabled = false;
            return;
          }}
          bsqPollStatus();
        }} catch (e) {{
          statusEl.textContent = "Can\u2019t reach update server. Run: python -m bite_score.webapp";
          btn.disabled = false;
        }}
      }}
    </script>
    """
    fmap.get_root().html.add_child(folium.Element(control_html))

    fmap.save(output_html)
    logger.info("Interactive Folium map saved to %s", output_html)
    return fmap


def build_plotly_map(geotiff_path: str):
    """
    Alternative visualization using Plotly's Densitymapbox (no Mapbox
    access token required when using an open-style basemap such as
    "open-street-map"). Downsamples the grid for a responsive browser plot.
    """
    import pandas as pd
    import plotly.graph_objects as go

    da = rioxarray.open_rasterio(geotiff_path, masked=True).squeeze()
    if da.rio.crs.to_epsg() != 4326:
        da = da.rio.reproject("EPSG:4326")

    y_dim, x_dim = da.dims[-2], da.dims[-1]
    step_y = max(1, da.sizes[y_dim] // 200)
    step_x = max(1, da.sizes[x_dim] // 200)
    da_small = da[::step_y, ::step_x]

    lon2d, lat2d = np.meshgrid(da_small[x_dim].values, da_small[y_dim].values)
    df = pd.DataFrame(
        {
            "lat": lat2d.ravel(),
            "lon": lon2d.ravel(),
            "bite_score": da_small.values.ravel(),
        }
    ).dropna()

    fig = go.Figure(
        go.Densitymapbox(
            lat=df["lat"],
            lon=df["lon"],
            z=df["bite_score"],
            radius=8,
            colorscale="Turbo",
            zmin=0,
            zmax=100,
            colorbar_title="Bite Score",
        )
    )
    fig.update_layout(
        mapbox_style="open-street-map",
        mapbox_center={"lat": MAP_CENTER[0], "lon": MAP_CENTER[1]},
        mapbox_zoom=8,
        margin=dict(l=0, r=0, t=0, b=0),
        title="Yellowfin Tuna Bite Probability Score - SE Queensland",
    )
    return fig
