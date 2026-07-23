"""
Tests for the v2 bite-score model's normalization/overlay functions:
SST bell-curve+gradient weighted average, chlorophyll optimal-band,
`weighted_overlay_v2` (WLC combination + graceful degradation), and
structure-score reuse (config.STRUCTURE_FEATURES_V2 trimmed to the 2
real, bathymetrically-plausible features).

Synthetic fixtures only (no live Copernicus/NOAA calls) -- reuses the
existing `reference_grid`/`coarse_raster` fixtures from conftest.py.
"""
import numpy as np
import pytest
import xarray as xr

from bite_score import config
from bite_score.normalization_v2 import normalize_chl_band, normalize_sst_bell, normalize_sst_bell_v2
from bite_score.overlay_v2 import weighted_overlay_v2
from bite_score.structure_layers import compute_structure_score


class TestStructureFeaturesV2Config:
    def test_queensland_seamount_dropped(self):
        assert "queensland_seamount" not in config.STRUCTURE_FEATURES_V2

    def test_only_tweed_and_noosa_canyons_remain(self):
        assert set(config.STRUCTURE_FEATURES_V2) == {"tweed_canyon", "noosa_canyon"}

    def test_compute_structure_score_uses_trimmed_features_by_default(self, reference_grid):
        # Reuse of structure_layers.py::compute_structure_score is a pure
        # default-argument benefit -- no code change there was needed once
        # config.STRUCTURE_FEATURES_V2 dropped Queensland Seamount.
        score = compute_structure_score(reference_grid)
        assert score.shape == reference_grid.shape
        finite = score.values[np.isfinite(score.values)]
        assert finite.size > 0
        assert finite.min() >= 0.0
        assert finite.max() <= 1.0


class TestLayerWeightsV2Config:
    def test_layer_weights_v2_sum_to_one(self):
        assert np.isclose(sum(config.LAYER_WEIGHTS_V2.values()), 1.0)

    def test_layer_weights_v2_include_all_seven_v2_factors(self):
        expected = {
            "sst_bell", "chl_band", "current_velocity", "bathymetry",
            "mld_gradient", "structure_score", "eddy_score",
        }
        assert set(config.LAYER_WEIGHTS_V2) == expected


class TestNormalizeSstBell:
    def test_peaks_at_1_exactly_at_peak_temperature(self):
        sst = xr.DataArray(
            np.full((4, 4), config.SST_BELL_PEAK_C),
            coords={"lat": np.linspace(-28.0, -26.0, 4), "lon": np.linspace(153.0, 154.0, 4)},
            dims=["lat", "lon"],
            name="sst",
        )
        score = normalize_sst_bell(sst)
        np.testing.assert_allclose(score.values, 1.0, atol=1e-9)

    def test_score_decreases_moving_away_from_peak(self):
        lat = np.linspace(-28.0, -26.0, 4)
        lon = np.linspace(153.0, 154.0, 4)
        peak = config.SST_BELL_PEAK_C
        sst = xr.DataArray(
            np.array([[peak, peak + 1, peak + 3, peak + 6]] * 4),
            coords={"lat": lat, "lon": lon},
            dims=["lat", "lon"],
            name="sst",
        )
        score = normalize_sst_bell(sst)
        row = score.values[0]
        assert row[0] > row[1] > row[2] > row[3]

    def test_score_within_20_to_24_optimal_window_is_at_least_half_maximum(self):
        lat = np.linspace(-28.0, -26.0, 2)
        lon = np.linspace(153.0, 154.0, 2)
        sst = xr.DataArray(
            np.array([[20.0, 24.0], [22.0, 22.0]]),
            coords={"lat": lat, "lon": lon},
            dims=["lat", "lon"],
            name="sst",
        )
        score = normalize_sst_bell(sst)
        assert (score.values >= 0.49).all()

    def test_nan_input_stays_nan(self):
        lat = np.linspace(-28.0, -26.0, 2)
        lon = np.linspace(153.0, 154.0, 2)
        sst = xr.DataArray(
            np.array([[np.nan, 22.0], [15.0, 30.0]]),
            coords={"lat": lat, "lon": lon},
            dims=["lat", "lon"],
            name="sst",
        )
        score = normalize_sst_bell(sst)
        assert np.isnan(score.values[0, 0])


class TestNormalizeSstBellV2WeightedAverage:
    def test_combination_is_weighted_average_not_product(self):
        """
        Kane's explicit correction: bell x gradient must NOT be a raw
        product (which would crush a perfect bell score of 1.0 down to
        whatever the independent gradient score happens to be) -- it must
        be a weighted average, so a perfect bell score with a middling
        gradient score still lands roughly at their average, not their
        product.
        """
        lat = np.linspace(-28.0, -26.0, 4)
        lon = np.linspace(153.0, 154.0, 4)
        sst = xr.DataArray(
            np.full((4, 4), config.SST_BELL_PEAK_C),  # perfect bell score everywhere (1.0)
            coords={"lat": lat, "lon": lon},
            dims=["lat", "lon"],
            name="sst",
        )
        # A gradient field whose robust-minmax-normalized score is
        # guaranteed to land somewhere strictly between 0 and 1 (a linear
        # ramp of values, not all-equal), so it's neither 0 nor 1.
        sst_gradient = xr.DataArray(
            np.linspace(0.0, 1.0, 16).reshape(4, 4),
            coords={"lat": lat, "lon": lon},
            dims=["lat", "lon"],
            name="sst_gradient",
        )

        combined = normalize_sst_bell_v2(sst, sst_gradient)

        # If this were a PRODUCT, combined == 1.0 * gradient_score == gradient_score.
        # If this is a 50/50 WEIGHTED AVERAGE, combined == 0.5*1.0 + 0.5*gradient_score,
        # i.e. strictly greater than gradient_score everywhere gradient_score < 1.0.
        from bite_score.normalization import normalize_sst_gradient
        gradient_score = normalize_sst_gradient(sst_gradient)
        assert (combined.values > gradient_score.values - 1e-9).all()
        # And specifically NOT equal to a straight product of bell(=1)*gradient.
        assert not np.allclose(combined.values, gradient_score.values)

    def test_combination_is_within_0_and_1(self):
        lat = np.linspace(-28.0, -26.0, 4)
        lon = np.linspace(153.0, 154.0, 4)
        sst = xr.DataArray(
            np.linspace(15.0, 30.0, 16).reshape(4, 4),
            coords={"lat": lat, "lon": lon},
            dims=["lat", "lon"],
            name="sst",
        )
        sst_gradient = xr.DataArray(
            np.linspace(0.0, 2.0, 16).reshape(4, 4),
            coords={"lat": lat, "lon": lon},
            dims=["lat", "lon"],
            name="sst_gradient",
        )
        combined = normalize_sst_bell_v2(sst, sst_gradient)
        finite = combined.values[np.isfinite(combined.values)]
        assert finite.size > 0
        assert finite.min() >= 0.0
        assert finite.max() <= 1.0


class TestNormalizeChlBand:
    def test_ideal_band_scores_1(self):
        lat = np.linspace(-28.0, -26.0, 2)
        lon = np.linspace(153.0, 154.0, 2)
        chl = xr.DataArray(
            np.array([[0.1, 0.2], [0.3, 0.25]]),
            coords={"lat": lat, "lon": lon},
            dims=["lat", "lon"],
            name="chl",
        )
        score = normalize_chl_band(chl)
        np.testing.assert_allclose(score.values, 1.0, atol=1e-9)

    def test_barren_below_ramp_min_scores_0(self):
        lat = np.linspace(-28.0, -26.0, 2)
        lon = np.linspace(153.0, 154.0, 2)
        chl = xr.DataArray(
            np.array([[0.0, 0.02], [0.01, 0.0]]),
            coords={"lat": lat, "lon": lon},
            dims=["lat", "lon"],
            name="chl",
        )
        score = normalize_chl_band(chl)
        np.testing.assert_allclose(score.values, 0.0, atol=1e-9)

    def test_murky_above_ramp_max_scores_0(self):
        lat = np.linspace(-28.0, -26.0, 2)
        lon = np.linspace(153.0, 154.0, 2)
        chl = xr.DataArray(
            np.array([[0.6, 1.0], [0.51, 2.0]]),
            coords={"lat": lat, "lon": lon},
            dims=["lat", "lon"],
            name="chl",
        )
        score = normalize_chl_band(chl)
        np.testing.assert_allclose(score.values, 0.0, atol=1e-9)

    def test_ramp_between_barren_and_ideal_is_intermediate(self):
        lat = np.linspace(-28.0, -26.0, 2)
        lon = np.linspace(153.0, 154.0, 2)
        # Midway between CHL_BAND_RAMP_MIN (0.05) and CHL_BAND_IDEAL_MIN (0.1).
        midpoint = (config.CHL_BAND_RAMP_MIN + config.CHL_BAND_IDEAL_MIN) / 2.0
        chl = xr.DataArray(
            np.full((2, 2), midpoint),
            coords={"lat": lat, "lon": lon},
            dims=["lat", "lon"],
            name="chl",
        )
        score = normalize_chl_band(chl)
        assert (score.values > 0.0).all()
        assert (score.values < 1.0).all()


class TestWeightedOverlayV2:
    def test_land_cells_are_nan_not_zero(self, reference_grid):
        depth_score = (reference_grid / reference_grid.max()).clip(min=0, max=1)
        one_layer = xr.full_like(depth_score, fill_value=0.5)

        bite_score, layer_scores = weighted_overlay_v2(
            one_layer, one_layer, one_layer, one_layer, one_layer, depth_score
        )
        land_mask = np.isnan(reference_grid.values)
        assert np.isnan(bite_score.values[land_mask]).all()
        assert np.isfinite(bite_score.values[~land_mask]).all()

    def test_bite_score_is_within_0_100(self, reference_grid):
        depth_score = (reference_grid / reference_grid.max()).clip(min=0, max=1)
        one_layer = xr.full_like(depth_score, fill_value=0.8)

        bite_score, _ = weighted_overlay_v2(
            one_layer, one_layer, one_layer, one_layer, one_layer, depth_score
        )
        finite = bite_score.values[np.isfinite(bite_score.values)]
        assert finite.size > 0
        assert finite.min() >= 0.0
        assert finite.max() <= 100.0

    def test_graceful_degradation_without_mld_still_reaches_full_range(self, reference_grid):
        depth_score = (reference_grid / reference_grid.max()).clip(min=0, max=1)
        one_layer = xr.full_like(depth_score, fill_value=1.0)

        bite_score, layer_scores = weighted_overlay_v2(
            one_layer, one_layer, one_layer, one_layer, one_layer, depth_score, mld_score=None
        )
        finite = bite_score.values[np.isfinite(bite_score.values)]
        # All 6 present factors maxed out at 1.0 -> after rescaling the
        # missing mld_gradient weight back in, this should reach ~100, not
        # be permanently capped at (1 - mld_weight) * 100.
        assert finite.max() > 99.0
        assert "mld" not in layer_scores

    def test_mld_score_present_is_included_in_layer_scores(self, reference_grid, coarse_raster):
        depth_score = (reference_grid / reference_grid.max()).clip(min=0, max=1)
        one_layer = xr.full_like(depth_score, fill_value=0.5)
        mld_score = (coarse_raster / coarse_raster.max()).clip(min=0, max=1)

        bite_score, layer_scores = weighted_overlay_v2(
            one_layer, one_layer, one_layer, one_layer, one_layer, depth_score, mld_score=mld_score
        )
        assert "mld" in layer_scores

    def test_weights_not_summing_to_one_raises(self, reference_grid):
        depth_score = (reference_grid / reference_grid.max()).clip(min=0, max=1)
        one_layer = xr.full_like(depth_score, fill_value=0.5)
        bad_weights = {
            "sst_bell": 0.5, "chl_band": 0.5, "current_velocity": 0.5,
            "bathymetry": 0.5, "mld_gradient": 0.5, "structure_score": 0.5, "eddy_score": 0.5,
        }
        with pytest.raises(ValueError):
            weighted_overlay_v2(
                one_layer, one_layer, one_layer, one_layer, one_layer, depth_score, weights=bad_weights
            )
