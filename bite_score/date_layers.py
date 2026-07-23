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
from .raster_utils import fsle_to_rgba, mld_to_rgba, open_score_raster, raster_to_rgba

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
    "distance_offshore": {"filename": "layer_distance_offshore.tif", "rgba_fn": raster_to_rgba},
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
