"""
Real, runnable tests for the moon phase / lunar illumination module:
`bite_score.moon_phase.moon_illumination_fraction` (a real astronomical
calculation via `astral` -- local computation, no network required),
`bite_score.moon_phase.moon_phase_details` solunar peak windows (also a
real astronomical calculation, via `astral.moon.elevation()` -- see that
module's docstring for how transit/antitransit are derived), and
`bite_score.overlay.apply_moon_phase_multiplier` (the deterministic
final-score multiplier formula Ripley wired in).

Supersedes tests/test_moon_phase_provisional.py, written before these
landed. See:
  - .squad/decisions/inbox/ash-mld-moonphase.md
  - .squad/decisions/inbox/ripley-mld-moon-scoring.md
  - .squad/decisions/inbox/ripley-solunar-peak-windows.md
"""
from datetime import datetime, timedelta

import pytest
import xarray as xr

from bite_score import config
from bite_score.moon_phase import moon_illumination_fraction, moon_phase_details
from bite_score.overlay import apply_moon_phase_multiplier


class TestMoonIlluminationFractionRange:
    @pytest.mark.parametrize(
        "target_date",
        ["2026-07-22", "2023-08-21", "2024-02-29", "2025-12-31", "2026-01-01"],
    )
    def test_returns_float_in_unit_range(self, target_date):
        value = moon_illumination_fraction(target_date)
        assert isinstance(value, float)
        assert 0.0 <= value <= 1.0

    def test_consecutive_days_change_smoothly(self):
        """
        Illumination should change gradually day-to-day (a lunar cycle is
        ~29.5 days) -- a large single-day jump would indicate a
        date-parsing/timezone bug rather than a real phase change. The
        cosine-approximation formula's maximum possible daily change is
        ~0.5 * sin(x) * (2*pi/28) =~ 0.11 for a 1-day phase step, so 0.15
        leaves headroom without being loose enough to hide a real bug.
        """
        v1 = moon_illumination_fraction("2026-07-21")
        v2 = moon_illumination_fraction("2026-07-22")
        assert abs(v1 - v2) < 0.15

    def test_full_lunar_cycle_spans_near_zero_to_near_one(self):
        """
        Cautious, self-verifying check on the real `astral`-backed
        ephemeris calculation: rather than asserting a *specific calendar
        date* is "the" full/new moon (unverifiable against a live
        astronomy service in this environment -- this is what the old
        provisional test's xfail(strict=False) reference-date assertions
        were flagging as unconfirmed), scan a full ~30-day span and
        confirm the illuminated fraction actually reaches both a
        near-dark minimum and a near-full maximum somewhere in it. That
        range coverage is guaranteed by the cosine-mapping formula over
        one full lunar cycle regardless of which specific day is which,
        so it's fully assertable without an external reference date.
        """
        start = datetime(2026, 7, 1)
        values = [
            moon_illumination_fraction((start + timedelta(days=i)).strftime("%Y-%m-%d"))
            for i in range(30)
        ]
        assert min(values) < 0.1
        assert max(values) > 0.9

    def test_lat_lon_params_do_not_change_result(self):
        """
        lat/lon are accepted for interface consistency but documented as
        unused (illumination fraction doesn't depend on observer
        location) -- confirm that's actually true rather than just
        documented.
        """
        default = moon_illumination_fraction("2026-07-22")
        explicit = moon_illumination_fraction("2026-07-22", lat=10.0, lon=100.0)
        assert default == explicit


class TestMoonPhaseMultiplierFormula:
    """
    Unlike the moon-phase ephemeris calculation above, the multiplier
    formula itself is a deterministic linear interpolation Ripley wrote --
    fully testable precisely, not an unverifiable external claim.
    """

    def test_config_bounds_are_0_8_and_1_2(self):
        assert config.MOON_MULTIPLIER_MIN == 0.8
        assert config.MOON_MULTIPLIER_MAX == 1.2

    def test_new_moon_illumination_gives_1_2x_multiplier(self):
        base = xr.DataArray([50.0])  # avoids the 0-100 clip in either direction
        scaled = apply_moon_phase_multiplier(base, 0.0)
        assert float(scaled.values[0]) / float(base.values[0]) == pytest.approx(1.2)

    def test_full_moon_illumination_gives_0_8x_multiplier(self):
        base = xr.DataArray([50.0])
        scaled = apply_moon_phase_multiplier(base, 1.0)
        assert float(scaled.values[0]) / float(base.values[0]) == pytest.approx(0.8)

    @pytest.mark.parametrize("illumination", [0.0, 0.25, 0.5, 0.75, 1.0])
    def test_matches_documented_linear_formula(self, illumination):
        base = xr.DataArray([50.0])
        scaled = apply_moon_phase_multiplier(base, illumination)
        expected_multiplier = (
            config.MOON_MULTIPLIER_MAX
            - illumination * (config.MOON_MULTIPLIER_MAX - config.MOON_MULTIPLIER_MIN)
        )
        assert float(scaled.values[0]) / float(base.values[0]) == pytest.approx(expected_multiplier)

    def test_multiplier_is_monotonically_decreasing_with_illumination(self):
        base = xr.DataArray([50.0])
        illuminations = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]
        multipliers = [
            float(apply_moon_phase_multiplier(base, i).values[0]) / float(base.values[0])
            for i in illuminations
        ]
        assert all(
            multipliers[i] > multipliers[i + 1] for i in range(len(multipliers) - 1)
        ), f"multiplier should strictly decrease as illumination increases, got {multipliers}"

    def test_clips_to_100_when_boosted_score_would_exceed_it(self):
        base = xr.DataArray([90.0])
        scaled = apply_moon_phase_multiplier(base, 0.0)  # 90 * 1.2 = 108, must clip
        assert float(scaled.values[0]) == pytest.approx(100.0)

    def test_clips_to_0_at_lower_bound(self):
        base = xr.DataArray([-5.0])  # exercises the min-clip branch
        scaled = apply_moon_phase_multiplier(base, 1.0)
        assert float(scaled.values[0]) == pytest.approx(0.0)

    def test_raises_on_out_of_range_illumination(self):
        base = xr.DataArray([50.0])
        with pytest.raises(ValueError):
            apply_moon_phase_multiplier(base, 1.5)
        with pytest.raises(ValueError):
            apply_moon_phase_multiplier(base, -0.1)

    def test_sets_illumination_and_multiplier_attrs(self):
        base = xr.DataArray([50.0])
        base.attrs["description"] = "test"
        scaled = apply_moon_phase_multiplier(base, 0.25)
        assert scaled.attrs["moon_illumination_fraction"] == 0.25
        assert scaled.attrs["moon_phase_multiplier"] == pytest.approx(1.1)
        assert scaled.attrs["description"] == "test"


class TestSolunarPeriods:
    """
    `moon_phase_details()["solunar_periods"]` -- classic Knight's solunar
    theory major/minor feeding windows. Major periods (transit/antitransit)
    are a real numerical search over `astral.moon.elevation()` (see
    moon_phase.py's module docstring); minor periods (moonrise/moonset)
    reuse astral's existing rise/set calculation. This is a heuristic, not
    a precision ephemeris need, so these tests check structure/ordering
    and real-datetime-ness rather than asserting exact literal times
    against an unverifiable external reference (same philosophy as the
    illumination-range tests above).
    """

    _ALL_KEYS = ("major_1", "major_2", "minor_1", "minor_2")

    @pytest.mark.parametrize(
        "target_date",
        ["2026-07-22", "2023-08-21", "2024-02-29", "2025-12-31"],
    )
    def test_schema_has_all_four_periods(self, target_date):
        periods = moon_phase_details(target_date)["solunar_periods"]
        assert set(periods.keys()) == set(self._ALL_KEYS)

    def test_major_periods_are_type_major_and_minor_periods_are_type_minor(self):
        periods = moon_phase_details("2026-07-22")["solunar_periods"]
        assert periods["major_1"]["type"] == "major"
        assert periods["major_2"]["type"] == "major"
        assert periods["minor_1"]["type"] == "minor"
        assert periods["minor_2"]["type"] == "minor"

    def test_periods_use_real_datetimes_not_fabricated_strings(self):
        """
        Every non-null start/center/end must round-trip through
        datetime.fromisoformat() -- i.e. it's a real computed instant, not
        a placeholder string.
        """
        periods = moon_phase_details("2026-07-22")["solunar_periods"]
        for key in self._ALL_KEYS:
            period = periods[key]
            for field in ("start", "center", "end"):
                value = period[field]
                assert value is not None, f"{key}.{field} should be populated on a normal date"
                datetime.fromisoformat(value)  # raises if not a real ISO datetime

    def test_major_periods_are_exactly_two_hours_wide(self):
        periods = moon_phase_details("2026-07-22")["solunar_periods"]
        for key in ("major_1", "major_2"):
            period = periods[key]
            start = datetime.fromisoformat(period["start"])
            end = datetime.fromisoformat(period["end"])
            center = datetime.fromisoformat(period["center"])
            assert end - start == timedelta(hours=2)
            assert center - start == timedelta(hours=1)

    def test_minor_periods_are_exactly_one_hour_wide(self):
        periods = moon_phase_details("2026-07-22")["solunar_periods"]
        for key in ("minor_1", "minor_2"):
            period = periods[key]
            start = datetime.fromisoformat(period["start"])
            end = datetime.fromisoformat(period["end"])
            center = datetime.fromisoformat(period["center"])
            assert end - start == timedelta(hours=1)
            assert center - start == timedelta(minutes=30)

    def test_minor_periods_centered_on_real_moonrise_moonset(self):
        """
        minor_1/minor_2 must be centered on the *same* moonrise/moonset
        values already returned at the top level of moon_phase_details()
        -- not a separately (re)computed or approximated value.
        """
        details = moon_phase_details("2026-07-22")
        periods = details["solunar_periods"]
        assert periods["minor_1"]["center"] == details["moonrise"]
        assert periods["minor_2"]["center"] == details["moonset"]

    def test_major_periods_do_not_overlap_minor_periods(self):
        """
        Major and minor windows are centered on different real events
        (transit/antitransit vs. rise/set), which are never coincident in
        practice -- confirm the four windows for a normal day come out as
        four genuinely distinct, non-overlapping-by-construction periods
        rather than accidentally colliding due to a computation bug.
        """
        periods = moon_phase_details("2026-07-22")["solunar_periods"]
        intervals = [
            (datetime.fromisoformat(periods[key]["start"]), datetime.fromisoformat(periods[key]["end"]))
            for key in self._ALL_KEYS
        ]
        for i in range(len(intervals)):
            for j in range(i + 1, len(intervals)):
                start_i, end_i = intervals[i]
                start_j, end_j = intervals[j]
                assert start_i >= end_j or start_j >= end_i, (
                    f"{self._ALL_KEYS[i]} {intervals[i]} overlaps {self._ALL_KEYS[j]} {intervals[j]}"
                )

    def test_antitransit_is_roughly_half_a_lunar_day_after_transit(self):
        """
        Transit and antitransit should be separated by roughly half the
        moon's ~24h50m diurnal cycle (~12h25m), not e.g. 12h00m exactly
        (which would indicate the search fell back to a solar-day
        assumption instead of really finding the moon's elevation
        extrema).
        """
        periods = moon_phase_details("2026-07-22")["solunar_periods"]
        transit = datetime.fromisoformat(periods["major_1"]["center"])
        antitransit = datetime.fromisoformat(periods["major_2"]["center"])
        gap = abs((antitransit - transit).total_seconds()) / 3600.0
        # Allow generous tolerance either side of 12h25m -- this is a
        # sanity bound on the search, not a precision assertion.
        assert 11.0 < gap < 13.5

    def test_major_periods_always_present_even_when_moon_never_rises_or_sets(self):
        """
        Transit/antitransit are geometric elevation extrema that exist
        every day regardless of whether the moon crosses the horizon --
        confirm majors stay fully populated on a date where moonrise or
        moonset is a real `null` (graceful) case.
        """
        start = datetime(2026, 1, 1)
        found_a_null_day = False
        for i in range(400):
            target_date = (start + timedelta(days=i)).strftime("%Y-%m-%d")
            details = moon_phase_details(target_date)
            if details["moonrise"] is None or details["moonset"] is None:
                found_a_null_day = True
                periods = details["solunar_periods"]
                for key in ("major_1", "major_2"):
                    assert periods[key]["start"] is not None
                    assert periods[key]["center"] is not None
                    assert periods[key]["end"] is not None
                    assert "note" not in periods[key]
                break
        assert found_a_null_day, "expected at least one no-moonrise-or-moonset day in this range"

    def test_minor_period_is_null_with_note_when_moonrise_or_moonset_does_not_occur(self):
        """
        Mirrors the existing moonrise/moonset null convention: when the
        underlying event doesn't occur that day, the minor period's
        start/center/end are all null and a `note` explains why -- never
        fabricated.
        """
        start = datetime(2026, 1, 1)
        checked = False
        for i in range(400):
            target_date = (start + timedelta(days=i)).strftime("%Y-%m-%d")
            details = moon_phase_details(target_date)
            periods = details["solunar_periods"]
            if details["moonrise"] is None:
                assert periods["minor_1"]["start"] is None
                assert periods["minor_1"]["center"] is None
                assert periods["minor_1"]["end"] is None
                assert periods["minor_1"]["note"] == details["moonrise_note"]
                checked = True
                break
            if details["moonset"] is None:
                assert periods["minor_2"]["start"] is None
                assert periods["minor_2"]["center"] is None
                assert periods["minor_2"]["end"] is None
                assert periods["minor_2"]["note"] == details["moonset_note"]
                checked = True
                break
        assert checked, "expected at least one no-moonrise-or-moonset day in this range"

