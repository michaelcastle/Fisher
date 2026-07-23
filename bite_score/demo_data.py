"""
Synthetic demo data generator.

Produces physically-plausible SST, chlorophyll, current (U/V), and
bathymetry fields for the Southeast Queensland AOI, WITHOUT any network
calls or credentials. This lets the full processing -> normalization ->
overlay -> export -> visualize pipeline be exercised and validated
end-to-end (e.g. for demos, CI, or offline development) using the exact
same code path (`bite_score.pipeline.compute_bite_score`) that runs
against real Copernicus Marine data.

The synthetic scene includes:
  - A diagonal sea-surface-temperature front (the East Australian Current
    edge commonly sits across this shelf).
  - A chlorophyll front broadly co-located with, but not identical to,
    the thermal front (inshore green water vs. offshore blue water).
  - A mesoscale eddy in the current field to generate current-edge signal.
  - A cross-shelf bathymetry gradient from the coast (shallow) out past
    the shelf break (100-600 m) to abyssal depths offshore.
"""
import numpy as np
import xarray as xr

from . import config


def _grid(resolution_deg: float):
    lons = np.arange(config.AOI["min_lon"], config.AOI["max_lon"] + 1e-9, resolution_deg)
    lats = np.arange(config.AOI["min_lat"], config.AOI["max_lat"] + 1e-9, resolution_deg)
    return lats, lons


def generate_physics_dataset(resolution_deg: float = 0.05, seed: int = 42) -> xr.Dataset:
    """Synthetic SST (thetao), currents (uo, vo), and SSHA (zos)."""
    rng = np.random.default_rng(seed)
    lats, lons = _grid(resolution_deg)
    lon2d, lat2d = np.meshgrid(lons, lats)

    # Normalized cross-shelf coordinate (0 = coast/west, 1 = offshore/east)
    cross_shelf = (lon2d - config.AOI["min_lon"]) / (config.AOI["max_lon"] - config.AOI["min_lon"])

    # --- SST: warm EAC water offshore, cooler shelf water inshore, with a
    # sharpened tanh front around the mid-shelf plus mild noise.
    front_position = 0.45 + 0.05 * np.sin(np.deg2rad(lat2d * 10))
    sst = 22.5 + 2.5 * np.tanh((cross_shelf - front_position) * 8) + rng.normal(0, 0.05, lon2d.shape)

    # --- Currents: southward-flowing EAC core (negative v = southward)
    # plus a mesoscale eddy centred mid-domain to create rotational shear
    # (current velocity edges), reflecting typical Moreton Bay eddy activity.
    eddy_lon, eddy_lat = 153.9, -26.7
    dx = (lon2d - eddy_lon) * 111_320 * np.cos(np.deg2rad(eddy_lat))
    dy = (lat2d - eddy_lat) * 111_320
    r = np.sqrt(dx**2 + dy**2) + 1e-6
    eddy_strength = 0.6 * np.exp(-(r / 45_000) ** 2)
    uo = -eddy_strength * (dy / r) + 0.15 * (cross_shelf - 0.3)
    vo = eddy_strength * (dx / r) - 0.6 * np.tanh((cross_shelf - front_position) * 6)

    # --- SSHA: broadly mirrors the eddy (anticyclonic = positive anomaly)
    zos = 0.15 * np.exp(-(r / 45_000) ** 2) + rng.normal(0, 0.01, lon2d.shape)

    ds = xr.Dataset(
        {
            "thetao": (("time", "lat", "lon"), sst[np.newaxis, :, :]),
            "uo": (("time", "lat", "lon"), uo[np.newaxis, :, :]),
            "vo": (("time", "lat", "lon"), vo[np.newaxis, :, :]),
            "zos": (("time", "lat", "lon"), zos[np.newaxis, :, :]),
        },
        coords={"time": [0], "lat": lats, "lon": lons},
    )
    return ds


def generate_current_time_series(n_days: int = 6, resolution_deg: float = 0.05, seed: int = 42) -> xr.Dataset:
    """
    Synthetic multi-day surface current (uo, vo) time series, for exercising
    the FSLE Lagrangian-integration code path (fsle.py) offline / without
    network calls. Unlike `generate_physics_dataset` (a single static
    snapshot), the mesoscale eddy here slowly drifts and the background
    shelf-flow front oscillates day-to-day, so neighbouring particles
    actually separate over time (a static, unchanging field would never
    produce a finite FSLE, since nothing would ever stretch particle
    pairs apart).
    """
    rng = np.random.default_rng(seed)
    lats, lons = _grid(resolution_deg)
    lon2d, lat2d = np.meshgrid(lons, lats)
    cross_shelf = (lon2d - config.AOI["min_lon"]) / (config.AOI["max_lon"] - config.AOI["min_lon"])

    uo_frames, vo_frames = [], []
    for day in range(n_days):
        # Eddy centre drifts slowly southward over the window.
        eddy_lon = 153.9 + 0.03 * day
        eddy_lat = -26.7 - 0.05 * day
        dx = (lon2d - eddy_lon) * 111_320 * np.cos(np.deg2rad(eddy_lat))
        dy = (lat2d - eddy_lat) * 111_320
        r = np.sqrt(dx**2 + dy**2) + 1e-6
        eddy_strength = 0.6 * np.exp(-(r / 45_000) ** 2)

        front_position = 0.45 + 0.05 * np.sin(np.deg2rad(lat2d * 10) + day * 0.35)
        uo = -eddy_strength * (dy / r) + 0.15 * (cross_shelf - 0.3)
        vo = eddy_strength * (dx / r) - 0.6 * np.tanh((cross_shelf - front_position) * 6)
        uo_frames.append(uo + rng.normal(0, 0.01, lon2d.shape))
        vo_frames.append(vo + rng.normal(0, 0.01, lon2d.shape))

    ds = xr.Dataset(
        {
            "uo": (("time", "lat", "lon"), np.stack(uo_frames)),
            "vo": (("time", "lat", "lon"), np.stack(vo_frames)),
        },
        coords={"time": np.arange(n_days), "lat": lats, "lon": lons},
    )
    return ds


def generate_biogeochemistry_dataset(resolution_deg: float = 0.1, seed: int = 7) -> xr.Dataset:
    """Synthetic chlorophyll-a (chl, mg/m^3) on a coarser native grid."""
    rng = np.random.default_rng(seed)
    lats, lons = _grid(resolution_deg)
    lon2d, lat2d = np.meshgrid(lons, lats)

    cross_shelf = (lon2d - config.AOI["min_lon"]) / (config.AOI["max_lon"] - config.AOI["min_lon"])
    front_position = 0.35 + 0.06 * np.cos(np.deg2rad(lat2d * 8))

    # High chlorophyll (green, productive) inshore -> low (blue, oligotrophic) offshore
    chl = 0.15 + 1.2 * (1 - np.tanh((cross_shelf - front_position) * 7)) / 2
    chl += rng.normal(0, 0.02, lon2d.shape)
    chl = np.clip(chl, 0.02, None)

    ds = xr.Dataset(
        {"chl": (("time", "lat", "lon"), chl[np.newaxis, :, :])},
        coords={"time": [0], "lat": lats, "lon": lons},
    )
    return ds


def generate_bathymetry(resolution_deg: float = 0.01) -> xr.DataArray:
    """
    Synthetic cross-shelf bathymetry: shallow coastal flats, a shelf break
    band (~100-600 m) roughly two-thirds of the way offshore, dropping to
    abyssal depths at the eastern edge - mirroring the real SEQ shelf
    profile off Moreton Island / the Sunshine Coast.
    """
    lats, lons = _grid(resolution_deg)
    lon2d, lat2d = np.meshgrid(lons, lats)
    cross_shelf = (lon2d - config.AOI["min_lon"]) / (config.AOI["max_lon"] - config.AOI["min_lon"])

    # Smooth S-curve from ~10 m at the coast to ~2500 m at the far offshore edge,
    # with the steep shelf-break transition centred around cross_shelf ~0.55-0.75.
    depth = 10 + 2490 / (1 + np.exp(-(cross_shelf - 0.62) * 12))
    depth += 15 * np.sin(np.deg2rad(lat2d * 20)) * cross_shelf  # mild along-shelf undulation

    # Simulate a narrow coastal land strip (negative depth = above sea
    # level) along the western edge, so the demo scene has a real
    # coastline to render/validate against -- real GEBCO data naturally
    # includes land, but the original synthetic profile never went above
    # 10m, so there was nothing for the map's land-outline layer to trace.
    depth = np.where(cross_shelf < 0.03, -20.0, depth)

    da = xr.DataArray(
        depth,
        coords={"lat": lats, "lon": lons},
        dims=("lat", "lon"),
        name="depth",
    )
    return da
