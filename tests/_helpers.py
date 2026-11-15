from __future__ import annotations

from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin

from mapbiomas_local.config import build_config

WIDTH = 700
HEIGHT = 600
TRANSFORM = from_origin(0.0, 0.6, 0.001, 0.001)


def write_rasters(input_dir: Path, years, pattern: str = "mapbiomas_col11_{year}.tif") -> dict:
    input_dir.mkdir(parents=True, exist_ok=True)
    base = np.full((HEIGHT, WIDTH), 3, dtype="uint8")
    base[:150, :] = 15
    base[150:250, :] = 9
    paths = {}
    for index, year in enumerate(years):
        data = base.copy()
        data[300:304, 100:103] = 9 if index % 2 == 0 else 3
        data[400:410, 400:430] = 4
        path = input_dir / pattern.format(year=year)
        profile = {
            "driver": "GTiff",
            "width": WIDTH,
            "height": HEIGHT,
            "count": 1,
            "dtype": "uint8",
            "crs": "EPSG:4326",
            "transform": TRANSFORM,
            "nodata": 0,
            "tiled": True,
            "blockxsize": 256,
            "blockysize": 256,
            "compress": "deflate",
            "BIGTIFF": "IF_SAFER",
        }
        with rasterio.open(path, "w", **profile) as dataset:
            dataset.write(data, 1)
            dataset.set_band_description(1, f"classification_{year}")
        paths[year] = path
    return paths


def make_config(tmp_path: Path, **overrides):
    input_dir = tmp_path / "input"
    years = list(range(2007, 2017))
    write_rasters(input_dir, years)
    data = {
        "input_dir": input_dir,
        "output_dir": tmp_path / "outputs",
        "window_size": 512,
        "halo": 16,
        "spatial_filter": True,
        "group_size_filter": 11,
        "group_size_exception": 11,
        "blip_filter": True,
        "secondary_end_rules": True,
        "checkpoint_every": 1,
        "log_level": "WARNING",
    }
    data.update(overrides)
    return build_config(data)
