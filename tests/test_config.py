from __future__ import annotations

import json

import pytest

from mapbiomas_local.config import build_config, load_config_file, merge_dicts

from _helpers import make_config


def test_toml_config_is_flattened(tmp_path):
    config = make_config(tmp_path)
    path = tmp_path / "config.toml"
    path.write_text(
        "\n".join(
            [
                "[run]",
                f'input_dir = "{config.input_dir.as_posix()}"',
                f'output_dir = "{config.output_dir.as_posix()}"',
                "window_size = 1024",
            ]
        ),
        encoding="utf-8",
    )
    data = load_config_file(path)
    assert data["window_size"] == 1024


def test_json_config(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"run": {"window_size": 2048}}), encoding="utf-8")
    assert load_config_file(path) == {"window_size": 2048}


def test_merge_dicts_ignores_none():
    merged = merge_dicts({"a": 1, "b": 2}, {"a": None, "b": 3})
    assert merged == {"a": 1, "b": 3}


def test_unknown_keys_are_kept_in_extra(tmp_path):
    config = make_config(tmp_path, custom_flag=True)
    assert config.extra == {"custom_flag": True}


def test_window_size_must_be_multiple_of_512(tmp_path):
    with pytest.raises(ValueError):
        make_config(tmp_path, window_size=1000)


def test_pattern_requires_year_placeholder(tmp_path):
    with pytest.raises(ValueError):
        make_config(tmp_path, filename_pattern="mapbiomas.tif")


def test_missing_paths_are_reported(tmp_path):
    with pytest.raises(FileNotFoundError):
        build_config({"input_dir": tmp_path / "missing", "output_dir": tmp_path / "outputs"})


def test_to_dict_roundtrip_types(tmp_path):
    config = make_config(tmp_path)
    data = config.to_dict()
    assert isinstance(data["input_dir"], str)
    assert data["window_size"] == 512
