"""
Orchestrator: run the full daily Yellowfin Tuna Bite Probability Score
pipeline end-to-end (ingest -> process -> normalize -> overlay -> export ->
visualize).

Usage:
    python -m bite_score.main --date 2026-07-18
"""
import argparse
import json
import logging
import os
import re

from . import config
from .bathymetry_composite import build_composite_bathymetry
from .data_ingestion import (
    fetch_daily_ocean_data,
    fetch_daily_ocean_data_v2,
    fetch_chl_composite,
    fetch_mld,
    fetch_mld_v2,
    load_bathymetry_v2,
    load_erddap_layer,
    load_erddap_layer_v2,
)
from .data_ingestion_lenigas import fetch_wind_data_lenigas
from .fsle import fetch_and_compute_fsle
from .moon_phase import moon_phase_details
from .overlay import apply_moon_phase_multiplier
from .pipeline import compute_bite_score, compute_bite_score_legacy
from .pipeline_v2 import compute_bite_score_v2
from .pipeline_lenigas import compute_bite_score_lenigas
from .export import export_geotiff
from .visualize import build_folium_map, build_plotly_map

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def run_pipeline(target_date: str = config.DEFAULT_TARGET_DATE) -> str:
    """Run the end-to-end pipeline for a single date and return the GeoTIFF path."""
    if not _DATE_RE.match(target_date or ""):
        raise ValueError(f"target_date must be in YYYY-MM-DD format, got: {target_date!r}")

    logger.info("=== Yellowfin Tuna Bite Score pipeline: %s ===", target_date)

    # 1. Data ingestion --------------------------------------------------
    ocean = fetch_daily_ocean_data(target_date)
    # Composite bathymetry: raw GEBCO (~450m) with the 3 supplementary
    # high-resolution local surveys (Sunshine Coast LiDAR, AusSeabed
    # Moreton Bay Approaches / Mudjimba Island) merged in wherever they
    # cover a cell -- see bathymetry_composite.py. This is both the
    # depth-suitability factor's input AND the alignment reference grid
    # every other daily layer gets resampled onto (see
    # overlay.py::weighted_overlay()), so real survey data measurably
    # improves accuracy in the areas it covers, not just the depth factor
    # in isolation.
    depth = build_composite_bathymetry()

    physics = ocean["physics"]

    # SST and chlorophyll are sourced from NOAA satellite products (MUR SST
    # ~1km, VIIRS chlorophyll ~4km) instead of the coarser Copernicus model
    # fields, since they resolve thermal/chlorophyll fronts far more sharply.
    # Chlorophyll fallback chain (highest→lowest accuracy):
    #   1. IMOS SRS OC NOAA-20 (0.0075°/833m, AUS regional atm. correction) — 2023-present
    #   2. VIIRS SNPP NRT (nesdisVHNchlaDaily)      — 4km, ~14-day rolling window
    #   3. VIIRS SNPP Science Quality (nesdisVHNSQchlaDaily) — 4km, 2012-present archive
    #   4. MODIS Aqua R2022SQ (erdMH1chla1day_R2022SQ)      — 4km, 2003-2022 archive
    #   5. Copernicus BGC model (cmems_mod_glo_bgc-pft_anfc_0.25deg_P1D-m) — 27km, last resort
    copernicus_sst = physics["thetao"].isel(time=0)
    if "depth" in copernicus_sst.dims:
        copernicus_sst = copernicus_sst.isel(depth=0)  # surface level only

    copernicus_chl = ocean["biogeochemistry"]["chl"].isel(time=0)
    if "depth" in copernicus_chl.dims:
        copernicus_chl = copernicus_chl.isel(depth=0)  # surface level only

    try:
        sst = load_erddap_layer("sst", target_date)
    except Exception:
        logger.warning(
            "NOAA MUR SST unavailable for %s, falling back to Copernicus SST", target_date, exc_info=True
        )
        sst = copernicus_sst

    try:
        chl = fetch_chl_composite(target_date)
        logger.info("Using IMOS SRS OC NOAA-20 chlorophyll composite (833m) for %s", target_date)
    except Exception:
        logger.warning(
            "IMOS OC chlorophyll unavailable for %s, trying VIIRS NRT...",
            target_date, exc_info=True,
        )
        try:
            chl = load_erddap_layer("chl", target_date)
        except Exception:
            logger.warning(
                "VIIRS NRT chlorophyll unavailable for %s, trying VIIRS Science Quality...",
                target_date, exc_info=True,
            )
            try:
                chl = load_erddap_layer("chl_sq", target_date)
                logger.info("Using VIIRS Science Quality chlorophyll for %s", target_date)
            except Exception:
                logger.warning(
                    "VIIRS SQ chlorophyll unavailable for %s, trying MODIS Aqua R2022SQ...",
                    target_date, exc_info=True,
                )
                try:
                    chl = load_erddap_layer("chl_modis", target_date)
                    logger.info("Using MODIS Aqua R2022SQ chlorophyll for %s", target_date)
                except Exception:
                    logger.warning(
                        "All satellite chlorophyll sources unavailable for %s, "
                        "falling back to Copernicus BGC model (27km)",
                        target_date, exc_info=True,
                    )
                    chl = copernicus_chl

    uo = physics["uo"].isel(time=0)
    vo = physics["vo"].isel(time=0)
    if "depth" in uo.dims:
        uo, vo = uo.isel(depth=0), vo.isel(depth=0)

    ssha = physics["zos"].isel(time=0)
    if "depth" in ssha.dims:
        ssha = ssha.isel(depth=0)

    # Mixed layer depth (mlotst): Kane-recommended #1 quick-win signal (see
    # .squad/decisions.md / .squad/decisions/inbox/ash-mld-moonphase.md) --
    # a proxy for vertically-compressed forage layers that concentrate tuna
    # feeding. Fetched from the same Copernicus Marine product
    # family/cadence/resolution as thetao/uo/vo/zos above, ahead of scoring
    # so it can feed into compute_bite_score() below as a 6th WLC factor
    # (see overlay.py::weighted_overlay / config.LAYER_WEIGHTS["mld_gradient"],
    # wired in by Ripley -- see
    # .squad/decisions/inbox/ripley-mld-moon-scoring.md). Degrades
    # gracefully (mld=None) rather than failing the whole pipeline, since
    # the assumed dataset id is unverified (see fetch_mld()'s docstring) --
    # weighted_overlay() proportionally rebalances the other 5 weights
    # when this happens.
    mld = None
    try:
        mld = fetch_mld(target_date)
    except Exception:
        logger.warning(
            "Mixed layer depth (mlotst) unavailable for %s; scoring without the MLD factor",
            target_date, exc_info=True,
        )

    # Moon phase / lunar illumination fraction: Kane-recommended #2
    # quick-win signal, pure astronomical calculation (no external data
    # ingestion, can't fail from network issues) -- a single day-level
    # scalar (0.0 = new moon/dark, 1.0 = full moon/bright) applied as a
    # UNIFORM MULTIPLIER on the final Bite Score below (Michael Castle's
    # decision -- see overlay.py::apply_moon_phase_multiplier for the
    # bounds/directionality rationale), computed here so it's available
    # before the final score is exported. `moon_phase_details()` also
    # returns phase_name/phase_age_days (real astral values, not derived
    # from illumination_fraction alone -- illumination is symmetric around
    # new/full so it can't distinguish waxing vs waning) for Lambert's
    # `/moon/<date>` detail page.
    moon_details = moon_phase_details(target_date)
    moon_illumination = moon_details["illumination_fraction"]

    # 2-4. Gradients, normalization, and WLC overlay ------------------------
    bite_score, layer_scores = compute_bite_score(sst, uo, vo, chl, ssha, depth, mld=mld)
    bite_score = apply_moon_phase_multiplier(bite_score, moon_illumination)

    # Also compute the original (pre-Gold-Coast-upgrade) 4-layer, SST-
    # referenced, nearest-neighbor overlay -- using the Copernicus model
    # SST/chlorophyll it originally relied on -- purely for side-by-side
    # comparison against the current, more accurate overlay. Deliberately
    # NOT given the MLD factor or the moon-phase multiplier, so it stays a
    # faithful reproduction of the original formula for comparison.
    bite_score_legacy = compute_bite_score_legacy(copernicus_sst, uo, vo, copernicus_chl, depth)

    # 5. Export + visualize -------------------------------------------------
    # Each day's outputs are archived under output/history/<date>/ (rather
    # than overwritten in place) so past days can be revisited later via the
    # dashboard's "View historical data" dropdown without re-running the
    # (slow, network-bound) pipeline again.
    date_dir = os.path.join(config.HISTORY_DIR, target_date)
    os.makedirs(date_dir, exist_ok=True)

    geotiff_path = export_geotiff(bite_score, output_path=os.path.join(date_dir, "bite_score.tif"))
    legacy_geotiff_path = export_geotiff(
        bite_score_legacy, output_path=os.path.join(date_dir, "bite_score_legacy.tif")
    )

    # The daily normalized contributing-factor layers that feed the WLC
    # overlay are also exported on their own, so the dashboard can offer
    # them as individually selectable "how it's calculated" map layers
    # rather than only showing the combined Bite Score. Depth-suitability
    # is skipped here -- it's bit-identical every run (depends only on the
    # static local bathymetry grid, not any daily data), so it's built
    # once and shared across all dates instead (see static_layers.py)
    # rather than being re-exported per date. The normalized MLD *score*
    # ("mld" key, 0-100 gradient/front strength) is also skipped here --
    # it would collide with the raw mlotst GeoTIFF (metres, not a 0-100
    # score) already exported below under the same "layer_mld.tif"
    # filename that Lambert's dashboard/date_layers.py expects.
    layer_geotiff_paths = {
        key: export_geotiff(layer, output_path=os.path.join(date_dir, f"layer_{key}.tif"))
        for key, layer in layer_scores.items()
        if key not in ("bathymetry", "mld")
    }

    # Finite-Size Lyapunov Exponent (FSLE): an independent diagnostic layer
    # (not one of the five weighted Bite Score factors) that reveals ocean
    # fronts / Lagrangian Coherent Structures by advecting virtual
    # particles through several days of forecast current data (see
    # fsle.py). Requires forward-looking forecast days beyond target_date,
    # which aren't always available (e.g. for far-past historical dates),
    # so this degrades gracefully rather than failing the whole pipeline.
    fsle_geotiff_path = None
    try:
        fsle_field = fetch_and_compute_fsle(target_date)
        fsle_geotiff_path = export_geotiff(fsle_field, output_path=os.path.join(date_dir, "layer_fsle.tif"))
    except Exception:
        logger.warning("FSLE computation unavailable for %s; skipping this layer", target_date, exc_info=True)

    # Satellite altimetry Sea Level Anomaly (SLA): an independent visual
    # reference layer (not a WLC factor) that reveals warm-core / cold-core
    # eddies and EAC meander structure. Sourced from NOAA CoastWatch ERDDAP
    # (nesdisSSH1day, multi-satellite RADS merged product, 0.25deg daily,
    # 2017-present). Degrades gracefully -- if the dataset is unavailable or
    # has no coverage for this date, the layer is simply absent on the map.
    sla_geotiff_path = None
    try:
        sla_obs = load_erddap_layer("sla", target_date)
        sla_geotiff_path = export_geotiff(sla_obs, output_path=os.path.join(date_dir, "layer_sla.tif"))
        logger.info("Satellite altimetry SLA exported for %s", target_date)
    except Exception:
        logger.warning(
            "Satellite altimetry SLA (nesdisSSH1day) unavailable for %s; skipping this layer",
            target_date, exc_info=True,
        )

    # Mixed layer depth (mlotst) raw raster: also exported on its own scale
    # (metres, not the 0-100 gradient/front score used internally by
    # weighted_overlay() above) for the dashboard's raw "MLD front" map
    # layer (see raster_utils.py::mld_to_rgba / date_layers.py). Reuses
    # the `mld` DataArray already fetched above (no re-fetch) -- `None`
    # here means the fetch already failed and was logged above, so this
    # layer is simply unavailable for this date, same as FSLE below.
    mld_geotiff_path = None
    if mld is not None:
        mld_geotiff_path = export_geotiff(mld, output_path=os.path.join(date_dir, "layer_mld.tif"))

    # Moon phase / lunar data: written as a small JSON side-file (like the
    # other *_meta.json assets in this project) rather than a GeoTIFF,
    # since it's day-level (0.0 = new moon/dark, 1.0 = full moon/bright,
    # plus phase name/age and real moonrise/moonset -- see
    # moon_phase.py::moon_phase_details() for exactly what's real vs
    # unavailable, e.g. tide is never included), not a spatial raster.
    # Reuses the dict already computed above (illumination_fraction was
    # also applied to `bite_score` as a uniform multiplier -- see
    # overlay.py::apply_moon_phase_multiplier) rather than recomputing.
    with open(os.path.join(date_dir, "moon_phase.json"), "w", encoding="utf-8") as f:
        json.dump({"date": target_date, **moon_details}, f)

    # High-resolution Sunshine Coast LiDAR bathymetry, and the two further
    # AusSeabed multibeam survey layers (Moreton Bay Approaches, Mudjimba
    # Island), are static/not tied to target_date at all -- they're now
    # built once and shared across every date's map (see static_layers.py,
    # served on demand by webapp.py) rather than being built here per run.

    # A single shared bite_score_map.html template now serves every date
    # (root "/" and every "/history/<date>") -- per-date layers are
    # fetched lazily client-side from /api/date-layer/<date>/<key>/*
    # (see date_layers.py / webapp.py), so nothing date-specific needs to
    # be baked into the HTML any more. Regenerating it here is cheap (it
    # only reads the static bathymetry domain bounds) and keeps it in sync
    # with any code changes to visualize.py.
    build_folium_map(output_html="bite_score_map.html")

    # Record which date "/" (and the "Latest" history entry) should show,
    # preserving the old "last run wins" behaviour -- e.g. backfilling an
    # older date via "Update Data" makes that the shown date, even if
    # chronologically-newer dates already exist under output/history/.
    with open(config.LATEST_DATE_PATH, "w", encoding="utf-8") as f:
        f.write(target_date)

    build_plotly_map(geotiff_path)  # returns a Plotly Figure; call .show() interactively if desired

    logger.info("Pipeline complete. GeoTIFF: %s", geotiff_path)
    return geotiff_path


def run_pipeline_v2(target_date: str = config.DEFAULT_TARGET_DATE) -> str:
    """
    Run the end-to-end v2 pipeline (structure/shelf-break scoring, real
    canyon proximity, bell-curve SST, optimal-band chlorophyll, vorticity-
    based eddy detection, seasonal multiplier) for a single date and
    return the v2 GeoTIFF path.

    This is a NEW, SEPARATE entry point (see
    .squad/decisions/inbox/ripley-seq-v2-scoring-model.md) -- it fetches
    its own AOI_V2-clipped data (via the `_v2`-suffixed ingestion
    functions below) and writes to a SEPARATE output location
    (output/history/<date>/v2/), so v1's `run_pipeline()` above and its
    existing per-date outputs are never touched or overwritten by a v2
    run for the same date.
    """
    if not _DATE_RE.match(target_date or ""):
        raise ValueError(f"target_date must be in YYYY-MM-DD format, got: {target_date!r}")

    logger.info("=== Yellowfin Tuna Bite Score v2 pipeline: %s ===", target_date)

    # 1. Data ingestion (v2: wider AOI_V2 extent, separate raw-data cache) -
    depth = load_bathymetry_v2()

    ocean = fetch_daily_ocean_data_v2(target_date)
    physics = ocean["physics"]

    copernicus_sst = physics["thetao"].isel(time=0)
    if "depth" in copernicus_sst.dims:
        copernicus_sst = copernicus_sst.isel(depth=0)

    copernicus_chl = ocean["biogeochemistry"]["chl"].isel(time=0)
    if "depth" in copernicus_chl.dims:
        copernicus_chl = copernicus_chl.isel(depth=0)

    try:
        sst = load_erddap_layer_v2("sst", target_date)
    except Exception:
        logger.warning(
            "NOAA MUR SST unavailable for %s (v2), falling back to Copernicus SST", target_date, exc_info=True
        )
        sst = copernicus_sst

    try:
        chl = fetch_chl_composite(target_date, aoi=config.AOI_V2, cache_suffix="_v2")
        logger.info("Using IMOS SRS OC NOAA-20 chlorophyll (833m) for %s (v2)", target_date)
    except Exception:
        logger.warning(
            "IMOS OC chlorophyll unavailable for %s (v2), trying VIIRS NRT...",
            target_date, exc_info=True,
        )
        try:
            chl = load_erddap_layer_v2("chl", target_date)
        except Exception:
            logger.warning(
                "VIIRS NRT chlorophyll unavailable for %s (v2), trying VIIRS Science Quality...",
                target_date, exc_info=True,
            )
            try:
                chl = load_erddap_layer_v2("chl_sq", target_date)
                logger.info("Using VIIRS Science Quality chlorophyll for %s (v2)", target_date)
            except Exception:
                logger.warning(
                    "VIIRS SQ chlorophyll unavailable for %s (v2), trying MODIS Aqua R2022SQ...",
                    target_date, exc_info=True,
                )
                try:
                    chl = load_erddap_layer_v2("chl_modis", target_date)
                    logger.info("Using MODIS Aqua R2022SQ chlorophyll for %s (v2)", target_date)
                except Exception:
                    logger.warning(
                        "All satellite chlorophyll sources unavailable for %s (v2), "
                        "falling back to Copernicus BGC model (27km)",
                        target_date, exc_info=True,
                    )
                    chl = copernicus_chl

    uo = physics["uo"].isel(time=0)
    vo = physics["vo"].isel(time=0)
    if "depth" in uo.dims:
        uo, vo = uo.isel(depth=0), vo.isel(depth=0)

    ssha = physics["zos"].isel(time=0)
    if "depth" in ssha.dims:
        ssha = ssha.isel(depth=0)

    # Mixed layer depth: reused as one of v2's 7 WLC factors, same
    # graceful-degradation contract as v1 (fetch failure -> score without it).
    mld = None
    try:
        mld = fetch_mld_v2(target_date)
    except Exception:
        logger.warning(
            "Mixed layer depth (mlotst) unavailable for %s (v2); scoring without the MLD factor",
            target_date, exc_info=True,
        )

    # 2-4. Gradients, v2 normalization, v2 WLC overlay + seasonal multiplier
    bite_score_v2, layer_scores_v2 = compute_bite_score_v2(
        sst, uo, vo, chl, ssha, depth, target_date, mld=mld
    )

    # 5. Export -----------------------------------------------------------
    # Written to a SEPARATE v2/ subdirectory under the same per-date
    # archive folder v1 uses, so v1's bite_score.tif / layer_*.tif files
    # for that date are never overwritten by a v2 run.
    date_dir = os.path.join(config.HISTORY_DIR, target_date, "v2")
    os.makedirs(date_dir, exist_ok=True)

    geotiff_path = export_geotiff(bite_score_v2, output_path=os.path.join(date_dir, "bite_score_v2.tif"))

    layer_geotiff_paths = {
        key: export_geotiff(layer, output_path=os.path.join(date_dir, f"layer_{key}.tif"))
        for key, layer in layer_scores_v2.items()
    }

    logger.info("v2 pipeline complete. GeoTIFF: %s", geotiff_path)
    return geotiff_path


def run_pipeline_lenigas(target_date: str = config.DEFAULT_TARGET_DATE) -> str:
    """
    Run the end-to-end "Lenigas" pipeline (fisherman-notes-derived scoring:
    SST bell curve, ramp-plateau-decline depth suitability, distance-
    offshore-from-coast, continuous vorticity-sign upwelling/downwelling,
    EAC-axis-position + EAC-convergence, asymmetric moon-phase multiplier)
    for a single date and return the Lenigas GeoTIFF path.

    This is a NEW, SEPARATE entry point (see
    .squad/decisions/inbox/ripley-lenigas-pipeline.md) -- NEVER "v3". It
    reuses the same AOI_V2-clipped ingestion functions v2 already uses
    (`load_bathymetry_v2`, `fetch_daily_ocean_data_v2`, `load_erddap_layer_v2`)
    since AOI_LENIGAS deliberately aliases AOI_V2 (verified sufficient
    coverage, see config.py), and writes to a SEPARATE
    output/history/<date>/lenigas/ subfolder, so neither v1's nor v2's
    existing per-date outputs are ever touched or overwritten by a
    Lenigas run for the same date.
    """
    if not _DATE_RE.match(target_date or ""):
        raise ValueError(f"target_date must be in YYYY-MM-DD format, got: {target_date!r}")

    logger.info("=== Yellowfin Tuna Bite Score Lenigas pipeline: %s ===", target_date)

    # 1. Data ingestion (reuses v2's AOI_V2-clipped sources, since
    #    AOI_LENIGAS aliases AOI_V2) -----------------------------------
    depth = load_bathymetry_v2()

    ocean = fetch_daily_ocean_data_v2(target_date)
    physics = ocean["physics"]

    copernicus_sst = physics["thetao"].isel(time=0)
    if "depth" in copernicus_sst.dims:
        copernicus_sst = copernicus_sst.isel(depth=0)

    try:
        sst = load_erddap_layer_v2("sst", target_date)
    except Exception:
        logger.warning(
            "NOAA MUR SST unavailable for %s (lenigas), falling back to Copernicus SST",
            target_date, exc_info=True,
        )
        sst = copernicus_sst

    uo = physics["uo"].isel(time=0)
    vo = physics["vo"].isel(time=0)
    if "depth" in uo.dims:
        uo, vo = uo.isel(depth=0), vo.isel(depth=0)

    # SSHA (zos): same raw field v1's ssha_gradient/v2's eddy score
    # already consume from this same fetch, reused here for the NEW
    # ssha_hotspot_lenigas factor (Kane's FINAL decision -- see
    # .squad/decisions/inbox/kane-lenigas-ssha-final-decision.md).
    zos = physics["zos"].isel(time=0)

    # Moon phase: same astronomical calculation v1 already uses, reused
    # here for its `phase_age_days` (needed by the NEW asymmetric Lenigas
    # moon-phase multiplier -- see overlay_lenigas.py::apply_moon_phase_multiplier_lenigas,
    # a genuinely different model from v1's illumination-fraction-based
    # `overlay.py::apply_moon_phase_multiplier`).
    moon_details = moon_phase_details(target_date)

    # Wind (Ash's data_ingestion_lenigas.py::fetch_wind_data_lenigas):
    # fetched here for validation/diagnostic purposes ONLY -- per Kane's
    # explicit scope note, wind is NOT yet one of the Lenigas WLC weights
    # (config.LAYER_WEIGHTS_LENIGAS) for this first build. Degrades
    # gracefully (wind=None) rather than failing the whole pipeline,
    # same contract as v1/v2's MLD factor, and reports the real NaN
    # fraction honestly rather than silently ignoring coverage gaps.
    wind = None
    try:
        wind = fetch_wind_data_lenigas(target_date)
        wind_speed_nan_fraction = float(
            wind["wind_speed"].isnull().sum() / wind["wind_speed"].size
        )
        logger.info(
            "Wind data fetched for %s (lenigas, informational only, not in WLC weights): "
            "%.1f%% NaN coverage",
            target_date, wind_speed_nan_fraction * 100.0,
        )
    except Exception:
        logger.warning(
            "Wind data (data_ingestion_lenigas.fetch_wind_data_lenigas) unavailable for %s; "
            "continuing without it (it is informational only, not a WLC factor)",
            target_date, exc_info=True,
        )

    # 2-4. Gradients, Lenigas normalization, Lenigas WLC overlay + seasonal
    #      + moon-phase multipliers ------------------------------------
    bite_score_lenigas, layer_scores_lenigas = compute_bite_score_lenigas(
        sst, uo, vo, depth, zos, target_date, phase_age_days=moon_details["phase_age_days"]
    )

    # 5. Export -------------------------------------------------------------
    # Written to a SEPARATE lenigas/ subdirectory under the same per-date
    # archive folder v1/v2 use, so their existing outputs for that date
    # are never overwritten by a Lenigas run.
    date_dir = os.path.join(config.HISTORY_DIR, target_date, config.LENIGAS_OUTPUT_SUBDIR)
    os.makedirs(date_dir, exist_ok=True)

    geotiff_path = export_geotiff(
        bite_score_lenigas, output_path=os.path.join(date_dir, "bite_score_lenigas.tif")
    )

    layer_geotiff_paths = {
        key: export_geotiff(layer, output_path=os.path.join(date_dir, f"layer_{key}.tif"))
        for key, layer in layer_scores_lenigas.items()
    }

    # Wind: exported as its own informational raster (NOT part of the WLC
    # layer_scores above) so its real coverage for this date is visible
    # on disk even though it isn't yet scored.
    if wind is not None:
        export_geotiff(wind["wind_speed"], output_path=os.path.join(date_dir, "layer_wind_speed.tif"))

    with open(os.path.join(date_dir, "moon_phase.json"), "w", encoding="utf-8") as f:
        json.dump({"date": target_date, **moon_details}, f)

    logger.info("Lenigas pipeline complete. GeoTIFF: %s", geotiff_path)
    return geotiff_path


def main():
    parser = argparse.ArgumentParser(
        description="Compute the daily Yellowfin Tuna Bite Probability Score for SE Queensland"
    )
    parser.add_argument("--date", default=config.DEFAULT_TARGET_DATE, help="Target date, YYYY-MM-DD")
    parser.add_argument(
        "--version",
        choices=["v1", "v2", "lenigas"],
        default="v1",
        help="Scoring model version to run: 'v1' (default, existing production pipeline), "
        "'v2' (separate structure/eddy/bell-curve model, writes to output/history/<date>/v2/), or "
        "'lenigas' (separate fisherman-notes-derived model, writes to "
        "output/history/<date>/lenigas/)",
    )
    args = parser.parse_args()
    if args.version == "v2":
        run_pipeline_v2(args.date)
    elif args.version == "lenigas":
        run_pipeline_lenigas(args.date)
    else:
        run_pipeline(args.date)


if __name__ == "__main__":
    main()
