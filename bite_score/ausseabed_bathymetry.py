"""
Optional supplementary high-resolution bathymetry layers sourced from
Geoscience Australia's AusSeabed open data catalogue -- real multibeam
survey grids, far finer than the ~450m GEBCO grid used everywhere else in
the pipeline, covering two small areas near the Sunshine Coast / Moreton
Bay:

- "Approaches to Moreton Bay" (HIPP SI 1021, AHO/Fugro, 2023): 30m
  resolution, covering the offshore shelf between the Sunshine Coast and
  the Moreton Bay entrance.
- "Mudjimba Island" (DETSI/Port of Brisbane, 2024): 0.5m resolution, a
  small ~1.5km x 1.5km patch right off Mudjimba, Sunshine Coast.

Both are public, no-auth, Creative Commons Attribution 4.0 downloads
(https://ausseabed.gov.au) -- downloaded once and cached to disk, same
lazy/cached pattern as the locally-supplied Sunshine Coast LiDAR survey
(see lidar_bathymetry.py). Since these already arrive as gridded GeoTIFFs
in EPSG:4326 (unlike the raw XYZ LiDAR point clouds), no custom gridding
is needed here -- just download, unzip, flip sign to this pipeline's
positive-down depth convention, and re-export.
"""
import logging
import os
import urllib.request
import zipfile

import numpy as np
import rioxarray  # noqa: F401  (registers the .rio accessor)

from . import config
from .export import export_geotiff

logger = logging.getLogger(__name__)

# AusSeabed's file server rejects/redirects requests with no User-Agent
# (same gotcha as the NOAA ERDDAP fetches in data_ingestion.py) -- always
# identify explicitly.
_USER_AGENT = "Mozilla/5.0 (compatible; FisherBiteScorePipeline/1.0)"

_DATASETS = {
    "moreton_bay_approaches": {
        "label": "Moreton Bay Approaches bathymetry",
        "zip_url": (
            "https://files.ausseabed.gov.au/survey/"
            "Approaches%20to%20Moreton%20Bay%20(HIPP%20SI%201021)%20Bathymetry%202023%2030m.zip"
        ),
        "zip_member": "ApproachestoMortonBay_SI1021_Bathymetry_Depth_30m_2023_cog.tiff",
        "output_path": config.MORETON_BAY_APPROACHES_TIF_PATH,
        "resolution_m": 30.0,
    },
    "mudjimba_island": {
        "label": "Mudjimba Island bathymetry",
        "zip_url": (
            "https://files.ausseabed.gov.au/survey/"
            "Mudjimba%20Island%20Bathymetry%202024%200.5m.zip"
        ),
        "zip_member": "Mudjimba_Island_Bathymetry_2024_0_5m_MSL_cog.tif",
        "output_path": config.MUDJIMBA_ISLAND_TIF_PATH,
        "resolution_m": 0.5,
    },
}

# Public alias so other modules (e.g. visualize.py, for hillshade pixel
# spacing) don't need to reach into "private" dataset metadata.
RESOLUTION_M = {key: meta["resolution_m"] for key, meta in _DATASETS.items()}


def _download_and_extract(zip_url: str, zip_member: str, dest_dir: str) -> str:
    os.makedirs(dest_dir, exist_ok=True)
    zip_path = os.path.join(dest_dir, "_download.zip")
    logger.info("Downloading %s", zip_url)
    req = urllib.request.Request(zip_url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=180) as response, open(zip_path, "wb") as f:
        f.write(response.read())
    try:
        with zipfile.ZipFile(zip_path) as zf:
            zf.extract(zip_member, dest_dir)
    finally:
        os.remove(zip_path)
    return os.path.join(dest_dir, zip_member)


def _build_dataset_geotiff(key: str, force_rebuild: bool = False) -> str:
    meta = _DATASETS[key]
    output_path = meta["output_path"]
    if os.path.exists(output_path) and not force_rebuild:
        return output_path

    raw_dir = os.path.join(config.RAW_DATA_DIR, "ausseabed")
    tif_path = os.path.join(raw_dir, meta["zip_member"])
    if not os.path.exists(tif_path) or force_rebuild:
        tif_path = _download_and_extract(meta["zip_url"], meta["zip_member"], raw_dir)

    da = rioxarray.open_rasterio(tif_path, masked=True).squeeze()
    # AusSeabed grids store MSL depth as a negative elevation (e.g. -50 =
    # 50m underwater) -- flip sign to this pipeline's positive-down depth
    # convention (same as data_ingestion.load_bathymetry()/lidar_bathymetry.py).
    depth = (-da).astype("float32")
    depth = depth.rio.write_crs(da.rio.crs)
    depth = depth.rio.write_nodata(np.nan)

    export_geotiff(depth, output_path=output_path)
    logger.info("Cached %s bathymetry to %s", meta["label"], output_path)
    return output_path


def build_moreton_bay_approaches_geotiff(force_rebuild: bool = False) -> str:
    """
    Real 30m-resolution multibeam bathymetry (AHO/Fugro via Geoscience
    Australia, 2023, CC BY 4.0) covering the offshore approaches to Moreton
    Bay -- far finer than the ~450m GEBCO grid used elsewhere. Downloaded
    once from AusSeabed and cached; only re-downloaded if missing or
    `force_rebuild=True`.
    """
    return _build_dataset_geotiff("moreton_bay_approaches", force_rebuild)


def build_mudjimba_island_geotiff(force_rebuild: bool = False) -> str:
    """
    Real 0.5m-resolution multibeam bathymetry (DETSI/Port of Brisbane via
    Geoscience Australia, 2024, CC BY 4.0) covering a small ~1.5km x 1.5km
    patch around Mudjimba Island, Sunshine Coast. Downloaded once from
    AusSeabed and cached; only re-downloaded if missing or
    `force_rebuild=True`.
    """
    return _build_dataset_geotiff("mudjimba_island", force_rebuild)
