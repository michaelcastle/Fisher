"""
Tests for the "Lenigas" bite-score model's overlay/scoring functions:
config.LAYER_WEIGHTS_LENIGAS validity, continuous vorticity-sign
upwelling/downwelling scoring, EAC-axis-position zone scoring (via the
new continuous signed-distance-from-axis helper), EAC-convergence
Gaussian scoring (present + absent-point fallback), `weighted_overlay_lenigas`
WLC combination, and the seasonal + asymmetric moon-phase multipliers.

Synthetic fixtures only (no live Copernicus/NOAA calls), reusing the
existing `reference_grid` fixture from conftest.py the same way
test_overlay_v2.py already does (align_to_reference doesn't care which
AOI a synthetic grid's coordinates happen to come from).
"""
import numpy as np
import pytest
import rioxarray  # noqa: F401  (registers the .rio accessor)
import xarray as xr

from bite_score import config
from bite_score.normalization_lenigas import (
    compute_ssha_anomaly_cm_lenigas,
    score_ssha_hotspot_lenigas,
)
from bite_score.overlay_lenigas import (
    apply_moon_phase_multiplier_lenigas,
    apply_seasonal_multiplier_lenigas,
    compute_signed_distance_from_eac_axis_km,
    score_eac_axis_position_lenigas,
    score_eac_convergence_lenigas,
    score_upwelling_downwelling_lenigas,
    weighted_overlay_lenigas,
)


def _grid(values, lat=None, lon=None, name="value", with_crs=False):
    lat = np.linspace(-28.0, -26.0, values.shape[0]) if lat is None else lat
    lon = np.linspace(153.0, 154.0, values.shape[1]) if lon is None else lon
    da = xr.DataArray(values, coords={"lat": lat, "lon": lon}, dims=["lat", "lon"], name=name)
    if with_crs:
        da = da.rio.write_crs(config.CRS)
        da = da.rio.set_spatial_dims(x_dim="lon", y_dim="lat")
    return da


class TestLayerWeightsLenigasConfig:
    def test_weights_sum_to_one(self):
        assert np.isclose(sum(config.LAYER_WEIGHTS_LENIGAS.values()), 1.0)

    def test_includes_all_seven_lenigas_factors(self):
        expected = {
            "sst_bell_lenigas", "depth_suitability_lenigas", "distance_offshore",
            "upwelling_downwelling", "eac_axis_position", "eac_convergence",
            "ssha_hotspot_lenigas",
        }
        assert set(config.LAYER_WEIGHTS_LENIGAS) == expected

    def test_wind_is_not_a_weighted_factor(self):
        assert not any("wind" in key for key in config.LAYER_WEIGHTS_LENIGAS)

    def test_ssha_hotspot_weight_is_0_10(self):
        assert config.LAYER_WEIGHTS_LENIGAS["ssha_hotspot_lenigas"] == pytest.approx(0.10)

    def test_original_six_weights_rescaled_by_0_90(self):
        # 0.15*0.90=0.135, 0.20*0.90=0.18, 0.10*0.90=0.09, 0.15*0.90=0.135,
        # 0.20*0.90=0.18, 0.20*0.90=0.18 -- see config.py's comment above
        # LAYER_WEIGHTS_LENIGAS for the full arithmetic.
        expected = {
            "sst_bell_lenigas": 0.135,
            "depth_suitability_lenigas": 0.18,
            "distance_offshore": 0.09,
            "upwelling_downwelling": 0.135,
            "eac_axis_position": 0.18,
            "eac_convergence": 0.18,
        }
        for key, value in expected.items():
            assert config.LAYER_WEIGHTS_LENIGAS[key] == pytest.approx(value)


class TestScoreUpwellingDownwellingLenigas:
    def test_zero_vorticity_scores_neutral_half(self):
        zeta = _grid(np.zeros((3, 3)), name="zeta")
        score = score_upwelling_downwelling_lenigas(zeta)
        np.testing.assert_allclose(score.values, 0.5, atol=1e-9)

    def test_negative_vorticity_upwelling_scores_above_half(self):
        # Negative zeta = clockwise = SH-cyclonic = upwelling-favorable
        # (structure_layers.py::compute_relative_vorticity's verified sign
        # convention) -> should score ABOVE neutral, approaching 1.0 for
        # strongly negative zeta.
        zeta = _grid(np.array([[-1e-5, -1e-4]] * 3), name="zeta")
        score = score_upwelling_downwelling_lenigas(zeta)
        assert (score.values > 0.5).all()
        assert score.values[0, 1] > score.values[0, 0]  # stronger negative -> closer to 1.0

    def test_positive_vorticity_downwelling_scores_below_half(self):
        zeta = _grid(np.array([[1e-5, 1e-4]] * 3), name="zeta")
        score = score_upwelling_downwelling_lenigas(zeta)
        assert (score.values < 0.5).all()

    def test_score_stays_within_0_and_1(self):
        zeta = _grid(np.array([[-1.0, 1.0], [-1e-3, 1e-3]]), name="zeta")
        score = score_upwelling_downwelling_lenigas(zeta)
        assert score.values.min() >= 0.0
        assert score.values.max() <= 1.0

    def test_nan_stays_nan(self):
        zeta = _grid(np.array([[np.nan, 0.0], [0.0, 0.0]]), name="zeta")
        score = score_upwelling_downwelling_lenigas(zeta)
        assert np.isnan(score.values[0, 0])


class TestEacAxisPositionScoring:
    def _axis_lon(self, lat_vals, axis_value=153.5):
        return xr.DataArray(
            np.full(lat_vals.size, axis_value), coords={"lat": lat_vals}, dims=["lat"], name="eac_axis_lon"
        )

    def test_west_of_axis_scores_west_score(self):
        lat = np.linspace(-28.0, -26.0, 2)
        lon = np.array([153.0, 153.5])  # 153.0 is west of the 153.5 axis
        grid = _grid(np.full((2, 2), 100.0), lat=lat, lon=lon, name="ref")
        axis_lon = self._axis_lon(lat)
        x_km = compute_signed_distance_from_eac_axis_km(grid, axis_lon)
        assert (x_km.values[:, 0] < 0).all()
        score = score_eac_axis_position_lenigas(x_km)
        np.testing.assert_allclose(score.values[:, 0], config.EAC_AXIS_WEST_SCORE / 100.0)

    def test_slack_zone_scores_maximum(self):
        lat = np.array([-27.0])
        axis_lon = self._axis_lon(lat, axis_value=153.0)
        # ~25km east of the axis at this latitude -> within the 15-40km slack zone.
        km_per_deg = 111.32 * np.cos(np.deg2rad(-27.0))
        lon_offset_deg = 25.0 / km_per_deg
        grid = _grid(np.full((1, 1), 100.0), lat=lat, lon=np.array([153.0 + lon_offset_deg]), name="ref")
        x_km = compute_signed_distance_from_eac_axis_km(grid, axis_lon)
        score = score_eac_axis_position_lenigas(x_km)
        assert score.values[0, 0] == pytest.approx(config.EAC_AXIS_SLACK_SCORE / 100.0, abs=1e-6)

    def test_far_east_scores_fade_score(self):
        lat = np.array([-27.0])
        axis_lon = self._axis_lon(lat, axis_value=153.0)
        km_per_deg = 111.32 * np.cos(np.deg2rad(-27.0))
        lon_offset_deg = 150.0 / km_per_deg  # far beyond the 80km fade boundary
        grid = _grid(np.full((1, 1), 100.0), lat=lat, lon=np.array([153.0 + lon_offset_deg]), name="ref")
        x_km = compute_signed_distance_from_eac_axis_km(grid, axis_lon)
        score = score_eac_axis_position_lenigas(x_km)
        assert score.values[0, 0] == pytest.approx(config.EAC_AXIS_FADE_SCORE / 100.0, abs=1e-6)

    def test_core_zone_ramps_between_west_and_core_score(self):
        lat = np.array([-27.0])
        axis_lon = self._axis_lon(lat, axis_value=153.0)
        km_per_deg = 111.32 * np.cos(np.deg2rad(-27.0))
        lon_offset_deg = 7.5 / km_per_deg  # halfway through the 0-15km core zone
        grid = _grid(np.full((1, 1), 100.0), lat=lat, lon=np.array([153.0 + lon_offset_deg]), name="ref")
        x_km = compute_signed_distance_from_eac_axis_km(grid, axis_lon)
        score = score_eac_axis_position_lenigas(x_km)
        west = config.EAC_AXIS_WEST_SCORE / 100.0
        core = config.EAC_AXIS_CORE_SCORE / 100.0
        assert west < score.values[0, 0] < core


class TestScoreEacConvergenceLenigas:
    def test_scores_one_exactly_at_the_convergence_point(self, reference_grid):
        point = (float(reference_grid.lat.values[len(reference_grid.lat) // 2]),
                 float(reference_grid.lon.values[len(reference_grid.lon) // 2]))
        score = score_eac_convergence_lenigas(reference_grid, [point])
        lat_idx = len(reference_grid.lat) // 2
        lon_idx = len(reference_grid.lon) // 2
        assert score.values[lat_idx, lon_idx] == pytest.approx(1.0, abs=1e-6)

    def test_no_points_falls_back_to_flat_neutral(self, reference_grid):
        score = score_eac_convergence_lenigas(reference_grid, [])
        finite = score.values[np.isfinite(score.values)]
        assert finite.size > 0
        np.testing.assert_allclose(finite, config.EAC_CONVERGENCE_NEUTRAL_SCORE / 100.0)

    def test_land_stays_nan_in_neutral_fallback(self, reference_grid):
        score = score_eac_convergence_lenigas(reference_grid, [])
        land_mask = np.isnan(reference_grid.values)
        assert np.isnan(score.values[land_mask]).all()


class TestWeightedOverlayLenigas:
    def test_land_cells_are_nan_not_zero(self, reference_grid):
        depth_score = (reference_grid / reference_grid.max()).clip(min=0, max=1)
        one_layer = xr.full_like(depth_score, fill_value=0.5)

        bite_score, layer_scores = weighted_overlay_lenigas(
            one_layer, depth_score, one_layer, one_layer, one_layer, one_layer, one_layer
        )
        land_mask = np.isnan(reference_grid.values)
        assert np.isnan(bite_score.values[land_mask]).all()
        assert np.isfinite(bite_score.values[~land_mask]).all()

    def test_bite_score_within_0_100(self, reference_grid):
        depth_score = (reference_grid / reference_grid.max()).clip(min=0, max=1)
        one_layer = xr.full_like(depth_score, fill_value=0.8)

        bite_score, _ = weighted_overlay_lenigas(
            one_layer, depth_score, one_layer, one_layer, one_layer, one_layer, one_layer
        )
        finite = bite_score.values[np.isfinite(bite_score.values)]
        assert finite.size > 0
        assert finite.min() >= 0.0
        assert finite.max() <= 100.0

    def test_all_layers_maxed_reaches_100(self, reference_grid):
        depth_score = (reference_grid / reference_grid.max()).clip(min=0, max=1)
        one_layer = xr.full_like(depth_score, fill_value=1.0)

        bite_score, _ = weighted_overlay_lenigas(
            one_layer, depth_score, one_layer, one_layer, one_layer, one_layer, one_layer
        )
        finite = bite_score.values[np.isfinite(bite_score.values)]
        assert finite.max() == pytest.approx(100.0, abs=1e-6)

    def test_includes_ssha_hotspot_lenigas_in_layer_scores(self, reference_grid):
        depth_score = (reference_grid / reference_grid.max()).clip(min=0, max=1)
        one_layer = xr.full_like(depth_score, fill_value=0.8)

        _, layer_scores = weighted_overlay_lenigas(
            one_layer, depth_score, one_layer, one_layer, one_layer, one_layer, one_layer
        )
        assert "ssha_hotspot_lenigas" in layer_scores

    def test_weights_not_summing_to_one_raises(self, reference_grid):
        depth_score = (reference_grid / reference_grid.max()).clip(min=0, max=1)
        one_layer = xr.full_like(depth_score, fill_value=0.5)
        bad_weights = {
            "sst_bell_lenigas": 0.5, "depth_suitability_lenigas": 0.5, "distance_offshore": 0.5,
            "upwelling_downwelling": 0.5, "eac_axis_position": 0.5, "eac_convergence": 0.5,
            "ssha_hotspot_lenigas": 0.5,
        }
        with pytest.raises(ValueError):
            weighted_overlay_lenigas(
                one_layer, depth_score, one_layer, one_layer, one_layer, one_layer, one_layer,
                weights=bad_weights,
            )


class TestComputeSshaAnomalyCmLenigas:
    def test_rebased_anomaly_has_zero_spatial_mean(self):
        # Real zos is always positive/absolute (never zero-centered) --
        # re-basing must recover an exact zero spatial mean.
        zos = _grid(np.array([[0.32, 0.45], [0.60, 0.90]]), name="zos")
        anomaly = compute_ssha_anomaly_cm_lenigas(zos)
        assert anomaly.values.mean() == pytest.approx(0.0, abs=1e-9)

    def test_converts_metres_to_cm(self):
        # A uniform 0.10m offset from the mean should re-base to exactly
        # +-10cm (metres -> cm conversion, since zos is in metres).
        zos = _grid(np.array([[0.40, 0.60]]), name="zos")
        anomaly = compute_ssha_anomaly_cm_lenigas(zos)
        np.testing.assert_allclose(anomaly.values, [[-10.0, 10.0]], atol=1e-9)

    def test_nan_stays_nan(self):
        zos = _grid(np.array([[np.nan, 0.5], [0.5, 0.5]]), name="zos")
        anomaly = compute_ssha_anomaly_cm_lenigas(zos)
        assert np.isnan(anomaly.values[0, 0])


class TestScoreSshaHotspotLenigas:
    def _anomaly_grid(self, n=100):
        # A wide, evenly-spread synthetic anomaly distribution so every
        # percentile bucket is populated.
        values = np.linspace(-25.0, 25.0, n).reshape(10, 10)
        return _grid(values, lat=np.linspace(-28.0, -26.0, 10), lon=np.linspace(153.0, 154.0, 10), name="anomaly")

    def test_score_stays_within_0_and_1(self):
        anomaly = self._anomaly_grid()
        for month in range(1, 13):
            score = score_ssha_hotspot_lenigas(anomaly, month)
            finite = score.values[np.isfinite(score.values)]
            assert finite.min() >= 0.0
            assert finite.max() <= 1.0

    def test_nan_stays_nan(self):
        anomaly = _grid(np.array([[np.nan, -5.0], [0.0, 5.0]]), name="anomaly")
        score = score_ssha_hotspot_lenigas(anomaly, month=1)
        assert np.isnan(score.values[0, 0])

    def test_peaks_at_upwelling_biased_percentile_not_symmetric(self):
        """
        Kane's shape fix: the score-vs-percentile curve is a single peak
        biased toward the LOW-percentile (upwelling) side of the
        distribution, monotonically declining toward BOTH tails -- NOT a
        symmetric curve centered on the 50th percentile. For every
        seasonal table, the percentile bucket where the max score is
        reached should sit below the 50th percentile.
        """
        percentiles = np.array(config.SSHA_HOTSPOT_PERCENTILES_LENIGAS, dtype="float64")
        for anchors in (
            config.SSHA_HOTSPOT_SCORES_DEFAULT_LENIGAS,
            config.SSHA_HOTSPOT_SCORES_WINTER_LENIGAS,
            config.SSHA_HOTSPOT_SCORES_PEAK_LENIGAS,
        ):
            anchors = np.array(anchors, dtype="float64")
            peak_idx = int(np.argmax(anchors))
            assert percentiles[peak_idx] < 50.0

    def test_winter_month_uses_winter_table(self):
        anomaly = self._anomaly_grid()
        score_winter = score_ssha_hotspot_lenigas(anomaly, month=7)
        score_default = score_ssha_hotspot_lenigas(anomaly, month=1)
        # The two tables genuinely differ (winter widens the favorable
        # upwelling band), so scores should not be identical everywhere.
        assert not np.allclose(
            score_winter.values[np.isfinite(score_winter.values)],
            score_default.values[np.isfinite(score_default.values)],
        )

    def test_peak_season_month_uses_peak_table(self):
        anomaly = self._anomaly_grid()
        score_peak = score_ssha_hotspot_lenigas(anomaly, month=11)
        score_default = score_ssha_hotspot_lenigas(anomaly, month=1)
        assert not np.allclose(
            score_peak.values[np.isfinite(score_peak.values)],
            score_default.values[np.isfinite(score_default.values)],
        )


class TestApplySeasonalMultiplierLenigas:
    def test_peak_season_september_uses_1_0_multiplier(self, reference_grid):
        bite_score = xr.full_like(reference_grid, fill_value=80.0)
        scaled = apply_seasonal_multiplier_lenigas(bite_score, "2026-09-15")
        finite = scaled.values[np.isfinite(scaled.values)]
        np.testing.assert_allclose(finite, 80.0)

    def test_off_season_march_uses_0_3_multiplier(self, reference_grid):
        bite_score = xr.full_like(reference_grid, fill_value=80.0)
        scaled = apply_seasonal_multiplier_lenigas(bite_score, "2026-03-15")
        finite = scaled.values[np.isfinite(scaled.values)]
        np.testing.assert_allclose(finite, 24.0)  # 80 * 0.3

    def test_matches_config_table_for_every_month(self, reference_grid):
        bite_score = xr.full_like(reference_grid, fill_value=100.0)
        for month, multiplier in config.SEASONAL_MULTIPLIER_LENIGAS.items():
            date = f"2026-{month:02d}-10"
            scaled = apply_seasonal_multiplier_lenigas(bite_score, date)
            finite = scaled.values[np.isfinite(scaled.values)]
            expected = min(100.0 * multiplier, 100.0)
            np.testing.assert_allclose(finite, expected)


class TestApplyMoonPhaseMultiplierLenigas:
    def test_full_moon_scores_low_multiplier(self, reference_grid):
        bite_score = xr.full_like(reference_grid, fill_value=80.0)
        scaled = apply_moon_phase_multiplier_lenigas(bite_score, phase_age_days=14.0)  # exact full moon
        finite = scaled.values[np.isfinite(scaled.values)]
        # anchor score at d=0 is 15 -> multiplier = 0.8 + 0.15*0.4 = 0.86
        np.testing.assert_allclose(finite, 80.0 * 0.86, atol=1e-6)

    def test_lead_up_to_full_moon_scores_higher_than_after(self, reference_grid):
        """
        Kane's spec/Michael's decision #6: the model is explicitly
        ASYMMETRIC around full moon -- a few days BEFORE full moon (d=-3)
        should score much higher (multiplier closer to 1.2x) than the
        equivalent number of days AFTER (d=+3, multiplier=1.0x), not a
        mirror image.
        """
        bite_score = xr.full_like(reference_grid, fill_value=50.0)
        before = apply_moon_phase_multiplier_lenigas(bite_score, phase_age_days=11.0)  # d = 11-14 = -3
        after = apply_moon_phase_multiplier_lenigas(bite_score, phase_age_days=17.0)  # d = 17-14 = +3
        before_val = before.values[np.isfinite(before.values)][0]
        after_val = after.values[np.isfinite(after.values)][0]
        assert before_val > after_val

    def test_baseline_anchor_score_50_is_exact_1x_noop(self, reference_grid):
        # d=+3 anchor score is 50 -> should be an exact no-op multiplier.
        bite_score = xr.full_like(reference_grid, fill_value=63.0)
        scaled = apply_moon_phase_multiplier_lenigas(bite_score, phase_age_days=17.0)
        finite = scaled.values[np.isfinite(scaled.values)]
        np.testing.assert_allclose(finite, 63.0, atol=1e-6)

    def test_multiplier_stays_within_0_8_and_1_2_bounds(self, reference_grid):
        bite_score = xr.full_like(reference_grid, fill_value=50.0)
        for phase_age_days in np.linspace(0.0, 27.9, 20):
            scaled = apply_moon_phase_multiplier_lenigas(bite_score, phase_age_days=phase_age_days)
            finite = scaled.values[np.isfinite(scaled.values)]
            assert (finite >= 50.0 * 0.8 - 1e-6).all()
            assert (finite <= 50.0 * 1.2 + 1e-6).all()
