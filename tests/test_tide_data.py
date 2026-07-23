"""
Real, runnable tests for tide data ingestion & tide-state classification:
`bite_score.data_ingestion.fetch_tide_data` (HTTP mocked via monkeypatch --
no live network dependency, so this suite passes reliably in CI/sandboxed
runs) and `bite_score.tide.filter_tide_sites` / `classify_tide_state` /
`next_tide_events` (fully offline, synthetic fixture data -- no network
needed at all).

See .squad/decisions/inbox/ripley-tide-data-ingestion.md -- this
supersedes the earlier "tide data permanently unavailable" conclusion in
.squad/decisions/inbox/ripley-moon-tide-data.md (that doc correctly found
astral has zero tidal capability, but hadn't checked for an actual
tide-gauge data source; the Queensland Government DES storm-tide feed
used here was verified live and does work).
"""
import io
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest
import requests

from bite_score import config
from bite_score.data_ingestion import fetch_tide_data
from bite_score.tide import classify_tide_state, filter_tide_sites, next_tide_events


def _synthetic_csv_text(hours: int = 48, interval_minutes: int = 10) -> str:
    """
    Build a synthetic CSV payload mimicking the real QLD DES feed's shape
    (LIVE-VERIFIED 2026-07-22, see fetch_tide_data()'s docstring): a
    human-readable banner first line, then the real header, then
    10-minute-interval rows for the two in-scope sites
    (tangalooma/maroochydore) plus one out-of-scope site (abellpoint, a
    real site code in the live feed) to exercise the site filter. Each
    site's `Prediction` follows a clean semi-diurnal (~12.4h period) sine
    wave so High/Low turning points are unambiguous.
    """
    lines = ["Tide Data provided @ 12:00hrs on 01-01-2026"]
    lines.append(
        "Site, Seconds, DateTime, Water Level, Prediction, Residual, Latitude, Longitude"
    )

    start = datetime(2026, 1, 1, 0, 0)
    n_steps = int(hours * 60 / interval_minutes)
    period_minutes = 12.4 * 60
    seconds_base = 1_767_225_600  # arbitrary epoch seconds for 2026-01-01T00:00

    sites = {
        "tangalooma": (-27.178, 153.371),
        "maroochydore": (-26.653, 153.101),
        "abellpoint": (-20.2608, 148.7103),
    }

    for site, (lat, lon) in sites.items():
        for i in range(n_steps):
            t = start + timedelta(minutes=interval_minutes * i)
            phase = 2 * np.pi * (interval_minutes * i) / period_minutes
            prediction = 1.5 + 1.0 * np.sin(phase)
            water_level = prediction + 0.05
            residual = 0.05
            seconds = seconds_base + interval_minutes * 60 * i
            # High precision (unlike the real feed's 3dp) so this perfectly
            # smooth synthetic sine wave doesn't round two adjacent samples
            # to an identical value right at a turning point -- real tide
            # data's rate of change is never *exactly* zero for more than
            # one sample, so an exact tie here would be a test-data
            # artifact, not a real-world case the algorithm needs to
            # handle.
            lines.append(
                f"{site},{seconds},{t.strftime('%Y-%m-%dT%H:%M')},"
                f"{water_level:.8f},{prediction:.8f},{residual:.3f},{lat},{lon}"
            )
    return "\n".join(lines) + "\n"


@pytest.fixture
def synthetic_tide_csv() -> str:
    return _synthetic_csv_text()


@pytest.fixture
def synthetic_tide_df(synthetic_tide_csv) -> pd.DataFrame:
    df = pd.read_csv(io.StringIO(synthetic_tide_csv), skiprows=1, skipinitialspace=True)
    df["DateTime"] = pd.to_datetime(df["DateTime"]).dt.tz_localize(config.TIDE_TIMEZONE)
    return df


class _FakeResponse:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        pass


class TestFetchTideData:
    def test_parses_mocked_csv_into_dataframe_with_expected_columns(
        self, monkeypatch, synthetic_tide_csv, tmp_path
    ):
        monkeypatch.setattr(
            "bite_score.data_ingestion.requests.get",
            lambda url, timeout: _FakeResponse(synthetic_tide_csv),
        )
        df = fetch_tide_data(output_directory=str(tmp_path))
        assert list(df.columns) == [
            "Site",
            "Seconds",
            "DateTime",
            "Water Level",
            "Prediction",
            "Residual",
            "Latitude",
            "Longitude",
        ]
        assert str(df["DateTime"].dt.tz) == str(config.TIDE_TIMEZONE)
        assert set(df["Site"].unique()) == {"tangalooma", "maroochydore", "abellpoint"}

    def test_falls_back_to_cached_copy_on_request_exception(
        self, monkeypatch, synthetic_tide_csv, tmp_path
    ):
        cache_path = tmp_path / "tide_data_latest.csv"
        cache_path.write_text(synthetic_tide_csv, encoding="utf-8")

        def _raise(*args, **kwargs):
            raise requests.exceptions.ConnectionError("simulated network failure")

        monkeypatch.setattr("bite_score.data_ingestion.requests.get", _raise)
        df = fetch_tide_data(output_directory=str(tmp_path))
        assert not df.empty
        assert "tangalooma" in set(df["Site"].unique())

    def test_raises_runtime_error_when_no_cache_and_request_fails(self, monkeypatch, tmp_path):
        def _raise(*args, **kwargs):
            raise requests.exceptions.ConnectionError("simulated network failure")

        monkeypatch.setattr("bite_score.data_ingestion.requests.get", _raise)
        with pytest.raises(RuntimeError):
            fetch_tide_data(output_directory=str(tmp_path))


class TestFilterTideSites:
    def test_filters_to_configured_sites_by_default(self, synthetic_tide_df):
        filtered = filter_tide_sites(synthetic_tide_df)
        assert set(filtered["Site"].unique()) == {"tangalooma", "maroochydore"}

    def test_accepts_explicit_site_list(self, synthetic_tide_df):
        filtered = filter_tide_sites(synthetic_tide_df, sites=["abellpoint"])
        assert set(filtered["Site"].unique()) == {"abellpoint"}


class TestClassifyTideState:
    def test_classifies_flooding_before_first_high(self, synthetic_tide_df):
        start = synthetic_tide_df["DateTime"].iloc[0]
        result = classify_tide_state(synthetic_tide_df, at_time=start + timedelta(minutes=90), site="tangalooma")
        assert result["state"] == "Flooding"
        assert result["site"] == "tangalooma"

    def test_classifies_ebbing_between_high_and_low(self, synthetic_tide_df):
        start = synthetic_tide_df["DateTime"].iloc[0]
        # Midpoint between the first High (~186min) and first Low (~558min).
        result = classify_tide_state(synthetic_tide_df, at_time=start + timedelta(minutes=372), site="tangalooma")
        assert result["state"] == "Ebbing"

    def test_classifies_flooding_between_low_and_next_high(self, synthetic_tide_df):
        start = synthetic_tide_df["DateTime"].iloc[0]
        # Midpoint between the first Low (~558min) and the second High (~930min).
        result = classify_tide_state(synthetic_tide_df, at_time=start + timedelta(minutes=744), site="tangalooma")
        assert result["state"] == "Flooding"

    def test_returns_slack_at_a_detected_turning_point(self, synthetic_tide_df):
        start = synthetic_tide_df["DateTime"].iloc[0]
        first_pass = classify_tide_state(
            synthetic_tide_df, at_time=start + timedelta(minutes=90), site="tangalooma"
        )
        peak_time = first_pass["nearest_peak_time"]

        result = classify_tide_state(synthetic_tide_df, at_time=peak_time, site="tangalooma")
        assert result["state"] == "Slack"
        assert result["time_to_nearest_peak"] <= timedelta(minutes=config.TIDE_SLACK_WINDOW_MINUTES)

    def test_naive_and_utc_aware_at_time_agree(self, synthetic_tide_df):
        start = synthetic_tide_df["DateTime"].iloc[0]
        naive_time = start.tz_localize(None) + timedelta(minutes=90)
        utc_time = (start + timedelta(minutes=90)).tz_convert(timezone.utc)

        naive_result = classify_tide_state(synthetic_tide_df, at_time=naive_time, site="tangalooma")
        utc_result = classify_tide_state(synthetic_tide_df, at_time=utc_time, site="tangalooma")
        assert naive_result["state"] == utc_result["state"]
        assert naive_result["at_time"] == utc_result["at_time"]

    def test_raises_for_at_time_outside_fetched_range(self, synthetic_tide_df):
        start = synthetic_tide_df["DateTime"].iloc[0]
        with pytest.raises(ValueError):
            classify_tide_state(synthetic_tide_df, at_time=start - timedelta(days=10), site="tangalooma")

    def test_raises_for_unknown_site(self, synthetic_tide_df):
        start = synthetic_tide_df["DateTime"].iloc[0]
        with pytest.raises(ValueError):
            classify_tide_state(synthetic_tide_df, at_time=start, site="not_a_real_site")


class TestNextTideEvents:
    def test_returns_next_high_and_low_after_given_time(self, synthetic_tide_df):
        start = synthetic_tide_df["DateTime"].iloc[0]
        result = next_tide_events(synthetic_tide_df, site="maroochydore", from_time=start)
        assert result["next_high"] is not None
        assert result["next_low"] is not None
        assert result["next_high"]["time"] > start
        assert result["next_low"]["time"] > start
        # Sine phase starts at 0 rising, so the first High precedes the first Low.
        assert result["next_high"]["time"] < result["next_low"]["time"]

    def test_returns_none_when_nothing_left_in_window(self, synthetic_tide_df):
        end = synthetic_tide_df["DateTime"].iloc[-1]
        result = next_tide_events(synthetic_tide_df, site="tangalooma", from_time=end)
        assert result["next_high"] is None
        assert result["next_low"] is None

    def test_raises_for_unknown_site(self, synthetic_tide_df):
        start = synthetic_tide_df["DateTime"].iloc[0]
        with pytest.raises(ValueError):
            next_tide_events(synthetic_tide_df, site="not_a_real_site", from_time=start)


class TestTideConfig:
    def test_tide_sites_include_tangalooma_and_maroochydore(self):
        assert set(config.TIDE_SITES) == {"tangalooma", "maroochydore"}

    def test_tide_data_url_is_https(self):
        assert config.TIDE_DATA_URL.startswith("https://")

    def test_slack_window_is_positive_minutes(self):
        assert config.TIDE_SLACK_WINDOW_MINUTES > 0
