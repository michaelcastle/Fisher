"""
Georeferences the Moreton Bay Game Fish Club "Fishing Locations" one-pager
PDF (http://www.mbgfc.com.au/uploads/1/4/3/5/143563089/1dfishinglocations.pdf)
into two cached, reusable assets:

  - a georeferenced RGB GeoTIFF of the chart raster itself (see
    `build_mbgfc_chart_geotiff`), for display as an optional map layer, and
  - a parsed list of exact FAD/SFAD/wave-buoy coordinates (see
    `load_mbgfc_locations`) lifted straight from the PDF's own text table,
    for display as point markers.

Chart raster reconstruction
----------------------------
The chart itself is not a single embedded image: PyMuPDF's
`page.get_image_info(xrefs=True)` shows it's split into 8 separate raster
strips (xrefs 75, 65, 66, 67, 68, 69, 70, 71) that are placed edge-to-edge,
top-to-bottom, with identical x-extents -- i.e. one large chart image tiled
into 8 vertical bands (probably a PDF-export size/memory limit on the
authoring side). They're reassembled here by pasting the raw pixmap bytes
in that order (not by re-rendering the page at some DPI, which would
resample/blur), giving a lossless 2355x3244px composite.

Georeferencing
----------------
The chart prints its own lat/lon reference grid (tick labels every 10' of
arc from 153E-155E and 26S-28S+), but those ticks are baked into the raster
image, not extractable as PDF text -- confirmed separately by checking that
every text word on the page matching a coordinate-like pattern belongs to
the FAD/SFAD table (PDF x 470-720pt), not the chart's own axis (a distinct,
non-overlapping region of the page). So the pixel<->lon/lat mapping below
was derived once via image-based gridline detection (column/row darkness
profiling on the stitched raster to find the bold degree gridlines) and
verified visually by overlaying the computed pixel positions back onto the
image and confirming they land exactly on the printed "153/154/155" and
"26/27/28" gridlines. The three measured pixel intervals per axis agree to
within ~0.15%, i.e. the chart uses a simple uniform (equirectangular)
degree grid rather than a true Mercator projection, so a single linear fit
per axis is used (no Mercator-inverse needed).
"""
import json
import logging
import os
import re

import numpy as np
import rasterio
import rasterio.transform
from PIL import Image

from . import config

logger = logging.getLogger(__name__)

# Order (top-to-bottom) of the embedded image strips that make up the full
# chart raster on page 0 of the PDF.
_STRIP_XREFS = [75, 65, 66, 67, 68, 69, 70, 71]

# Pixel calibration of the stitched (un-cropped) 2355x3244 raster -- see
# module docstring. Verified visually against the printed grid labels.
_CAL_PX_X = [303.0, 1188.0, 2074.0]   # pixel columns at 153E, 154E, 155E
_CAL_LON = [153.0, 154.0, 155.0]
_CAL_PX_Y = [690.0, 1686.0, 2681.0]   # pixel rows at 26S, 27S, 28S
_CAL_LAT = [-26.0, -27.0, -28.0]

# Crop box (stitched-image pixel space) of the outer chart border, so the
# exported GeoTIFF doesn't carry the surrounding white page margin / axis
# label strip.
_CROP_BOX = (46, 351, 2338, 3196)  # x0, y0, x1, y1

# PDF text-word x-range (points) that the FAD/SFAD/wave-buoy coordinate
# table occupies -- used to isolate its words from everything else on the
# page (titles, logos, disclaimers) when parsing locations.
_TABLE_X_RANGE = (470, 720)

_COORD_RE = re.compile(
    r"(\d+)\s*\u00b0\s*([\d.]+)\s*'\s*([NS])\s+(\d+)\s*\u00b0\s*([\d.]+)\s*'\s*([EW])"
)


def _stitch_chart_image(pdf_path: str) -> Image.Image:
    import fitz  # PyMuPDF -- optional heavy dependency, only needed to (re)build this cache

    doc = fitz.open(pdf_path)
    page = doc[0]
    strips = []
    for xref in _STRIP_XREFS:
        pix = fitz.Pixmap(doc, xref)
        strips.append(Image.frombytes("RGB", (pix.width, pix.height), pix.samples))

    width = strips[0].width
    total_height = sum(s.height for s in strips)
    stitched = Image.new("RGB", (width, total_height))
    y = 0
    for strip in strips:
        stitched.paste(strip, (0, y))
        y += strip.height
    return stitched


def build_mbgfc_chart_geotiff(force_rebuild: bool = False) -> str:
    """
    Reassemble + georeference the MBGFC chart raster into a cached RGB
    GeoTIFF (EPSG:4326) and return its path. Cached at
    `config.MBGFC_CHART_TIF_PATH`; only rebuilt if missing or
    `force_rebuild=True`, since the source PDF is static.
    """
    output_path = config.MBGFC_CHART_TIF_PATH
    if os.path.exists(output_path) and not force_rebuild:
        return output_path

    pdf_path = config.MBGFC_PDF_PATH
    if not os.path.exists(pdf_path):
        raise FileNotFoundError(f"MBGFC chart PDF not found at {pdf_path}")

    stitched = _stitch_chart_image(pdf_path)

    x0, y0, x1, y1 = _CROP_BOX
    cropped = stitched.crop((x0, y0, x1, y1))

    lon_slope, lon_intercept = (float(c) for c in np.polyfit(_CAL_PX_X, _CAL_LON, 1))
    lat_slope, lat_intercept = (float(c) for c in np.polyfit(_CAL_PX_Y, _CAL_LAT, 1))

    # Re-express the fit relative to the crop's own origin (pixel (0,0) in
    # the cropped image == pixel (x0, y0) in the original stitched image).
    origin_lon = lon_slope * x0 + lon_intercept
    origin_lat = lat_slope * y0 + lat_intercept

    transform = rasterio.transform.from_origin(
        origin_lon, origin_lat, lon_slope, -lat_slope
    )

    array = np.array(cropped)  # (H, W, 3) uint8
    bands = np.moveaxis(array, -1, 0)  # -> (3, H, W) for rasterio

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with rasterio.open(
        output_path,
        "w",
        driver="GTiff",
        height=bands.shape[1],
        width=bands.shape[2],
        count=3,
        dtype=bands.dtype,
        crs="EPSG:4326",
        transform=transform,
    ) as dst:
        dst.write(bands)

    logger.info(
        "Georeferenced MBGFC chart written to %s (%dx%d px)",
        output_path, bands.shape[2], bands.shape[1],
    )
    return output_path


def build_mbgfc_chart_png(force_rebuild: bool = False) -> tuple:
    """
    Derive a plain PNG + bounds-metadata JSON from the georeferenced
    GeoTIFF (see `build_mbgfc_chart_geotiff`) and return
    (png_path, meta_json_path).

    These are the assets the dashboard server (webapp.py) actually serves
    to the browser as standalone, static endpoints (`/api/mbgfc/chart.png`
    and `/api/mbgfc/meta`), so the chart layer is fetched at view time by
    every generated map page instead of being embedded into each one --
    it's a single shared resource, always available/selectable on any
    date's map, that never needs rebuilding when a new pipeline run/date
    is generated (only when the source PDF itself changes).
    """
    png_path = config.MBGFC_CHART_PNG_PATH
    meta_path = config.MBGFC_CHART_META_JSON_PATH
    if os.path.exists(png_path) and os.path.exists(meta_path) and not force_rebuild:
        return png_path, meta_path

    geotiff_path = build_mbgfc_chart_geotiff(force_rebuild=force_rebuild)
    with rasterio.open(geotiff_path) as src:
        rgb = src.read()  # (3, H, W)
        bounds = src.bounds  # (left, bottom, right, top)

    array = np.moveaxis(rgb, 0, -1)  # -> (H, W, 3)
    os.makedirs(os.path.dirname(png_path) or ".", exist_ok=True)
    Image.fromarray(array).save(png_path)

    meta = {
        "bounds": [[bounds.bottom, bounds.left], [bounds.top, bounds.right]],
    }
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)

    logger.info("MBGFC chart PNG + bounds written to %s / %s", png_path, meta_path)
    return png_path, meta_path


def _location_category(name: str) -> str:
    upper = name.upper()
    if "WAVE BUOY" in upper:
        return "wave_buoy"
    if upper.startswith("SFAD"):
        return "sfad"
    if upper.startswith("FAD"):
        return "fad"
    return "other"


def _parse_locations_from_pdf(pdf_path: str) -> list:
    import fitz  # PyMuPDF

    doc = fitz.open(pdf_path)
    page = doc[0]
    words = page.get_text("words")  # (x0, y0, x1, y1, word, block, line, word_no)
    lo, hi = _TABLE_X_RANGE
    table_words = [w for w in words if lo <= w[0] <= hi]

    blocks = {}
    for w in table_words:
        blocks.setdefault(w[5], []).append(w)

    records = []
    for block_id in sorted(blocks.keys()):
        ordered = sorted(blocks[block_id], key=lambda w: (w[6], w[0]))
        text = " ".join(w[4] for w in ordered)
        match = _COORD_RE.search(text)
        if not match:
            continue

        name = text[: match.start()].strip()
        if not name or name.lower() == "description":
            continue

        remainder = text[match.end():].strip()
        depth_match = re.search(r"\d+(\.\d+)?", remainder)
        depth_m = float(depth_match.group(0)) if depth_match else None

        lat_deg, lat_min, lat_hemi, lon_deg, lon_min, lon_hemi = match.groups()
        lat = float(lat_deg) + float(lat_min) / 60.0
        if lat_hemi == "S":
            lat = -lat
        lon = float(lon_deg) + float(lon_min) / 60.0
        if lon_hemi == "W":
            lon = -lon

        records.append({
            "name": name,
            "category": _location_category(name),
            "lat": round(lat, 5),
            "lon": round(lon, 5),
            "depth_m": depth_m,
        })

    return records


def load_mbgfc_locations(force_rebuild: bool = False) -> list:
    """
    Return the FAD/SFAD/wave-buoy coordinate table from the MBGFC chart PDF
    as a list of {name, category, lat, lon, depth_m} dicts, parsed directly
    from the PDF's own text (not the chart image), so it's exact rather
    than pixel-estimated. Cached to `config.MBGFC_LOCATIONS_JSON_PATH`.
    """
    cache_path = config.MBGFC_LOCATIONS_JSON_PATH
    if os.path.exists(cache_path) and not force_rebuild:
        with open(cache_path, "r", encoding="utf-8") as f:
            return json.load(f)

    pdf_path = config.MBGFC_PDF_PATH
    if not os.path.exists(pdf_path):
        raise FileNotFoundError(f"MBGFC chart PDF not found at {pdf_path}")

    records = _parse_locations_from_pdf(pdf_path)
    if not records:
        raise ValueError("No FAD/SFAD/wave-buoy locations parsed from MBGFC chart PDF")

    os.makedirs(os.path.dirname(cache_path) or ".", exist_ok=True)
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2)

    return records
