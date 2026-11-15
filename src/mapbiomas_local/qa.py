from __future__ import annotations

import json
import logging
import random
from pathlib import Path

import numpy as np
import rasterio
from tqdm import tqdm

from .config import RunConfig
from .raster_io import check_grids, iter_windows

logger = logging.getLogger(__name__)

VALID_CLASSES = {1, 2, 3, 4, 5, 6, 7}
ALLOWED_CLASSES = {0} | VALID_CLASSES


def _deforestation_paths(config: RunConfig) -> dict[int, Path]:
    paths = {}
    for path in sorted(config.deforestation_dir.glob("deforestation_*.tif")):
        try:
            year = int(path.stem.split("_")[-1])
        except ValueError:
            continue
        paths[year] = path
    if not paths:
        raise FileNotFoundError(f"No deforestation products in {config.deforestation_dir}")
    return dict(sorted(paths.items()))


def qa_products(
    config: RunConfig, progress: bool = True, sample_blocks: int | None = None
) -> dict:
    config.create_output_dirs()
    paths = _deforestation_paths(config)
    years = sorted(paths)
    grid = check_grids(paths)
    errors: list[str] = []
    warnings: list[str] = []
    stats: dict[int, dict] = {year: {} for year in years}

    totals = {year: np.zeros(256, dtype=np.int64) for year in years}
    if config.max_windows or config.window_start:
        windows = list(iter_windows(grid.width, grid.height, config.window_size))
        if config.window_start:
            windows = windows[config.window_start :]
        if config.max_windows:
            windows = windows[: config.max_windows]
        scan = "windows %d-%d" % (config.window_start, config.window_start + len(windows))
    elif sample_blocks:
        rng = random.Random(0)
        size = min(512, grid.width, grid.height)
        windows = [
            rasterio.windows.Window(
                rng.randrange(0, max(1, grid.width - size + 1)),
                rng.randrange(0, max(1, grid.height - size + 1)),
                size,
                size,
            )
            for _ in range(sample_blocks)
        ]
        scan = "sampled (%d blocks)" % sample_blocks
    else:
        windows = list(iter_windows(grid.width, grid.height, config.window_size))
        scan = "full"
    datasets = {year: rasterio.open(path) for year, path in paths.items()}
    try:
        for year, ds in datasets.items():
            if ds.count != 1:
                errors.append(f"{year}: expected 1 band, found {ds.count}")
            if ds.dtypes[0] != "uint8":
                errors.append(f"{year}: expected uint8, found {ds.dtypes[0]}")
            if ds.nodata != 0:
                errors.append(f"{year}: expected nodata 0, found {ds.nodata}")
            tags = ds.tags()
            for key in ("product", "years", "recommended_start", "warmup_years"):
                if not tags.get(key):
                    warnings.append(f"{year}: missing tag '{key}'")
        iterator = tqdm(windows, desc="qa", unit="win") if progress else windows
        for window in iterator:
            for year, ds in datasets.items():
                data = ds.read(1, window=window)
                totals[year] += np.bincount(data.ravel(), minlength=256)
    finally:
        for ds in datasets.values():
            ds.close()

    for year in years:
        counts = totals[year]
        present = sorted(int(v) for v in np.nonzero(counts)[0])
        invalid = sorted(set(present) - ALLOWED_CLASSES)
        stats[year] = {
            "classes": present,
            "pixels": {str(value): int(counts[value]) for value in present},
            "valid_pixels": int(counts[list(VALID_CLASSES)].sum()),
            "nodata_pixels": int(counts[0]),
        }
        if invalid:
            errors.append(f"{year}: invalid classes written: {invalid}")

    if len(years) < 6:
        warnings.append(f"only {len(years)} years in the product; the method expects >= 6")
    if years and years == list(range(years[0], years[-1] + 1)):
        pass
    else:
        warnings.append("the product does not form a contiguous annual series")

    secondary = {}
    age_path = config.secondary_vegetation_dir / "secondary_vegetation_age.tif"
    freq_path = config.secondary_vegetation_dir / "deforestation_frequency.tif"
    for name, path in (("age", age_path), ("frequency", freq_path)):
        if path.is_file():
            with rasterio.open(path) as ds:
                secondary[name] = {
                    "path": str(path),
                    "count": ds.count,
                    "nodata": ds.nodata,
                    "grid_matches": (
                        ds.width == grid.width
                        and ds.height == grid.height
                        and list(ds.transform)[:6] == list(grid.transform)[:6]
                    ),
                }
        else:
            secondary[name] = {"path": str(path), "exists": False}

    report = {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "years": years,
        "grid": {
            "width": grid.width,
            "height": grid.height,
            "crs": str(grid.crs),
            "transform": list(grid.transform)[:6],
        },
        "stats": {str(year): value for year, value in stats.items()},
        "secondary": secondary,
        "scan": scan,
    }
    json_path = config.reports_dir / "product_qa.json"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    report["report_path"] = str(json_path)
    return report


def format_qa(report: dict) -> str:
    lines = ["=" * 68, "CONTROLE DE QUALIDADE DOS PRODUTOS", "=" * 68]
    lines.append(f"Anos: {report['years']}")
    lines.append(f"Leitura: {report.get('scan', 'full')}")
    grid = report["grid"]
    lines.append(f"Grade: {grid['width']} x {grid['height']} px, {grid['crs']}")
    lines.append("")
    lines.append(f"{'ano':>4}  {'validos':>14}  {'nodata':>14}  classes")
    for year in report["years"]:
        info = report["stats"][str(year)]
        lines.append(
            f"{year:>4}  {info['valid_pixels']:>14,}  {info['nodata_pixels']:>14,}  "
            f"{info['classes']}"
        )
    lines.append("")
    if report["errors"]:
        lines.append("ERROS:")
        lines.extend(f"  - {message}" for message in report["errors"])
    if report["warnings"]:
        lines.append("AVISOS:")
        lines.extend(f"  - {message}" for message in report["warnings"])
    lines.append("RESULTADO: " + ("CONSISTENTE" if report["ok"] else "INCONSISTENTE"))
    lines.append("=" * 68)
    return "\n".join(lines)
