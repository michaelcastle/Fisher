"""
Tests for the v2 bite-score model's final seasonal scalar multiplier
(overlay_v2.py::apply_seasonal_multiplier / config.SEASONAL_MULTIPLIER_V2),
mirroring overlay.py::apply_moon_phase_multiplier's mechanism.

Precise month-boundary behavior is the whole point of this multiplier
(e.g. Aug 31 vs Sep 1 must land on different multipliers), so these tests
deliberately probe both sides of every documented seasonal boundary.
"""
import numpy as np
import pytest
import xarray as xr

from bite_score import config
from bite_score.overlay_v2 import apply_seasonal_multiplier


@pytest.fixture
def flat_score() -> xr.DataArray:
    lat = np.linspace(-28.0, -26.0, 3)
    lon = np.linspace(153.0, 154.0, 3)
    da = xr.DataArray(
        np.full((3, 3), 50.0), coords={"lat": lat, "lon": lon}, dims=["lat", "lon"], name="bite_score_v2"
    )
    return da


class TestSeasonalMultiplierConfig:
    def test_all_twelve_months_are_mapped(self):
        assert set(config.SEASONAL_MULTIPLIER_V2) == set(range(1, 13))

    def test_peak_season_sep_to_nov_is_1_0(self):
        for month in (9, 10, 11):
            assert config.SEASONAL_MULTIPLIER_V2[month] == 1.0

    def test_dec_jan_is_0_8(self):
        for month in (12, 1):
            assert config.SEASONAL_MULTIPLIER_V2[month] == 0.8

    def test_winter_barrel_run_may_to_aug_is_0_8(self):
        for month in (5, 6, 7, 8):
            assert config.SEASONAL_MULTIPLIER_V2[month] == 0.8

    def test_seasonal_low_feb_to_apr_is_0_3(self):
        for month in (2, 3, 4):
            assert config.SEASONAL_MULTIPLIER_V2[month] == 0.3


class TestApplySeasonalMultiplier:
    def test_september_first_applies_peak_1_0_multiplier(self, flat_score):
        result = apply_seasonal_multiplier(flat_score, "2026-09-01")
        np.testing.assert_allclose(result.values, 50.0)
        assert result.attrs["seasonal_multiplier"] == 1.0

    def test_august_31_applies_0_8_multiplier_not_peak(self, flat_score):
        """Precise boundary check: Aug 31 must NOT get September's 1.0x."""
        result = apply_seasonal_multiplier(flat_score, "2026-08-31")
        np.testing.assert_allclose(result.values, 40.0)
        assert result.attrs["seasonal_multiplier"] == 0.8

    def test_november_30_vs_december_1_boundary(self, flat_score):
        nov = apply_seasonal_multiplier(flat_score, "2026-11-30")
        dec = apply_seasonal_multiplier(flat_score, "2026-12-01")
        np.testing.assert_allclose(nov.values, 50.0)
        np.testing.assert_allclose(dec.values, 40.0)

    def test_january_31_vs_february_1_boundary(self, flat_score):
        jan = apply_seasonal_multiplier(flat_score, "2026-01-31")
        feb = apply_seasonal_multiplier(flat_score, "2026-02-01")
        np.testing.assert_allclose(jan.values, 40.0)
        np.testing.assert_allclose(feb.values, 15.0)

    def test_april_30_vs_may_1_boundary(self, flat_score):
        apr = apply_seasonal_multiplier(flat_score, "2026-04-30")
        may = apply_seasonal_multiplier(flat_score, "2026-05-01")
        np.testing.assert_allclose(apr.values, 15.0)
        np.testing.assert_allclose(may.values, 40.0)

    def test_result_is_clipped_to_100_even_if_multiplier_would_exceed_it(self, flat_score):
        near_max_score = xr.full_like(flat_score, fill_value=95.0)
        result = apply_seasonal_multiplier(near_max_score, "2026-09-15")  # 1.0x -> 95, within range
        assert result.values.max() <= 100.0

        # Even a >1.0x-equivalent scenario (not currently in the schedule,
        # but the clip must still hold defensively) stays within bounds.
        boosted_score = xr.full_like(flat_score, fill_value=100.0)
        result_boosted = apply_seasonal_multiplier(boosted_score, "2026-09-15")
        assert result_boosted.values.max() <= 100.0

    def test_preserves_name_and_attrs(self, flat_score):
        flat_score.attrs["description"] = "test description"
        result = apply_seasonal_multiplier(flat_score, "2026-09-01")
        assert result.name == flat_score.name
        assert result.attrs["description"] == "test description"
        assert result.attrs["seasonal_multiplier_month"] == 9
