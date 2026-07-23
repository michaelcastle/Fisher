"""
End-to-end synthetic-grid tests for the "Lenigas" scoring pipeline:
`pipeline_lenigas.py::compute_distance_from_coast_km`,
`detect_eac_convergence_point`, and `compute_bite_score_lenigas`.

Synthetic fixtures only (no live Copernicus/NOAA/ERDDAP calls) -- builds
small lat/lon grids with a west-side "land" strip (negative depth) and an
eastward-deepening sea, following this suite's existing conventions (see
tests/test_structure_layers.py::_make_depth_grid).
"""
import numpy as np
import pytest
import rioxarray  # noqa: F401  (registers the .rio accessor)
import xarray as xr

from bite_score import config
from bite_score.pipeline_lenigas import (
    compute_bite_score_lenigas,
    compute_distance_from_coast_km,
    detect_eac_convergence_point,
)


def _make_grids(n_lat=6, n_lon=30, convergence_row=None):
    """
    A synthetic AOI_LENIGAS-like grid: a west-side land strip (depth<=0,
    lon indices 0-2) followed by sea deepening eastward up to ~3200m
    (spanning the full Lenigas depth-suitability ramp/plateau/decline
    range), SST held at the Lenigas bell-curve peak everywhere (isolates
    the other 5 factors' behavior in the end-to-end assertions below),
    and a current field whose per-row speed maximum ("EAC axis") sits at
    the same longitude index (15) on every row -- except optionally one
    `convergence_row`, where the along-axis u-component is flipped
    negative (westward), to exercise
    `detect_eac_convergence_point`'s single-row detection.
    """
    lat = np.linspace(-27.5, -26.5, n_lat)
    lon = np.linspace(153.0, 155.2, n_lon)

    depth_1d = np.linspace(-50.0, 3200.0, n_lon)
    depth_1d[:3] = -50.0  # a clear west-side land strip
    depth = np.tile(depth_1d, (n_lat, 1))
    depth_da = xr.DataArray(depth, coords={"lat": lat, "lon": lon}, dims=["lat", "lon"], name="depth")
    depth_da = depth_da.rio.write_crs(config.CRS)
    depth_da = depth_da.rio.set_spatial_dims(x_dim="lon", y_dim="lat")

    sst_da = xr.DataArray(
        np.full((n_lat, n_lon), config.SST_BELL_PEAK_C_LENIGAS),
        coords={"lat": lat, "lon": lon}, dims=["lat", "lon"], name="sst",
    )

    lon_idx = np.arange(n_lon)
    gaussian = np.exp(-((lon_idx - 15.0) ** 2) / (2.0 * 3.0**2))
    u = np.tile(gaussian, (n_lat, 1))
    if convergence_row is not None:
        u[convergence_row] = -gaussian
    v = np.full((n_lat, n_lon), -0.2)  # mild southward flow everywhere

    uo_da = xr.DataArray(u, coords={"lat": lat, "lon": lon}, dims=["lat", "lon"], name="uo")
    vo_da = xr.DataArray(v, coords={"lat": lat, "lon": lon}, dims=["lat", "lon"], name="vo")

    # Synthetic zos (sea surface height, metres): a real absolute
    # dynamic-topography-like field (always positive, ~0.32-0.90m,
    # matching Ash's real-data feasibility investigation) with a smooth
    # spatial gradient across longitude, so re-basing yields a genuine
    # spread of anomalies rather than a degenerate flat field.
    zos_1d = np.linspace(0.32, 0.90, n_lon)
    zos = np.tile(zos_1d, (n_lat, 1))
    zos_da = xr.DataArray(zos, coords={"lat": lat, "lon": lon}, dims=["lat", "lon"], name="zos")

    return sst_da, uo_da, vo_da, depth_da, zos_da


class TestComputeDistanceFromCoastKm:
    def test_land_stays_nan(self):
        _, _, _, depth, _ = _make_grids()
        distance = compute_distance_from_coast_km(depth)
        land_mask = depth.values <= 0
        assert np.isnan(distance.values[land_mask]).all()

    def test_distance_increases_moving_away_from_land(self):
        _, _, _, depth, _ = _make_grids()
        distance = compute_distance_from_coast_km(depth)
        row = distance.values[0]
        sea = row[np.isfinite(row)]
        # Monotonically non-decreasing while still east of the land strip
        # (the land strip is only on the west edge, so distance should
        # simply increase moving east across this synthetic grid).
        assert (np.diff(sea) >= -1e-6).all()

    def test_sea_cells_are_positive(self):
        _, _, _, depth, _ = _make_grids()
        distance = compute_distance_from_coast_km(depth)
        sea_mask = depth.values > 0
        assert (distance.values[sea_mask] > 0).all()


class TestDetectEacConvergencePoint:
    def test_no_westward_flow_returns_empty_list(self):
        _, uo, vo, _, _ = _make_grids(convergence_row=None)
        points = detect_eac_convergence_point(uo, vo)
        assert points == []

    def test_westward_flow_at_axis_is_detected(self):
        _, uo, vo, depth, _ = _make_grids(convergence_row=2)
        points = detect_eac_convergence_point(uo, vo)
        assert len(points) == 1
        detected_lat, detected_lon = points[0]
        assert detected_lat == pytest.approx(float(depth["lat"].values[2]))
        # The detected longitude should be at (or very near) the axis,
        # i.e. lon index 15.
        assert detected_lon == pytest.approx(float(depth["lon"].values[15]), abs=0.05)

    def test_returns_at_most_one_point(self):
        _, uo, vo, _, _ = _make_grids(convergence_row=3)
        points = detect_eac_convergence_point(uo, vo)
        assert len(points) <= 1


class TestComputeBiteScoreLenigas:
    def test_returns_bite_score_and_seven_layers(self):
        sst, uo, vo, depth, zos = _make_grids(convergence_row=2)
        bite_score, layer_scores = compute_bite_score_lenigas(
            sst, uo, vo, depth, zos, "2026-09-22", phase_age_days=14.0
        )
        assert set(layer_scores) == set(config.LAYER_WEIGHTS_LENIGAS)
        assert bite_score.name == "bite_score_lenigas"

    def test_bite_score_within_0_100_and_land_masked(self):
        sst, uo, vo, depth, zos = _make_grids(convergence_row=2)
        bite_score, _ = compute_bite_score_lenigas(
            sst, uo, vo, depth, zos, "2026-09-22", phase_age_days=14.0
        )
        finite = bite_score.values[np.isfinite(bite_score.values)]
        assert finite.size > 0
        assert finite.min() >= 0.0
        assert finite.max() <= 100.0

        land_mask = depth.values <= 0
        # bite_score is on depth's own grid (used as the alignment
        # reference), so land cells there should be NaN.
        assert np.isnan(bite_score.values[land_mask]).all()

    def test_seasonal_multiplier_reduces_off_season_score(self):
        sst, uo, vo, depth, zos = _make_grids(convergence_row=2)
        peak_season, _ = compute_bite_score_lenigas(
            sst, uo, vo, depth, zos, "2026-09-22", phase_age_days=14.0
        )
        off_season, _ = compute_bite_score_lenigas(
            sst, uo, vo, depth, zos, "2026-03-22", phase_age_days=14.0
        )
        peak_finite = peak_season.values[np.isfinite(peak_season.values)]
        off_finite = off_season.values[np.isfinite(off_season.values)]
        assert peak_finite.mean() > off_finite.mean()

    def test_phase_age_days_defaults_to_real_moon_phase_when_omitted(self):
        sst, uo, vo, depth, zos = _make_grids(convergence_row=2)
        # Should not raise even without an explicit phase_age_days -- it's
        # computed internally via moon_phase.py::moon_phase_details().
        bite_score, _ = compute_bite_score_lenigas(sst, uo, vo, depth, zos, "2026-07-22")
        finite = bite_score.values[np.isfinite(bite_score.values)]
        assert finite.size > 0

    def test_ssha_hotspot_layer_present_and_within_0_100(self):
        sst, uo, vo, depth, zos = _make_grids(convergence_row=2)
        _, layer_scores = compute_bite_score_lenigas(
            sst, uo, vo, depth, zos, "2026-07-22", phase_age_days=14.0
        )
        ssha_layer = layer_scores["ssha_hotspot_lenigas"]
        finite = ssha_layer.values[np.isfinite(ssha_layer.values)]
        assert finite.size > 0
        assert finite.min() >= 0.0
        assert finite.max() <= 100.0
