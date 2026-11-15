from __future__ import annotations

import rasterio

from mapbiomas_local.preflight import preflight

from _helpers import make_config


def test_preflight_ok(tmp_path):
    config = make_config(tmp_path)
    report = preflight(config, start=2007, end=2016, n_blocks=4)
    assert report["ok"], report["errors"]
    assert report["selected_years"] == list(range(2007, 2017))
    assert report["missing_years"] == []
    assert report["grid"]["width"] == 700
    assert 3 in report["classes_sampled"]


def test_preflight_reports_missing_years(tmp_path):
    config = make_config(tmp_path)
    report = preflight(config, start=2003, end=2016, n_blocks=4)
    assert report["missing_years"] == [2003, 2004, 2005, 2006]
    assert report["ok"]
    assert any("missing years" in message for message in report["warnings"])


def test_preflight_rejects_short_series(tmp_path):
    config = make_config(tmp_path)
    report = preflight(config, start=2014, end=2016, n_blocks=4)
    assert not report["ok"]
    assert report["selected_years"] == [2014, 2015, 2016]


def test_preflight_detects_grid_mismatch(tmp_path):
    config = make_config(tmp_path)
    path = config.input_dir / "mapbiomas_col11_2010.tif"
    with rasterio.open(path) as src:
        profile = src.profile
    profile.update(width=650)
    with rasterio.open(path, "w", **profile):
        pass
    report = preflight(config, start=2007, end=2016, n_blocks=4)
    assert not report["ok"]
    assert any("grid differs" in message for message in report["errors"])


def test_preflight_detects_truncated_file(tmp_path):
    config = make_config(tmp_path)
    path = config.input_dir / "mapbiomas_col11_2012.tif"
    path.write_bytes(path.read_bytes()[:100])
    report = preflight(config, start=2007, end=2016, n_blocks=4)
    assert not report["ok"]
    assert report["files"][2012]["errors"]
