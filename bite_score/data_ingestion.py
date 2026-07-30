"""
Data ingestion module.

Handles fetching daily NetCDF ocean data from the Copernicus Marine Service
(via the official `copernicusmarine` Python toolbox), loading the static
bathymetry grid (GEBCO / AusSeabed), and fetching live tide telemetry/
predictions from the Queensland Government DES storm-tide feed (see
fetch_tide_data()).
"""
import io
import logging
import os
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Dict, List

import pandas as pd
import requests
import xarray as xr

from . import config

logger = logging.getLogger(__name__)

# NOAA's ERDDAP server rejects/redirects some requests that don't send a
# browser-like User-Agent (observed as a confusing 302 -> 403 for some
# dataset aliases), so always identify explicitly.
_ERDDAP_USER_AGENT = "Mozilla/5.0 (compatible; FisherBiteScorePipeline/1.0)"

# --- IMOS SRS Ocean Colour (NOAA-20 / VIIRS, 0.0075° ≈ 833 m) ---------------
# THREDDS OPeNDAP ASCII endpoint for the IMOS SRS daily ocean colour gridded
# product (NOAA-20 / JPSS-1 VIIRS).  Binary OPeNDAP is blocked behind a
# libcurl/openssl version mismatch in this environment; the plain-HTTP ASCII
# endpoint works fine and returns only ~1 MB for the SEQ AOI.
_IMOS_OC_THREDDS_BASE = (
    "https://thredds.aodn.org.au/thredds/dodsC/IMOS/SRS/OC/gridded/noaa20/P1D"
)
_IMOS_OC_LAT_ORIGIN = 12.0    # northernmost latitude of the IMOS OC grid
_IMOS_OC_LON_ORIGIN = 78.0    # westernmost longitude of the IMOS OC grid
_IMOS_OC_STEP       = 0.0075  # degrees per pixel (~833 m)
_IMOS_OC_FILL       = -999.0  # fill / no-data sentinel in the raw product

# The "(last)" ERDDAP fallback (grab whatever granule is currently newest) is
# only a reasonable substitute for the *exact requested date* when that date
# is recent -- i.e. the granule is simply missing yet due to normal
# processing latency/cloud gaps. For a genuinely historical request (weeks,
# months, or years in the past), "latest available" would silently return
# TODAY's conditions mislabeled as the requested historical date, which is
# wrong for any real analysis. Beyond this many days in the past, refuse the
# fallback and raise instead, so callers (main.py) fall back to a dataset
# that actually has historical coverage (Copernicus's reanalysis fields).
_MAX_LATEST_FALLBACK_AGE_DAYS = 14


def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def _download_erddap_url(url: str, output_path: str) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": _ERDDAP_USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as response, open(output_path, "wb") as f:
        f.write(response.read())


def fetch_erddap_subset(
    dataset_key: str,
    target_date: str,
    output_directory: str = config.RAW_DATA_DIR,
    aoi: dict = config.AOI,
    cache_suffix: str = "",
) -> str:
    """
    Fetch a daily satellite SST/chlorophyll subset from NOAA CoastWatch
    ERDDAP (griddap), clipped to `aoi` (defaults to the v1 `config.AOI`),
    at much finer native resolution than the equivalent Copernicus model
    fields.

    Satellite observation products can have processing/cloud-cover gaps, so
    if no granule exists for `target_date` this falls back to the most
    recent available granule (ERDDAP's `(last)` time index) rather than
    failing outright.

    `aoi`/`cache_suffix` are additive, backward-compatible parameters used
    by the v2 bite-score model's wider AOI_V2 fetches (see
    `load_erddap_layer_v2`) -- `cache_suffix` (e.g. "_v2") keeps the v2
    on-disk cache filename distinct from v1's, so running v1 and v2 for the
    same date never overwrites/collides with each other's cached raw file
    despite sharing the same `dataset_key`/`target_date`. Every existing
    (v1) caller omits both, so behaviour there is completely unchanged.

    No authentication is required; NOAA ERDDAP griddap endpoints are public.
    Returns the local path to the downloaded NetCDF file.
    """
    cfg = config.ERDDAP_DATASETS[dataset_key]
    _ensure_dir(output_directory)

    lat_range = f"({aoi['min_lat']}):1:({aoi['max_lat']})"
    lon_range = f"({aoi['min_lon']}):1:({aoi['max_lon']})"
    altitude_dim = ["(0.0):1:(0.0)"] if cfg.get("has_altitude") else []

    def _build_url(time_dim: str) -> str:
        dims = [time_dim] + altitude_dim + [lat_range, lon_range]
        query = f"{cfg['variable']}[{']['.join(dims)}]"
        return f"{config.ERDDAP_BASE_URL}/{cfg['dataset_id']}.nc?{query}"

    logger.info(
        "Requesting NOAA ERDDAP dataset=%s variable=%s date=%s",
        cfg["dataset_id"], cfg["variable"], target_date,
    )
    output_path = os.path.join(output_directory, f"{dataset_key}_erddap{cache_suffix}_{target_date}.nc")
    time_dim = f"({target_date}T00:00:00Z):1:({target_date}T00:00:00Z)"
    try:
        _download_erddap_url(_build_url(time_dim), output_path)
        return output_path
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            raise RuntimeError(
                f"Failed to fetch {cfg['dataset_id']} from NOAA ERDDAP for {target_date}: {exc}"
            ) from exc

    # No granule for the exact requested date (common for satellite obs due
    # to processing latency / cloud gaps). Only fall back to "latest
    # available" if the requested date is recent enough that this is a
    # plausible explanation -- otherwise (a genuinely historical request)
    # that fallback would silently mislabel today's conditions as the
    # requested historical date, so raise instead and let the caller fall
    # back to a dataset with real historical coverage (e.g. Copernicus).
    target_dt = datetime.strptime(target_date, "%Y-%m-%d")
    age_days = (datetime.now(timezone.utc).replace(tzinfo=None) - target_dt).days
    if age_days > _MAX_LATEST_FALLBACK_AGE_DAYS:
        raise RuntimeError(
            f"{cfg['dataset_id']} has no granule for {target_date}, which is {age_days} "
            f"days in the past -- beyond the {_MAX_LATEST_FALLBACK_AGE_DAYS}-day near-real-time "
            "latency window this dataset's rolling archive covers. Refusing to substitute "
            "the latest available granule, since that would silently misrepresent today's "
            "conditions as this historical date."
        )

    logger.warning(
        "%s has no granule for %s; falling back to the most recent available date",
        cfg["dataset_id"], target_date,
    )
    fallback_path = os.path.join(output_directory, f"{dataset_key}_erddap{cache_suffix}_latest.nc")
    try:
        _download_erddap_url(_build_url("(last):1:(last)"), fallback_path)
    except Exception as exc:
        raise RuntimeError(
            f"Failed to fetch {cfg['dataset_id']} from NOAA ERDDAP (both {target_date} and latest failed): {exc}"
        ) from exc
    return fallback_path


def load_erddap_layer(dataset_key: str, target_date: str) -> xr.DataArray:
    """
    Fetch (if needed) and open a satellite SST/CHL layer, reduced to a plain
    2D (lat, lon) field ready for the gradient/normalization pipeline.
    """
    cfg = config.ERDDAP_DATASETS[dataset_key]
    path = fetch_erddap_subset(dataset_key, target_date)
    da = xr.open_dataset(path)[cfg["variable"]]
    if "time" in da.dims:
        da = da.isel(time=0)
    if "altitude" in da.dims:
        da = da.isel(altitude=0)
    return da


def load_erddap_layer_v2(dataset_key: str, target_date: str) -> xr.DataArray:
    """
    v2 counterpart of `load_erddap_layer`: fetches the same NOAA ERDDAP
    SST/CHL satellite layer, but clipped to the wider `config.AOI_V2`
    extent (via `fetch_erddap_subset`'s `aoi` param) and cached under a
    `_v2`-suffixed filename so it never collides with v1's cached file for
    the same date.
    """
    cfg = config.ERDDAP_DATASETS[dataset_key]
    path = fetch_erddap_subset(dataset_key, target_date, aoi=config.AOI_V2, cache_suffix="_v2")
    da = xr.open_dataset(path)[cfg["variable"]]
    if "time" in da.dims:
        da = da.isel(time=0)
    if "altitude" in da.dims:
        da = da.isel(altitude=0)
    return da


def _parse_imos_oc_ascii(text: str, target_date: str) -> xr.DataArray:
    """
    Parse an IMOS SRS OC OPeNDAP ASCII response into an ``xr.DataArray``
    named ``'chlor_a'``, ready for the existing chlorophyll pipeline path.

    The response format is::

        Dataset { ... }
        ---------...----------
        chl_oci.chl_oci[1][R][C]
        [0][0], v00, v01, ...
        [0][1], v10, v11, ...
        ...

        chl_oci.time[1]  ...
        chl_oci.latitude[R]  ...
        chl_oci.longitude[C]  ...

        latitude[R]
        -26.0025, -26.01, ...

        longitude[C]
        153.0, 153.0075, ...
    """
    import numpy as np

    sep = "---------------------------------------------\n"
    if sep not in text:
        raise RuntimeError(
            f"Unexpected IMOS OC ASCII response format for {target_date}"
        )
    _, body = text.split(sep, 1)
    sections = body.split("\n\n")

    def _find_section(prefix: str) -> str:
        for sec in sections:
            if sec.strip().startswith(prefix):
                return sec.strip()
        raise RuntimeError(
            f"IMOS OC ASCII section '{prefix}' not found for {target_date}"
        )

    def _parse_1d(section: str) -> np.ndarray:
        lines = section.splitlines()
        vals: list = []
        for line in lines[1:]:
            vals.extend(float(x) for x in line.split(",") if x.strip())
        return np.array(vals, dtype=np.float64)

    def _parse_2d(section: str) -> np.ndarray:
        lines = section.splitlines()
        rows: list = []
        for line in lines[1:]:
            # Each data row: '[t][r], v0, v1, v2, ...'
            # Partition on the first ', ' to strip the '[t][r]' index token.
            _, _, data_part = line.partition(", ")
            if data_part:
                rows.append([float(x) for x in data_part.split(", ")])
        return np.array(rows, dtype=np.float32)

    lat_vals = _parse_1d(_find_section("latitude["))
    lon_vals = _parse_1d(_find_section("longitude["))
    chl_raw  = _parse_2d(_find_section("chl_oci.chl_oci["))

    chl_data = np.where(chl_raw == _IMOS_OC_FILL, np.nan, chl_raw)

    da = xr.DataArray(
        chl_data,
        dims=["latitude", "longitude"],
        coords={"latitude": lat_vals, "longitude": lon_vals},
        name="chlor_a",
    )
    da.attrs.update({
        "long_name": "Chlorophyll Concentration, OCI Algorithm (IMOS NOAA-20)",
        "units": "mg m^-3",
        "source": f"IMOS SRS OC NOAA-20 P1D {target_date}",
    })
    return da


def fetch_imos_oc_chl(
    target_date: str,
    aoi: dict = config.AOI,
    output_directory: str = config.RAW_DATA_DIR,
    cache_suffix: str = "",
) -> xr.DataArray:
    """
    Fetch daily chlorophyll-a from the IMOS SRS NOAA-20 Ocean Colour product
    via THREDDS OPeNDAP ASCII, spatially clipped to *aoi*.

    Resolution : 0.0075° (~833 m) — **5× finer** than the 4 km NOAA ERDDAP
                 VIIRS products this replaces as the primary source.
    Coverage   : 78°E–180°E, 60°S–12°N (full Australian regional domain).
    Archive    : 2023-present, ~1-day latency.
    Sensor     : NOAA-20 (JPSS-1) VIIRS, Australian-regional atmospheric
                 correction applied by IMOS SRS.

    Only ~1 MB is downloaded per request (OPeNDAP ASCII spatial subset),
    avoiding the 100+ MB full-Australia file download.  The parsed result is
    cached as a local NetCDF so repeat runs for the same date are instant.

    Returns an ``xr.DataArray`` named ``'chlor_a'`` (same name as the NOAA
    ERDDAP VIIRS products) with ``(latitude, longitude)`` coordinates,
    compatible with the existing chlorophyll pipeline path.
    """
    _ensure_dir(output_directory)
    cache_path = os.path.join(
        output_directory,
        f"chl_imos_oc{cache_suffix}_{target_date}.nc",
    )
    if os.path.exists(cache_path):
        logger.info("IMOS OC chl: loading from cache %s", cache_path)
        return xr.open_dataset(cache_path)["chlor_a"]

    date_obj = datetime.strptime(target_date, "%Y-%m-%d")
    yyyy     = date_obj.strftime("%Y")
    mm       = date_obj.strftime("%m")
    yyyymmdd = date_obj.strftime("%Y%m%d")

    filename = f"J.P1D.{yyyymmdd}T053000Z.aust.chl_oci.nc"
    file_url = f"{_IMOS_OC_THREDDS_BASE}/{yyyy}/{mm}/{filename}"

    step      = _IMOS_OC_STEP
    lat0_idx  = round((_IMOS_OC_LAT_ORIGIN - aoi["max_lat"]) / step)
    lat1_idx  = round((_IMOS_OC_LAT_ORIGIN - aoi["min_lat"]) / step)
    lon0_idx  = round((aoi["min_lon"] - _IMOS_OC_LON_ORIGIN) / step)
    lon1_idx  = round((aoi["max_lon"] - _IMOS_OC_LON_ORIGIN) / step)

    ascii_url = (
        f"{file_url}.ascii?"
        f"chl_oci[0][{lat0_idx}:{lat1_idx}][{lon0_idx}:{lon1_idx}],"
        f"latitude[{lat0_idx}:{lat1_idx}],"
        f"longitude[{lon0_idx}:{lon1_idx}]"
    )

    logger.info(
        "IMOS OC chl: fetching %s (lat_idx %d–%d, lon_idx %d–%d)",
        target_date, lat0_idx, lat1_idx, lon0_idx, lon1_idx,
    )
    try:
        resp = requests.get(
            ascii_url, timeout=60, headers={"User-Agent": _ERDDAP_USER_AGENT}
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise RuntimeError(
            f"IMOS OC THREDDS request failed for {target_date}: {exc}"
        ) from exc

    da = _parse_imos_oc_ascii(resp.text, target_date)
    # Persist to disk cache so repeated runs for the same date are instant.
    da.to_dataset(name="chlor_a").to_netcdf(cache_path)
    return da


def fetch_chl_composite(
    target_date: str,
    lookback_days: int = 7,
    min_coverage_fraction: float = 0.50,
    aoi: dict = None,
    output_directory: str = config.RAW_DATA_DIR,
    cache_suffix: str = "",
) -> xr.DataArray:
    """
    Multi-day most-recent-valid IMOS OC chlorophyll composite.

    Fetches today's IMOS OC chlorophyll first.  If the fraction of non-NaN
    pixels is below `min_coverage_fraction` (default 50 %), cloud gaps are
    backfilled by the most recent available prior day (up to `lookback_days`
    days back), in newest-first order, until the threshold is met or the
    lookback window is exhausted.

    This is the standard "most-recent-valid" (MRV) compositing approach used
    by ocean-colour operational products to reduce cloud patchiness without
    introducing temporal smearing: a pixel's value is always from the most
    recent cloud-free observation, not a multi-day average.

    Raises ``RuntimeError`` (or any exception from ``fetch_imos_oc_chl``) if
    even the target date itself cannot be fetched -- callers should use the
    same try/except fallback chain as before.

    Returns an ``xr.DataArray`` in exactly the same format as
    ``fetch_imos_oc_chl`` so it is a drop-in replacement.
    """
    import numpy as np

    if aoi is None:
        aoi = config.AOI

    # Always fetch the target date first -- raises on failure so the
    # existing fallback chain in main.py is unchanged.
    base_da = fetch_imos_oc_chl(
        target_date, aoi=aoi, output_directory=output_directory, cache_suffix=cache_suffix
    )
    composite = base_da.values.copy()

    coverage = float(np.isfinite(composite).sum()) / composite.size
    if coverage >= min_coverage_fraction:
        logger.info(
            "CHL composite %s: single day %.1f%% valid -- no backfill needed",
            target_date, coverage * 100,
        )
        return base_da

    logger.info(
        "CHL composite %s: %.1f%% valid (< %.0f%% threshold) -- backfilling up to %d prior days",
        target_date, coverage * 100, min_coverage_fraction * 100, lookback_days,
    )

    date_obj = datetime.strptime(target_date, "%Y-%m-%d")
    for delta in range(1, lookback_days + 1):
        gap_mask = ~np.isfinite(composite)
        if not gap_mask.any():
            break  # fully covered

        prior_date = (date_obj - timedelta(days=delta)).strftime("%Y-%m-%d")
        try:
            prior_da = fetch_imos_oc_chl(
                prior_date, aoi=aoi, output_directory=output_directory, cache_suffix=cache_suffix
            )
        except Exception:
            logger.debug("CHL composite: no IMOS OC data for prior day -%d (%s)", delta, prior_date)
            continue

        # IMOS OC uses a fixed grid so grids should be identical, but
        # interpolate to the base grid with nearest-neighbour to be safe.
        try:
            prior_vals = prior_da.interp(
                latitude=base_da.latitude, longitude=base_da.longitude, method="nearest"
            ).values
        except Exception:
            prior_vals = prior_da.values

        composite = np.where(gap_mask & np.isfinite(prior_vals), prior_vals, composite)
        coverage = float(np.isfinite(composite).sum()) / composite.size
        logger.info(
            "CHL composite %s: after day -%d (%s): %.1f%% valid",
            target_date, delta, prior_date, coverage * 100,
        )
        if coverage >= min_coverage_fraction:
            break

    return base_da.copy(data=composite)


def fetch_copernicus_subset(
    dataset_id: str,
    variables: List[str],
    target_date: str,
    output_filename: str,
    output_directory: str = config.RAW_DATA_DIR,
    aoi: dict = config.AOI,
) -> str:
    """
    Fetch a daily NetCDF subset from the Copernicus Marine Service, clipped
    to `aoi` (defaults to the v1 `config.AOI`), using the
    `copernicusmarine` toolbox.

    `aoi` is an additive, backward-compatible parameter used by the v2
    bite-score model's wider AOI_V2 fetches (see `fetch_daily_ocean_data_v2`
    / `fetch_mld_v2`) -- every existing (v1) caller omits it, so v1
    behaviour is completely unchanged. `output_filename` is already always
    caller-supplied, so v2 callers keep their cached files distinct from
    v1's simply by passing a differently-named filename.

    Authentication:
        Reads COPERNICUSMARINE_SERVICE_USERNAME / COPERNICUSMARINE_SERVICE_PASSWORD
        from the environment (populated from a local, gitignored .env file via
        python-dotenv - see .env.example). Falls back to any credentials
        already stored by `copernicusmarine login` if the env vars aren't set.
        Credentials are never hardcoded here.

    Returns the local path to the downloaded NetCDF file.
    """
    import copernicusmarine  # lazy import: keeps this module importable without the dependency

    _ensure_dir(output_directory)
    logger.info("Requesting dataset=%s variables=%s date=%s", dataset_id, variables, target_date)

    username = os.environ.get("COPERNICUSMARINE_SERVICE_USERNAME") or None
    password = os.environ.get("COPERNICUSMARINE_SERVICE_PASSWORD") or None

    copernicusmarine.subset(
        dataset_id=dataset_id,
        variables=variables,
        minimum_longitude=aoi["min_lon"],
        maximum_longitude=aoi["max_lon"],
        minimum_latitude=aoi["min_lat"],
        maximum_latitude=aoi["max_lat"],
        start_datetime=f"{target_date}T00:00:00",
        end_datetime=f"{target_date}T23:59:59",
        output_filename=output_filename,
        output_directory=output_directory,
        username=username,
        password=password,
        overwrite=True,
    )

    return os.path.join(output_directory, output_filename)


def fetch_mld(target_date: str) -> xr.DataArray:
    """
    Fetch (and cache) the Copernicus Marine mixed layer depth (`mlotst`)
    field for the given date, following the exact same fetch/auth/caching
    pattern as `fetch_daily_ocean_data()`'s thetao/uo/vo/zos fetches, and
    return a plain 2D (lat, lon) DataArray ready for the gradient/
    normalization pipeline -- same "fetch + open + squeeze" shape as
    `load_erddap_layer()`.

    NOTE: `config.COPERNICUS_DATASETS["mld"]["dataset_id"]` is an assumed
    dataset id (same combined dataset as "ssha"/zos), not yet confirmed
    against a live Copernicus Marine catalogue query in this environment --
    see the comment there and `.squad/decisions/inbox/ash-mld-moonphase.md`.
    """
    cfg = config.COPERNICUS_DATASETS["mld"]
    path = fetch_copernicus_subset(
        dataset_id=cfg["dataset_id"],
        variables=cfg["variables"],
        target_date=target_date,
        output_filename=f"mld_{target_date}.nc",
    )
    ds = xr.open_dataset(path)
    mld = ds["mlotst"]
    if "time" in mld.dims:
        mld = mld.isel(time=0)
    if "depth" in mld.dims:
        mld = mld.isel(depth=0)  # surface-referenced value only

    # Real Copernicus Marine NetCDF output uses "latitude"/"longitude" dim
    # names (see load_bathymetry()/overlay._prep_spatial() for the same
    # rename applied elsewhere in this pipeline) -- normalize to lat/lon
    # here so this raster is directly exportable/composable without every
    # caller needing to know which naming convention the source used.
    rename_map = {}
    if "latitude" in mld.dims:
        rename_map["latitude"] = "lat"
    if "longitude" in mld.dims:
        rename_map["longitude"] = "lon"
    if rename_map:
        mld = mld.rename(rename_map)

    mld.name = "mlotst"
    return mld


def fetch_mld_v2(target_date: str) -> xr.DataArray:
    """
    v2 counterpart of `fetch_mld`: fetches the same Copernicus Marine
    mixed layer depth (`mlotst`) field, but clipped to the wider
    `config.AOI_V2` extent and cached under a `_v2`-suffixed filename so it
    never collides with v1's cached file for the same date. Reused
    unmodified as one of v2's 7 WLC factors (see
    config.LAYER_WEIGHTS_V2["mld_gradient"] / pipeline_v2.py), same
    unverified-dataset-id caveat as `fetch_mld` above applies here too.
    """
    cfg = config.COPERNICUS_DATASETS["mld"]
    path = fetch_copernicus_subset(
        dataset_id=cfg["dataset_id"],
        variables=cfg["variables"],
        target_date=target_date,
        output_filename=f"mld_v2_{target_date}.nc",
        aoi=config.AOI_V2,
    )
    ds = xr.open_dataset(path)
    mld = ds["mlotst"]
    if "time" in mld.dims:
        mld = mld.isel(time=0)
    if "depth" in mld.dims:
        mld = mld.isel(depth=0)  # surface-referenced value only

    rename_map = {}
    if "latitude" in mld.dims:
        rename_map["latitude"] = "lat"
    if "longitude" in mld.dims:
        rename_map["longitude"] = "lon"
    if rename_map:
        mld = mld.rename(rename_map)

    mld.name = "mlotst"
    return mld


def fetch_current_velocity_series(
    start_date: str,
    n_days: int,
    output_directory: str = config.RAW_DATA_DIR,
) -> xr.Dataset:
    """
    Fetch `n_days` of daily surface current vectors (u/v), starting at
    `start_date`, from the Copernicus Marine analysis-forecast product.

    Needed for the FSLE diagnostic layer (see fsle.py), which integrates
    Lagrangian particle trajectories forward in time -- a single day's
    snapshot (as used elsewhere in the pipeline) can't reveal how currents
    evolve over multiple days, which is what actually separates drifting
    particles and reveals convergence fronts. Relies on the "anfc"
    (analysis-and-forecast) product's rolling forecast window extending
    far enough beyond `start_date`; raises if it doesn't.
    """
    import copernicusmarine  # lazy import: keeps this module importable without the dependency

    cfg = config.COPERNICUS_DATASETS["currents"]
    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = start_dt + timedelta(days=n_days - 1)
    output_filename = f"currents_series_{start_date}_{n_days}d.nc"

    _ensure_dir(output_directory)
    logger.info(
        "Requesting %d-day current time series dataset=%s date_range=%s..%s",
        n_days, cfg["dataset_id"], start_date, end_dt.strftime("%Y-%m-%d"),
    )

    username = os.environ.get("COPERNICUSMARINE_SERVICE_USERNAME") or None
    password = os.environ.get("COPERNICUSMARINE_SERVICE_PASSWORD") or None

    copernicusmarine.subset(
        dataset_id=cfg["dataset_id"],
        variables=cfg["variables"],
        minimum_longitude=config.AOI["min_lon"],
        maximum_longitude=config.AOI["max_lon"],
        minimum_latitude=config.AOI["min_lat"],
        maximum_latitude=config.AOI["max_lat"],
        start_datetime=f"{start_date}T00:00:00",
        end_datetime=f"{end_dt.strftime('%Y-%m-%d')}T23:59:59",
        output_filename=output_filename,
        output_directory=output_directory,
        username=username,
        password=password,
        overwrite=True,
    )

    path = os.path.join(output_directory, output_filename)
    ds = xr.open_dataset(path)
    if "depth" in ds.dims:
        ds = ds.isel(depth=0)
    return ds


def fetch_daily_ocean_data(target_date: str) -> Dict[str, xr.Dataset]:
    """
    Fetch SST, currents, SSHA (physics) and chlorophyll-a (biogeochemistry)
    data for the given date and return them as opened xarray Datasets.

    Copernicus Marine publishes SST, currents, and SSHA as separate
    single-variable datasets, so each is fetched independently and merged
    into one "physics" Dataset.
    """
    datasets: Dict[str, xr.Dataset] = {}

    physics_parts = []
    for key in ("sst", "currents", "ssha"):
        cfg = config.COPERNICUS_DATASETS[key]
        path = fetch_copernicus_subset(
            dataset_id=cfg["dataset_id"],
            variables=cfg["variables"],
            target_date=target_date,
            output_filename=f"{key}_{target_date}.nc",
        )
        physics_parts.append(xr.open_dataset(path))
    datasets["physics"] = xr.merge(physics_parts, compat="override", join="inner")

    bgc_cfg = config.COPERNICUS_DATASETS["biogeochemistry"]
    bgc_path = fetch_copernicus_subset(
        dataset_id=bgc_cfg["dataset_id"],
        variables=bgc_cfg["variables"],
        target_date=target_date,
        output_filename=f"bgc_{target_date}.nc",
    )
    datasets["biogeochemistry"] = xr.open_dataset(bgc_path)

    return datasets


def fetch_daily_ocean_data_v2(target_date: str) -> Dict[str, xr.Dataset]:
    """
    v2 counterpart of `fetch_daily_ocean_data`: fetches the same SST,
    currents, SSHA (physics) and chlorophyll-a (biogeochemistry) data, but
    clipped to the wider `config.AOI_V2` extent and cached under
    `_v2`-suffixed filenames so v1 and v2 fetches for the same date never
    collide in the raw data cache.
    """
    datasets: Dict[str, xr.Dataset] = {}

    physics_parts = []
    for key in ("sst", "currents", "ssha"):
        cfg = config.COPERNICUS_DATASETS[key]
        path = fetch_copernicus_subset(
            dataset_id=cfg["dataset_id"],
            variables=cfg["variables"],
            target_date=target_date,
            output_filename=f"{key}_v2_{target_date}.nc",
            aoi=config.AOI_V2,
        )
        physics_parts.append(xr.open_dataset(path))
    datasets["physics"] = xr.merge(physics_parts, compat="override", join="inner")

    bgc_cfg = config.COPERNICUS_DATASETS["biogeochemistry"]
    bgc_path = fetch_copernicus_subset(
        dataset_id=bgc_cfg["dataset_id"],
        variables=bgc_cfg["variables"],
        target_date=target_date,
        output_filename=f"bgc_v2_{target_date}.nc",
        aoi=config.AOI_V2,
    )
    datasets["biogeochemistry"] = xr.open_dataset(bgc_path)

    return datasets


def load_bathymetry() -> xr.DataArray:
    """
    Load the static bathymetry grid (e.g. GEBCO) and clip it to the AOI.

    Returns a DataArray of *positive-down depth in metres* named "depth".
    """
    if not os.path.exists(config.BATHYMETRY_NC_PATH):
        raise FileNotFoundError(
            f"Bathymetry grid not found at {config.BATHYMETRY_NC_PATH}. "
            "Download a GEBCO/AusSeabed NetCDF grid and set BATHYMETRY_NC_PATH."
        )

    ds = xr.open_dataset(config.BATHYMETRY_NC_PATH)

    # GEBCO uses "elevation" (negative = below sea level); AusSeabed grids
    # sometimes already publish positive-down "depth".
    if "elevation" in ds.data_vars:
        depth = -ds["elevation"]
    elif "depth" in ds.data_vars:
        depth = ds["depth"]
    else:
        raise KeyError(f"Could not find an elevation/depth variable in {list(ds.data_vars)}")

    lat_name = "lat" if "lat" in depth.coords else "latitude"
    lon_name = "lon" if "lon" in depth.coords else "longitude"

    depth = depth.sortby(lat_name).sel(
        {
            lat_name: slice(config.AOI["min_lat"], config.AOI["max_lat"]),
            lon_name: slice(config.AOI["min_lon"], config.AOI["max_lon"]),
        }
    )
    depth.name = "depth"
    return depth


def load_bathymetry_v2() -> xr.DataArray:
    """
    v2 counterpart of `load_bathymetry`: loads the wider-coverage GEBCO
    grid (`config.BATHYMETRY_V2_NC_PATH`, verified to genuinely cover
    Tweed Canyon/Noosa Canyon plus a comfortable structure-scoring buffer
    around both) and clips it to `config.AOI_V2` instead of v1's
    `BATHYMETRY_NC_PATH`/`AOI`.

    Returns a DataArray of *positive-down depth in metres* named "depth",
    same convention as `load_bathymetry`, used as v2's alignment reference
    grid (see overlay_v2.py::weighted_overlay_v2) and as the direct input
    to structure_layers.py::compute_structure_score.
    """
    if not os.path.exists(config.BATHYMETRY_V2_NC_PATH):
        raise FileNotFoundError(
            f"v2 bathymetry grid not found at {config.BATHYMETRY_V2_NC_PATH}. "
            "Fetch a GEBCO/AusSeabed NetCDF grid covering AOI_V2 and set BATHYMETRY_V2_NC_PATH."
        )

    ds = xr.open_dataset(config.BATHYMETRY_V2_NC_PATH)

    if "elevation" in ds.data_vars:
        depth = -ds["elevation"]
    elif "depth" in ds.data_vars:
        depth = ds["depth"]
    else:
        raise KeyError(f"Could not find an elevation/depth variable in {list(ds.data_vars)}")

    lat_name = "lat" if "lat" in depth.coords else "latitude"
    lon_name = "lon" if "lon" in depth.coords else "longitude"

    depth = depth.sortby(lat_name).sel(
        {
            lat_name: slice(config.AOI_V2["min_lat"], config.AOI_V2["max_lat"]),
            lon_name: slice(config.AOI_V2["min_lon"], config.AOI_V2["max_lon"]),
        }
    )
    depth.name = "depth"
    return depth


def fetch_tide_data(
    output_directory: str = config.RAW_DATA_DIR,
    timeout: int = 15,
) -> pd.DataFrame:
    """
    Fetch the Queensland Government DES storm-tide telemetry/predictions
    feed (`config.TIDE_DATA_URL`) and parse it into a pandas DataFrame.

    Supersedes the earlier "tide data permanently unavailable" conclusion
    (see .squad/decisions/inbox/ripley-moon-tide-data.md) -- astral (the
    only astronomy library already installed) genuinely has no tidal
    model, but this DES feed is a real, live, unauthenticated data source
    that was not previously known/checked.

    Real schema (LIVE-VERIFIED 2026-07-22, not assumed):
        Site, Seconds, DateTime, Water Level, Prediction, Residual,
        Latitude, Longitude
    covering ~23 QLD sites at a 10-minute sampling interval. Two quirks
    confirmed by inspecting a real response, not guessed:
      - The response body's first line is a human-readable
        "Tide Data provided @ HH:MMhrs on DD-MM-YYYY" banner, not part of
        the CSV header -- skipped here via `skiprows=1`.
      - `DateTime` values (e.g. "2026-07-08T00:00") have no timezone
        suffix; confirmed this is local Queensland time. QLD does not
        observe daylight saving, so `Australia/Brisbane` is a fixed
        UTC+10 offset year-round -- localizing is unambiguous (no DST
        "repeated"/"missing" hour edge cases possible).
      - `Water Level`/`Residual` (but not `Prediction`) can contain a
        `-99` sentinel for the newest 1-2 rows where the real-time gauge
        reading isn't in yet -- irrelevant here since tide-state/turning-
        point logic (see tide.py) uses the pure astronomical `Prediction`
        column, not the observed `Water Level`.

    Unlike every other `fetch_*` function in this module, this feed is not
    parameterized by a `target_date` -- the DES server always returns
    whatever rolling ~7-day window (observed in practice: ending at the
    most recent 10-minute tick) it currently has published. So there is no
    per-date output filename to cache under; instead the latest successful
    raw response is cached to a fixed path and used as a fallback if a
    later request fails (network hiccup, DES server maintenance, etc.),
    so a transient outage doesn't take every tide-dependent caller down
    with it.

    Raises RuntimeError if the live fetch fails and no usable cached copy
    exists yet.
    """
    _ensure_dir(output_directory)
    cache_path = os.path.join(output_directory, "tide_data_latest.csv")

    try:
        response = requests.get(config.TIDE_DATA_URL, timeout=timeout)
        response.raise_for_status()
        raw_text = response.text
    except requests.exceptions.RequestException as exc:
        if os.path.exists(cache_path):
            logger.warning(
                "Live fetch of QLD DES tide data failed (%s); falling back to the "
                "last cached copy at %s (may be stale).",
                exc,
                cache_path,
            )
            with open(cache_path, "r", encoding="utf-8") as f:
                raw_text = f.read()
        else:
            raise RuntimeError(
                f"Failed to fetch tide data from {config.TIDE_DATA_URL}: {exc}"
            ) from exc
    else:
        with open(cache_path, "w", encoding="utf-8", newline="") as f:
            f.write(raw_text)

    df = pd.read_csv(io.StringIO(raw_text), skiprows=1, skipinitialspace=True)
    df["DateTime"] = pd.to_datetime(df["DateTime"]).dt.tz_localize(config.TIDE_TIMEZONE)
    return df
