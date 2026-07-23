"""
Finite-Size Lyapunov Exponent (FSLE) computation.

An FSLE field (units: 1/day) highlights the thin, filamentary ocean fronts
and Lagrangian Coherent Structures (LCS) where converging surface currents
concentrate drifting plankton/baitfish -- a signal invisible in any single
day's current snapshot (which is all the existing `current_velocity`
factor in overlay.py sees). It is computed by actually advecting a dense
grid of virtual particle pairs through several days of the *time-varying*
current field and measuring how fast neighbouring particles separate.

This is an independent diagnostic layer -- NOT one of the five weighted
factors in the Bite Score (see config.LAYER_WEIGHTS) -- rendered as its own
optional/toggleable map overlay (see visualize.py) alongside a
"How FSLE Is Calculated" explanation.

Method (standard finite-size Lyapunov exponent approach, as used by
operational products like AVISO/CMEMS FSLE):
  1. Seed a dense grid of particles across the AOI, each with 4 neighbours
     (east/west/north/south) offset by an initial separation `delta0`.
  2. Integrate every particle's trajectory forward through the (bilinearly
     space-interpolated, linearly time-interpolated) surface current field
     using 4th-order Runge-Kutta (RK4).
  3. At every step, reconstruct the local deformation gradient tensor from
     the four neighbour positions and take the largest eigenvalue of the
     Cauchy-Green tensor -- this is the squared "stretching factor" between
     the current and initial separation.
  4. The first time the stretching factor implies the pair has grown from
     `delta0` to the final threshold `delta_f`, record that elapsed time tau.
  5. FSLE = (1/tau) * ln(delta_f / delta0).

Particle pairs that never reach delta_f within the available integration
window are left as NaN (no resolvable front at this location/timescale).
"""
import logging

import numpy as np
import xarray as xr
from scipy.interpolate import RegularGridInterpolator

logger = logging.getLogger(__name__)

SECONDS_PER_DAY = 86_400.0
METRES_PER_DEGREE_LAT = 111_320.0

# --- Tunable FSLE parameters (typical values, following AVISO/CMEMS FSLE
# product conventions, scaled down for this AOI's ~9km-resolution currents) --
DELTA0_M = 3_000.0          # initial particle-pair separation (metres)
SEPARATION_FACTOR = 8.0     # delta_f = SEPARATION_FACTOR * delta0
RK4_STEP_HOURS = 6.0        # integration timestep
MAX_INTEGRATION_DAYS = 5.0  # give up (NaN) if a pair hasn't separated by then
SEED_STEP_DEG = 0.03        # spacing of the base seed grid (~3km)

# Days of current data needed: today .. today + MAX_INTEGRATION_DAYS.
REQUIRED_FORECAST_DAYS = int(np.ceil(MAX_INTEGRATION_DAYS)) + 1


def _lat_lon_names(ds) -> tuple:
    lat_name = "lat" if "lat" in ds.dims else "latitude"
    lon_name = "lon" if "lon" in ds.dims else "longitude"
    return lat_name, lon_name


def _velocity_interpolators(u: np.ndarray, v: np.ndarray, lat: np.ndarray, lon: np.ndarray):
    """
    Build one bilinear spatial interpolator per time step for u and v.
    NaNs (land / missing) are filled with 0 so trajectories don't blow up
    near the coast -- particles that wander over land simply stop
    advecting instead of crashing the integration.
    """
    u_filled = np.nan_to_num(u, nan=0.0)
    v_filled = np.nan_to_num(v, nan=0.0)
    u_interps = [
        RegularGridInterpolator((lat, lon), u_filled[t], bounds_error=False, fill_value=0.0)
        for t in range(u.shape[0])
    ]
    v_interps = [
        RegularGridInterpolator((lat, lon), v_filled[t], bounds_error=False, fill_value=0.0)
        for t in range(v.shape[0])
    ]
    return u_interps, v_interps


def _sample_velocity_deg_per_day(lons, lats, t_days, u_interps, v_interps, n_times):
    """
    Sample u/v (m/s) at arbitrary (lon, lat) points and fractional time
    `t_days` (days since the first available snapshot), linearly
    interpolating between the two bracketing daily fields, and convert to
    degrees/day (longitude scaled by cos(latitude) per-particle).
    """
    t_days = np.clip(t_days, 0.0, n_times - 1)
    t0 = int(np.floor(t_days))
    t1 = min(t0 + 1, n_times - 1)
    frac = t_days - t0

    pts = np.column_stack([lats, lons])
    u0 = u_interps[t0](pts)
    v0 = v_interps[t0](pts)
    if t1 == t0:
        u_ms, v_ms = u0, v0
    else:
        u1 = u_interps[t1](pts)
        v1 = v_interps[t1](pts)
        u_ms = u0 * (1 - frac) + u1 * frac
        v_ms = v0 * (1 - frac) + v1 * frac

    dlat_dt = v_ms * SECONDS_PER_DAY / METRES_PER_DEGREE_LAT
    dlon_dt = u_ms * SECONDS_PER_DAY / (METRES_PER_DEGREE_LAT * np.cos(np.deg2rad(lats)))
    return dlon_dt, dlat_dt


def _rk4_advect(lon, lat, t_days, dt_days, u_interps, v_interps, n_times):
    """One RK4 step advecting (lon, lat) particles forward by dt_days."""
    k1_lon, k1_lat = _sample_velocity_deg_per_day(lon, lat, t_days, u_interps, v_interps, n_times)
    k2_lon, k2_lat = _sample_velocity_deg_per_day(
        lon + dt_days / 2 * k1_lon, lat + dt_days / 2 * k1_lat, t_days + dt_days / 2, u_interps, v_interps, n_times
    )
    k3_lon, k3_lat = _sample_velocity_deg_per_day(
        lon + dt_days / 2 * k2_lon, lat + dt_days / 2 * k2_lat, t_days + dt_days / 2, u_interps, v_interps, n_times
    )
    k4_lon, k4_lat = _sample_velocity_deg_per_day(
        lon + dt_days * k3_lon, lat + dt_days * k3_lat, t_days + dt_days, u_interps, v_interps, n_times
    )
    new_lon = lon + dt_days / 6 * (k1_lon + 2 * k2_lon + 2 * k3_lon + k4_lon)
    new_lat = lat + dt_days / 6 * (k1_lat + 2 * k2_lat + 2 * k3_lat + k4_lat)
    return new_lon, new_lat


def compute_fsle_field(
    uv_series: xr.Dataset,
    delta0_m: float = DELTA0_M,
    separation_factor: float = SEPARATION_FACTOR,
    rk4_step_hours: float = RK4_STEP_HOURS,
    max_integration_days: float = MAX_INTEGRATION_DAYS,
    seed_step_deg: float = SEED_STEP_DEG,
) -> xr.DataArray:
    """
    Compute the forward FSLE field (units 1/day) from a time series of
    surface current vectors.

    `uv_series` must be an xr.Dataset with data variables "uo"/"vo" (m/s,
    eastward/northward) and dims (time, lat|latitude, lon|longitude), at
    least 2 time steps, ordered ascending in time.
    """
    lat_name, lon_name = _lat_lon_names(uv_series)
    u = uv_series["uo"].transpose("time", lat_name, lon_name).values.astype("float64")
    v = uv_series["vo"].transpose("time", lat_name, lon_name).values.astype("float64")
    lat = uv_series[lat_name].values.astype("float64")
    lon = uv_series[lon_name].values.astype("float64")
    n_times = u.shape[0]
    if n_times < 2:
        raise ValueError("compute_fsle_field requires at least 2 time steps of current data")

    # RegularGridInterpolator requires ascending coordinates.
    if lat[0] > lat[-1]:
        lat = lat[::-1]
        u = u[:, ::-1, :]
        v = v[:, ::-1, :]
    if lon[0] > lon[-1]:
        lon = lon[::-1]
        u = u[:, :, ::-1]
        v = v[:, :, ::-1]

    u_interps, v_interps = _velocity_interpolators(u, v, lat, lon)

    # Base seed grid (independent of the native current-field resolution --
    # FSLE benefits from seeding finer than the velocity field itself, since
    # chaotic advection can reveal sub-grid-scale structure).
    seed_lons = np.arange(lon.min(), lon.max(), seed_step_deg)
    seed_lats = np.arange(lat.min(), lat.max(), seed_step_deg)
    grid_lon, grid_lat = np.meshgrid(seed_lons, seed_lats)
    n_points = grid_lon.size
    lat_ref = float(np.mean(seed_lats))
    m_per_deg_lon = METRES_PER_DEGREE_LAT * np.cos(np.deg2rad(lat_ref))

    delta0_lat_deg = delta0_m / METRES_PER_DEGREE_LAT
    delta0_lon_deg = delta0_m / m_per_deg_lon

    center_lon = grid_lon.ravel()
    center_lat = grid_lat.ravel()

    # Four neighbours per seed point, used to reconstruct the local
    # deformation gradient via centred finite differences.
    px = {
        "e": center_lon + delta0_lon_deg, "w": center_lon - delta0_lon_deg,
        "n": center_lon.copy(), "s": center_lon.copy(),
    }
    py = {
        "e": center_lat.copy(), "w": center_lat.copy(),
        "n": center_lat + delta0_lat_deg, "s": center_lat - delta0_lat_deg,
    }

    dt_days = rk4_step_hours / 24.0
    n_steps = int(np.ceil(max_integration_days / dt_days))

    tau = np.full(n_points, np.nan)
    resolved = np.zeros(n_points, dtype=bool)
    t_days = 0.0

    for _step in range(n_steps):
        for key in ("e", "w", "n", "s"):
            px[key], py[key] = _rk4_advect(px[key], py[key], t_days, dt_days, u_interps, v_interps, n_times)
        t_days += dt_days

        # Local Cartesian (equirectangular) approximation, referenced to the
        # seed grid's mean latitude, for measuring separations consistently.
        x_e, y_e = px["e"] * m_per_deg_lon, py["e"] * METRES_PER_DEGREE_LAT
        x_w, y_w = px["w"] * m_per_deg_lon, py["w"] * METRES_PER_DEGREE_LAT
        x_n, y_n = px["n"] * m_per_deg_lon, py["n"] * METRES_PER_DEGREE_LAT
        x_s, y_s = px["s"] * m_per_deg_lon, py["s"] * METRES_PER_DEGREE_LAT

        dxdX = (x_e - x_w) / (2 * delta0_m)
        dydX = (y_e - y_w) / (2 * delta0_m)
        dxdY = (x_n - x_s) / (2 * delta0_m)
        dydY = (y_n - y_s) / (2 * delta0_m)

        c11 = dxdX**2 + dydX**2
        c22 = dxdY**2 + dydY**2
        c12 = dxdX * dxdY + dydX * dydY

        trace = c11 + c22
        det = c11 * c22 - c12**2
        disc = np.sqrt(np.clip(trace**2 / 4 - det, 0, None))
        lambda_max = trace / 2 + disc
        rho = np.sqrt(np.clip(lambda_max, 0, None))  # current separation / delta0

        newly_resolved = (~resolved) & (rho >= separation_factor)
        tau[newly_resolved] = t_days
        resolved |= newly_resolved

        if resolved.all():
            break

    with np.errstate(divide="ignore", invalid="ignore"):
        fsle_flat = np.where(resolved, np.log(separation_factor) / tau, np.nan)

    fsle = fsle_flat.reshape(grid_lat.shape)
    result = xr.DataArray(
        fsle.astype("float32"),
        coords={"lat": seed_lats, "lon": seed_lons},
        dims=("lat", "lon"),
        name="fsle",
    )
    result.attrs["description"] = "Finite-Size Lyapunov Exponent (1/day)"
    result.attrs["delta0_m"] = delta0_m
    result.attrs["separation_factor"] = separation_factor
    return result


def fetch_and_compute_fsle(target_date: str) -> xr.DataArray:
    """
    Fetch the multi-day forward current-velocity time series needed for
    Lagrangian integration (today .. today + a few forecast days) and
    compute the FSLE field for `target_date`.

    Raises if the underlying forecast data isn't available (e.g. far-past
    historical dates beyond the analysis-forecast product's rolling
    window) -- callers should treat this as an optional layer and degrade
    gracefully rather than failing the whole pipeline (see main.py).
    """
    from .data_ingestion import fetch_current_velocity_series

    uv_series = fetch_current_velocity_series(target_date, n_days=REQUIRED_FORECAST_DAYS)
    return compute_fsle_field(uv_series)
