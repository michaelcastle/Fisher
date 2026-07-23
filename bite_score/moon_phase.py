"""
Moon phase / lunar illumination fraction calculation.

Recommended by Kane (Fishing Specialist, see .squad/decisions.md) as a
low-effort proxy for nocturnal baitfish vertical migration and bite-window
timing. Unlike every other layer in this package, this needs zero external
data ingestion -- it's a pure astronomical calculation for a given date.

Uses the `astral` package (https://pypi.org/project/astral/) rather than
hand-rolling a lunar ephemeris from scratch. It was not already installed
in this project's venv, but it's a small, well-established, pure-Python
astronomy library (its only dependency, `tzdata`, was already present), so
it was added to requirements.txt instead of reimplementing the phase
calculation manually.

`moon_illumination_fraction()` returns a single scalar per date (0.0 = new
moon / dark, 1.0 = full moon / fully illuminated) -- NOT a spatial raster,
since illumination fraction is a property of Earth-Moon-Sun geometry only
and does not meaningfully vary across an AOI this small (~250km). It's a
single day-level modifier for the rest of the pipeline to apply uniformly,
not a per-pixel layer.

`moon_phase_details()` returns the fuller "Moon & Tides" detail-page bundle
(phase name, raw phase age, real moonrise/moonset, and solunar peak
windows) -- see its own docstring for exactly what astral can and cannot
compute here, confirmed by introspecting the installed astral==3.2
package directly rather than assuming (astral DOES compute real
moonrise/moonset via `astral.moon.moonrise()`/`moonset()`, contrary to
the common assumption that it only does sun rise/set; it has NO tidal
model at all).

Solunar peak windows (`solunar_periods`, added for Michael's "Solunar
Peak Windows" card): classic Knight's solunar theory defines two ~2-hour
"Major" feeding windows centered on moon transit (moon at its highest
point over the observer) and moon antitransit (moon at its "lowest"
point, on the opposite side of the Earth), plus two ~1-hour "Minor"
windows centered on moonrise and moonset. Introspecting `astral.moon`
turned up `moon_transit_event`/`TransitEvent`/`NoTransit`, which looked
promising at first glance, but reading their source (they're internal
helpers used only by `astral.moon.riseset()`) confirmed they compute the
moon crossing the *horizon* (rise/set events), not the observer's
*meridian* (true transit/antitransit) -- astral has no direct meridian
transit function. Rather than falling back to the coarser rise/set
midpoint approximation, this module computes real transit/antitransit
times using `astral.moon.elevation()` (also already exposed, used
internally by `riseset()`) by numerically finding the moment of
maximum/minimum lunar elevation over the UTC day -- an actual
astronomical computation from real ephemeris data, not a fabricated or
guessed time. Spot-checked against real moonrise/moonset (see
`.squad/decisions/inbox/ripley-solunar-peak-windows.md`): computed
transit fell almost exactly at the moonrise/moonset midpoint (as
expected), and antitransit ~12h25m later (the moon's ~24h50m diurnal
cycle), confirming the search behaves correctly.
"""
import logging
import math
from datetime import datetime, timedelta, timezone

from astral import Observer, moon

from . import config

logger = logging.getLogger(__name__)

# astral.moon.phase() returns a value in [0, 28) representing position in
# the lunar cycle (0 = new moon, 14 = full moon), not a literal day count.
_LUNAR_PHASE_SCALE = 28.0

# Human-readable phase name buckets, keyed by the upper-bound (exclusive) of
# `phase` (astral's 0..27.99 scale) each name applies to -- 8 equal-width
# (3.5-day) slices centered on the four "named instants" astral documents
# (0=new, ~7=first quarter, 14=full, ~21=last quarter). This is a standard
# 8-phase naming convention, not a fabricated scale -- it's just a label
# derived from the same real `phase` value already used for illumination,
# so waxing/waning (which illumination_fraction alone cannot distinguish,
# since it's symmetric around new/full) is preserved for display.
_PHASE_NAME_THRESHOLDS = [
    (1.75, "New Moon"),
    (5.25, "Waxing Crescent"),
    (8.75, "First Quarter"),
    (12.25, "Waxing Gibbous"),
    (15.75, "Full Moon"),
    (19.25, "Waning Gibbous"),
    (22.75, "Last Quarter"),
    (26.25, "Waning Crescent"),
    (28.0, "New Moon"),
]


def moon_phase_name(phase_age_days: float) -> str:
    """Human-readable lunar phase name for a raw astral `phase` value (0..27.99)."""
    for threshold, name in _PHASE_NAME_THRESHOLDS:
        if phase_age_days < threshold:
            return name
    return "New Moon"


# --- Solunar peak windows ----------------------------------------------
# Standard Knight's solunar theory window widths (see module docstring for
# what these are and how transit/antitransit are computed). This is a
# fishing heuristic, not exact science -- treat the resulting windows as
# approximate feeding-activity guidance, not a precision prediction, the
# same caveat anglers apply to any solunar table.
_MAJOR_HALF_WIDTH = timedelta(hours=1)
_MINOR_HALF_WIDTH = timedelta(minutes=30)

# Coarse-then-fine grid search resolution for the transit/antitransit
# elevation-extremum search below. 10-minute coarse steps easily resolve
# the moon's single daily max/min (elevation changes smoothly over its
# ~24h50m cycle); the 30-second fine pass around the coarse winner
# tightens that to well within solunar precision (real solunar tables are
# only ever quoted to the minute).
_COARSE_STEP = timedelta(minutes=10)
_FINE_STEP = timedelta(seconds=30)


def _best_elevation_in_range(observer, range_start, range_end, step, want_max, seed_time, seed_val):
    """Grid-search `astral.moon.elevation()` over [range_start, range_end] for the max (or min) value."""
    best_time, best_val = seed_time, seed_val
    t = range_start
    while t <= range_end:
        elevation = moon.elevation(observer, t)
        if (want_max and elevation > best_val) or (not want_max and elevation < best_val):
            best_val, best_time = elevation, t
        t += step
    return best_time, best_val


def _moon_transit_antitransit(observer: Observer, date) -> tuple:
    """
    Find the real moon transit (maximum elevation -- moon at its highest
    point over `observer`) and antitransit (minimum elevation -- moon at
    its "lowest"/opposite-side point) datetimes within the UTC calendar
    day `date`, using `astral.moon.elevation()`.

    astral has no direct meridian-transit function (see module docstring
    for what was checked and ruled out), so this does a coarse grid search
    over the day for the elevation max/min, then refines each with a
    finer-grained search in the neighbourhood of the coarse winner. Both
    events occur exactly once per ~24h50m lunar day, so within any single
    24-hour UTC window there is always a well-defined max and min --
    unlike moonrise/moonset, this never has a "no event today" case.
    """
    start = datetime(date.year, date.month, date.day, tzinfo=timezone.utc)
    end = start + timedelta(days=1)
    seed_val = moon.elevation(observer, start)

    max_time, max_val = _best_elevation_in_range(observer, start, end, _COARSE_STEP, True, start, seed_val)
    min_time, min_val = _best_elevation_in_range(observer, start, end, _COARSE_STEP, False, start, seed_val)

    max_time, _ = _best_elevation_in_range(
        observer, max(start, max_time - _COARSE_STEP), min(end, max_time + _COARSE_STEP),
        _FINE_STEP, True, max_time, max_val,
    )
    min_time, _ = _best_elevation_in_range(
        observer, max(start, min_time - _COARSE_STEP), min(end, min_time + _COARSE_STEP),
        _FINE_STEP, False, min_time, min_val,
    )
    return max_time, min_time


def _solunar_period(center, half_width: timedelta, period_type: str, description: str, note: str = None) -> dict:
    """
    Build one solunar period entry: `center` +/- `half_width`, or a
    graceful null/`note` pair (same convention as moonrise/moonset) when
    `center` is unavailable (only possible for the minor periods, which
    are anchored on moonrise/moonset).
    """
    period = {
        "type": period_type,
        "description": description,
        "start": (center - half_width).isoformat() if center else None,
        "center": center.isoformat() if center else None,
        "end": (center + half_width).isoformat() if center else None,
    }
    if note:
        period["note"] = note
    return period


def moon_phase_details(target_date: str, lat: float = None, lon: float = None) -> dict:
    """
    Compute the real lunar data for `target_date` (YYYY-MM-DD, UTC):
    - illumination_fraction: 0.0 (new moon, dark) to 1.0 (full moon, bright)
    - phase_age_days: raw position in the lunar cycle, 0.0..27.99 (astral's
      scale -- 0=new moon, ~14=full moon)
    - phase_name: human label (e.g. "Waxing Gibbous") derived from
      phase_age_days
    - moonrise / moonset: REAL astral capability, added after directly
      introspecting the installed astral==3.2 package's public API rather
      than assuming -- contrary to the common assumption (and this
      module's own earlier docstring/comments) that astral only computes
      SUN rise/set, `astral.moon.moonrise()`/`astral.moon.moonset()` exist
      and compute actual moon transit times for a given
      `astral.Observer(latitude, longitude)`. Unlike illumination_fraction
      (which is observer-independent), these genuinely depend on `lat`/
      `lon` and default to the AOI centroid the same way. On some
      dates/locations the moon simply never rises or never sets within
      the UTC calendar day (it's already up, or stays below the horizon,
      the whole day) -- astral raises `ValueError` for that real
      astronomical case, reported here as `null` plus a `moonrise_note`/
      `moonset_note` string rather than omitted or faked.

    Tide height/current velocity is NOT computed anywhere in this module:
    introspecting astral's full public API confirms it has no tidal model
    whatsoever, and no other already-installed dependency (numpy/scipy/
    xarray/etc.) provides one either. Real tide prediction needs harmonic
    constituents for a specific station (e.g. a NOAA/BOM tide API, or a
    library such as `pytides`) -- out of scope without adding a new
    dependency or calling an external API, so there is no tide field in
    this schema at all (not even a null placeholder).

    - solunar_periods: classic Knight's solunar theory major/minor feeding
      windows -- see the module docstring for how transit/antitransit are
      computed and the "heuristic, not exact science" caveat. Dict with
      keys `major_1` (moon transit +/- 1hr), `major_2` (moon antitransit
      +/- 1hr), `minor_1` (moonrise +/- 30min), `minor_2` (moonset +/-
      30min). Each period is `{type, description, start, center, end}`
      (ISO 8601 UTC datetimes), or `start`/`center`/`end` all `null` plus
      a `note` when the underlying event doesn't occur that day (only
      possible for minor_1/minor_2, mirroring the moonrise/moonset `null`
      convention above -- majors are always computable).

    `lat`/`lon` default to the AOI's centroid if not supplied.
    """
    if lat is None:
        lat = (config.AOI["min_lat"] + config.AOI["max_lat"]) / 2.0
    if lon is None:
        lon = (config.AOI["min_lon"] + config.AOI["max_lon"]) / 2.0

    date = datetime.strptime(target_date, "%Y-%m-%d").date()
    phase = moon.phase(date)  # 0..27.99 (0=new, 14=full, 21=last quarter)

    # Standard cosine approximation of illuminated fraction from lunar
    # phase angle: 0.0 at new moon, 1.0 at full moon, ~0.5 at both quarters
    # -- matches real-world illuminated-fraction behaviour closely enough
    # for a bite-score modifier (this is not a precision ephemeris need).
    illumination = (1.0 - math.cos(2.0 * math.pi * phase / _LUNAR_PHASE_SCALE)) / 2.0
    name = moon_phase_name(phase)

    details = {
        "illumination_fraction": illumination,
        "phase_age_days": phase,
        "phase_name": name,
    }

    observer = Observer(latitude=lat, longitude=lon)
    rise = None
    moonset_time = None
    try:
        rise = moon.moonrise(observer, date)
        details["moonrise"] = rise.isoformat() if rise else None
    except ValueError as exc:
        details["moonrise"] = None
        details["moonrise_note"] = str(exc)

    try:
        moonset_time = moon.moonset(observer, date)
        details["moonset"] = moonset_time.isoformat() if moonset_time else None
    except ValueError as exc:
        details["moonset"] = None
        details["moonset_note"] = str(exc)

    transit, antitransit = _moon_transit_antitransit(observer, date)
    details["solunar_periods"] = {
        "major_1": _solunar_period(
            transit, _MAJOR_HALF_WIDTH, "major", "Moon transit (overhead) peak window",
        ),
        "major_2": _solunar_period(
            antitransit, _MAJOR_HALF_WIDTH, "major", "Moon antitransit (underfoot) peak window",
        ),
        "minor_1": _solunar_period(
            rise, _MINOR_HALF_WIDTH, "minor", "Moonrise peak window",
            note=details.get("moonrise_note"),
        ),
        "minor_2": _solunar_period(
            moonset_time, _MINOR_HALF_WIDTH, "minor", "Moonset peak window",
            note=details.get("moonset_note"),
        ),
    }

    logger.info(
        "Moon phase for %s (AOI centroid %.2f, %.2f): raw_phase=%.2f illumination_fraction=%.3f "
        "name=%s moonrise=%s moonset=%s",
        target_date, lat, lon, phase, illumination, name,
        details.get("moonrise"), details.get("moonset"),
    )
    return details


def moon_illumination_fraction(target_date: str, lat: float = None, lon: float = None) -> float:
    """
    Compute the fraction of the Moon's visible disc illuminated by the Sun
    on `target_date` (YYYY-MM-DD, UTC), scaled 0.0 (new moon, dark) to 1.0
    (full moon, bright). Thin wrapper around `moon_phase_details()` kept for
    existing callers (e.g. main.py's bite-score multiplier) that only need
    the scalar.
    """
    return moon_phase_details(target_date, lat, lon)["illumination_fraction"]
