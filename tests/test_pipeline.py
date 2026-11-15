from __future__ import annotations

import numpy as np
import pytest
import rasterio
from rasterio.windows import Window

from mapbiomas_local.deforestation import run_deforestation
from mapbiomas_local.raster_io import (
    core_slice,
    discover_years,
    expand_window,
    iter_windows,
)
from mapbiomas_local.rules import (
    apply_deforestation_method,
    apply_spatial_filter,
    build_lookup,
)
from mapbiomas_local.qa import qa_products
from mapbiomas_local.secondary_vegetation import (
    deforestation_frequency,
    run_secondary_products,
    secondary_vegetation_age,
)

from _helpers import make_config


def test_deforestation_matches_full_array_reference(tmp_path):
    config = make_config(tmp_path)
    years = list(range(2007, 2017))
    summary = run_deforestation(config, progress=False, force=True)
    assert summary["years"] == years
    assert summary["warmup_years"] == [2007, 2008]
    assert summary["recommended_start"] == 2009
    assert summary["windows_completed"] == 4

    paths = discover_years(config.input_dir, config.filename_pattern)
    stack = np.stack(
        [
            rasterio.open(paths[year]).read(1, window=Window(0, 0, 700, 600))
            for year in years
        ],
        axis=0,
    )
    aggregated = build_lookup()[stack]
    expected = apply_deforestation_method(aggregated.copy())
    apply_spatial_filter(expected, threshold=11, exception_years=(years[-1],), years=years)

    for pos, year in enumerate(years):
        path = config.deforestation_dir / f"deforestation_{year}.tif"
        with rasterio.open(path) as dataset:
            actual = dataset.read(1)
            assert dataset.nodata == 0
            assert dataset.tags()["recommended_start"] == "2009"
            assert dataset.tags()["warmup_years"] == "2007,2008"
        assert np.array_equal(actual, expected[pos]), f"mismatch in {year}"


def test_spatial_filter_tiled_with_halo_matches_full():
    rng = np.random.default_rng(7)
    stack = rng.choice([1, 2, 3, 4, 5, 6], size=(8, 130, 150)).astype("uint8")
    full = stack.copy()
    apply_spatial_filter(full, threshold=11, years=list(range(8)))

    tiled = stack.copy()
    for window in iter_windows(150, 130, 64):
        expanded = expand_window(window, 16, 150, 130)
        rows = slice(int(expanded.row_off), int(expanded.row_off + expanded.height))
        cols = slice(int(expanded.col_off), int(expanded.col_off + expanded.width))
        sub = stack[:, rows, cols].copy()
        apply_spatial_filter(sub, threshold=11, years=list(range(8)))
        core_rows, core_cols = core_slice(expanded, window)
        tiled[:, rows, cols][:, core_rows, core_cols] = sub[:, core_rows, core_cols]
    assert np.array_equal(full, tiled)


def test_deforestation_requires_enough_years(tmp_path):
    config = make_config(tmp_path, years=[2010, 2011, 2012], deforestation_start=2010)
    with pytest.raises(ValueError):
        run_deforestation(config, progress=False, force=True)


def test_secondary_products(tmp_path):
    config = make_config(tmp_path)
    run_deforestation(config, progress=False, force=True)
    summary = run_secondary_products(config, progress=False)
    assert summary["years"] == list(range(2007, 2017))
    with rasterio.open(summary["age"]) as dataset:
        assert dataset.count == 10
        age = dataset.read(1, window=Window(0, 0, 700, 600))
        assert age.shape == (600, 700)
        assert age.dtype == np.uint8
    with rasterio.open(summary["frequency"]) as dataset:
        frequency = dataset.read(1, window=Window(0, 0, 700, 600))
        assert frequency.shape == (600, 700)
        assert frequency.dtype == np.uint8


def test_qa_products(tmp_path):
    config = make_config(tmp_path)
    run_deforestation(config, progress=False, force=True)
    report = qa_products(config, progress=False, sample_blocks=8)
    assert report["ok"], report["errors"]
    assert report["years"] == list(range(2007, 2017))
    assert report["stats"]["2009"]["classes"]


def test_age_and_frequency_functions():
    stack = np.zeros((4, 3, 3), dtype="uint8")
    stack[:, 0, 0] = [3, 3, 1, 3]
    stack[:, 0, 1] = [4, 4, 4, 4]
    age = secondary_vegetation_age(stack)
    assert age[:, 0, 0].tolist() == [1, 2, 0, 1]
    frequency = deforestation_frequency(stack)
    assert frequency[0, 1] == 4
    assert frequency[0, 0] == 0
