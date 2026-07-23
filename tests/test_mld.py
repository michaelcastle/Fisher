"""
Real, runnable tests for the Mixed Layer Depth (MLD) integration:
`bite_score.data_ingestion.fetch_mld` (raw Copernicus fetch -- requires
live network/credentials, so only its signature is checked here, not a
live call) and `bite_score.overlay.weighted_overlay`'s optional
`mld_score` kwarg / graceful-degradation behavior (fully testable with
synthetic fixtures, no network needed).

Supersedes tests/test_mld_provisional.py, written before Ash's
`fetch_mld()` / Ripley's `weighted_overlay(..., mld_score=...)` wiring
landed. See:
  - .squad/decisions/inbox/ash-mld-moonphase.md
  - .squad/decisions/inbox/ripley-mld-moon-scoring.md
"""
import inspect

import numpy as np
import pytest
import xarray as xr

from bite_score import config
from bite_score.data_ingestion import fetch_mld
from bite_score.overlay import align_to_reference, weighted_overlay


def _uniform_layer(value: float) -> xr.DataArray:
    """
    A small, NaN-free synthetic raster with a single uniform value across
    the whole AOI -- used so weighted-sum arithmetic in weighted_overlay()
    can be asserted against an exact expected number instead of just a
    range, without any land-mask NaNs muddying the expected value.
    """
    lat = np.linspace(config.AOI["min_lat"], config.AOI["max_lat"], 6)
    lon = np.linspace(config.AOI["min_lon"], config.AOI["max_lon"], 6)
    da = xr.DataArray(
        np.full((6, 6), value), coords={"lat": lat, "lon": lon}, dims=["lat", "lon"]
    )
    da = da.rio.write_crs(config.CRS)
    da = da.rio.set_spatial_dims(x_dim="lon", y_dim="lat")
    return da


class TestFetchMldSignature:
    """
    fetch_mld() requires a live Copernicus Marine subset request (network +
    credentials, plus an unverified dataset-id assumption -- see Ash's
    decision doc) that this offline pass doesn't perform. This only checks
    the entry point exists with the expected signature, so a rename/removal
    is caught immediately rather than silently going undetected until the
    next live pipeline run.
    """

    def test_fetch_mld_exists_with_target_date_param(self):
        sig = inspect.signature(fetch_mld)
        assert list(sig.parameters) == ["target_date"]


class TestMldGradientAlignment:
    def test_mld_raster_aligns_to_reference_shape_dims_and_crs(self, reference_grid, coarse_raster):
        ref, (aligned,) = align_to_reference(reference_grid, coarse_raster)
        assert aligned.shape == ref.shape
        assert aligned.dims == ref.dims
        assert list(aligned.dims) == ["lat", "lon"]
        assert aligned.rio.crs == ref.rio.crs == config.CRS


class TestLayerWeightsConfig:
    def test_layer_weights_include_mld_gradient_and_sum_to_one(self):
        assert "mld_gradient" in config.LAYER_WEIGHTS
        assert np.isclose(sum(config.LAYER_WEIGHTS.values()), 1.0)


class TestWeightedOverlayMldGracefulDegradation:
    def test_without_mld_score_rescales_remaining_five_weights_to_one(self):
        """
        With mld_score absent, weights["mld_gradient"] must be dropped and
        the other 5 weights rescaled back up to sum to 1.0 -- a uniform
        0.6 input on every one of the 5 active layers should therefore
        land at exactly 60, not be capped below it by the "missing" 0.12
        mld weight.
        """
        depth_score = _uniform_layer(0.6)
        one_layer = _uniform_layer(0.6)

        bite_score, layer_scores = weighted_overlay(
            one_layer, one_layer, one_layer, one_layer, depth_score
        )
        assert "mld" not in layer_scores
        assert set(layer_scores) == {"sst", "chl", "current", "ssha", "bathymetry"}
        np.testing.assert_allclose(bite_score.values, 60.0, atol=1e-6)

    def test_with_mld_score_includes_mld_layer_and_no_rescale_needed(self):
        """
        With mld_score present, all 6 configured weights already sum to
        1.0 (no rescale factor needed) -- a uniform 0.6 input across all
        6 layers should also land at exactly 60.
        """
        depth_score = _uniform_layer(0.6)
        one_layer = _uniform_layer(0.6)
        mld_score = _uniform_layer(0.6)

        bite_score, layer_scores = weighted_overlay(
            one_layer, one_layer, one_layer, one_layer, depth_score, mld_score=mld_score
        )
        assert "mld" in layer_scores
        assert set(layer_scores) == {"sst", "chl", "current", "ssha", "bathymetry", "mld"}
        np.testing.assert_allclose(bite_score.values, 60.0, atol=1e-6)

    def test_strong_mld_signal_raises_score_relative_to_without_it(self):
        """
        Graceful degradation shouldn't just avoid crashing -- a strong MLD
        front signal present should visibly move the combined score
        relative to identical inputs without it (uniform 0.4 elsewhere).
        """
        depth_score = _uniform_layer(0.4)
        base_layer = _uniform_layer(0.4)
        strong_mld = _uniform_layer(1.0)

        bite_score_without, _ = weighted_overlay(
            base_layer, base_layer, base_layer, base_layer, depth_score
        )
        bite_score_with, _ = weighted_overlay(
            base_layer, base_layer, base_layer, base_layer, depth_score, mld_score=strong_mld
        )
        assert float(bite_score_with.mean()) > float(bite_score_without.mean())

    def test_land_masking_preserved_with_mld_present(self, reference_grid):
        depth_score = (reference_grid / np.nanmax(reference_grid.values)).clip(min=0, max=1)
        one_layer = xr.full_like(depth_score, fill_value=0.6)
        mld_score = xr.full_like(depth_score, fill_value=0.6)

        bite_score, _ = weighted_overlay(
            one_layer, one_layer, one_layer, one_layer, depth_score, mld_score=mld_score
        )
        land_mask = np.isnan(reference_grid.values)
        assert np.isnan(bite_score.values[land_mask]).all()
        assert np.isfinite(bite_score.values[~land_mask]).all()

    def test_bite_score_stays_within_0_100_with_mld_present(self, reference_grid):
        depth_score = (reference_grid / np.nanmax(reference_grid.values)).clip(min=0, max=1)
        one_layer = xr.full_like(depth_score, fill_value=0.8)
        mld_score = xr.full_like(depth_score, fill_value=0.9)

        bite_score, _ = weighted_overlay(
            one_layer, one_layer, one_layer, one_layer, depth_score, mld_score=mld_score
        )
        finite = bite_score.values[np.isfinite(bite_score.values)]
        assert finite.size > 0
        assert finite.min() >= 0.0
        assert finite.max() <= 100.0
