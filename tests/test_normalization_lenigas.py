"""
Tests for the "Lenigas" bite-score model's normalization functions:
SST bell curve (peak=24.5C, sigma=1.3C), depth suitability (ramp-plateau-
decline: 500->1000->1500->3000m), and distance-offshore-from-coast
(ramp-plateau-decline: 40->60->80->100km).

Synthetic fixtures only (no live Copernicus/NOAA calls), following this
suite's existing conventions (see conftest.py / test_structure_layers.py):
dims named "lat"/"lon", CRS EPSG:4326 where relevant.
"""
import numpy as np
import pytest
import rioxarray  # noqa: F401  (registers the .rio accessor)
import xarray as xr

from bite_score import config
from bite_score.normalization_lenigas import (
    normalize_depth_suitability_lenigas,
    normalize_distance_offshore_lenigas,
    normalize_sst_bell_lenigas,
)


def _grid(values, lat=None, lon=None, name="value"):
    lat = np.linspace(-28.0, -26.0, values.shape[0]) if lat is None else lat
    lon = np.linspace(153.0, 154.0, values.shape[1]) if lon is None else lon
    da = xr.DataArray(values, coords={"lat": lat, "lon": lon}, dims=["lat", "lon"], name=name)
    return da


class TestNormalizeSstBellLenigas:
    def test_peaks_at_1_exactly_at_24_5c(self):
        sst = _grid(np.full((4, 4), config.SST_BELL_PEAK_C_LENIGAS), name="sst")
        score = normalize_sst_bell_lenigas(sst)
        np.testing.assert_allclose(score.values, 1.0, atol=1e-9)

    def test_score_at_23_and_26_is_roughly_half_maximum(self):
        # 23C and 26C are the edges of the notes' stated "23-26C" band;
        # sigma=1.3 was derived by treating that band as the curve's FWHM
        # around the 24.5C peak (see config.SST_BELL_SIGMA_C_LENIGAS's
        # docstring), so both edges should score close to 0.5.
        sst = _grid(np.array([[23.0, 26.0], [24.5, 24.5]]), name="sst")
        score = normalize_sst_bell_lenigas(sst)
        assert score.values[0, 0] == pytest.approx(0.5, abs=0.05)
        assert score.values[0, 1] == pytest.approx(0.5, abs=0.05)

    def test_score_decreases_moving_away_from_peak(self):
        peak = config.SST_BELL_PEAK_C_LENIGAS
        sst = _grid(np.array([[peak, peak + 1, peak + 3, peak + 6]] * 4), name="sst")
        score = normalize_sst_bell_lenigas(sst)
        row = score.values[0]
        assert row[0] > row[1] > row[2] > row[3]

    def test_nan_input_stays_nan(self):
        sst = _grid(np.array([[np.nan, 24.5], [20.0, 30.0]]), name="sst")
        score = normalize_sst_bell_lenigas(sst)
        assert np.isnan(score.values[0, 0])


class TestNormalizeDepthSuitabilityLenigas:
    def test_below_ramp_min_scores_zero(self):
        depth = _grid(np.full((2, 2), 300.0), name="depth")
        score = normalize_depth_suitability_lenigas(depth)
        np.testing.assert_allclose(score.values, 0.0)

    def test_plateau_1000_to_1500_scores_one(self):
        depth = _grid(np.array([[1000.0, 1200.0], [1400.0, 1500.0]]), name="depth")
        score = normalize_depth_suitability_lenigas(depth)
        np.testing.assert_allclose(score.values, 1.0)

    def test_ramps_up_between_500_and_1000(self):
        depth = _grid(np.array([[500.0, 750.0], [900.0, 1000.0]]), name="depth")
        score = normalize_depth_suitability_lenigas(depth)
        flat = score.values.flatten()
        assert flat[0] == pytest.approx(0.0, abs=1e-6)
        assert flat[3] == pytest.approx(1.0, abs=1e-6)
        assert flat[0] < flat[1] < flat[2] < flat[3]

    def test_declines_after_1500_and_reaches_zero_by_3000(self):
        depth = _grid(np.array([[1500.0, 2000.0], [2500.0, 3000.0]]), name="depth")
        score = normalize_depth_suitability_lenigas(depth)
        flat = score.values.flatten()
        assert flat[0] == pytest.approx(1.0, abs=1e-6)
        assert flat[3] == pytest.approx(0.0, abs=1e-6)
        assert flat[0] > flat[1] > flat[2] > flat[3]

    def test_beyond_3000m_stays_zero_not_negative(self):
        depth = _grid(np.full((2, 2), 4800.0), name="depth")  # real abyssal depth in this AOI
        score = normalize_depth_suitability_lenigas(depth)
        np.testing.assert_allclose(score.values, 0.0)

    def test_land_depth_zero_or_below_is_nan(self):
        depth = _grid(np.array([[-5.0, 0.0], [1200.0, 1200.0]]), name="depth")
        score = normalize_depth_suitability_lenigas(depth)
        assert np.isnan(score.values[0, 0])
        assert np.isnan(score.values[0, 1])
        assert not np.isnan(score.values[1, 0])


class TestNormalizeDistanceOffshoreLenigas:
    def test_below_40km_scores_zero(self):
        distance = _grid(np.full((2, 2), 10.0), name="distance_km")
        score = normalize_distance_offshore_lenigas(distance)
        np.testing.assert_allclose(score.values, 0.0)

    def test_plateau_60_to_80km_scores_one(self):
        distance = _grid(np.array([[60.0, 70.0], [75.0, 80.0]]), name="distance_km")
        score = normalize_distance_offshore_lenigas(distance)
        np.testing.assert_allclose(score.values, 1.0)

    def test_declines_after_80km_and_reaches_zero_by_100km(self):
        distance = _grid(np.array([[80.0, 90.0], [95.0, 100.0]]), name="distance_km")
        score = normalize_distance_offshore_lenigas(distance)
        flat = score.values.flatten()
        assert flat[0] == pytest.approx(1.0, abs=1e-6)
        assert flat[3] == pytest.approx(0.0, abs=1e-6)
        assert flat[0] > flat[1] > flat[2] > flat[3]

    def test_beyond_100km_stays_zero(self):
        distance = _grid(np.full((2, 2), 200.0), name="distance_km")
        score = normalize_distance_offshore_lenigas(distance)
        np.testing.assert_allclose(score.values, 0.0)

    def test_nan_distance_stays_nan(self):
        distance = _grid(np.array([[np.nan, 70.0], [70.0, 70.0]]), name="distance_km")
        score = normalize_distance_offshore_lenigas(distance)
        assert np.isnan(score.values[0, 0])
