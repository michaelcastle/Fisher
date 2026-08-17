"""
On-demand PNG/meta assets for the per-date Bite Score layers -- the main
heatmap, the legacy comparison heatmap, the four daily contributing-factor
layers (SST/chlorophyll/current/SSHA), and FSLE. Unlike static_layers.py,
these genuinely differ per date, so they're cached under that date's own
`output/history/<date>/` folder rather than globally -- but, like the
static layers, they're still built lazily on first request rather than
embedded directly into a generated HTML page.

This is what lets a single `bite_score_map.html` template (see
visualize.py::build_folium_map()) serve every date, past or future,
without needing its own generated HTML file: the template only ever
references `/api/date-layer/<date>/<key>/*`, with `<date>` resolved
client-side (from the URL, or from `/api/latest-date`).
"""
import json
import logging
import os
import re

import numpy as np
from PIL import Image

from . import config
from .raster_utils import fsle_to_rgba, mld_to_rgba, open_score_raster, raster_to_rgba, sla_contour_geojson, sla_to_rgba

logger = logging.getLogger(__name__)

# "demo" is accepted alongside real YYYY-MM-DD dates so `run_demo.py`'s
# synthetic output (stored under output/history/demo/) can be viewed
# through the same dashboard/template, without polluting the real
# Historical Data list (which only lists directories matching the stricter
# date-only pattern -- see webapp.py::_list_history_dates()).
_DATE_KEY_RE = re.compile(r"^(?:\d{4}-\d{2}-\d{2}|demo)$")

# Registry of per-date layers: the GeoTIFF filename `main.py`/`run_demo.py`
# already export into each date's history folder, and how to convert it to
# an RGBA image for display.
DATE_LAYER_SPECS = {
    "bite_score": {"filename": "bite_score.tif", "rgba_fn": raster_to_rgba},
    "legacy": {"filename": "bite_score_legacy.tif", "rgba_fn": raster_to_rgba},
    "sst": {"filename": "layer_sst.tif", "rgba_fn": raster_to_rgba},
    "chl": {"filename": "layer_chl.tif", "rgba_fn": raster_to_rgba},
    "current": {"filename": "layer_current.tif", "rgba_fn": raster_to_rgba},
    "ssha": {"filename": "layer_ssha.tif", "rgba_fn": raster_to_rgba},
    # Raw mixed layer depth (metres), not yet a 0-100 score -- see
    # mld_to_rgba()'s docstring and _CONTRIBUTING_LAYERS in visualize.py.
    # Ripley owns turning this into a real WLC gradient/front factor.
    "mld": {"filename": "layer_mld.tif", "rgba_fn": mld_to_rgba},
    "fsle": {"filename": "layer_fsle.tif", "rgba_fn": fsle_to_rgba},
    # Satellite altimetry Sea Level Anomaly: diverging blue/white/red,
    # positive = warm-core eddy, negative = cold-core / upwelling zone.
    # Fetched from NOAA CoastWatch ERDDAP (nesdisSSH1day, no auth).
    # Not available for every date (2017-present archive, ~3-day NRT lag).
    "sla": {"filename": "layer_sla.tif", "rgba_fn": sla_to_rgba},
}


# v2 ("Beta") registry: mirrors DATE_LAYER_SPECS above exactly, but reads
# from that date's SEPARATE output/history/<date>/v2/ subfolder (see
# main.py::run_pipeline_v2()/pipeline_v2.py::compute_bite_score_v2()) so
# v1's DATE_LAYER_SPECS/build_date_layer_assets() above are never touched.
# Every v2 layer (the combined score and all 6-7 contributing factors) is
# already scaled 0-100 by overlay_v2.py::weighted_overlay_v2(), so
# raster_to_rgba (v1's plain 0-100 colour-mapper) works unmodified for all
# of them -- unlike v1's raw-metres "mld" layer above, v2's "mld" entry is
# a normalized 0-100 gradient score, not a raw depth field.
DATE_LAYER_SPECS_V2 = {
    "bite_score_v2": {"filename": "bite_score_v2.tif", "rgba_fn": raster_to_rgba},
    "structure": {"filename": "layer_structure.tif", "rgba_fn": raster_to_rgba},
    "sst_bell": {"filename": "layer_sst_bell.tif", "rgba_fn": raster_to_rgba},
    "chl_band": {"filename": "layer_chl_band.tif", "rgba_fn": raster_to_rgba},
    "eddy": {"filename": "layer_eddy.tif", "rgba_fn": raster_to_rgba},
    "current": {"filename": "layer_current.tif", "rgba_fn": raster_to_rgba},
    "bathymetry": {"filename": "layer_bathymetry.tif", "rgba_fn": raster_to_rgba},
    "mld": {"filename": "layer_mld.tif", "rgba_fn": raster_to_rgba},
}


def validate_date_key(date: str) -> str:
    if not _DATE_KEY_RE.match(date or ""):
        raise ValueError(f"date must be YYYY-MM-DD (or 'demo'), got: {date!r}")
    return date


def build_date_layer_assets(date: str, key: str, force_rebuild: bool = False) -> tuple:
    """
    Build (if not already cached) and return (png_path, meta_json_path) for
    one of the per-date layers in `DATE_LAYER_SPECS`, reading its already-
    exported GeoTIFF from `output/history/<date>/`. Raises `KeyError` for
    an unknown layer key, or `FileNotFoundError` if that date/layer
    combination hasn't been computed (e.g. FSLE unavailable for that date,
    or the date itself was never processed) -- webapp.py turns either into
    a 404 response.

    The PNG is the already-colour-mapped RGBA image (browser-ready); the
    JSON holds its lat/lon bounds plus the raw value min/max (used to show
    the "Score range" stat in the sidebar) -- same split used by
    static_layers.py::build_raster_layer_assets().
    """
    validate_date_key(date)
    if key not in DATE_LAYER_SPECS:
        raise KeyError(f"Unknown date layer: {key!r}")
    spec = DATE_LAYER_SPECS[key]
    date_dir = os.path.join(config.HISTORY_DIR, date)
    geotiff_path = os.path.join(date_dir, spec["filename"])
    if not os.path.isfile(geotiff_path):
        raise FileNotFoundError(f"No {key!r} data for {date!r}")

    png_path = os.path.join(date_dir, f"chart_{key}.png")
    meta_path = os.path.join(date_dir, f"meta_{key}.json")
    if os.path.exists(png_path) and os.path.exists(meta_path) and not force_rebuild:
        return png_path, meta_path

    _da, values, bounds = open_score_raster(geotiff_path)
    rgba = spec["rgba_fn"](values)
    rgba_uint8 = (np.clip(rgba, 0.0, 1.0) * 255).astype("uint8")
    Image.fromarray(rgba_uint8, mode="RGBA").save(png_path)

    finite_values = values[np.isfinite(values)]
    meta = {
        "bounds": [[bounds[1], bounds[0]], [bounds[3], bounds[2]]],
        "min": float(finite_values.min()) if finite_values.size else None,
        "max": float(finite_values.max()) if finite_values.size else None,
    }
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f)

    logger.info("Cached %s layer for %s to %s / %s", key, date, png_path, meta_path)
    return png_path, meta_path


def build_date_layer_assets_v2(date: str, key: str, force_rebuild: bool = False) -> tuple:
    """
    v2 ("Beta") counterpart of build_date_layer_assets() above -- identical
    caching/RGBA-conversion logic, but reads/writes under that date's
    SEPARATE output/history/<date>/v2/ subfolder (DATE_LAYER_SPECS_V2)
    instead of the date dir's root, so it can never collide with or
    overwrite any of v1's cached chart_<key>.png/meta_<key>.json files for
    the same date. Raises FileNotFoundError (turned into a 404 by
    webapp.py) whenever Ripley's v2 pipeline hasn't been run for that date
    yet -- the normal, expected case for the vast majority of dates while
    v2 is still experimental/Beta.
    """
    validate_date_key(date)
    if key not in DATE_LAYER_SPECS_V2:
        raise KeyError(f"Unknown v2 date layer: {key!r}")
    spec = DATE_LAYER_SPECS_V2[key]
    v2_dir = os.path.join(config.HISTORY_DIR, date, "v2")
    geotiff_path = os.path.join(v2_dir, spec["filename"])
    if not os.path.isfile(geotiff_path):
        raise FileNotFoundError(f"No v2 (Beta) {key!r} data for {date!r}")

    png_path = os.path.join(v2_dir, f"chart_{key}.png")
    meta_path = os.path.join(v2_dir, f"meta_{key}.json")
    if os.path.exists(png_path) and os.path.exists(meta_path) and not force_rebuild:
        return png_path, meta_path

    _da, values, bounds = open_score_raster(geotiff_path)
    rgba = spec["rgba_fn"](values)
    rgba_uint8 = (np.clip(rgba, 0.0, 1.0) * 255).astype("uint8")
    Image.fromarray(rgba_uint8, mode="RGBA").save(png_path)

    finite_values = values[np.isfinite(values)]
    meta = {
        "bounds": [[bounds[1], bounds[0]], [bounds[3], bounds[2]]],
        "min": float(finite_values.min()) if finite_values.size else None,
        "max": float(finite_values.max()) if finite_values.size else None,
    }
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f)

    logger.info("Cached v2 %s layer for %s to %s / %s", key, date, png_path, meta_path)
    return png_path, meta_path


# Lenigas registry: mirrors DATE_LAYER_SPECS_V2 above exactly, but reads
# from that date's SEPARATE output/history/<date>/lenigas/ subfolder (see
# main.py::run_pipeline_lenigas()/pipeline_lenigas.py::compute_bite_score_lenigas())
# so v1's DATE_LAYER_SPECS/build_date_layer_assets() and v2's
# DATE_LAYER_SPECS_V2/build_date_layer_assets_v2() above are never touched.
# "Lenigas" -- named after the SEQ fisherman podcast account this
# experimental model is based on -- must NEVER be referred to as "v3"
# anywhere in this codebase. The combined score and all 6 WLC factors are
# already scaled 0-100 by overlay_lenigas.py::weighted_overlay_lenigas(),
# so raster_to_rgba works unmodified for them; wind speed is informational
# only (not part of the WLC weights, see config.LAYER_WEIGHTS_LENIGAS) and
# is a raw m/s field, so it reuses mld_to_rgba's generic percentile-clipped
# raw-field renderer instead (same treatment v1 gives its own raw-metres
# MLD diagnostic layer).
DATE_LAYER_SPECS_LENIGAS = {
    "bite_score_lenigas": {"filename": "bite_score_lenigas.tif", "rgba_fn": raster_to_rgba},
    "sst_bell": {"filename": "layer_sst_bell_lenigas.tif", "rgba_fn": raster_to_rgba},
    "depth_suitability": {"filename": "layer_depth_suitability_lenigas.tif", "rgba_fn": raster_to_rgba},
    "upwelling_downwelling": {"filename": "layer_upwelling_downwelling.tif", "rgba_fn": raster_to_rgba},
    "eac_axis_position": {"filename": "layer_eac_axis_position.tif", "rgba_fn": raster_to_rgba},
    "eac_convergence": {"filename": "layer_eac_convergence.tif", "rgba_fn": raster_to_rgba},
    "ssha_hotspot": {"filename": "layer_ssha_hotspot_lenigas.tif", "rgba_fn": raster_to_rgba},
    "wind_speed": {"filename": "layer_wind_speed.tif", "rgba_fn": mld_to_rgba},
}


def build_date_layer_assets_lenigas(date: str, key: str, force_rebuild: bool = False) -> tuple:
    """
    Lenigas counterpart of build_date_layer_assets_v2() above -- identical
    caching/RGBA-conversion logic, but reads/writes under that date's
    SEPARATE output/history/<date>/lenigas/ subfolder (DATE_LAYER_SPECS_LENIGAS,
    config.LENIGAS_OUTPUT_SUBDIR) instead of v1's date-dir root or v2's
    "v2" subfolder, so it can never collide with either. Raises
    FileNotFoundError (turned into a 404 by webapp.py) whenever Ripley's
    Lenigas pipeline hasn't been run for that date yet -- the normal,
    expected case for most dates while this experimental model is only
    available for a handful of test dates.
    """
    validate_date_key(date)
    if key not in DATE_LAYER_SPECS_LENIGAS:
        raise KeyError(f"Unknown Lenigas date layer: {key!r}")
    spec = DATE_LAYER_SPECS_LENIGAS[key]
    lenigas_dir = os.path.join(config.HISTORY_DIR, date, config.LENIGAS_OUTPUT_SUBDIR)
    geotiff_path = os.path.join(lenigas_dir, spec["filename"])
    if not os.path.isfile(geotiff_path):
        raise FileNotFoundError(f"No Lenigas {key!r} data for {date!r}")

    png_path = os.path.join(lenigas_dir, f"chart_{key}.png")
    meta_path = os.path.join(lenigas_dir, f"meta_{key}.json")
    if os.path.exists(png_path) and os.path.exists(meta_path) and not force_rebuild:
        return png_path, meta_path

    _da, values, bounds = open_score_raster(geotiff_path)
    rgba = spec["rgba_fn"](values)
    rgba_uint8 = (np.clip(rgba, 0.0, 1.0) * 255).astype("uint8")
    Image.fromarray(rgba_uint8, mode="RGBA").save(png_path)

    finite_values = values[np.isfinite(values)]
    meta = {
        "bounds": [[bounds[1], bounds[0]], [bounds[3], bounds[2]]],
        "min": float(finite_values.min()) if finite_values.size else None,
        "max": float(finite_values.max()) if finite_values.size else None,
    }
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f)

    logger.info("Cached Lenigas %s layer for %s to %s / %s", key, date, png_path, meta_path)
    return png_path, meta_path


# GT registry: mirrors DATE_LAYER_SPECS_LENIGAS above exactly, but reads
# from that date's SEPARATE output/history/<date>/gt/ subfolder so it
# can never collide with any of v1/v2/Lenigas's cached assets. All six WLC
# factor layers plus the combined bite score are 0-100 rasters, so
# raster_to_rgba works unmodified for them all.
DATE_LAYER_SPECS_GT = {
    "bite_score_gt":      {"filename": "bite_score_gt.tif",             "rgba_fn": raster_to_rgba},
    "eac_edge_gt":        {"filename": "layer_eac_edge_gt.tif",         "rgba_fn": raster_to_rgba},
    "upwelling_gt":       {"filename": "layer_upwelling_gt.tif",        "rgba_fn": raster_to_rgba},
    "depth_gt":           {"filename": "layer_depth_gt.tif",            "rgba_fn": raster_to_rgba},
    "structure_gt":       {"filename": "layer_structure_gt.tif",        "rgba_fn": raster_to_rgba},
    "sst_gt":             {"filename": "layer_sst_gt.tif",              "rgba_fn": raster_to_rgba},
    "moon_phase_gt":      {"filename": "layer_moon_phase_gt.tif",       "rgba_fn": raster_to_rgba},
    "current_gradient_gt":{"filename": "layer_current_gradient_gt.tif", "rgba_fn": raster_to_rgba},
    "north_wind_gt":      {"filename": "layer_north_wind_gt.tif",       "rgba_fn": raster_to_rgba},
}


def build_date_layer_assets_gt(date: str, key: str, force_rebuild: bool = False) -> tuple:
    """
    GT counterpart of build_date_layer_assets_lenigas() -- reads/writes
    under output/history/<date>/gt/ so it can never overwrite any of
    v1/v2/Lenigas's cached chart_<key>.png/meta_<key>.json files.

    Raises KeyError for an unknown layer key; FileNotFoundError if the GT
    pipeline hasn't been run for this date yet (webapp.py turns either into
    a 404 response).
    """
    validate_date_key(date)
    if key not in DATE_LAYER_SPECS_GT:
        raise KeyError(f"Unknown GT date layer: {key!r}")
    spec = DATE_LAYER_SPECS_GT[key]
    gt_dir = os.path.join(config.HISTORY_DIR, date, config.GT_OUTPUT_SUBDIR)
    geotiff_path = os.path.join(gt_dir, spec["filename"])
    if not os.path.isfile(geotiff_path):
        raise FileNotFoundError(f"No GT {key!r} data for {date!r}")

    png_path = os.path.join(gt_dir, f"chart_{key}.png")
    meta_path = os.path.join(gt_dir, f"meta_{key}.json")
    if os.path.exists(png_path) and os.path.exists(meta_path) and not force_rebuild:
        return png_path, meta_path

    _da, values, bounds = open_score_raster(geotiff_path)
    rgba = spec["rgba_fn"](values)
    rgba_uint8 = (np.clip(rgba, 0.0, 1.0) * 255).astype("uint8")
    Image.fromarray(rgba_uint8, mode="RGBA").save(png_path)

    finite_values = values[np.isfinite(values)]
    meta = {
        "bounds": [[bounds[1], bounds[0]], [bounds[3], bounds[2]]],
        "min": float(finite_values.min()) if finite_values.size else None,
        "max": float(finite_values.max()) if finite_values.size else None,
    }
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f)

    logger.info("Cached GT %s layer for %s to %s / %s", key, date, png_path, meta_path)
    return png_path, meta_path


# Outerline ("v3" / Yellowfin Environmental Hotspot Score) registry:
# mirrors DATE_LAYER_SPECS_GT above exactly, but reads from that date's
# SEPARATE output/history/<date>/outerline/ subfolder (see
# main.py::run_pipeline_outerline() / pipeline_outerline.py) so it can
# never collide with any other model's cached assets. The combined
# hotspot score and every WLC factor layer are already scaled 0-100 by
# overlay_outerline.py::weighted_overlay_outerline(), so raster_to_rgba
# works unmodified for all of them, including feature_convergence_count
# (an integer count 0-8, rendered on the same 0-100 colour ramp -- its
# real range is shown via the min/max in the accompanying meta JSON).
DATE_LAYER_SPECS_OUTERLINE = {
    "hotspot_score_outerline":  {"filename": "hotspot_score_outerline.tif", "rgba_fn": raster_to_rgba},
    "sst_suitability":          {"filename": "layer_sst_suitability.tif", "rgba_fn": raster_to_rgba},
    "sst_front":                {"filename": "layer_sst_front.tif", "rgba_fn": raster_to_rgba},
    "eac_boundary":              {"filename": "layer_eac_boundary.tif", "rgba_fn": raster_to_rgba},
    "current_convergence":      {"filename": "layer_current_convergence.tif", "rgba_fn": raster_to_rgba},
    "current_interaction":      {"filename": "layer_current_interaction.tif", "rgba_fn": raster_to_rgba},
    "sla_boundary":              {"filename": "layer_sla_boundary.tif", "rgba_fn": raster_to_rgba},
    "upwelling_downwelling":    {"filename": "layer_upwelling_downwelling.tif", "rgba_fn": raster_to_rgba},
    "bathymetry":                {"filename": "layer_bathymetry.tif", "rgba_fn": raster_to_rgba},
    "bait_proxy":                {"filename": "layer_bait_proxy.tif", "rgba_fn": raster_to_rgba},
    "fsle_front":                {"filename": "layer_fsle_front.tif", "rgba_fn": raster_to_rgba},
    "wind_visibility":          {"filename": "layer_wind_visibility.tif", "rgba_fn": raster_to_rgba},
    "feature_convergence_count": {"filename": "layer_feature_convergence_count.tif", "rgba_fn": raster_to_rgba},
}


def build_date_layer_assets_outerline(date: str, key: str, force_rebuild: bool = False) -> tuple:
    """
    Outerline counterpart of build_date_layer_assets_gt() -- reads/writes
    under output/history/<date>/outerline/ so it can never overwrite any
    other model's cached chart_<key>.png/meta_<key>.json files.

    Raises KeyError for an unknown layer key; FileNotFoundError if the
    Outerline pipeline hasn't been run for this date yet (webapp.py turns
    either into a 404 response). `season` and `feature_convergence_count`
    (a scalar-broadcast and a count layer, not "gradient/front" layers
    like the rest) are still plain 0-100-range GeoTIFFs, so no special
    handling is needed here.
    """
    validate_date_key(date)
    if key not in DATE_LAYER_SPECS_OUTERLINE:
        raise KeyError(f"Unknown Outerline date layer: {key!r}")
    spec = DATE_LAYER_SPECS_OUTERLINE[key]
    outerline_dir = os.path.join(config.HISTORY_DIR, date, config.OUTERLINE_OUTPUT_SUBDIR)
    geotiff_path = os.path.join(outerline_dir, spec["filename"])
    if not os.path.isfile(geotiff_path):
        raise FileNotFoundError(f"No Outerline {key!r} data for {date!r}")

    png_path = os.path.join(outerline_dir, f"chart_{key}.png")
    meta_path = os.path.join(outerline_dir, f"meta_{key}.json")
    if os.path.exists(png_path) and os.path.exists(meta_path) and not force_rebuild:
        return png_path, meta_path

    _da, values, bounds = open_score_raster(geotiff_path)
    rgba = spec["rgba_fn"](values)
    rgba_uint8 = (np.clip(rgba, 0.0, 1.0) * 255).astype("uint8")
    Image.fromarray(rgba_uint8, mode="RGBA").save(png_path)

    finite_values = values[np.isfinite(values)]
    meta = {
        "bounds": [[bounds[1], bounds[0]], [bounds[3], bounds[2]]],
        "min": float(finite_values.min()) if finite_values.size else None,
        "max": float(finite_values.max()) if finite_values.size else None,
    }
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f)

    logger.info("Cached Outerline %s layer for %s to %s / %s", key, date, png_path, meta_path)
    return png_path, meta_path


def build_sla_contours_json(date: str, force_rebuild: bool = False) -> str:
    """
    Build (if not already cached) and return the path to the per-date SLA
    contour GeoJSON file (``sla_contours.json`` under
    ``output/history/<date>/``).

    Raises ``FileNotFoundError`` if ``layer_sla.tif`` hasn't been computed
    for this date (webapp.py turns that into a 404).  Contour levels are
    ±0.3, ±0.2, ±0.1 and 0.0 m -- chosen to bracket typical EAC eddy
    amplitudes in SE Queensland waters.
    """
    validate_date_key(date)
    date_dir = os.path.join(config.HISTORY_DIR, date)
    sla_tif_path = os.path.join(date_dir, "layer_sla.tif")
    if not os.path.isfile(sla_tif_path):
        raise FileNotFoundError(f"No SLA layer for {date!r} -- layer_sla.tif not found")

    out_path = os.path.join(date_dir, "sla_contours.json")
    if os.path.isfile(out_path) and not force_rebuild:
        return out_path

    geojson, labels = sla_contour_geojson(sla_tif_path)
    payload = {"geojson": geojson, "labels": labels}
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, separators=(",", ":"))
    logger.info("SLA contours cached for %s → %s", date, out_path)
    return out_path
