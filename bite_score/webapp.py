"""
Minimal local dashboard server for the Yellowfin Tuna Bite Score map.

Serves the generated `bite_score_map.html` and exposes a small JSON API so
the page's "Update Data" button can trigger a fresh pipeline run (fetching
new satellite/ocean data for a chosen date) and then reload the map, without
needing any extra frontend framework or dependencies - built entirely on the
Python standard library `http.server`.

Usage:
    python -m bite_score.webapp
    python -m bite_score.webapp --port 8765 --no-browser
"""
import argparse
import json
import logging
import os
import re
import threading
import time
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from . import config
from .data_ingestion import fetch_tide_data
from .main import run_pipeline, run_pipeline_v2, run_pipeline_lenigas, run_pipeline_gt, run_pipeline_outerline
from .mbgfc_chart import build_mbgfc_chart_png, load_mbgfc_locations
from .date_layers import (
    DATE_LAYER_SPECS,
    DATE_LAYER_SPECS_V2,
    DATE_LAYER_SPECS_LENIGAS,
    DATE_LAYER_SPECS_GT,
    DATE_LAYER_SPECS_OUTERLINE,
    build_date_layer_assets,
    build_date_layer_assets_v2,
    build_date_layer_assets_lenigas,
    build_date_layer_assets_gt,
    build_date_layer_assets_outerline,
    build_sla_contours_json,
    validate_date_key,
)
from .pipeline_outerline import sample_point_outerline_from_date
from .catching_tactics_page import build_catching_tactics_html
from .yellowfin_tips_page import build_yellowfin_tips_html
from .conditions_page import build_conditions_html
from .windy_api import fetch_all as windy_fetch_all
from .moon_tide_page import build_moon_tide_page_html
from .tide import classify_tide_state, next_tide_events
from .static_layers import (
    RASTER_LAYERS,
    build_bathymetry_contours_json,
    build_land_outline_geojson,
    build_raster_layer_assets,
)

logger = logging.getLogger(__name__)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAP_HTML_PATH = os.path.join(REPO_ROOT, "bite_score_map.html")
STATIC_DIR = os.path.join(REPO_ROOT, "static")

# Only matches real YYYY-MM-DD dates -- used for the Historical Data list
# and the "/" root route's fallback "latest date", so `run_demo.py`'s
# synthetic "demo" output (see date_layers._DATE_KEY_RE) never shows up
# there or gets picked as "latest".
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

_state_lock = threading.Lock()
_state = {"state": "idle", "message": "", "date": None}

# In-memory cache for the live QLD DES tide feed (see fetch_tide_data()) --
# backs GET /api/tide-state/<date>. The feed is a 7-day rolling window
# sampled every 10 minutes; without this cache every single page view of
# /moon/<date> would trigger a fresh live GET to the external DES server,
# which is unnecessary load for data that barely changes minute-to-minute.
_tide_cache_lock = threading.Lock()
_tide_cache = {"df": None, "fetched_at": None}


def _get_tide_dataframe():
    """
    Return the cached tide DataFrame, re-fetching from the live feed only
    if the cache is missing or older than config.TIDE_CACHE_TTL_MINUTES.
    Propagates RuntimeError (from fetch_tide_data()) if a fresh fetch is
    needed and both the live request and its on-disk fallback cache fail.
    """
    now = time.monotonic()
    with _tide_cache_lock:
        cached_df = _tide_cache["df"]
        fetched_at = _tide_cache["fetched_at"]
        if (
            cached_df is not None
            and fetched_at is not None
            and (now - fetched_at) < config.TIDE_CACHE_TTL_MINUTES * 60
        ):
            return cached_df

    df = fetch_tide_data()
    with _tide_cache_lock:
        _tide_cache["df"] = df
        _tide_cache["fetched_at"] = time.monotonic()
    return df


def _list_history_dates() -> list:
    """Dates (YYYY-MM-DD) with an archived Bite Score GeoTIFF under output/history/, newest first."""
    if not os.path.isdir(config.HISTORY_DIR):
        return []
    dates = []
    for name in os.listdir(config.HISTORY_DIR):
        if _DATE_RE.match(name) and os.path.isfile(
            os.path.join(config.HISTORY_DIR, name, "bite_score.tif")
        ):
            dates.append(name)
    return sorted(dates, reverse=True)


def _latest_date() -> str:
    """
    The date the "/" root route should show -- whichever date's
    `run_pipeline()` call completed most recently (see config.LATEST_DATE_PATH),
    falling back to the chronologically-latest archived date if that
    marker file doesn't exist yet (e.g. a fresh checkout with pre-existing
    history but no run since this feature was added).
    """
    if os.path.isfile(config.LATEST_DATE_PATH):
        with open(config.LATEST_DATE_PATH, "r", encoding="utf-8") as f:
            date = f.read().strip()
        if _DATE_RE.match(date):
            return date
    dates = _list_history_dates()
    return dates[0] if dates else None


def _clear_date_layer_cache(target_date: str) -> None:
    """
    Delete all cached layer render files for `target_date` so they are
    regenerated from the freshly-written TIFs on the next browser request.

    Removes ``chart_*.png``, ``meta_*.json``, and ``sla_contours.json``
    from the date directory root and from every recognised sub-pipeline
    subfolder (``v2/``, ``lenigas/``).  Only the render cache is cleared;
    the TIFs themselves (which the pipelines just wrote) are preserved.
    """
    date_dir = os.path.join(config.HISTORY_DIR, target_date)
    subdirs = [date_dir]
    for sub in ("v2", config.LENIGAS_OUTPUT_SUBDIR, config.GT_OUTPUT_SUBDIR, config.OUTERLINE_OUTPUT_SUBDIR):
        p = os.path.join(date_dir, sub)
        if os.path.isdir(p):
            subdirs.append(p)

    removed = 0
    for d in subdirs:
        for fname in os.listdir(d):
            if fname.startswith("chart_") or fname.startswith("meta_") or fname == "sla_contours.json":
                try:
                    os.remove(os.path.join(d, fname))
                    removed += 1
                except OSError:
                    pass
    logger.info("Cleared %d cached layer file(s) for %s", removed, target_date)


def _run_update_job(target_date: str) -> None:
    with _state_lock:
        _state.update(state="running", message=f"Fetching ocean data for {target_date}...", date=target_date)
    try:
        run_pipeline(target_date)
        with _state_lock:
            _state.update(state="running", message=f"Running v2 (Beta) pipeline for {target_date}...", date=target_date)
        run_pipeline_v2(target_date)
        with _state_lock:
            _state.update(state="running", message=f"Running Lenigas pipeline for {target_date}...", date=target_date)
        run_pipeline_lenigas(target_date)
        with _state_lock:
            _state.update(state="running", message=f"Running GT pipeline for {target_date}...", date=target_date)
        run_pipeline_gt(target_date)
        with _state_lock:
            _state.update(state="running", message=f"Running Outerline pipeline for {target_date}...", date=target_date)
        run_pipeline_outerline(target_date)
        with _state_lock:
            _state.update(state="running", message=f"Refreshing layer cache for {target_date}...", date=target_date)
        _clear_date_layer_cache(target_date)
        with _state_lock:
            _state.update(state="done", message=f"Updated for {target_date}", date=target_date)
    except Exception as exc:
        logger.exception("Pipeline update failed")
        with _state_lock:
            _state.update(state="error", message=str(exc), date=target_date)


class BiteScoreRequestHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        logger.info("%s - %s", self.address_string(), fmt % args)

    def _send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        # Strip any query string (e.g. "?layers=..." from a shareable direct
        # link -- see visualize.py::bsqBuildShareUrl()/bsqGetLayersFromUrl())
        # before routing below. Every route here matches on exact/prefix/
        # suffix checks against `self.path` with no query-string handling of
        # its own, so a link like "/history/2026-07-22?layers=sst,mld" would
        # otherwise fail `/history/<date>`'s date-format validation (the
        # query string would be treated as part of the date). The `layers`
        # param is only ever read client-side (location.search), the server
        # never needs to see it.
        self.path = urlsplit(self.path).path
        if self.path in ("/", "/index.html", "/bite_score_map.html"):
            if not os.path.exists(MAP_HTML_PATH):
                self._send_json(
                    {"message": "No map generated yet. POST /api/update first, or run the pipeline once."},
                    status=404,
                )
                return
            with open(MAP_HTML_PATH, "rb") as f:
                body = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/api/status":
            with _state_lock:
                self._send_json(dict(_state))
        elif self.path == "/api/history":
            self._send_json({"dates": _list_history_dates()})
        elif self.path == "/api/latest-date":
            self._send_json({"date": _latest_date()})
        elif self.path == "/api/mbgfc/chart.png":
            # Built lazily, once, on first request -- a single shared
            # static asset independent of any pipeline run/date, so it
            # never needs rebuilding when a new date is processed.
            try:
                png_path, _meta_path = build_mbgfc_chart_png()
            except Exception as exc:
                logger.warning("MBGFC chart PNG unavailable", exc_info=True)
                self._send_json({"message": str(exc)}, status=404)
                return
            with open(png_path, "rb") as f:
                body = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "public, max-age=3600")
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/api/mbgfc/meta":
            try:
                _png_path, meta_path = build_mbgfc_chart_png()
            except Exception as exc:
                logger.warning("MBGFC chart metadata unavailable", exc_info=True)
                self._send_json({"message": str(exc)}, status=404)
                return
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
            self._send_json(meta)
        elif self.path == "/api/mbgfc/locations":
            try:
                locations = load_mbgfc_locations()
            except Exception as exc:
                logger.warning("MBGFC locations unavailable", exc_info=True)
                self._send_json({"message": str(exc)}, status=404)
                return
            self._send_json({"locations": locations})
        elif self.path == "/api/waypoints":
            waypoints_path = os.path.join(
                os.path.dirname(__file__), "..", "data", "processed", "fishing_waypoints.json"
            )
            waypoints_path = os.path.normpath(waypoints_path)
            try:
                with open(waypoints_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception as exc:
                logger.warning("Fishing waypoints unavailable", exc_info=True)
                self._send_json({"message": str(exc)}, status=404)
                return
            self._send_json(data)
        elif self.path.startswith("/api/static-layer/") and self.path.endswith("/chart.png"):
            # Shared bathymetry/relief-shading raster layers (depth-
            # suitability, and the 4 stacked images -- base plus 3 native-
            # resolution local survey insets -- behind the single unified
            # "Bathymetry relief map" toggle): identical on every date, so
            # built lazily once on first request and cached -- see
            # static_layers.py.
            key = self.path[len("/api/static-layer/"):-len("/chart.png")]
            if key not in RASTER_LAYERS:
                self._send_json({"message": f"Unknown layer: {key}"}, status=404)
                return
            try:
                png_path, _meta_path = build_raster_layer_assets(key)
            except Exception as exc:
                logger.warning("Static raster layer %s unavailable", key, exc_info=True)
                self._send_json({"message": str(exc)}, status=404)
                return
            with open(png_path, "rb") as f:
                body = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "public, max-age=3600")
            self.end_headers()
            self.wfile.write(body)
        elif self.path.startswith("/api/static-layer/") and self.path.endswith("/meta"):
            key = self.path[len("/api/static-layer/"):-len("/meta")]
            if key not in RASTER_LAYERS:
                self._send_json({"message": f"Unknown layer: {key}"}, status=404)
                return
            try:
                _png_path, meta_path = build_raster_layer_assets(key)
            except Exception as exc:
                logger.warning("Static raster layer %s metadata unavailable", key, exc_info=True)
                self._send_json({"message": str(exc)}, status=404)
                return
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
            self._send_json(meta)
        elif self.path == "/api/bathymetry/contours":
            # Depth-contour (isobath) lines + labels -- also identical every
            # date (derived from the static GEBCO grid), so built lazily
            # once and cached, same treatment as the raster layers above.
            try:
                contours_path = build_bathymetry_contours_json()
            except Exception as exc:
                logger.warning("Bathymetry contours unavailable", exc_info=True)
                self._send_json({"message": str(exc)}, status=404)
                return
            with open(contours_path, "r", encoding="utf-8") as f:
                contours = json.load(f)
            self._send_json(contours)
        elif self.path.startswith("/api/date-layer/") and self.path.endswith("/sla_contours/contours.json"):
            # Per-date SLA contour lines (GeoJSON) -- derived from each
            # date's layer_sla.tif by sla_contour_geojson() in raster_utils.py,
            # cached as sla_contours.json under output/history/<date>/.
            date_str = self.path[len("/api/date-layer/"):-len("/sla_contours/contours.json")]
            try:
                validate_date_key(date_str)
            except ValueError as exc:
                self._send_json({"message": str(exc)}, status=400)
                return
            try:
                sla_contours_path = build_sla_contours_json(date_str)
            except FileNotFoundError as exc:
                self._send_json({"message": str(exc)}, status=404)
                return
            except Exception as exc:
                logger.warning("SLA contours unavailable for %s", date_str, exc_info=True)
                self._send_json({"message": str(exc)}, status=404)
                return
            with open(sla_contours_path, "r", encoding="utf-8") as f:
                sla_contours_data = json.load(f)
            self._send_json(sla_contours_data)
        elif self.path == "/api/bathymetry/land-outline":
            # Coastline outline traced from the static bathymetry grid's
            # own nodata mask -- also identical every date, cached the
            # same way as the contours above.
            try:
                outline_path = build_land_outline_geojson()
            except Exception as exc:
                logger.warning("Land outline unavailable", exc_info=True)
                self._send_json({"message": str(exc)}, status=404)
                return
            with open(outline_path, "r", encoding="utf-8") as f:
                outline = json.load(f)
            self._send_json(outline)
        elif self.path.startswith("/api/moon-phase/"):
            # Day-level (non-spatial) moon illumination scalar, written by
            # main.py::run_pipeline() as a small JSON side-file per date
            # (same "*_meta.json" convention as the other per-date assets)
            # rather than a GeoTIFF/PNG -- there's nothing to rasterize.
            # 404 for historical dates archived before this feature
            # existed, or any date never processed at all -- the sidebar
            # handles that by simply omitting the readout (see
            # bsqLoadMoonPhase() in visualize.py's injected JS).
            date_str = self.path[len("/api/moon-phase/"):].strip("/")
            try:
                validate_date_key(date_str)
            except ValueError as exc:
                self._send_json({"message": str(exc)}, status=400)
                return
            moon_phase_path = os.path.join(config.HISTORY_DIR, date_str, "moon_phase.json")
            if not os.path.isfile(moon_phase_path):
                self._send_json({"message": f"No moon phase data for {date_str}"}, status=404)
                return
            with open(moon_phase_path, "r", encoding="utf-8") as f:
                moon_phase = json.load(f)
            self._send_json(moon_phase)
        elif self.path.startswith("/api/tide-state/"):
            # Real tide height/state for both configured QLD DES sites
            # (Tangalooma/Moreton Island, Maroochydore/Mooloolaba) -- see
            # tide.py + data_ingestion.py::fetch_tide_data(). The DES feed
            # is a live ~7-day ROLLING window, not tied to any archived
            # pipeline date -- "date" in the URL is kept only for
            # consistency with the other per-date routes; the actual tide
            # state/next-events are always evaluated at each site's own
            # latest fetched sample (not the local system clock -- a
            # sandboxed/demo clock can genuinely drift out of sync with
            # the live feed's real-world anchor time, which would
            # otherwise make every request look "outside the fetched
            # range" even though the data itself is current). Viewing a
            # historical date outside the live window simply gets each
            # site back as "available": false (a real, honest "no data
            # for that date" outcome, not a bug).
            date_str = self.path[len("/api/tide-state/"):].strip("/")
            try:
                validate_date_key(date_str)
            except ValueError as exc:
                self._send_json({"message": str(exc)}, status=400)
                return

            try:
                tide_df = _get_tide_dataframe()
            except RuntimeError as exc:
                logger.warning("Tide data temporarily unavailable", exc_info=True)
                self._send_json(
                    {"message": "Tide data temporarily unavailable", "detail": str(exc)},
                    status=503,
                )
                return

            def _format_event(event):
                if not event:
                    return None
                return {"time": event["time"].isoformat(), "height_m": event["height_m"]}

            sites_payload = {}
            reference_times = {}
            for site_code, location_name in config.TIDE_SITES.items():
                site_payload = {
                    "site_code": site_code,
                    "location_name": location_name,
                    "available": False,
                }
                try:
                    site_rows = tide_df[tide_df["Site"].str.lower() == site_code.lower()]
                    if site_rows.empty:
                        raise ValueError(f"No tide data returned for site '{site_code}'.")
                    # Use the feed's own latest sample as the reference
                    # "now" for this site, rather than the local system
                    # clock -- the feed is a rolling live window anchored
                    # to the real world, and the wall clock in this
                    # environment can genuinely drift out of sync with it
                    # (e.g. a demo/sandbox clock set ahead of real time),
                    # which would otherwise make every request look like
                    # it's "outside the fetched range" even though the
                    # data itself is perfectly real and current.
                    reference_time = site_rows["DateTime"].max()
                    reference_times[site_code] = reference_time
                    state = classify_tide_state(tide_df, reference_time, site_code)
                    events = next_tide_events(tide_df, site_code, reference_time)
                except (ValueError, KeyError) as exc:
                    site_payload["message"] = str(exc)
                else:
                    site_payload.update(
                        {
                            "available": True,
                            "state": state["state"],
                            "as_of": state["at_time"].isoformat(),
                            "next_high": _format_event(events["next_high"]),
                            "next_low": _format_event(events["next_low"]),
                        }
                    )
                sites_payload[site_code] = site_payload

            as_of = max(reference_times.values()).isoformat() if reference_times else datetime.now(config.TIDE_TIMEZONE).isoformat()
            self._send_json({"date": date_str, "as_of": as_of, "sites": sites_payload})
        elif self.path.startswith("/api/tide-series/"):
            # Full tide Prediction time series for the given date, for both
            # configured QLD DES sites -- backs the tide graph on /moon/<date>.
            # Returns 10-minute-interval Prediction values filtered to the
            # 24-hour window of `date_str` in Brisbane time. Gracefully
            # returns available:false for dates outside the rolling live window.
            date_str = self.path[len("/api/tide-series/"):].strip("/")
            try:
                validate_date_key(date_str)
            except ValueError as exc:
                self._send_json({"message": str(exc)}, status=400)
                return
            try:
                tide_df = _get_tide_dataframe()
            except RuntimeError as exc:
                self._send_json({"message": str(exc)}, status=503)
                return
            try:
                from datetime import date as _date_cls
                day_start = datetime.strptime(date_str, "%Y-%m-%d").replace(
                    hour=0, minute=0, second=0, microsecond=0,
                    tzinfo=config.TIDE_TIMEZONE,
                )
                day_end = day_start.replace(hour=23, minute=59, second=59)
            except ValueError:
                self._send_json({"message": "Invalid date format"}, status=400)
                return
            sites_series = {}
            for site_code, location_name in config.TIDE_SITES.items():
                site_rows = tide_df[
                    (tide_df["Site"].str.lower() == site_code.lower())
                    & (tide_df["DateTime"] >= day_start)
                    & (tide_df["DateTime"] <= day_end)
                ].sort_values("DateTime").reset_index(drop=True)
                if site_rows.empty:
                    sites_series[site_code] = {"location_name": location_name, "available": False}
                    continue
                series = [
                    {
                        "time": row["DateTime"].isoformat(),
                        "prediction": round(float(row["Prediction"]), 3),
                    }
                    for _, row in site_rows.iterrows()
                ]
                # Simple local-extremum turning points (same logic as tide.py)
                import numpy as np
                from scipy.signal import argrelextrema
                vals = site_rows["Prediction"].to_numpy()
                high_idx = argrelextrema(vals, np.greater, order=2)[0]
                low_idx = argrelextrema(vals, np.less, order=2)[0]
                turning = []
                for idx in sorted(list(high_idx) + list(low_idx)):
                    turning.append({
                        "time": site_rows["DateTime"].iloc[idx].isoformat(),
                        "type": "High" if idx in high_idx else "Low",
                        "height_m": round(float(vals[idx]), 2),
                    })
                sites_series[site_code] = {
                    "location_name": location_name,
                    "available": True,
                    "series": series,
                    "turning_points": turning,
                }
            self._send_json({"date": date_str, "sites": sites_series})
        elif self.path in ("/api/sst-raw/png", "/api/sst-raw/meta"):
            # Custom SST rendering with a fixed 17-29 °C colour scale.
            # Reads the latest NOAA MUR SST NetCDF from the raw-data cache
            # and renders it using sst_celsius_to_rgba(), returning either a
            # PNG image (for Leaflet ImageOverlay) or bounds/range metadata.
            import io as _io
            import numpy as _np
            import xarray as _xr
            from PIL import Image as _PilImage
            from .raster_utils import sst_celsius_to_rgba as _sst_rgba
            sst_path = os.path.join(config.RAW_DATA_DIR, "sst_erddap_latest.nc")
            if not os.path.isfile(sst_path):
                self._send_json({"message": "SST data not available — run the pipeline first."}, status=404)
                return
            try:
                ds = _xr.open_dataset(sst_path)
                v = ds["analysed_sst"].squeeze()
                values = v.values.astype(float)
                # NOAA MUR SST is delivered in Kelvin for some date ranges;
                # detect and convert automatically.
                finite = values[_np.isfinite(values)]
                if finite.size > 0 and float(_np.nanmean(finite)) > 100:
                    values = values - 273.15
                # MUR lat/lon coordinates; north-up flip for display.
                lat_vals = v["latitude"].values
                if float(lat_vals[0]) < float(lat_vals[-1]):
                    values = values[::-1, :]
                lat_min = float(lat_vals.min())
                lat_max = float(lat_vals.max())
                lon_vals = v["longitude"].values
                lon_min = float(lon_vals.min())
                lon_max = float(lon_vals.max())
                bounds = [[lat_min, lon_min], [lat_max, lon_max]]
                if self.path.endswith("/meta"):
                    finite_c = values[_np.isfinite(values)]
                    self._send_json({
                        "bounds": bounds,
                        "colorscale": {"min": 17.0, "max": 29.0, "unit": "°C"},
                        "data_min": round(float(_np.nanmin(finite_c)), 2) if finite_c.size else None,
                        "data_max": round(float(_np.nanmax(finite_c)), 2) if finite_c.size else None,
                        "source": "NOAA MUR SST (ERDDAP jplMURSST41)",
                    })
                    return
                rgba = _sst_rgba(values)
                rgba_uint8 = (_np.clip(rgba, 0.0, 1.0) * 255).astype("uint8")
                img = _PilImage.fromarray(rgba_uint8, mode="RGBA")
                buf = _io.BytesIO()
                img.save(buf, format="PNG")
                png_bytes = buf.getvalue()
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(png_bytes)))
                self.send_header("Cache-Control", "public, max-age=600")
                self.end_headers()
                self.wfile.write(png_bytes)
            except Exception as _exc:
                logger.warning("SST raw render failed: %s", _exc, exc_info=True)
                self._send_json({"message": str(_exc)}, status=500)
        elif self.path.startswith("/api/date-layer/") and (
            self.path.endswith("/chart.png") or self.path.endswith("/meta")
        ):
            # Per-date layers (the Bite Score heatmap itself, the legacy
            # comparison heatmap, the four daily contributing factors, and
            # FSLE) -- these DO vary per date, so unlike the shared static
            # layers above they're cached per-date rather than globally,
            # but are still built lazily on first request rather than
            # embedded into a generated page -- see date_layers.py. This is
            # what lets a single bite_score_map.html template serve every
            # date without its own generated HTML file.
            suffix = "/chart.png" if self.path.endswith("/chart.png") else "/meta"
            rest = self.path[len("/api/date-layer/"):-len(suffix)]
            date_str, _, key = rest.partition("/")
            try:
                validate_date_key(date_str)
            except ValueError as exc:
                self._send_json({"message": str(exc)}, status=400)
                return
            if key not in DATE_LAYER_SPECS:
                self._send_json({"message": f"Unknown layer: {key}"}, status=404)
                return
            try:
                png_path, meta_path = build_date_layer_assets(date_str, key)
            except FileNotFoundError as exc:
                self._send_json({"message": str(exc)}, status=404)
                return
            except Exception as exc:
                logger.warning("Date layer %s/%s unavailable", date_str, key, exc_info=True)
                self._send_json({"message": str(exc)}, status=404)
                return
            if suffix == "/chart.png":
                with open(png_path, "rb") as f:
                    body = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(body)))
                # no-store (not the 1hr public caching used by the static
                # layers below): this PNG is regenerated whenever the
                # pipeline is re-run for this date, but the URL never
                # changes, so a long-lived Cache-Control let browsers keep
                # showing a stale heatmap after a fresh "Update Data" run
                # even though the meta endpoint (already fetched with
                # cache: "no-store" client-side) reported fresh min/max.
                # The file is already cheap to serve (cached on disk by
                # date_layers.py), so there's no real cost to always
                # revalidating.
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
            else:
                with open(meta_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                self._send_json(meta)
        elif self.path.startswith("/api/date-layer-lenigas/") and (
            self.path.endswith("/chart.png") or self.path.endswith("/meta")
        ):
            # Lenigas counterpart of /api/date-layer-v2/ below -- the
            # combined Lenigas Bite Score heatmap plus its 6 WLC factors
            # (sst_bell/depth_suitability/distance_offshore/
            # upwelling_downwelling/eac_axis_position/eac_convergence) plus
            # the informational-only wind_speed layer, read from that
            # date's SEPARATE output/history/<date>/lenigas/ subfolder (see
            # date_layers.py::DATE_LAYER_SPECS_LENIGAS/
            # build_date_layer_assets_lenigas() and
            # main.py::run_pipeline_lenigas()). Most dates simply don't
            # have a Lenigas run yet -- expected while this experimental
            # model is only available for a handful of test dates, and
            # surfaces here as an ordinary 404 (never a 500/crash). Never
            # referred to as "v3" anywhere.
            suffix = "/chart.png" if self.path.endswith("/chart.png") else "/meta"
            rest = self.path[len("/api/date-layer-lenigas/"):-len(suffix)]
            date_str, _, key = rest.partition("/")
            try:
                validate_date_key(date_str)
            except ValueError as exc:
                self._send_json({"message": str(exc)}, status=400)
                return
            if key not in DATE_LAYER_SPECS_LENIGAS:
                self._send_json({"message": f"Unknown Lenigas layer: {key}"}, status=404)
                return
            try:
                png_path, meta_path = build_date_layer_assets_lenigas(date_str, key)
            except FileNotFoundError as exc:
                self._send_json({"message": str(exc)}, status=404)
                return
            except Exception as exc:
                logger.warning("Lenigas date layer %s/%s unavailable", date_str, key, exc_info=True)
                self._send_json({"message": str(exc)}, status=404)
                return
            if suffix == "/chart.png":
                with open(png_path, "rb") as f:
                    body = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(body)))
                # no-store: see the identical comment on /api/date-layer/
                # above -- this URL doesn't change when the Lenigas
                # pipeline is re-run for the same date, so long-lived
                # caching here was the cause of the map "not updating"
                # after downloading fresh data for a date.
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
            else:
                with open(meta_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                self._send_json(meta)
        elif self.path.startswith("/api/date-layer-gt/") and (
            self.path.endswith("/chart.png") or self.path.endswith("/meta")
        ):
            # GT (Giant Trevally) counterpart of /api/date-layer-lenigas/
            # above -- the combined GT Bite Score heatmap plus its 6 WLC
            # factors (eac_edge_gt/upwelling_gt/depth_gt/sst_gt/
            # current_gradient_gt/north_wind_gt), read from that date's
            # SEPARATE output/history/<date>/gt/ subfolder (see
            # date_layers.py::DATE_LAYER_SPECS_GT/build_date_layer_assets_gt()
            # and main.py::run_pipeline_gt()). Most dates simply don't have
            # a GT run yet -- expected, surfaces here as an ordinary 404
            # (never a 500/crash). Never referred to as "v4" anywhere.
            suffix = "/chart.png" if self.path.endswith("/chart.png") else "/meta"
            rest = self.path[len("/api/date-layer-gt/"):-len(suffix)]
            date_str, _, key = rest.partition("/")
            try:
                validate_date_key(date_str)
            except ValueError as exc:
                self._send_json({"message": str(exc)}, status=400)
                return
            if key not in DATE_LAYER_SPECS_GT:
                self._send_json({"message": f"Unknown GT layer: {key}"}, status=404)
                return
            try:
                png_path, meta_path = build_date_layer_assets_gt(date_str, key)
            except FileNotFoundError as exc:
                self._send_json({"message": str(exc)}, status=404)
                return
            except Exception as exc:
                logger.warning("GT date layer %s/%s unavailable", date_str, key, exc_info=True)
                self._send_json({"message": str(exc)}, status=404)
                return
            if suffix == "/chart.png":
                with open(png_path, "rb") as f:
                    body = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(body)))
                # no-store: see the identical comment on /api/date-layer/
                # above.
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
            else:
                with open(meta_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                self._send_json(meta)
        elif self.path.startswith("/api/date-layer-outerline/") and self.path.endswith("/point"):
            # Outerline ("v3" / Yellowfin Environmental Hotspot Score)
            # "click for details" endpoint: samples the nearest grid cell
            # to ?lat=&lon= in that date's already-exported layer GeoTIFFs
            # and returns the hotspot score, every contributing component
            # (0-100), the feature-convergence count, and a plain-English
            # explanation string (see pipeline_outerline.py::sample_point_outerline_from_date()).
            # Unlike every other /api/date-layer*/ route, this has no
            # "chart.png"/"meta" suffix -- it answers a single point query,
            # not an image tile.
            date_str = self.path[len("/api/date-layer-outerline/"):-len("/point")]
            try:
                validate_date_key(date_str)
            except ValueError as exc:
                self._send_json({"message": str(exc)}, status=400)
                return
            query = dict(pair.split("=") for pair in urlsplit(self.path).query.split("&") if "=" in pair)
            try:
                lat = float(query["lat"])
                lon = float(query["lon"])
            except (KeyError, ValueError):
                self._send_json({"message": "lat and lon query parameters are required"}, status=400)
                return
            try:
                result = sample_point_outerline_from_date(date_str, lat, lon)
            except FileNotFoundError as exc:
                self._send_json({"message": str(exc)}, status=404)
                return
            except Exception as exc:
                logger.warning("Outerline point query %s (%s,%s) failed", date_str, lat, lon, exc_info=True)
                self._send_json({"message": str(exc)}, status=500)
                return
            self._send_json(result)
        elif self.path.startswith("/api/date-layer-outerline/") and (
            self.path.endswith("/chart.png") or self.path.endswith("/meta")
        ):
            # Outerline ("v3" / Yellowfin Environmental Hotspot Score)
            # counterpart of /api/date-layer-gt/ above -- the combined
            # hotspot score heatmap plus its WLC factor layers, read from
            # that date's SEPARATE output/history/<date>/outerline/
            # subfolder (see date_layers.py::DATE_LAYER_SPECS_OUTERLINE/
            # build_date_layer_assets_outerline() and
            # main.py::run_pipeline_outerline()). Most dates simply don't
            # have an Outerline run yet -- expected, surfaces here as an
            # ordinary 404 (never a 500/crash).
            suffix = "/chart.png" if self.path.endswith("/chart.png") else "/meta"
            rest = self.path[len("/api/date-layer-outerline/"):-len(suffix)]
            date_str, _, key = rest.partition("/")
            try:
                validate_date_key(date_str)
            except ValueError as exc:
                self._send_json({"message": str(exc)}, status=400)
                return
            if key not in DATE_LAYER_SPECS_OUTERLINE:
                self._send_json({"message": f"Unknown Outerline layer: {key}"}, status=404)
                return
            try:
                png_path, meta_path = build_date_layer_assets_outerline(date_str, key)
            except FileNotFoundError as exc:
                self._send_json({"message": str(exc)}, status=404)
                return
            except Exception as exc:
                logger.warning("Outerline date layer %s/%s unavailable", date_str, key, exc_info=True)
                self._send_json({"message": str(exc)}, status=404)
                return
            if suffix == "/chart.png":
                with open(png_path, "rb") as f:
                    body = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
            else:
                with open(meta_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                self._send_json(meta)
        elif self.path.startswith("/api/date-layer-v2/") and (
            self.path.endswith("/chart.png") or self.path.endswith("/meta")
        ):
            # v2 ("Beta") counterpart of /api/date-layer/ above -- the
            # combined v2 Bite Score heatmap plus its 6-7 contributing
            # factors (structure/eddy/sst_bell/chl_band/current/
            # bathymetry/mld), read from that date's SEPARATE
            # output/history/<date>/v2/ subfolder (see
            # date_layers.py::DATE_LAYER_SPECS_V2/build_date_layer_assets_v2()
            # and main.py::run_pipeline_v2()). Most dates simply don't have
            # a v2 run yet -- that's expected while this model is Beta, and
            # surfaces here as an ordinary 404 (never a 500/crash), which
            # the map page's JS turns into a clear "v2 not available for
            # this date" sidebar message instead of a blank/broken layer.
            suffix = "/chart.png" if self.path.endswith("/chart.png") else "/meta"
            rest = self.path[len("/api/date-layer-v2/"):-len(suffix)]
            date_str, _, key = rest.partition("/")
            try:
                validate_date_key(date_str)
            except ValueError as exc:
                self._send_json({"message": str(exc)}, status=400)
                return
            if key not in DATE_LAYER_SPECS_V2:
                self._send_json({"message": f"Unknown v2 layer: {key}"}, status=404)
                return
            try:
                png_path, meta_path = build_date_layer_assets_v2(date_str, key)
            except FileNotFoundError as exc:
                self._send_json({"message": str(exc)}, status=404)
                return
            except Exception as exc:
                logger.warning("v2 date layer %s/%s unavailable", date_str, key, exc_info=True)
                self._send_json({"message": str(exc)}, status=404)
                return
            if suffix == "/chart.png":
                with open(png_path, "rb") as f:
                    body = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(body)))
                # no-store: see the identical comment on /api/date-layer/
                # above.
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
            else:
                with open(meta_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                self._send_json(meta)
        elif self.path.startswith("/history/"):
            # A single shared template (see visualize.py::build_folium_map())
            # serves every date -- its JS resolves which date to fetch
            # layers for straight from this URL path, so there's no
            # per-date HTML file to look up here. Just confirm the date was
            # actually processed (has an archived Bite Score GeoTIFF)
            # before serving the same template as "/".
            date_str = self.path[len("/history/"):].strip("/")
            try:
                validate_date_key(date_str)
            except ValueError as exc:
                self._send_json({"message": str(exc)}, status=400)
                return
            date_tif = os.path.join(config.HISTORY_DIR, date_str, "bite_score.tif")
            if not os.path.isfile(date_tif):
                self._send_json({"message": f"No archived data for {date_str}"}, status=404)
                return
            if not os.path.exists(MAP_HTML_PATH):
                self._send_json({"message": "No map generated yet. Run the pipeline once."}, status=404)
                return
            with open(MAP_HTML_PATH, "rb") as f:
                body = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/tactics":
            body = build_catching_tactics_html().encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/tips":
            body = build_yellowfin_tips_html().encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/conditions":
            body = build_conditions_html().encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
        elif self.path.startswith("/moon/"):
            # Standalone "Moon & Tides" detail page (Lambert) -- a small
            # dark glass-panel/bento-grid page, NOT the Folium map, so it's
            # rendered by its own template (moon_tide_page.py) rather than
            # reusing MAP_HTML_PATH. Only validates the date is well-formed
            # (same permissive check as /history/<date>'s date_layers
            # validator, which also accepts run_demo.py's "demo") -- it
            # does NOT require an archived bite_score.tif to exist, since
            # this page only needs moon_phase.json (fetched client-side via
            # /api/moon-phase/<date>, which already 404s gracefully if that
            # date hasn't been processed).
            date_str = self.path[len("/moon/"):].strip("/")
            try:
                validate_date_key(date_str)
            except ValueError as exc:
                self._send_json({"message": str(exc)}, status=400)
                return
            body = build_moon_tide_page_html(date_str).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
        elif self.path.startswith("/static/"):
            # Serve files from the repo-root static/ folder (e.g. images
            # referenced by standalone pages like /tactics).
            filename = os.path.basename(self.path[len("/static/"):])
            if not filename:
                self._send_json({"message": "Not found"}, status=404)
                return
            file_path = os.path.join(STATIC_DIR, filename)
            if not os.path.isfile(file_path):
                self._send_json({"message": "Not found"}, status=404)
                return
            ext = os.path.splitext(filename)[1].lower()
            mime = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                    ".gif": "image/gif", ".webp": "image/webp", ".svg": "image/svg+xml"}.get(ext, "application/octet-stream")
            with open(file_path, "rb") as f:
                body = f.read()
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "public, max-age=86400")
            self.end_headers()
            self.wfile.write(body)
        else:
            self._send_json({"message": "Not found"}, status=404)

    def do_POST(self):
        if self.path == "/api/update":
            length = int(self.headers.get("Content-Length", 0) or 0)
            raw = self.rfile.read(length) if length else b"{}"
            try:
                payload = json.loads(raw or b"{}")
            except json.JSONDecodeError:
                payload = {}
            target_date = (payload.get("date") or "").strip() or config.DEFAULT_TARGET_DATE

            with _state_lock:
                if _state["state"] == "running":
                    self._send_json({"message": "An update is already running"}, status=409)
                    return

            thread = threading.Thread(target=_run_update_job, args=(target_date,), daemon=True)
            thread.start()
            self._send_json({"status": "started", "date": target_date}, status=202)
        elif self.path == "/api/windy/forecast":
            length = int(self.headers.get("Content-Length", 0) or 0)
            raw = self.rfile.read(length) if length else b"{}"
            try:
                payload = json.loads(raw or b"{}")
            except json.JSONDecodeError:
                self._send_json({"message": "Invalid JSON"}, status=400)
                return
            try:
                lat = float(payload.get("lat", -27.0))
                lon = float(payload.get("lon", 154.0))
            except (TypeError, ValueError):
                self._send_json({"message": "lat/lon must be numbers"}, status=400)
                return
            # Bounds-check: SE Queensland + seamount region
            if not (-35.0 <= lat <= -20.0 and 140.0 <= lon <= 160.0):
                self._send_json({"message": "lat/lon out of supported range"}, status=400)
                return
            try:
                result = windy_fetch_all(lat, lon)
            except Exception as exc:
                self._send_json({"errors": {"all": str(exc)}}, status=500)
                return
            self._send_json(result)
        else:
            self._send_json({"message": "Not found"}, status=404)


def serve(port: int = 8765, open_browser: bool = True) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    server = ThreadingHTTPServer(("127.0.0.1", port), BiteScoreRequestHandler)
    url = f"http://127.0.0.1:{port}/"
    logger.info("Serving Bite Score dashboard at %s (Ctrl+C to stop)", url)
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down.")
        server.shutdown()


def main():
    parser = argparse.ArgumentParser(description="Serve the Yellowfin Tuna Bite Score dashboard")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true", help="Don't auto-open a browser tab")
    args = parser.parse_args()
    serve(port=args.port, open_browser=not args.no_browser)


if __name__ == "__main__":
    main()
