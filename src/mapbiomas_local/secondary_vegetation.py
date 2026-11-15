from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import rasterio
from tqdm import tqdm

from .config import OUTPUT_NODATA, RunConfig
from .raster_io import (
    check_grids,
    create_output,
    iter_windows,
    output_tags,
)
from .rules import (
    ClassCode,
    DEFORESTATION_CLASSES,
    SECONDARY_VEGETATION_CLASSES,
)


def secondary_vegetation_age(stack: np.ndarray) -> np.ndarray:
    age = np.zeros(stack.shape, dtype="uint8")
    previous = np.zeros(stack.shape[1:], dtype="uint16")
    for pos in range(stack.shape[0]):
        is_sv = np.isin(stack[pos], SECONDARY_VEGETATION_CLASSES)
        current = (previous + is_sv.astype("uint16")) * is_sv
        age[pos] = np.clip(current, 0, 255).astype("uint8")
        previous = current
    return age


def deforestation_frequency(
    stack: np.ndarray,
    start: int = 0,
    end: int | None = None,
) -> np.ndarray:
    if end is None:
        end = stack.shape[0]
    window = stack[start:end]
    counts = np.zeros(window.shape[1:], dtype="uint8")
    for band in window:
        counts += np.isin(band, DEFORESTATION_CLASSES)
    return counts


def transition_by_coverage(transitions: np.ndarray, coverage_previous: np.ndarray) -> np.ndarray:
    result = transitions.astype("uint16") * 100 + coverage_previous.astype("uint16")
    result[transitions == ClassCode.NO_DATA] = 0
    return result.astype("uint16")


def _transition_paths(config: RunConfig) -> dict[int, Path]:
    paths = {}
    for path in sorted(config.deforestation_dir.glob("deforestation_*.tif")):
        year = int(path.stem.split("_")[-1])
        paths[year] = path
    if not paths:
        raise FileNotFoundError(
            f"No deforestation products found in {config.deforestation_dir}"
        )
    return dict(sorted(paths.items()))


def run_secondary_products(config: RunConfig, progress: bool = True) -> dict:
    config.create_output_dirs()
    paths = _transition_paths(config)
    grid = check_grids(paths)
    years = sorted(paths)
    age_path = config.secondary_vegetation_dir / "secondary_vegetation_age.tif"
    create_output(
        age_path,
        grid,
        count=len(years),
        dtype="uint8",
        nodata=OUTPUT_NODATA,
        descriptions=[f"secondary_vegetation_age_{year}" for year in years],
        tags=output_tags(
            "secondary_vegetation_age",
            years,
            {
                "encoding": "consecutive years in classes 3 or 5; 0 otherwise",
                "nodata": str(OUTPUT_NODATA),
            },
        ),
    )

    freq_path = config.secondary_vegetation_dir / "deforestation_frequency.tif"
    create_output(
        freq_path,
        grid,
        count=1,
        dtype="uint8",
        nodata=OUTPUT_NODATA,
        descriptions=[f"deforestation_frequency_{years[0]}_{years[-1]}"],
        tags=output_tags(
            "deforestation_frequency",
            years,
            {"encoding": "number of years with class 4 or 6 in the period"},
        ),
    )

    datasets = {year: rasterio.open(path) for year, path in paths.items()}
    age_writer = rasterio.open(age_path, "r+")
    freq_writer = rasterio.open(freq_path, "r+")
    try:
        windows = list(iter_windows(grid.width, grid.height, config.window_size))
        if config.window_start:
            windows = windows[config.window_start :]
        if config.max_windows is not None:
            windows = windows[: config.max_windows]
        iterator = tqdm(windows, desc="secondary", unit="win") if progress else windows
        for window in iterator:
            stack = np.stack(
                [datasets[year].read(1, window=window) for year in years], axis=0
            )
            age = secondary_vegetation_age(stack)
            frequency = deforestation_frequency(stack)
            for band, year in enumerate(years, start=1):
                age_writer.write(age[band - 1], band, window=window)
            freq_writer.write(frequency, 1, window=window)
    finally:
        for dataset in datasets.values():
            dataset.close()
        age_writer.close()
        freq_writer.close()

    summary = {
        "age": str(age_path),
        "frequency": str(freq_path),
        "years": years,
    }
    (config.reports_dir / "secondary_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    return summary
