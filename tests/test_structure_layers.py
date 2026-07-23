"""
Unit tests for bite_score/structure_layers.py -- v2 structure-scoring
primitives (shelf-break proximity, named-point Gaussian proximity,
combined structure_score, relative-vorticity computation, and
eddy_score).

Synthetic grids only -- no live data/network access, matching the
existing test suite's conventions (see conftest.py).
"""
import numpy as np
import pytest
import rioxarray  # noqa: F401  (registers the .rio accessor)
import xarray as xr

from bite_score import structure_layers


def _make_depth_grid(n=41):
    """
    A synthetic depth grid where depth increases linearly with longitude
    (west=shallow, east=deep), so the 100-200m contour band sits at a
    known, single east-west location -- lets tests assert exact distances
    to the band along the longitude axis.
    """
    lat = np.linspace(-27.0, -26.9, 5)  # a few rows, values irrelevant to this axis
    lon = np.linspace(153.0, 154.0, n)
    depth_1d = np.linspace(0.0, 1000.0, n)  # 0m (west) -> 1000m (east)
    depth = np.tile(depth_1d, (lat.size, 1))
    da = xr.DataArray(depth, coords={"lat": lat, "lon": lon}, dims=["lat", "lon"], name="depth")
    da = da.rio.write_crs("EPSG:4326")
    da = da.rio.set_spatial_dims(x_dim="lon", y_dim="lat")
    return da


class TestShelfBreakDistanceScore:
    def test_band_cells_score_one(self):
        depth = _make_depth_grid()
        score = structure_layers.shelf_break_distance_score(depth)
        band_mask = (depth.values >= 100.0) & (depth.values <= 200.0)
        assert band_mask.any()
        np.testing.assert_allclose(score.values[band_mask], 1.0)

    def test_land_stays_nan(self):
        depth = _make_depth_grid()
        depth = depth.where(depth > 0)  # simulate a land/nodata mask at depth==0
        score = structure_layers.shelf_break_distance_score(depth)
        assert np.isnan(score.values[np.isnan(depth.values)]).all()

    def test_score_decays_to_zero_by_inside_km_on_shallow_side(self):
        depth = _make_depth_grid()
        score = structure_layers.shelf_break_distance_score(
            depth, inside_km=5.0, outside_km=20.0
        )
        # Far west (shallowest) cells are well beyond the 5km "inside" ramp
        # from the contour band -> should be scored 0.
        assert score.values[:, 0] == pytest.approx(0.0, abs=1e-6)

    def test_score_decays_to_zero_by_outside_km_on_deep_side(self):
        depth = _make_depth_grid()
        score = structure_layers.shelf_break_distance_score(
            depth, inside_km=5.0, outside_km=20.0
        )
        # Far east (deepest) cells are well beyond the 20km "outside" ramp.
        assert score.values[:, -1] == pytest.approx(0.0, abs=1e-6)

    def test_asymmetric_falloff_deep_side_more_forgiving_than_shallow_side(self):
        """
        At the same real distance from the band, the deep (outside) side
        should score higher than the shallow (inside) side, since
        outside_km (20) > inside_km (5) per Michael's spec.
        """
        depth = _make_depth_grid()
        score = structure_layers.shelf_break_distance_score(
            depth, inside_km=5.0, outside_km=20.0
        )
        lon = depth["lon"].values
        band_mask = (depth.values[0] >= 100.0) & (depth.values[0] <= 200.0)
        band_lon = lon[band_mask].mean()

        # Pick a shallow-side and deep-side cell equidistant (in degrees,
        # close enough given the small lat range here) from the band, at
        # an offset (~0.15 deg ~ 15km) beyond the 5km "inside" ramp but
        # still within the 20km "outside" ramp -- shallow side should
        # already be fully ramped to 0, deep side should still be > 0.
        offset_deg = 0.15
        shallow_idx = np.argmin(np.abs(lon - (band_lon - offset_deg)))
        deep_idx = np.argmin(np.abs(lon - (band_lon + offset_deg)))
        assert score.values[0, deep_idx] > score.values[0, shallow_idx]


class TestPointGaussianProximityScore:
    def test_peak_score_at_nearest_cell_to_point(self):
        depth = _make_depth_grid()
        point_lat, point_lon = -26.95, 153.5
        score = structure_layers.point_gaussian_proximity_score(depth, point_lat, point_lon, sigma_km=15.0)

        flat_idx = np.argmax(score.values)
        max_idx = np.unravel_index(flat_idx, score.values.shape)
        # The max score should occur at the grid cell closest to the point.
        lat_grid, lon_grid = structure_layers._latlon_meshgrid(depth, "lat", "lon")
        dist_at_max = structure_layers._haversine_distance_km(
            lat_grid[max_idx], lon_grid[max_idx], point_lat, point_lon
        )
        all_dists = structure_layers._haversine_distance_km(lat_grid, lon_grid, point_lat, point_lon)
        assert dist_at_max == pytest.approx(all_dists.min())

    def test_score_decreases_monotonically_with_distance(self):
        depth = _make_depth_grid()
        point_lat, point_lon = -26.95, 153.0
        score = structure_layers.point_gaussian_proximity_score(depth, point_lat, point_lon, sigma_km=15.0)

        row = score.values[0]  # single latitude row -> distance increases with lon here
        # Row should be monotonically non-increasing as longitude moves away from point_lon.
        assert np.all(np.diff(row) <= 1e-9)

    def test_score_is_bounded_zero_to_one(self):
        depth = _make_depth_grid()
        score = structure_layers.point_gaussian_proximity_score(depth, -26.95, 153.5, sigma_km=15.0)
        assert score.values.min() >= 0.0
        assert score.values.max() <= 1.0 + 1e-9


class TestStructureScore:
    def test_combines_via_elementwise_max(self):
        depth = _make_depth_grid()
        shelf = structure_layers.shelf_break_distance_score(depth)
        points = structure_layers.named_feature_proximity_score(depth)
        combined = structure_layers.compute_structure_score(depth)

        np.testing.assert_allclose(combined.values, np.fmax(shelf.values, points.values))

    def test_output_bounded_zero_to_one(self):
        depth = _make_depth_grid()
        combined = structure_layers.compute_structure_score(depth)
        finite = combined.values[np.isfinite(combined.values)]
        assert finite.min() >= 0.0
        assert finite.max() <= 1.0 + 1e-9


def _make_rotation_field(omega: float, n: int = 21):
    """
    Synthetic solid-body-rotation current field u,v on a small lat/lon
    grid, centred at the grid's midpoint, following v_x=omega*y_index,
    style construction directly in metre-space so the expected zeta sign
    is unambiguous regardless of grid resolution.

    Uses u = -omega*y, v = omega*x (metres, y=north, x=east) which is the
    standard convention: omega > 0 is COUNTER-clockwise (as verified in
    structure_layers.compute_relative_vorticity's docstring), giving
    zeta = dv/dx - du/dy = 2*omega.
    """
    lat = np.linspace(-27.05, -26.95, n)
    lon = np.linspace(153.45, 153.55, n)

    lat_mid = lat.mean()
    y_m = (lat - lat_mid) * structure_layers.METRES_PER_DEGREE_LAT
    x_m = (lon - lon.mean()) * structure_layers.METRES_PER_DEGREE_LAT * np.cos(np.deg2rad(lat_mid))

    y_grid, x_grid = np.meshgrid(y_m, x_m, indexing="ij")
    u = -omega * y_grid
    v = omega * x_grid

    u_da = xr.DataArray(u, coords={"lat": lat, "lon": lon}, dims=["lat", "lon"], name="uo")
    v_da = xr.DataArray(v, coords={"lat": lat, "lon": lon}, dims=["lat", "lon"], name="vo")
    return u_da, v_da


class TestComputeRelativeVorticity:
    def test_counterclockwise_rotation_gives_positive_vorticity(self):
        u, v = _make_rotation_field(omega=1e-4)
        zeta = structure_layers.compute_relative_vorticity(u, v)
        interior = zeta.values[2:-2, 2:-2]  # avoid edge effects from np.gradient
        assert np.all(interior > 0)

    def test_clockwise_rotation_gives_negative_vorticity(self):
        u, v = _make_rotation_field(omega=-1e-4)
        zeta = structure_layers.compute_relative_vorticity(u, v)
        interior = zeta.values[2:-2, 2:-2]
        assert np.all(interior < 0)

    def test_vorticity_magnitude_approximately_two_omega(self):
        omega = 1e-4
        u, v = _make_rotation_field(omega=omega)
        zeta = structure_layers.compute_relative_vorticity(u, v)
        interior = zeta.values[2:-2, 2:-2]
        np.testing.assert_allclose(interior, 2.0 * omega, rtol=0.05)

    def test_sign_independent_of_input_lat_order(self):
        """Descending-lat input should give the identical (sorted) result."""
        u, v = _make_rotation_field(omega=1e-4)
        u_desc = u.isel(lat=slice(None, None, -1))
        v_desc = v.isel(lat=slice(None, None, -1))

        zeta_asc = structure_layers.compute_relative_vorticity(u, v)
        zeta_desc = structure_layers.compute_relative_vorticity(u_desc, v_desc)
        np.testing.assert_allclose(zeta_asc.values, zeta_desc.values)


class TestComputeEddyScore:
    def test_counterclockwise_plus_positive_ssha_scores_high(self):
        u, v = _make_rotation_field(omega=1e-4)  # counter-clockwise -> positive zeta
        zeta = structure_layers.compute_relative_vorticity(u, v)
        ssha = xr.full_like(zeta, fill_value=0.1)  # positive SSHA everywhere

        eddy = structure_layers.compute_eddy_score(zeta, ssha)
        interior = eddy.values[2:-2, 2:-2]
        assert np.all(interior > 0)

    def test_clockwise_plus_positive_ssha_scores_zero(self):
        u, v = _make_rotation_field(omega=-1e-4)  # clockwise -> negative zeta
        zeta = structure_layers.compute_relative_vorticity(u, v)
        ssha = xr.full_like(zeta, fill_value=0.1)

        eddy = structure_layers.compute_eddy_score(zeta, ssha)
        np.testing.assert_allclose(eddy.values, 0.0)

    def test_counterclockwise_plus_negative_ssha_scores_zero(self):
        u, v = _make_rotation_field(omega=1e-4)
        zeta = structure_layers.compute_relative_vorticity(u, v)
        ssha = xr.full_like(zeta, fill_value=-0.1)  # cold-core signature

        eddy = structure_layers.compute_eddy_score(zeta, ssha)
        np.testing.assert_allclose(eddy.values, 0.0)

    def test_eddy_score_bounded_zero_to_one(self):
        u, v = _make_rotation_field(omega=1e-4)
        zeta = structure_layers.compute_relative_vorticity(u, v)
        ssha = xr.full_like(zeta, fill_value=0.1)

        eddy = structure_layers.compute_eddy_score(zeta, ssha)
        assert eddy.values.min() >= 0.0
        assert eddy.values.max() <= 1.0 + 1e-9
