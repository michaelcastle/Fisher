"""
Offline demo runner: generates synthetic SST/CHL/current/bathymetry fields
for the Southeast Queensland AOI (no Copernicus credentials required),
runs them through the real `bite_score` processing -> normalization ->
WLC overlay pipeline, and exports a GeoTIFF + interactive Folium/Plotly
maps.

Usage:
    python run_demo.py
"""
import logging
import os

from bite_score import config
from bite_score.demo_data import (
    generate_bathymetry,
    generate_biogeochemistry_dataset,
    generate_current_time_series,
    generate_physics_dataset,
)
from bite_score.fsle import compute_fsle_field
from bite_score.pipeline import compute_bite_score, compute_bite_score_legacy
from bite_score.export import export_geotiff
from bite_score.visualize import build_folium_map, build_plotly_map

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)


def main():
    logger.info("=== Yellowfin Tuna Bite Score DEMO (synthetic data, SE Queensland) ===")

    physics = generate_physics_dataset()
    bgc = generate_biogeochemistry_dataset()
    depth = generate_bathymetry()

    sst = physics["thetao"].isel(time=0)
    uo = physics["uo"].isel(time=0)
    vo = physics["vo"].isel(time=0)
    chl = bgc["chl"].isel(time=0)
    ssha = physics["zos"].isel(time=0)

    bite_score, layer_scores = compute_bite_score(sst, uo, vo, chl, ssha, depth)
    bite_score_legacy = compute_bite_score_legacy(sst, uo, vo, chl, depth)

    logger.info(
        "Bite score stats -> min=%.1f max=%.1f mean=%.1f",
        float(bite_score.min()),
        float(bite_score.max()),
        float(bite_score.mean()),
    )

    # Archived under output/history/demo/ using the same filenames/layout
    # as a real dated pipeline run, so the shared bite_score_map.html
    # template's date-keyed API endpoints (/api/date-layer/demo/<key>/*,
    # see date_layers.py) can serve it identically -- view it via
    # `python -m bite_score.webapp` then browse to /history/demo.
    demo_dir = os.path.join(config.HISTORY_DIR, "demo")
    os.makedirs(demo_dir, exist_ok=True)

    geotiff_path = export_geotiff(bite_score, output_path=os.path.join(demo_dir, "bite_score.tif"))
    legacy_geotiff_path = export_geotiff(
        bite_score_legacy, output_path=os.path.join(demo_dir, "bite_score_legacy.tif")
    )
    layer_geotiff_paths = {
        key: export_geotiff(layer, output_path=os.path.join(demo_dir, f"layer_{key}.tif"))
        for key, layer in layer_scores.items()
        if key != "bathymetry"
    }

    # Synthetic FSLE diagnostic layer -- exercises the same Lagrangian-
    # integration code path (fsle.py) as the real pipeline, using a
    # synthetic drifting-eddy current time series instead of a real
    # multi-day Copernicus forecast fetch.
    current_series = generate_current_time_series()
    fsle_field = compute_fsle_field(current_series)
    fsle_geotiff_path = export_geotiff(fsle_field, output_path=os.path.join(demo_dir, "layer_fsle.tif"))

    # Real (not synthetic) high-resolution Sunshine Coast LiDAR bathymetry,
    # and the two further AusSeabed multibeam survey layers (Moreton Bay
    # Approaches, Mudjimba Island), plus the Depth-suitability factor, are
    # static datasets independent of the demo's synthetic fields -- they're
    # now built once and shared across every date's map (see
    # static_layers.py, served on demand by webapp.py) rather than being
    # built here.

    # A single shared bite_score_map.html template now serves every date,
    # including "demo" -- per-date layers are fetched lazily client-side
    # from /api/date-layer/demo/<key>/* rather than baked into the HTML.
    build_folium_map(output_html="bite_score_map.html")
    build_plotly_map(geotiff_path)

    logger.info("Demo complete.")
    logger.info("GeoTIFF: %s", geotiff_path)
    logger.info("Interactive map: run `python -m bite_score.webapp` then open http://localhost:8000/history/demo")



if __name__ == "__main__":
    main()

