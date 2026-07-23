"""
Tide-state classification and turning-point (High/Low) lookup.

Operates on the DataFrame returned by
`data_ingestion.py::fetch_tide_data()` (Queensland Government DES
storm-tide feed) -- this module is pure feature extraction over an
already-fetched tabular DataFrame, no network access of its own, mirroring
how fsle.py/moon_phase.py sit as their own standalone algorithm modules
separate from data_ingestion.py's fetch-only functions.

Two site codes are in scope for this project (see config.TIDE_SITES):
  - "tangalooma": a real locality on the north-western shore of Moreton
    Island (Moreton Bay).
  - "maroochydore": immediately adjacent to Mooloolaba, Sunshine Coast.

High/Low turning points are found with `scipy.signal.argrelextrema`
(already an installed project dependency -- see requirements.txt) applied
to the site's `Prediction` column (the pure astronomical forecast, not the
`Water Level` column, which can carry a `-99` missing-data sentinel for
the newest 1-2 rows -- see fetch_tide_data()'s docstring).
"""
import logging
from datetime import datetime, timedelta
from typing import List, Optional

import numpy as np
import pandas as pd
from scipy.signal import argrelextrema

from . import config

logger = logging.getLogger(__name__)


def filter_tide_sites(df: pd.DataFrame, sites: Optional[List[str]] = None) -> pd.DataFrame:
    """
    Narrow the full multi-site tide feed (see fetch_tide_data(), ~23 QLD
    sites) down to the sites this project cares about -- by default
    `config.TIDE_SITES` (tangalooma/maroochydore). Matches case-
    insensitively against the feed's lowercase `Site` codes, and returns
    rows sorted by site then `DateTime` so downstream turning-point
    detection can assume chronological order per site.
    """
    site_keys = [s.lower() for s in (sites if sites is not None else config.TIDE_SITES.keys())]
    filtered = df[df["Site"].str.lower().isin(site_keys)].copy()
    return filtered.sort_values(["Site", "DateTime"]).reset_index(drop=True)


def _site_series(df: pd.DataFrame, site: str) -> pd.DataFrame:
    site_df = df[df["Site"].str.lower() == site.lower()].sort_values("DateTime").reset_index(drop=True)
    if site_df.empty:
        raise ValueError(
            f"No tide data found for site '{site}'. Configured sites: {list(config.TIDE_SITES)}"
        )
    return site_df


def _coerce_to_tide_timezone(at_time: datetime) -> pd.Timestamp:
    ts = pd.Timestamp(at_time)
    if ts.tzinfo is None:
        return ts.tz_localize(config.TIDE_TIMEZONE)
    return ts.tz_convert(config.TIDE_TIMEZONE)


def _turning_points(site_df: pd.DataFrame) -> pd.DataFrame:
    """
    Identify local maxima (High tide) / minima (Low tide) in a single
    site's `Prediction` series, already sorted chronologically.
    """
    values = site_df["Prediction"].to_numpy()
    high_idx = argrelextrema(values, np.greater, order=1)[0]
    low_idx = argrelextrema(values, np.less, order=1)[0]

    turning = pd.concat(
        [
            site_df.iloc[high_idx].assign(tide_type="High"),
            site_df.iloc[low_idx].assign(tide_type="Low"),
        ]
    )
    turning = turning.sort_values("DateTime").reset_index(drop=True)
    return turning[["DateTime", "tide_type", "Prediction"]]


def _slope_state(site_df: pd.DataFrame, at_time: pd.Timestamp) -> str:
    """
    Fallback classification when `at_time` falls outside the bracket of
    two detected turning points (e.g. right at the start/end of the
    fetched window) -- compares the raw samples immediately either side
    of `at_time` instead.
    """
    pos = int((site_df["DateTime"] - at_time).abs().idxmin())
    lo = max(pos - 1, 0)
    hi = min(pos + 1, len(site_df) - 1)
    slope = site_df["Prediction"].iloc[hi] - site_df["Prediction"].iloc[lo]
    if slope > 0:
        return "Flooding"
    if slope < 0:
        return "Ebbing"
    return "Slack"


def classify_tide_state(df: pd.DataFrame, at_time: datetime, site: str) -> dict:
    """
    Classify the tide state for `site` at `at_time` as "Flooding" (rising
    towards the next High), "Ebbing" (falling towards the next Low), or
    "Slack" (within `config.TIDE_SLACK_WINDOW_MINUTES` of a High/Low
    turning point, i.e. near-zero rate of change).

    `at_time` may be naive (assumed already Australia/Brisbane local time)
    or timezone-aware (converted to Australia/Brisbane).

    Returns a dict:
        {
            "site": str,
            "at_time": pd.Timestamp (tz-aware, Australia/Brisbane),
            "state": "Flooding" | "Ebbing" | "Slack",
            "nearest_peak_type": "High" | "Low",
            "nearest_peak_time": pd.Timestamp,
            "nearest_peak_value_m": float,
            "time_to_nearest_peak": pd.Timedelta,
        }

    Raises ValueError if `site` has no rows in `df`, if `at_time` falls
    outside the fetched data's time range, or if no High/Low turning
    point could be identified at all (e.g. too few rows for `site`).
    """
    site_df = _site_series(df, site)
    at_time = _coerce_to_tide_timezone(at_time)

    series_start, series_end = site_df["DateTime"].iloc[0], site_df["DateTime"].iloc[-1]
    if not (series_start <= at_time <= series_end):
        raise ValueError(
            f"at_time {at_time} is outside the fetched tide data range "
            f"[{series_start}, {series_end}] for site '{site}'."
        )

    turning = _turning_points(site_df)
    if turning.empty:
        raise ValueError(f"Could not identify any High/Low turning points for site '{site}'.")

    deltas = (turning["DateTime"] - at_time).abs()
    nearest_idx = deltas.idxmin()
    nearest_time = turning.loc[nearest_idx, "DateTime"]
    nearest_type = turning.loc[nearest_idx, "tide_type"]
    nearest_value = turning.loc[nearest_idx, "Prediction"]
    time_to_nearest = abs(at_time - nearest_time)

    slack_window = timedelta(minutes=config.TIDE_SLACK_WINDOW_MINUTES)
    if time_to_nearest <= slack_window:
        state = "Slack"
    else:
        before = turning[turning["DateTime"] <= at_time]
        after = turning[turning["DateTime"] >= at_time]
        if not before.empty and not after.empty:
            prev_type = before.iloc[-1]["tide_type"]
            next_type = after.iloc[0]["tide_type"]
            if prev_type == "Low" and next_type == "High":
                state = "Flooding"
            elif prev_type == "High" and next_type == "Low":
                state = "Ebbing"
            else:
                # Shouldn't happen for cleanly alternating turning points,
                # but fall back to the raw sample-to-sample slope rather
                # than raising, if it ever does.
                state = _slope_state(site_df, at_time)
        else:
            # at_time falls before the first / after the last detected
            # turning point within the fetched window.
            state = _slope_state(site_df, at_time)

    return {
        "site": site,
        "at_time": at_time,
        "state": state,
        "nearest_peak_type": nearest_type,
        "nearest_peak_time": nearest_time,
        "nearest_peak_value_m": float(nearest_value),
        "time_to_nearest_peak": time_to_nearest,
    }


def next_tide_events(df: pd.DataFrame, site: str, from_time: datetime) -> dict:
    """
    Return the next High and next Low tide turning points for `site`
    strictly after `from_time`.

    `from_time` may be naive (assumed already Australia/Brisbane local
    time) or timezone-aware (converted to Australia/Brisbane).

    Returns a dict:
        {
            "site": str,
            "from_time": pd.Timestamp (tz-aware, Australia/Brisbane),
            "next_high": {"time": pd.Timestamp, "height_m": float} | None,
            "next_low": {"time": pd.Timestamp, "height_m": float} | None,
        }
    `next_high`/`next_low` are None if the fetched ~7-day window doesn't
    extend far enough past `from_time` to contain one.

    Raises ValueError if `site` has no rows in `df`.
    """
    site_df = _site_series(df, site)
    from_time = _coerce_to_tide_timezone(from_time)

    turning = _turning_points(site_df)
    upcoming = turning[turning["DateTime"] > from_time]

    def _event(tide_type: str) -> Optional[dict]:
        rows = upcoming[upcoming["tide_type"] == tide_type]
        if rows.empty:
            return None
        row = rows.iloc[0]
        return {"time": row["DateTime"], "height_m": float(row["Prediction"])}

    return {
        "site": site,
        "from_time": from_time,
        "next_high": _event("High"),
        "next_low": _event("Low"),
    }
