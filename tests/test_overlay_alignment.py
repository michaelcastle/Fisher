"""
Real, runnable tests against the EXISTING (already-landed) alignment/
normalization interface in overlay.py -- not provisional. These establish
a working baseline for the test scaffolding itself, and document the
exact grid-alignment contract any new raster layer (e.g. Ash's MLD layer)
must satisfy: same shape/dims as the reference grid after
`align_to_reference`, and NaN cells surviving through to the final
land-masked output rather than being silently coerced to 0.

No network/credentials needed -- everything here uses the synthetic
fixtures in conftest.py.
"""
import numpy as np
import xarray as xr
from rasterio.enums import Resampling

from bite_score.overlay import align_to_reference, weighted_overlay


class TestAlignToReference:
    def test_aligned_layer_matches_reference_shape_and_dims(self, reference_grid, coarse_raster):
        ref, (aligned,) = align_to_reference(reference_grid, coarse_raster)
        assert aligned.shape == ref.shape
        assert aligned.dims == ref.dims
        assert list(aligned.dims) == ["lat", "lon"]

    def test_aligned_layer_uses_reference_coordinates(self, reference_grid, coarse_raster):
        ref, (aligned,) = align_to_reference(reference_grid, coarse_raster)
        np.testing.assert_allclose(aligned["lat"].values, ref["lat"].values)
        np.testing.assert_allclose(aligned["lon"].values, ref["lon"].values)

    def test_bilinear_upsample_produces_finite_values_where_source_had_data(
        self, reference_grid, coarse_raster
    ):
        ref, (aligned,) = align_to_reference(
            reference_grid, coarse_raster, resampling=Resampling.bilinear
        )
        # The coarse source has no NaNs, so after upsampling onto the finer
        # reference grid, cells within the coarse grid's convex hull should
        # still be finite (not spuriously NaN'd out by the resampling step).
        assert np.isfinite(aligned.values).any()

    def test_all_nan_source_tile_does_not_crash_alignment(self, reference_grid):
        """
        Edge case: an entirely-missing/all-NaN input tile (e.g. a Copernicus
        fetch that returned an empty/degenerate subset) must not raise
        during alignment -- it should just propagate as an all-NaN aligned
        layer so callers can decide how to degrade gracefully.
        """
        all_nan = xr.full_like(reference_grid, fill_value=np.nan)
        ref, (aligned,) = align_to_reference(reference_grid, all_nan)
        assert aligned.shape == ref.shape
        assert np.isnan(aligned.values).all()

    def test_zero_overlap_tile_produces_all_nan_after_alignment(self, reference_grid):
        """
        Edge case: a source tile with real data but zero geographic overlap
        with the reference grid's AOI (e.g. a badly-clipped fetch) should
        align to an all-NaN result (no crash, no spurious extrapolated
        values) rather than silently misaligning data.
        """
        lat = np.linspace(10.0, 12.0, 4)  # nowhere near the real SEQ AOI
        lon = np.linspace(10.0, 12.0, 4)
        values = np.full((4, 4), 42.0)
        disjoint = xr.DataArray(
            values, coords={"lat": lat, "lon": lon}, dims=["lat", "lon"], name="disjoint"
        )
        disjoint = disjoint.rio.write_crs("EPSG:4326")
        disjoint = disjoint.rio.set_spatial_dims(x_dim="lon", y_dim="lat")

        ref, (aligned,) = align_to_reference(reference_grid, disjoint)
        assert aligned.shape == ref.shape
        assert np.isnan(aligned.values).all()


class TestWeightedOverlayLandMasking:
    def test_land_cells_are_nan_not_zero(self, reference_grid):
        """
        Regression guard for the previously-fixed "land outline never
        worked" bug (see repo memory): land cells (NaN in the depth
        reference grid) must stay NaN in the final bite_score output, not
        get silently zeroed by `.fillna(0)` during the weighted sum.
        """
        depth_score = reference_grid / reference_grid.max()  # fake 0-1 "suitability"
        one_layer = xr.full_like(depth_score, fill_value=0.5)

        bite_score, layer_scores = weighted_overlay(
            one_layer, one_layer, one_layer, one_layer, depth_score
        )
        land_mask = np.isnan(reference_grid.values)
        assert np.isnan(bite_score.values[land_mask]).all()
        assert np.isfinite(bite_score.values[~land_mask]).all()

    def test_bite_score_is_within_0_100(self, reference_grid):
        depth_score = (reference_grid / reference_grid.max()).clip(min=0, max=1)
        one_layer = xr.full_like(depth_score, fill_value=0.8)

        bite_score, _ = weighted_overlay(one_layer, one_layer, one_layer, one_layer, depth_score)
        finite = bite_score.values[np.isfinite(bite_score.values)]
        assert finite.size > 0
        assert finite.min() >= 0.0
        assert finite.max() <= 100.0
