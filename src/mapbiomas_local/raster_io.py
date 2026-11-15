from __future__ import annotations

import datetime
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Sequence

import numpy as np
import rasterio
from rasterio.crs import CRS
from rasterio.enums import Resampling
from rasterio.transform import Affine
from rasterio.windows import Window

from .config import OUTPUT_NODATA


def discover_years(input_dir: str | Path, pattern: str) -> dict[int, Path]:
    input_dir = Path(input_dir)
    if "{year}" not in pattern:
        raise ValueError("filename_pattern must contain '{year}'")
    regex = re.compile(
        "^"
        + re.escape(pattern).replace(re.escape("{year}"), r"(?P<year>\d{4})")
        + "$",
        re.IGNORECASE,
    )
    found: dict[int, Path] = {}
    for path in sorted(input_dir.iterdir()):
        if not path.is_file():
            continue
        match = regex.match(path.name)
        if match:
            year = int(match.group("year"))
            if year in found:
                raise ValueError(
                    f"Duplicate files for year {year}: {found[year].name} and {path.name}"
                )
            found[year] = path
    if not found:
        raise FileNotFoundError(
            f"No files matching {pattern!r} found in {input_dir}"
        )
    return dict(sorted(found.items()))


@dataclass(frozen=True)
class RasterGrid:
    crs: CRS
    transform: Affine
    width: int
    height: int
    dtype: str
    nodata: float | None

    @classmethod
    def from_raster(cls, path: str | Path) -> "RasterGrid":
        with rasterio.open(path) as ds:
            return cls(
                crs=CRS.from_user_input(ds.crs),
                transform=ds.transform,
                width=ds.width,
                height=ds.height,
                dtype=ds.dtypes[0],
                nodata=ds.nodata,
            )

    def assert_compatible(self, other: "RasterGrid", name: str = "") -> None:
        problems = []
        if self.crs != other.crs:
            problems.append(f"CRS {self.crs} != {other.crs}")
        if self.width != other.width or self.height != other.height:
            problems.append(f"size {self.width}x{self.height} != {other.width}x{other.height}")
        if not self.transform.almost_equals(other.transform):
            problems.append(f"transform {self.transform} != {other.transform}")
        if problems:
            prefix = f"{name}: " if name else ""
            raise ValueError(prefix + "; ".join(problems))


def check_grids(paths: Mapping[int, Path]) -> RasterGrid:
    if not paths:
        raise ValueError("No raster paths provided")
    years = sorted(paths)
    reference = RasterGrid.from_raster(paths[years[0]])
    for year in years[1:]:
        other = RasterGrid.from_raster(paths[year])
        reference.assert_compatible(other, f"year {year}")
    return reference


def iter_windows(
    width: int,
    height: int,
    window_size: int,
    max_windows: int | None = None,
) -> Iterable[Window]:
    count = 0
    for row_off in range(0, height, window_size):
        for col_off in range(0, width, window_size):
            win = Window(
                col_off,
                row_off,
                min(window_size, width - col_off),
                min(window_size, height - row_off),
            )
            yield win
            count += 1
            if max_windows is not None and count >= max_windows:
                return


def expand_window(window: Window, halo: int, width: int, height: int) -> Window:
    row0 = max(0, int(window.row_off) - halo)
    col0 = max(0, int(window.col_off) - halo)
    row1 = min(height, int(window.row_off + window.height) + halo)
    col1 = min(width, int(window.col_off + window.width) + halo)
    return Window(col0, row0, col1 - col0, row1 - row0)


def core_slice(expanded: Window, window: Window) -> tuple[slice, slice]:
    row = int(window.row_off - expanded.row_off)
    col = int(window.col_off - expanded.col_off)
    return (
        slice(row, row + int(window.height)),
        slice(col, col + int(window.width)),
    )


class RasterStack:
    def __init__(self, paths: Mapping[int, Path]):
        self.paths = dict(sorted(paths.items()))
        self._datasets: dict[int, rasterio.DatasetReader] = {}

    def __enter__(self) -> "RasterStack":
        for year, path in self.paths.items():
            self._datasets[year] = rasterio.open(path)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        for dataset in self._datasets.values():
            dataset.close()
        self._datasets.clear()

    def read(self, window: Window, years: Sequence[int] | None = None) -> np.ndarray:
        selected = list(years) if years is not None else list(self.paths)
        bands = [
            self._datasets[year].read(
                1,
                window=window,
                out_dtype="uint8",
                resampling=Resampling.nearest,
            )
            for year in selected
        ]
        return np.stack(bands, axis=0)


def create_output(
    path: str | Path,
    grid: RasterGrid,
    count: int = 1,
    dtype: str = "uint8",
    nodata: int | float = OUTPUT_NODATA,
    descriptions: Sequence[str] | None = None,
    tags: Mapping[str, str] | None = None,
    compress: str = "deflate",
) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    profile = {
        "driver": "GTiff",
        "width": grid.width,
        "height": grid.height,
        "count": count,
        "dtype": dtype,
        "crs": grid.crs,
        "transform": grid.transform,
        "nodata": nodata,
        "tiled": True,
        "blockxsize": 512,
        "blockysize": 512,
        "compress": compress,
        "predictor": 2,
        "interleave": "band",
        "BIGTIFF": "IF_SAFER",
    }
    with rasterio.open(path, "w", **profile) as dataset:
        if descriptions:
            dataset.descriptions = tuple(descriptions)
        if tags:
            dataset.update_tags(**{key: str(value) for key, value in tags.items()})
    return path


def output_tags(
    product: str,
    years: Sequence[int],
    extra: Mapping[str, str] | None = None,
) -> dict[str, str]:
    from . import __version__

    tags = {
        "product": product,
        "years": f"{years[0]}-{years[-1]}" if years else "",
        "created_utc": datetime.datetime.now(datetime.timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
        "software": f"mapbiomas-local {__version__}",
        "source": "MapBiomas Collection 11 public coverage v3",
        "grid": "native grid of the input rasters",
    }
    if extra:
        tags.update({key: str(value) for key, value in extra.items()})
    return tags
