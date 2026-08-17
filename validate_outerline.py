"""
Validation script for the "Outerline Method" (v3) Yellowfin Environmental
Hotspot Score against the real 11 October 2023 Point Lookout event: real
yellowfin busting up extensively at ~250m depth, east of Point Lookout,
QLD (fishermen intended to continue out to ~1,000m but didn't need to --
strong evidence depth alone is NOT predictive of yellowfin presence).

This script deliberately does NOT tune the model to make the known event
site score highly. It runs the Outerline pipeline against real historical
data exactly as it existed on 2023-10-11 (subject to whatever historical
data sources are actually available for that date -- e.g. FSLE requires
forward-forecast days that don't exist for a date this far in the past,
so it will legitimately be absent and its weight redistributed, same as
every other model in this codebase), then reports, honestly:

  1. The Outerline score at the real historical event location (the
     actual grid cell nearest ~250m depth, east of Point Lookout --
     derived from real bathymetry data, not an assumed coordinate).
  2. The single highest-ranked hotspot anywhere in the AOI that day.
  3. The distance between the two.
  4. Which components agreed (favourable at both locations) and which
     disagreed (favourable only at the global maximum).

Usage:
    python validate_outerline.py
    python validate_outerline.py --date 2023-10-11 --skip-run   # reuse a prior run
"""
import argparse
import logging
import os

import numpy as np
import rioxarray  # noqa: F401  (registers the .rio accessor)

from bite_score import config
from bite_score.data_ingestion import load_bathymetry_v2
from bite_score.date_layers import DATE_LAYER_SPECS_OUTERLINE
from bite_score.main import run_pipeline_outerline
from bite_score.pipeline_outerline import sample_point_outerline_from_date
from bite_score.structure_layers import _haversine_distance_km

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

TARGET_DATE = "2023-10-11"
POINT_LOOKOUT_LAT = -27.4322
POINT_LOOKOUT_LON = 153.5473


def find_known_site(target_lat: float = POINT_LOOKOUT_LAT, base_lon: float = POINT_LOOKOUT_LON, target_depth_m: float = 250.0):
    """
    Locate the real grid cell nearest Point Lookout's latitude, EAST of
    the coastline, whose bathymetry is closest to `target_depth_m` --
    the real historical event location derived from actual GEBCO/survey
    bathymetry data, rather than an assumed/guessed coordinate.
    """
    depth = load_bathymetry_v2()
    lat_name = "lat" if "lat" in depth.dims else "latitude"
    lon_name = "lon" if "lon" in depth.dims else "longitude"

    row = depth.sel({lat_name: target_lat}, method="nearest")
    lons = row[lon_name].values
    values = row.values

    east_mask = lons > base_lon
    candidate_lons = lons[east_mask]
    candidate_depths = values[east_mask]
    finite = np.isfinite(candidate_depths) & (candidate_depths > 0)
    candidate_lons = candidate_lons[finite]
    candidate_depths = candidate_depths[finite]

    if candidate_lons.size == 0:
        raise RuntimeError("No finite offshore bathymetry found east of Point Lookout at this latitude")

    idx = int(np.argmin(np.abs(candidate_depths - target_depth_m)))
    found_lat = float(row[lat_name].values)
    found_lon = float(candidate_lons[idx])
    found_depth = float(candidate_depths[idx])
    return found_lat, found_lon, found_depth


def find_global_hotspot(date: str):
    """Locate the single highest-scoring grid cell anywhere in the AOI for `date`."""
    outerline_dir = os.path.join(config.HISTORY_DIR, date, config.OUTERLINE_OUTPUT_SUBDIR)
    path = os.path.join(outerline_dir, DATE_LAYER_SPECS_OUTERLINE["hotspot_score_outerline"]["filename"])
    da = rioxarray.open_rasterio(path, masked=True).squeeze()
    values = da.values
    if not np.isfinite(values).any():
        raise RuntimeError("Outerline hotspot raster has no finite values")
    flat_idx = int(np.nanargmax(values))
    row_idx, col_idx = np.unravel_index(flat_idx, values.shape)
    lat = float(da["y"].values[row_idx])
    lon = float(da["x"].values[col_idx])
    return lat, lon


def _print_site(label: str, result: dict, extra: str = "") -> None:
    print(f"\n{label}:")
    print(f"  lat={result['grid_cell']['lat']:.4f}  lon={result['grid_cell']['lon']:.4f}{extra}")
    print(f"  Hotspot score: {result['hotspot_score']:.1f} / 100")
    print(f"  Feature convergence count: {result['feature_convergence_count']:.0f}")
    print(f"  Explanation: {result['explanation']}")
    print("  Component breakdown:")
    for key, value in sorted(result["components"].items()):
        shown = "n/a" if value is None else f"{value:.1f}"
        print(f"    {key:24s}: {shown}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", default=TARGET_DATE)
    parser.add_argument(
        "--skip-run", action="store_true",
        help="Reuse an already-computed Outerline run for this date instead of re-fetching data",
    )
    args = parser.parse_args()

    if not args.skip_run:
        logger.info(
            "Running the Outerline Method pipeline for %s (historical data as it existed on that date)...",
            args.date,
        )
        run_pipeline_outerline(args.date)

    known_lat, known_lon, known_depth = find_known_site()
    logger.info(
        "Derived known-event site from real bathymetry: lat=%.4f lon=%.4f depth=%.1fm "
        "(nearest real grid cell to ~250m east of Point Lookout)",
        known_lat, known_lon, known_depth,
    )

    known_result = sample_point_outerline_from_date(args.date, known_lat, known_lon)
    max_lat, max_lon = find_global_hotspot(args.date)
    max_result = sample_point_outerline_from_date(args.date, max_lat, max_lon)

    distance_km = float(_haversine_distance_km(np.array([known_result["grid_cell"]["lat"]]), np.array([known_result["grid_cell"]["lon"]]), max_result["grid_cell"]["lat"], max_result["grid_cell"]["lon"])[0])

    print("=" * 78)
    print(f"OUTERLINE METHOD VALIDATION -- {args.date} (11 Oct 2023 Point Lookout event)")
    print("=" * 78)
    _print_site("Known event site (real ~250m depth east of Point Lookout)", known_result, extra=f"  depth={known_depth:.0f}m")
    _print_site("Highest-ranked hotspot anywhere in the AOI that day", max_result)

    print(f"\nDistance between known event site and the global maximum: {distance_km:.1f} km")

    threshold = config.FEATURE_PRESENCE_THRESHOLD_OUTERLINE
    known_c, max_c = known_result["components"], max_result["components"]

    print("\nComponents that AGREED (favourable, i.e. >= threshold, at BOTH locations):")
    agreed = False
    for key in config.CONVERGENCE_COUNT_COMPONENTS_OUTERLINE:
        kv, mv = known_c.get(key), max_c.get(key)
        if kv is not None and mv is not None and kv >= threshold and mv >= threshold:
            print(f"  {key}: known={kv:.1f}  max={mv:.1f}")
            agreed = True
    if not agreed:
        print("  (none)")

    print("\nComponents that DISAGREED (favourable at the global maximum, not at the known site):")
    disagreed = False
    for key in config.CONVERGENCE_COUNT_COMPONENTS_OUTERLINE:
        kv, mv = known_c.get(key), max_c.get(key)
        m_fav = mv is not None and mv >= threshold
        k_fav = kv is not None and kv >= threshold
        if m_fav and not k_fav:
            kv_str = "n/a" if kv is None else f"{kv:.1f}"
            print(f"  {key}: known={kv_str}  max={mv:.1f}")
            disagreed = True
    if not disagreed:
        print("  (none)")

    print(
        "\nNote: this model was NOT tuned to make the known event site score highly. "
        "Weights/thresholds are the standing config.WEIGHTS_OUTERLINE values, applied "
        "identically to every date."
    )


if __name__ == "__main__":
    main()
