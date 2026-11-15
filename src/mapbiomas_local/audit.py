from __future__ import annotations

import json
import logging
import random
from pathlib import Path

import numpy as np
import rasterio

from .config import RunConfig
from .raster_io import discover_years

logger = logging.getLogger(__name__)


def _raster_profile(path: Path) -> dict:
    with rasterio.open(path) as ds:
        return {
            "file": path.name,
            "size_mb": round(path.stat().st_size / 1e6, 1),
            "driver": ds.driver,
            "count": ds.count,
            "dtype": ds.dtypes[0],
            "nodata": ds.nodata,
            "crs": str(ds.crs),
            "width": ds.width,
            "height": ds.height,
            "pixels": ds.width * ds.height,
            "transform": list(ds.transform)[:6],
            "bounds": list(ds.bounds),
            "resolution": [ds.transform.a, abs(ds.transform.e)],
            "tiled": bool(ds.profile.get("tiled")),
            "block_shapes": ds.block_shapes,
            "compress": ds.profile.get("compress"),
            "predictor": ds.profile.get("predictor"),
            "overview_levels": ds.overviews(1),
            "band_descriptions": ds.descriptions,
            "tags": ds.tags(),
        }


def _sample_classes(path: Path, n_blocks: int, block_size: int, seed: int) -> list[int]:
    rng = random.Random(seed)
    classes: set[int] = set()
    with rasterio.open(path) as ds:
        for _ in range(n_blocks):
            max_row = max(0, ds.height - block_size)
            max_col = max(0, ds.width - block_size)
            row = rng.randrange(0, max_row + 1)
            col = rng.randrange(0, max_col + 1)
            window = rasterio.windows.Window(
                col, row, min(block_size, ds.width), min(block_size, ds.height)
            )
            data = ds.read(1, window=window)
            classes.update(int(v) for v in np.unique(data))
    return sorted(classes)


def audit_rasters(
    input_dir: str | Path,
    pattern: str,
    n_blocks: int = 12,
    block_size: int = 512,
    seed: int = 0,
) -> dict:
    paths = discover_years(input_dir, pattern)
    profiles = {}
    classes = {}
    for year, path in paths.items():
        profiles[year] = _raster_profile(path)
        classes[year] = _sample_classes(path, n_blocks, block_size, seed + year)
    keys = [
        "crs",
        "width",
        "height",
        "transform",
        "dtype",
        "nodata",
        "tiled",
        "block_shapes",
        "compress",
        "count",
    ]
    varying = {}
    for key in keys:
        values = {json.dumps(profile[key], default=str) for profile in profiles.values()}
        if len(values) > 1:
            varying[key] = sorted(values)
    years = sorted(paths)
    total_bytes = sum(path.stat().st_size for path in paths.values())
    report = {
        "years": years,
        "n_files": len(paths),
        "total_size_gb": round(total_bytes / 1e9, 2),
        "pixels_per_raster": profiles[years[0]]["pixels"],
        "uncompressed_pixels_all_years": profiles[years[0]]["pixels"] * len(paths),
        "grid_varying_keys": varying,
        "grid_consistent": not varying,
        "classes_sampled_native": classes,
        "class_union": sorted({c for values in classes.values() for c in values}),
        "profiles": {str(year): profiles[year] for year in years},
        "warnings": [],
    }
    if varying:
        report["warnings"].append(
            "Raster grids differ across years; reprojection or alignment is required."
        )
    report["warnings"].append(
        "Overview levels may have been generated with averaging. Never use decimated "
        "reads for categorical analysis; always read native resolution."
    )
    return report


def write_audit_report(config: RunConfig, n_blocks: int = 12) -> dict:
    config.create_output_dirs()
    report = audit_rasters(config.input_dir, config.filename_pattern, n_blocks=n_blocks)
    report["configuration"] = config.to_dict()
    json_path = config.reports_dir / "audit_report.json"
    json_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )
    md_path = config.reports_dir / "audit_report.md"
    lines = [
        "# Data audit",
        "",
        f"- Raster files: {report['n_files']}",
        f"- Years: {report['years'][0]}..{report['years'][-1]}",
        f"- Total size: {report['total_size_gb']} GB",
        f"- Pixels per raster: {report['pixels_per_raster']:,}",
        f"- Grid consistent: {report['grid_consistent']}",
        f"- Native classes (sampled): {report['class_union']}",
        "",
        "## Warnings",
        "",
    ]
    lines.extend(f"- {warning}" for warning in report["warnings"])
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"json": json_path, "markdown": md_path, "report": report}
