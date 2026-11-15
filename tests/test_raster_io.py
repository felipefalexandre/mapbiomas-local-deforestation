from __future__ import annotations

import numpy as np
import pytest
import rasterio
from rasterio.windows import Window

from mapbiomas_local.raster_io import (
    RasterGrid,
    check_grids,
    core_slice,
    discover_years,
    expand_window,
    iter_windows,
)

from _helpers import make_config


def test_discover_years_sorted(tmp_path):
    config = make_config(tmp_path)
    found = discover_years(config.input_dir, config.filename_pattern)
    assert sorted(found) == list(range(2007, 2017))


def test_discover_years_rejects_invalid_pattern(tmp_path):
    config = make_config(tmp_path)
    with pytest.raises(ValueError):
        discover_years(config.input_dir, "mapbiomas.tif")


def test_iter_windows_covers_raster():
    windows = list(iter_windows(700, 600, 512))
    assert len(windows) == 4
    covered = np.zeros((600, 700), dtype=bool)
    for window in windows:
        rows = slice(int(window.row_off), int(window.row_off + window.height))
        cols = slice(int(window.col_off), int(window.col_off + window.width))
        assert not covered[rows, cols].any()
        covered[rows, cols] = True
    assert covered.all()


def test_expand_window_clips_at_edges():
    window = Window(0, 0, 512, 512)
    expanded = expand_window(window, 16, 700, 600)
    assert (expanded.col_off, expanded.row_off) == (0, 0)
    assert (expanded.width, expanded.height) == (528, 528)
    corner = Window(512, 512, 188, 88)
    expanded = expand_window(corner, 16, 700, 600)
    assert expanded.col_off == 496 and expanded.row_off == 496
    assert expanded.col_off + expanded.width == 700
    assert expanded.row_off + expanded.height == 600


def test_core_slice_offsets():
    window = Window(512, 512, 188, 88)
    expanded = expand_window(window, 16, 700, 600)
    rows, cols = core_slice(expanded, window)
    assert rows.start == 16 and rows.stop == 104
    assert cols.start == 16 and cols.stop == 204


def test_check_grids(tmp_path):
    config = make_config(tmp_path)
    paths = discover_years(config.input_dir, config.filename_pattern)
    grid = check_grids(paths)
    assert isinstance(grid, RasterGrid)
    assert (grid.width, grid.height) == (700, 600)


def test_check_grids_detects_mismatch(tmp_path):
    config = make_config(tmp_path)
    paths = discover_years(config.input_dir, config.filename_pattern)
    bad = tmp_path / "bad.tif"
    with rasterio.open(config.input_dir / "mapbiomas_col11_2007.tif") as src:
        profile = src.profile
    profile.update(width=650)
    with rasterio.open(bad, "w", **profile):
        pass
    paths[2017] = bad
    with pytest.raises(ValueError):
        check_grids(paths)
