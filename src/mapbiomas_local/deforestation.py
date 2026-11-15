from __future__ import annotations

import json
import logging
from pathlib import Path

import numpy as np
import rasterio
from rasterio.windows import Window
from tqdm import tqdm

from .config import OUTPUT_NODATA, RunConfig
from .raster_io import (
    RasterGrid,
    RasterStack,
    check_grids,
    check_readable,
    core_slice,
    create_output,
    discover_years,
    expand_window,
    iter_windows,
    output_tags,
)
from .rules import (
    apply_deforestation_method,
    apply_spatial_filter,
    build_lookup,
)

logger = logging.getLogger(__name__)

# Local safety guard, not a rule of the original GEE script: the longest
# kernel is 6 years and the first two years are warm-up.
MIN_YEARS = 6


class MultiTiffWriter:
    def __init__(self, paths: dict[int, Path]):
        self.paths = paths
        self._datasets = {}

    def __enter__(self) -> "MultiTiffWriter":
        for year, path in self.paths.items():
            self._datasets[year] = rasterio.open(path, "r+")
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        for ds in self._datasets.values():
            ds.close()
        self._datasets.clear()

    def write(self, year: int, array: np.ndarray, window: Window) -> None:
        self._datasets[year].write(array, 1, window=window)


def deforestation_years(config: RunConfig, available: dict[int, Path]) -> list[int]:
    if config.years:
        years = [int(y) for y in config.years if int(y) in available]
    else:
        years = sorted(available)
    if config.deforestation_start is not None:
        years = [y for y in years if y >= config.deforestation_start]
    if config.deforestation_end is not None:
        years = [y for y in years if y <= config.deforestation_end]
    if len(years) < MIN_YEARS:
        raise ValueError(
            f"At least {MIN_YEARS} years are required, got {len(years)}: {years}"
        )
    missing = [y for y in years if y not in available]
    if missing:
        raise FileNotFoundError(f"Years missing from input: {missing}")
    return years


def _signature(config: RunConfig, years: list[int], grid: RasterGrid) -> str:
    return json.dumps(
        {
            "years": years,
            "window_size": config.window_size,
            "halo": config.halo,
            "spatial_filter": config.spatial_filter,
            "group_size_filter": config.group_size_filter,
            "group_size_exception": config.group_size_exception,
            "blip_filter": config.blip_filter,
            "secondary_end_rules": config.secondary_end_rules,
            "grid": [grid.width, grid.height, list(grid.transform)[:6], str(grid.crs)],
        },
        sort_keys=True,
    )


def _load_completed(state_path: Path, signature: str) -> set:
    if not state_path.is_file():
        return set()
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except Exception:
        return set()
    if state.get("signature") != signature:
        return set()
    return set(tuple(item) for item in state.get("completed", []))


def _save_completed(state_path: Path, signature: str, completed: set) -> None:
    payload = {"signature": signature, "completed": sorted(list(item) for item in completed)}
    state_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = state_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    tmp.replace(state_path)


def _output_tags(config: RunConfig, year: int, years: list[int]) -> dict:
    first, last = years[0], years[-1]
    warmup = years[:2] if len(years) >= 3 else years[:-1]
    return output_tags(
        "deforestation",
        [year],
        {
            "transition_encoding": "0=no data;1=anthropic;2=primary veg;3=secondary veg;"
            "4=primary suppression;5=recovery;6=secondary suppression;7=other",
            "method": "MapBiomas C11 temporal rules (local reimplementation)",
            "series_first_year": str(first),
            "series_last_year": str(last),
            "warmup_years": ",".join(str(y) for y in warmup),
            "recommended_start": str(years[2] if len(years) >= 3 else years[0]),
            "spatial_filter": str(config.spatial_filter),
            "group_size_filter": str(config.group_size_filter),
            "nodata": str(OUTPUT_NODATA),
            "input_divergence": "public C11 coverage, not the internal integration-ft asset",
        },
    )


def run_deforestation(
    config: RunConfig,
    progress: bool = True,
    force: bool = False,
) -> dict:
    config.create_output_dirs()
    available = discover_years(config.input_dir, config.filename_pattern)
    years = deforestation_years(config, available)
    selected_paths = {year: available[year] for year in years}
    grid = check_grids(selected_paths)

    output_paths = {
        year: config.deforestation_dir / f"deforestation_{year}.tif" for year in years
    }
    signature = _signature(config, years, grid)
    state_path = config.intermediate_dir / "deforestation_state.json"
    completed = set() if force else _load_completed(state_path, signature)
    resume = bool(completed) and all(path.is_file() for path in output_paths.values())
    if resume:
        problems = check_readable([output_paths[year] for year in years])
        if problems:
            logger.warning(
                "Existing outputs failed the read verification; they will be "
                "regenerated."
            )
            for message in problems:
                logger.warning("  %s", message)
            resume = False
            completed = set()
    if completed and not resume:
        completed = set()
    if resume:
        logger.info("Resuming deforestation: %d windows already completed", len(completed))
    else:
        for year, path in output_paths.items():
            create_output(
                path,
                grid,
                count=1,
                dtype="uint8",
                nodata=OUTPUT_NODATA,
                descriptions=[f"classification_{year}"],
                tags=_output_tags(config, year, years),
                compress=config.compression,
            )

    windows = list(iter_windows(grid.width, grid.height, config.window_size))
    if config.window_start:
        windows = windows[config.window_start :]
    if config.max_windows is not None:
        windows = windows[: config.max_windows]
    total = len(windows)
    iterator = tqdm(windows, desc="deforestation", unit="win") if progress else windows

    exception_years = (years[-1],)
    processed = 0
    lut = build_lookup()
    with RasterStack(selected_paths) as stack, MultiTiffWriter(output_paths) as writer:
        for window in iterator:
            key = (int(window.row_off), int(window.col_off))
            if key in completed:
                continue
            h, w = int(window.height), int(window.width)

            expanded = expand_window(window, config.halo, grid.width, grid.height)
            raw = stack.read(expanded, years=years)
            if not raw.any():
                completed.add(key)
                processed += 1
                if processed % config.checkpoint_every == 0:
                    _save_completed(state_path, signature, completed)
                continue

            aggregated = lut[raw]
            transitions = apply_deforestation_method(
                aggregated,
                blip=config.blip_filter,
                secondary_end_rules=config.secondary_end_rules,
            )
            if config.spatial_filter:
                apply_spatial_filter(
                    transitions,
                    threshold=config.group_size_filter,
                    exception_years=exception_years,
                    exception_threshold=config.group_size_exception,
                    years=years,
                )

            rows, cols = core_slice(expanded, window)
            core = transitions[:, rows, cols]
            for pos, year in enumerate(years):
                writer.write(year, core[pos], window)

            completed.add(key)
            processed += 1
            if processed % config.checkpoint_every == 0:
                _save_completed(state_path, signature, completed)

    _save_completed(state_path, signature, completed)
    problems = check_readable([output_paths[year] for year in years])
    if problems:
        raise RuntimeError(
            "generated products failed the read verification: "
            + "; ".join(problems[:3])
        )
    warmup = years[:2] if len(years) >= 3 else years[:-1]
    summary = {
        "years": years,
        "warmup_years": warmup,
        "recommended_start": years[2] if len(years) >= 3 else years[0],
        "windows_total": total,
        "windows_completed": len(completed),
        "outputs": {str(year): str(path) for year, path in output_paths.items()},
        "parameters": {
            "spatial_filter": config.spatial_filter,
            "group_size_filter": config.group_size_filter,
            "group_size_exception": config.group_size_exception,
            "blip_filter": config.blip_filter,
            "secondary_end_rules": config.secondary_end_rules,
        },
        "notes": [
            "Warm-up years should not be used as final products.",
            "Input is the public C11 coverage, not the internal integration-ft asset.",
        ],
    }
    summary_path = config.reports_dir / "deforestation_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    summary["summary_path"] = str(summary_path)
    return summary
