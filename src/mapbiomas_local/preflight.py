from __future__ import annotations

import json
import logging
import random
import shutil
from pathlib import Path

import numpy as np
import rasterio

from .config import RunConfig
from .raster_io import discover_years
from .rules import CLASS_LOOKUP

logger = logging.getLogger(__name__)

KNOWN_CLASSES = {int(source) for source, _ in CLASS_LOOKUP} | {0}
REQUIRED_YEARS = 6


def _sample_windows(ds: rasterio.DatasetReader, n_blocks: int, block_size: int, seed: int):
    rng = random.Random(seed)
    size = min(block_size, ds.width, ds.height)
    max_row = ds.height - size
    max_col = ds.width - size
    seen = set()
    for _ in range(n_blocks):
        row = rng.randrange(0, max_row + 1) if max_row > 0 else 0
        col = rng.randrange(0, max_col + 1) if max_col > 0 else 0
        key = (row // size, col // size)
        if key in seen:
            continue
        seen.add(key)
        yield rasterio.windows.Window(col, row, size, size)


def _check_raster(
    year: int,
    path: Path,
    n_blocks: int,
    block_size: int,
    deep: bool,
) -> dict:
    info = {
        "year": year,
        "file": path.name,
        "size_mb": round(path.stat().st_size / 1e6, 1) if path.exists() else 0.0,
        "ok": True,
        "errors": [],
        "warnings": [],
        "classes": [],
        "unknown_classes": [],
        "blank_blocks": 0,
        "blocks_read": 0,
        "overviews": [],
    }
    if path.stat().st_size <= 0:
        info["ok"] = False
        info["errors"].append("file is empty")
        return info

    try:
        with rasterio.open(path) as ds:
            info.update(
                {
                    "driver": ds.driver,
                    "width": ds.width,
                    "height": ds.height,
                    "count": ds.count,
                    "dtype": ds.dtypes[0],
                    "nodata": ds.nodata,
                    "crs": str(ds.crs),
                    "transform": list(ds.transform)[:6],
                    "tiled": bool(ds.profile.get("tiled")),
                    "block_shapes": ds.block_shapes,
                    "compression": ds.profile.get("compress"),
                    "overviews": ds.overviews(1),
                }
            )
            if ds.count != 1:
                info["errors"].append(f"expected 1 band, found {ds.count}")
            if ds.dtypes[0] != "uint8":
                info["errors"].append(f"expected uint8, found {ds.dtypes[0]}")
            if ds.nodata != 0:
                info["warnings"].append(f"nodata is {ds.nodata}, expected 0")
            if ds.crs is None:
                info["errors"].append("missing CRS")
            if ds.overviews(1):
                info["warnings"].append(
                    "overview levels exist and may be averaged; the pipeline never reads them"
                )

            counts = np.zeros(256, dtype=np.int64)
            windows = (
                (win for _, win in ds.block_windows(1))
                if deep
                else _sample_windows(ds, n_blocks, block_size, seed=year)
            )
            for window in windows:
                try:
                    data = ds.read(1, window=window)
                except Exception as exc:
                    info["errors"].append(f"unreadable block at {window}: {exc}")
                    break
                info["blocks_read"] += 1
                if not data.any():
                    info["blank_blocks"] += 1
                counts += np.bincount(data.ravel(), minlength=256)
            info["classes"] = [int(v) for v in np.nonzero(counts)[0]]
            unknown = sorted(set(info["classes"]) - KNOWN_CLASSES)
            info["unknown_classes"] = unknown
            if unknown:
                info["warnings"].append(
                    f"classes not mapped by the lookup: {unknown} (they become 0)"
                )
            if info["blocks_read"] and info["blank_blocks"] == info["blocks_read"]:
                info["warnings"].append("all sampled blocks are empty (all zeros)")
    except Exception as exc:
        info["ok"] = False
        info["errors"].append(f"cannot open/read: {exc}")

    if info["errors"]:
        info["ok"] = False
    return info


def _requested_years(
    available: list[int], start: int | None, end: int | None
) -> tuple[list[int], list[int]]:
    if start is None and end is None:
        return list(available), []
    first = start if start is not None else available[0]
    last = end if end is not None else available[-1]
    if first > last:
        return [], []
    wanted = list(range(first, last + 1))
    selected = [year for year in wanted if year in available]
    missing = [year for year in wanted if year not in available]
    return selected, missing


def preflight(
    config: RunConfig,
    start: int | None = None,
    end: int | None = None,
    n_blocks: int = 12,
    block_size: int = 512,
    deep: bool = False,
) -> dict:
    errors: list[str] = []
    warnings: list[str] = []
    files: dict[int, dict] = {}
    grid = None

    try:
        available_map = discover_years(config.input_dir, config.filename_pattern)
    except Exception as exc:
        return {
            "ok": False,
            "errors": [str(exc)],
            "warnings": [],
            "available_years": [],
            "selected_years": [],
            "missing_years": [],
            "files": {},
        }

    available = sorted(available_map)
    selected, missing = _requested_years(available, start, end)
    if missing:
        warnings.append(f"missing years in the requested period: {missing}")
    if not selected:
        errors.append("no years available for the requested period")
    elif len(selected) < REQUIRED_YEARS:
        errors.append(
            f"at least {REQUIRED_YEARS} years are required, only {len(selected)} available"
        )

    reference = None
    for year in selected:
        logger.info("preflight: %s", available_map[year].name)
        info = _check_raster(year, available_map[year], n_blocks, block_size, deep)
        files[year] = info
        errors.extend(f"{year}: {message}" for message in info["errors"])
        warnings.extend(f"{year}: {message}" for message in info["warnings"])
        if not info.get("width"):
            continue
        signature = (
            info.get("crs"),
            info.get("width"),
            info.get("height"),
            tuple(info.get("transform", [])),
        )
        if reference is None:
            reference = signature
            grid = {key: info.get(key) for key in ("crs", "width", "height", "transform")}
        elif signature != reference:
            errors.append(
                f"{year}: grid differs from the reference year "
                f"({info.get('width')}x{info.get('height')}, {info.get('crs')})"
            )

    classes = sorted({value for info in files.values() for value in info["classes"]})
    unknown = sorted({value for info in files.values() for value in info["unknown_classes"]})
    if unknown:
        warnings.append(
            f"unknown raw classes across the series: {unknown}; verify the input version"
        )
    if selected and len(selected) >= 3:
        warnings.append(
            f"the first two years ({selected[0]}, {selected[1]}) are warm-up; "
            f"the first recommended product is {selected[2]}"
        )

    try:
        usage = shutil.disk_usage(config.output_dir if config.output_dir.exists() else config.output_dir.parent)
        free_gb = round(usage.free / 1e9, 1)
        expected_gb = round(len(selected) * 2.5, 1)
        if free_gb < expected_gb + 10:
            warnings.append(
                f"only {free_gb} GB free in the output drive; estimated need is ~{expected_gb} GB"
            )
    except Exception:
        free_gb = None

    report = {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "input_dir": str(config.input_dir),
        "pattern": config.filename_pattern,
        "requested_period": [start, end],
        "available_years": available,
        "selected_years": selected,
        "missing_years": missing,
        "n_selected": len(selected),
        "grid": grid,
        "classes_sampled": classes,
        "unknown_classes": unknown,
        "deep_scan": deep,
        "blocks_per_file": n_blocks,
        "output_free_gb": free_gb,
        "files": files,
    }
    return report


def format_report(report: dict) -> str:
    lines = []
    lines.append("=" * 68)
    lines.append("VERIFICACAO DOS DADOS DE ENTRADA")
    lines.append("=" * 68)
    lines.append(f"Pasta: {report.get('input_dir')}")
    lines.append(f"Padrao: {report.get('pattern')}")
    lines.append(f"Anos disponiveis: {report.get('available_years')}")
    lines.append(f"Anos selecionados: {report.get('selected_years')}")
    if report.get("missing_years"):
        lines.append(f"Anos faltando no periodo: {report['missing_years']}")
    grid = report.get("grid")
    if grid:
        lines.append(
            f"Grade: {grid.get('width')} x {grid.get('height')} px, {grid.get('crs')}"
        )
    lines.append(f"Classes amostradas: {report.get('classes_sampled')}")
    if report.get("deep_scan"):
        lines.append("Leitura: completa (todos os blocos)")
    else:
        lines.append(f"Leitura: amostral ({report.get('blocks_per_file')} blocos por ano)")
    lines.append("")
    for year, info in sorted(report.get("files", {}).items()):
        status = "OK " if info["ok"] else "ERRO"
        lines.append(
            f"  [{status}] {year}  {info['size_mb']:>8.1f} MB  "
            f"classes={info['classes']}"
        )
        for message in info["errors"]:
            lines.append(f"         erro: {message}")
        for message in info["warnings"]:
            lines.append(f"         aviso: {message}")
    lines.append("")
    if report["errors"]:
        lines.append("ERROS BLOQUEANTES:")
        lines.extend(f"  - {message}" for message in report["errors"])
    if report["warnings"]:
        lines.append("AVISOS:")
        lines.extend(f"  - {message}" for message in report["warnings"])
    lines.append("")
    lines.append("RESULTADO: " + ("APTO PARA PROCESSAR" if report["ok"] else "NAO APTO"))
    lines.append("=" * 68)
    return "\n".join(lines)


def write_preflight_report(config: RunConfig, report: dict) -> dict:
    config.create_output_dirs()
    json_path = config.reports_dir / "preflight.json"
    json_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )
    md_path = config.reports_dir / "preflight.md"
    md_path.write_text("```\n" + format_report(report) + "\n```\n", encoding="utf-8")
    return {"json": json_path, "markdown": md_path}
