"""
Lenigas wind data ingestion.

NEW data source for the "Lenigas" scoring model -- no wind ingestion
existed anywhere in this pipeline before this module (confirmed via a
full-codebase search). Separate, additive-only module: does not import
from or modify data_ingestion.py's v1/v2 functions, and v1/v2
config/output are completely untouched.

Source: NOAA CoastWatch ERDDAP (the same public, no-auth server already
used for MUR SST / VIIRS chlorophyll -- see
data_ingestion.py::fetch_erddap_subset), dataset `erdQCwindproducts7day`:
Metop-C ASCAT scatterometer wind, merged into a 7-day rolling composite
(wind_speed, wind_direction, wind_u, wind_v at 10m height, ~0.333deg/
~35km resolution), real coverage 2021-08-31-present.

Why the 7-day composite and not the 1-day composite: both were
live-tested (see .squad/decisions/inbox/ash-lenigas-implementation.md).
The 1-day composite (`erdQCwindproducts1day`) was found to be ENTIRELY
NaN across `config.AOI_V2` on the one date tested -- near-coast ASCAT
quality-control masking can evidently blank out the whole AOI on a given
day. The 7-day composite reliably had ~75-80% finite coverage across 3
independently-tested dates spanning 2023 and 2026 -- a real, verified
tradeoff of temporal freshness for spatial completeness, not an
arbitrary choice.
"""
import logging
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone

import xarray as xr

from . import config

logger = logging.getLogger(__name__)

# Same NOAA ERDDAP User-Agent requirement as data_ingestion.py's
# fetch_erddap_subset (the server rejects/redirects some requests
# without a browser-like UA).
_ERDDAP_USER_AGENT = "Mozilla/5.0 (compatible; FisherBiteScorePipeline/1.0)"


def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def _download_erddap_url(url: str, output_path: str) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": _ERDDAP_USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as response, open(output_path, "wb") as f:
        f.write(response.read())


def fetch_wind_data_lenigas(
    target_date: str,
    output_directory: str = config.RAW_DATA_DIR,
    aoi: dict = config.AOI_V2,
) -> xr.Dataset:
    """
    Fetch (and cache) real wind speed/direction/u/v for the Lenigas
    model, clipped to `aoi` (defaults to `config.AOI_V2`), from NOAA
    CoastWatch ERDDAP's `erdQCwindproducts7day` dataset (see module
    docstring for why this dataset was chosen over the daily composite).

    Follows the same "(last)" fallback pattern as
    `data_ingestion.py::fetch_erddap_subset` for dates not yet published
    (this feed has a real ~5-6 week production lag), bounded by
    `config.LENIGAS_WIND_MAX_LATEST_FALLBACK_AGE_DAYS` so a genuine
    multi-month archive gap can't silently substitute a far-off date.

    Returns an opened `xr.Dataset` with `wind_speed` (m/s),
    `wind_direction` (degrees, direction the wind is FROM), `wind_u`/
    `wind_v` (m/s, eastward/northward components) on `lat`/`lon` dims
    (renamed from the source's `latitude`/`longitude`), with the scalar
    `time`/`altitude` dims squeezed out. No authentication required;
    NOAA ERDDAP griddap endpoints are public.
    """
    dataset_id = config.LENIGAS_WIND_ERDDAP_DATASET_ID
    variables = config.LENIGAS_WIND_ERDDAP_VARIABLES
    altitude = config.LENIGAS_WIND_ALTITUDE_M

    _ensure_dir(output_directory)

    lat_range = f"({aoi['min_lat']}):1:({aoi['max_lat']})"
    lon_range = f"({aoi['min_lon']}):1:({aoi['max_lon']})"

    def _build_url(time_dim: str) -> str:
        dims = f"[{time_dim}][({altitude})][{lat_range}][{lon_range}]"
        query = ",".join(f"{var}{dims}" for var in variables)
        return f"{config.ERDDAP_BASE_URL}/{dataset_id}.nc?{query}"

    logger.info(
        "Requesting Lenigas wind data dataset=%s date=%s", dataset_id, target_date
    )
    output_path = os.path.join(output_directory, f"wind_lenigas_{target_date}.nc")
    time_dim = f"({target_date}T12:00:00Z):1:({target_date}T12:00:00Z)"

    try:
        _download_erddap_url(_build_url(time_dim), output_path)
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            raise RuntimeError(
                f"Failed to fetch {dataset_id} wind data from NOAA ERDDAP for "
                f"{target_date}: {exc}"
            ) from exc

        # No granule for the exact requested date. Only fall back to
        # "latest available" if the requested date is recent enough that
        # normal production lag is a plausible explanation -- otherwise a
        # genuinely historical request would silently get mislabeled with
        # today's wind conditions. See
        # config.LENIGAS_WIND_MAX_LATEST_FALLBACK_AGE_DAYS.
        target_dt = datetime.strptime(target_date, "%Y-%m-%d")
        age_days = (datetime.now(timezone.utc).replace(tzinfo=None) - target_dt).days
        if abs(age_days) > config.LENIGAS_WIND_MAX_LATEST_FALLBACK_AGE_DAYS:
            raise RuntimeError(
                f"{dataset_id} has no granule for {target_date} (no exact match), "
                f"which is {age_days} days from today -- beyond the "
                f"{config.LENIGAS_WIND_MAX_LATEST_FALLBACK_AGE_DAYS}-day window this "
                "dataset's rolling archive/production lag plausibly covers. Refusing "
                "to silently substitute the latest available granule for a gap this "
                "large."
            ) from exc

        logger.warning(
            "%s has no exact granule for %s; falling back to the most recent "
            "available date",
            dataset_id, target_date,
        )
        fallback_path = os.path.join(output_directory, "wind_lenigas_latest.nc")
        try:
            _download_erddap_url(_build_url("(last):1:(last)"), fallback_path)
        except Exception as fallback_exc:
            raise RuntimeError(
                f"Failed to fetch {dataset_id} wind data from NOAA ERDDAP (both "
                f"{target_date} and latest failed): {fallback_exc}"
            ) from fallback_exc
        output_path = fallback_path

    ds = xr.open_dataset(output_path)

    rename_map = {}
    if "latitude" in ds.dims:
        rename_map["latitude"] = "lat"
    if "longitude" in ds.dims:
        rename_map["longitude"] = "lon"
    if rename_map:
        ds = ds.rename(rename_map)

    if "time" in ds.dims:
        ds = ds.isel(time=0)
    if "altitude" in ds.dims:
        ds = ds.isel(altitude=0)

    return ds
