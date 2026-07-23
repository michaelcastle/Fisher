"""
Real, runnable tests for the "Lenigas" scoring model's new pieces:
  - `bite_score.data_ingestion_lenigas.fetch_wind_data_lenigas` (NOAA
    ERDDAP wind ingestion -- HTTP mocked via monkeypatch at the same
    `_download_erddap_url` boundary the rest of this codebase's ERDDAP
    fetchers use, so no live network call happens in this test run, but
    the real URL-building/fallback/parsing logic is fully exercised).
  - `bite_score.eac_axis` (EAC axis detection + east/west classification,
    and the vorticity-sign upwelling/downwelling classifier) -- fully
    synthetic, no network needed.

See .squad/decisions/inbox/ash-lenigas-implementation.md for the live
verification of the wind data source itself (real NOAA ERDDAP fetches,
run outside pytest, that led to the erdQCwindproducts7day choice).
"""
import urllib.error

import numpy as np
import pytest
import xarray as xr

from bite_score import config, eac_axis
from bite_score.data_ingestion_lenigas import fetch_wind_data_lenigas
from bite_score.structure_layers import METRES_PER_DEGREE_LAT, compute_relative_vorticity


def _write_synthetic_wind_nc(path: str, n_lat: int = 4, n_lon: int = 5) -> None:
    """A small, real-shaped synthetic NetCDF matching erdQCwindproducts7day's
    actual schema (time, altitude, latitude, longitude dims; wind_speed/
    wind_direction/wind_u/wind_v variables), used to stand in for a live
    ERDDAP download in tests."""
    lat = np.linspace(config.AOI_V2["min_lat"], config.AOI_V2["max_lat"], n_lat)
    lon = np.linspace(config.AOI_V2["min_lon"], config.AOI_V2["max_lon"], n_lon)
    shape = (1, 1, n_lat, n_lon)
    ds = xr.Dataset(
        {
            "wind_speed": (("time", "altitude", "latitude", "longitude"), np.full(shape, 6.5)),
            "wind_direction": (("time", "altitude", "latitude", "longitude"), np.full(shape, 135.0)),
            "wind_u": (("time", "altitude", "latitude", "longitude"), np.full(shape, -4.6)),
            "wind_v": (("time", "altitude", "latitude", "longitude"), np.full(shape, 4.6)),
        },
        coords={"time": [0], "altitude": [10.0], "latitude": lat, "longitude": lon},
    )
    ds.to_netcdf(path)


class TestFetchWindDataLenigas:
    def test_returns_dataset_with_expected_variables_renamed_dims(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            "bite_score.data_ingestion_lenigas._download_erddap_url",
            lambda url, output_path: _write_synthetic_wind_nc(output_path),
        )

        ds = fetch_wind_data_lenigas("2026-05-01", output_directory=str(tmp_path))

        assert isinstance(ds, xr.Dataset)
        for var in ("wind_speed", "wind_direction", "wind_u", "wind_v"):
            assert var in ds.data_vars
        assert "lat" in ds.dims and "lon" in ds.dims
        assert "time" not in ds.dims
        assert "altitude" not in ds.dims
        assert float(ds["wind_speed"].isel(lat=0, lon=0)) == 6.5

    def test_falls_back_to_last_when_exact_date_missing(self, monkeypatch, tmp_path):
        def fake_download(url, output_path):
            if "(last)" in url:
                _write_synthetic_wind_nc(output_path)
            else:
                raise urllib.error.HTTPError(url, 404, "Not Found", None, None)

        monkeypatch.setattr(
            "bite_score.data_ingestion_lenigas._download_erddap_url", fake_download
        )

        # Recent date (within the fallback age window) -- should succeed
        # via the "(last)" fallback rather than raising.
        ds = fetch_wind_data_lenigas("2026-07-20", output_directory=str(tmp_path))
        assert "wind_speed" in ds.data_vars

    def test_raises_when_gap_exceeds_fallback_age_window(self, monkeypatch, tmp_path):
        def always_404(url, output_path):
            raise urllib.error.HTTPError(url, 404, "Not Found", None, None)

        monkeypatch.setattr(
            "bite_score.data_ingestion_lenigas._download_erddap_url", always_404
        )

        with pytest.raises(RuntimeError):
            fetch_wind_data_lenigas("2000-01-01", output_directory=str(tmp_path))

    def test_non_404_http_error_raises_immediately_without_fallback(self, monkeypatch, tmp_path):
        calls = []

        def fake_download(url, output_path):
            calls.append(url)
            raise urllib.error.HTTPError(url, 500, "Server Error", None, None)

        monkeypatch.setattr(
            "bite_score.data_ingestion_lenigas._download_erddap_url", fake_download
        )

        with pytest.raises(RuntimeError):
            fetch_wind_data_lenigas("2026-05-01", output_directory=str(tmp_path))
        assert len(calls) == 1  # no fallback attempt for a non-404 error


def _make_jet_speed_field(peak_lon: float, n_lat: int = 9, n_lon: int = 15) -> xr.DataArray:
    """
    Synthetic current-speed field with a single, clear Gaussian speed
    peak at `peak_lon`, identical at every latitude row -- mirrors the
    real v2 currents data pattern (a single per-latitude speed maximum
    tapering on both sides) documented in
    .squad/decisions/inbox/ash-lenigas-feasibility.md.
    """
    lat = np.linspace(config.AOI_V2["min_lat"], config.AOI_V2["max_lat"], n_lat)
    lon = np.linspace(config.AOI_V2["min_lon"], config.AOI_V2["max_lon"], n_lon)
    profile = np.exp(-((lon - peak_lon) ** 2) / (2 * 0.3**2))
    speed = np.tile(profile, (n_lat, 1))
    return xr.DataArray(speed, coords={"lat": lat, "lon": lon}, dims=["lat", "lon"], name="current_speed")


class TestFindEacAxisLongitude:
    def test_axis_matches_known_jet_peak_at_every_latitude(self):
        lon = np.linspace(config.AOI_V2["min_lon"], config.AOI_V2["max_lon"], 15)
        peak_lon = lon[6]
        speed = _make_jet_speed_field(peak_lon, n_lon=15)

        axis = eac_axis.find_eac_axis_longitude(speed)

        assert axis.dims == ("lat",)
        np.testing.assert_allclose(axis.values, peak_lon)

    def test_all_nan_row_yields_nan_axis(self):
        speed = _make_jet_speed_field(peak_lon=154.0)
        speed = speed.copy()
        speed.values[0, :] = np.nan

        axis = eac_axis.find_eac_axis_longitude(speed)

        assert np.isnan(axis.values[0])
        assert np.isfinite(axis.values[1:]).all()


class TestClassifyEastWestOfAxis:
    def test_cells_east_and_west_of_axis_classified_correctly(self):
        lat = np.array([-27.0, -26.5])
        lon = np.array([153.0, 153.5, 154.0, 154.5, 155.0])
        grid = xr.DataArray(
            np.ones((2, 5)), coords={"lat": lat, "lon": lon}, dims=["lat", "lon"]
        )
        axis_lon = xr.DataArray([154.0, 154.0], coords={"lat": lat}, dims=["lat"])

        result = eac_axis.classify_east_west_of_axis(grid, axis_lon)

        expected_row = np.array([-1.0, -1.0, -1.0, 1.0, 1.0])
        np.testing.assert_array_equal(result.values[0], expected_row)
        np.testing.assert_array_equal(result.values[1], expected_row)

    def test_nan_grid_cells_stay_nan(self):
        lat = np.array([-27.0])
        lon = np.array([153.0, 154.0, 155.0])
        grid = xr.DataArray(
            np.array([[1.0, np.nan, 1.0]]), coords={"lat": lat, "lon": lon}, dims=["lat", "lon"]
        )
        axis_lon = xr.DataArray([154.0], coords={"lat": lat}, dims=["lat"])

        result = eac_axis.classify_east_west_of_axis(grid, axis_lon)

        assert np.isnan(result.values[0, 1])

    def test_nan_axis_row_yields_nan_classification(self):
        lat = np.array([-27.0, -26.5])
        lon = np.array([153.0, 154.0, 155.0])
        grid = xr.DataArray(
            np.ones((2, 3)), coords={"lat": lat, "lon": lon}, dims=["lat", "lon"]
        )
        axis_lon = xr.DataArray([np.nan, 154.0], coords={"lat": lat}, dims=["lat"])

        result = eac_axis.classify_east_west_of_axis(grid, axis_lon)

        assert np.isnan(result.values[0]).all()
        assert np.isfinite(result.values[1]).all()


class TestComputeEacAxisClassification:
    def test_end_to_end_with_synthetic_uo_vo(self):
        n_lat, n_lon = 6, 11
        lat = np.linspace(config.AOI_V2["min_lat"], config.AOI_V2["max_lat"], n_lat)
        lon = np.linspace(config.AOI_V2["min_lon"], config.AOI_V2["max_lon"], n_lon)
        peak_lon = lon[5]

        # A southward-flowing jet (vo dominates) with speed peaking at
        # peak_lon in every row -- uo left at zero so speed == |vo|.
        profile = np.exp(-((lon - peak_lon) ** 2) / (2 * 0.4**2))
        vo_vals = -1.0 * np.tile(profile, (n_lat, 1))
        uo = xr.DataArray(np.zeros((n_lat, n_lon)), coords={"lat": lat, "lon": lon}, dims=["lat", "lon"], name="uo")
        vo = xr.DataArray(vo_vals, coords={"lat": lat, "lon": lon}, dims=["lat", "lon"], name="vo")

        result = eac_axis.compute_eac_axis_classification(uo, vo)

        assert result.values[0, 0] == -1.0  # westernmost cell, west of axis
        assert result.values[0, -1] == 1.0  # easternmost cell, east of axis


def _make_rotation_field(omega: float, n: int = 21):
    """Synthetic solid-body-rotation current field (same construction as
    tests/test_structure_layers.py's `_make_rotation_field`): omega > 0 is
    counter-clockwise, giving zeta = 2*omega (positive)."""
    lat = np.linspace(-27.05, -26.95, n)
    lon = np.linspace(153.45, 153.55, n)

    lat_mid = lat.mean()
    y_m = (lat - lat_mid) * METRES_PER_DEGREE_LAT
    x_m = (lon - lon.mean()) * METRES_PER_DEGREE_LAT * np.cos(np.deg2rad(lat_mid))

    y_grid, x_grid = np.meshgrid(y_m, x_m, indexing="ij")
    u = -omega * y_grid
    v = omega * x_grid

    u_da = xr.DataArray(u, coords={"lat": lat, "lon": lon}, dims=["lat", "lon"], name="uo")
    v_da = xr.DataArray(v, coords={"lat": lat, "lon": lon}, dims=["lat", "lon"], name="vo")
    return u_da, v_da


class TestClassifyUpwellingDownwelling:
    def test_negative_zero_positive_and_nan_classified_correctly(self):
        vorticity = xr.DataArray(
            [[-1e-4, 0.0, 1e-4, np.nan]],
            coords={"lat": [-27.0], "lon": [153.0, 153.1, 153.2, 153.3]},
            dims=["lat", "lon"],
        )

        result = eac_axis.classify_upwelling_downwelling(vorticity)

        np.testing.assert_array_equal(result.values[0, :3], [1.0, 0.0, -1.0])
        assert np.isnan(result.values[0, 3])


class TestComputeUpwellingDownwelling:
    def test_clockwise_rotation_is_upwelling_favorable(self):
        u, v = _make_rotation_field(omega=-1e-4)  # clockwise -> negative zeta
        result = eac_axis.compute_upwelling_downwelling(u, v)
        interior = result.values[2:-2, 2:-2]
        assert np.all(interior == 1.0)

    def test_counterclockwise_rotation_is_downwelling_unfavorable(self):
        u, v = _make_rotation_field(omega=1e-4)  # counter-clockwise -> positive zeta
        result = eac_axis.compute_upwelling_downwelling(u, v)
        interior = result.values[2:-2, 2:-2]
        assert np.all(interior == -1.0)

    def test_matches_calling_compute_relative_vorticity_directly(self):
        """Confirms compute_upwelling_downwelling reuses (not
        reimplements) structure_layers.compute_relative_vorticity -- the
        sign classification must agree with directly classifying that
        function's own output."""
        u, v = _make_rotation_field(omega=-1e-4)
        zeta = compute_relative_vorticity(u, v)
        expected = eac_axis.classify_upwelling_downwelling(zeta)
        actual = eac_axis.compute_upwelling_downwelling(u, v)
        np.testing.assert_allclose(actual.values, expected.values, equal_nan=True)
