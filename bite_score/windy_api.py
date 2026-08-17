"""
Windy.com Point Forecast API integration for SE Queensland fishing locations.

Fetches wind (GFS), waves (gfsWave), and ocean currents (CMEMS) in parallel.

Requires WINDY_API_KEY set in .env or environment:
  - Free testing tier: 500 req/day, data is randomly shuffled (dev only).
  - Professional: €990/yr, 10,000 req/day, real forecast data.

Docs: https://api.windy.com/point-forecast/docs
"""

import json
import logging
import math
import os
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)

WINDY_API_URL = "https://api.windy.com/api/point-forecast/v2"

# Key SE Queensland offshore fishing locations
FISHING_LOCATIONS = [
    {"id": "brisbane_canyon", "name": "Brisbane Canyon",  "lat": -27.0,  "lon": 154.0},
    {"id": "sunshine_coast",  "name": "Sunshine Coast",   "lat": -26.65, "lon": 153.85},
    {"id": "north_reef",      "name": "North Reef",       "lat": -26.4,  "lon": 153.7},
    {"id": "moreton_island",  "name": "Moreton Island",   "lat": -27.1,  "lon": 153.6},
    {"id": "gold_coast",      "name": "Gold Coast",       "lat": -27.95, "lon": 154.1},
    {"id": "qld_seamount",    "name": "Qld Seamount",     "lat": -26.5,  "lon": 155.0},
]


def _api_key() -> str:
    from . import config as _cfg  # deferred to avoid circular at module level
    return (getattr(_cfg, "WINDY_API_KEY", None) or os.environ.get("WINDY_API_KEY") or "").strip()


def _post(payload: dict) -> dict:
    key = _api_key()
    if not key:
        raise RuntimeError("WINDY_API_KEY not configured — add it to .env")
    data = json.dumps({**payload, "key": key}).encode("utf-8")
    req = urllib.request.Request(
        WINDY_API_URL, data=data,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Windy API {exc.code}: {body}") from exc


def _ms_to_kt(ms):
    return round(float(ms) * 1.94384, 1) if ms is not None else None


def _speed_kt(u, v):
    if u is None or v is None:
        return None
    return round(math.hypot(float(u), float(v)) * 1.94384, 1)


def _dir_from(u, v):
    """Meteorological direction — where wind/flow comes FROM (degrees)."""
    if u is None or v is None:
        return None
    return round(math.degrees(math.atan2(-float(u), -float(v))) % 360, 0)


def _dir_to(u, v):
    """Oceanographic direction — where current flows TO (degrees)."""
    if u is None or v is None:
        return None
    return round(math.degrees(math.atan2(float(u), float(v))) % 360, 0)


def _safe(arr, i):
    try:
        return arr[i]
    except (TypeError, IndexError):
        return None


def _fetch_wind(lat: float, lon: float) -> dict:
    raw = _post({
        "lat": lat, "lon": lon, "model": "gfs",
        "parameters": ["wind", "windGust", "cape", "pressure"],
    })
    ts = raw.get("ts", [])
    u = raw.get("wind_u-surface", [])
    v = raw.get("wind_v-surface", [])
    g = raw.get("gust-surface", [])
    c = raw.get("cape-surface", [])
    p = raw.get("pressure-surface", [])
    data = []
    for i, t in enumerate(ts):
        pi = _safe(p, i)
        ci = _safe(c, i)
        data.append({
            "ts":       t,
            "wind_kt":  _speed_kt(_safe(u, i), _safe(v, i)),
            "wind_dir": _dir_from(_safe(u, i), _safe(v, i)),
            "gust_kt":  _ms_to_kt(_safe(g, i)),
            "cape":     round(ci, 0) if ci is not None else None,
            "pressure": round(pi / 100, 1) if pi is not None else None,
        })
    return {"model": "gfs", "data": data}


def _fetch_waves(lat: float, lon: float) -> dict:
    raw = _post({
        "lat": lat, "lon": lon, "model": "gfsWave",
        "parameters": ["waves", "swell1", "wavesPower"],
    })
    ts  = raw.get("ts", [])
    wh  = raw.get("waves_height-surface", [])
    wp  = raw.get("waves_period-surface", [])
    wd  = raw.get("waves_direction-surface", [])
    sh  = raw.get("swell1_height-surface", [])
    sp  = raw.get("swell1_period-surface", [])
    sd  = raw.get("swell1_direction-surface", [])
    pwr = raw.get("waves_power-surface", [])
    data = []
    for i, t in enumerate(ts):
        pi = _safe(pwr, i)
        data.append({
            "ts":        t,
            "wave_h":    round(_safe(wh, i), 2)   if _safe(wh, i)  is not None else None,
            "wave_p":    round(_safe(wp, i), 1)   if _safe(wp, i)  is not None else None,
            "wave_dir":  round(_safe(wd, i), 0)   if _safe(wd, i)  is not None else None,
            "swell_h":   round(_safe(sh, i), 2)   if _safe(sh, i)  is not None else None,
            "swell_p":   round(_safe(sp, i), 1)   if _safe(sp, i)  is not None else None,
            "swell_dir": round(_safe(sd, i), 0)   if _safe(sd, i)  is not None else None,
            "power_kw":  round(pi / 1000, 2)      if pi             is not None else None,
        })
    return {"model": "gfsWave", "data": data}


def _fetch_currents(lat: float, lon: float) -> dict:
    raw = _post({
        "lat": lat, "lon": lon, "model": "cmems",
        "parameters": ["currents", "currentsTide"],
    })
    ts = raw.get("ts", [])
    cu = raw.get("seacurrents_u-surface", [])
    cv = raw.get("seacurrents_v-surface", [])
    tu = raw.get("seacurrents_tide_u-surface", [])
    tv = raw.get("seacurrents_tide_v-surface", [])
    data = []
    for i, t in enumerate(ts):
        data.append({
            "ts":          t,
            "current_kt":  _speed_kt(_safe(cu, i), _safe(cv, i)),
            "current_dir": _dir_to(_safe(cu, i), _safe(cv, i)),
            "tide_kt":     _speed_kt(_safe(tu, i), _safe(tv, i)),
        })
    return {"model": "cmems", "data": data}


def fetch_all(lat: float, lon: float) -> dict:
    """Fetch wind + waves + ocean currents in parallel for the given point."""
    results: dict = {}
    errors: dict = {}
    tasks = {
        "wind":     (_fetch_wind,     lat, lon),
        "waves":    (_fetch_waves,    lat, lon),
        "currents": (_fetch_currents, lat, lon),
    }
    with ThreadPoolExecutor(max_workers=3) as ex:
        futs = {ex.submit(fn, la, lo): name for name, (fn, la, lo) in tasks.items()}
        for fut in as_completed(futs):
            name = futs[fut]
            try:
                results[name] = fut.result()
            except Exception as exc:
                logger.warning("Windy %s fetch failed: %s", name, exc)
                errors[name] = str(exc)
    if errors:
        results["errors"] = errors
    return results
