"""
Export the final Bite Score raster to a GeoTIFF using rioxarray/rasterio.
"""
import logging
import os

import numpy as np
import rioxarray  # noqa: F401  (registers the .rio accessor)
import xarray as xr

from . import config

logger = logging.getLogger(__name__)


def export_geotiff(bite_score: xr.DataArray, output_path: str = None, crs: str = config.CRS) -> str:
    """
    Write the Bite Score DataArray to disk as a single-band, LZW-compressed
    float32 GeoTIFF.
    """
    if output_path is None:
        os.makedirs(config.OUTPUT_DIR, exist_ok=True)
        output_path = os.path.join(config.OUTPUT_DIR, "bite_score.tif")
    else:
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    raster = bite_score.astype("float32")
    if "lat" in raster.dims and "lon" in raster.dims:
        raster = raster.rio.set_spatial_dims(x_dim="lon", y_dim="lat", inplace=False)
    if raster.rio.crs is None:
        raster = raster.rio.write_crs(crs)
    # Explicitly tag NaN as the nodata value so land/masked cells round-trip
    # correctly through GeoTIFF (GDAL/rioxarray don't infer nodata from the
    # pixel values alone -- without this tag, downstream `masked=True` reads
    # can't reliably distinguish "no data" from a real score of 0).
    raster = raster.rio.write_nodata(np.nan)

    raster.rio.to_raster(output_path, dtype="float32", compress="LZW")
    logger.info("Bite score raster written to %s", output_path)
    return output_path
