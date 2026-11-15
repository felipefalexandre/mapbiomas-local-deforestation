from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional, Sequence

_DEFAULT_PATTERN = "mapbiomas_col11_{year}.tif"
OUTPUT_NODATA = 0


@dataclass
class RunConfig:
    input_dir: Path
    output_dir: Path
    filename_pattern: str = _DEFAULT_PATTERN
    years: Optional[Sequence[int]] = None
    deforestation_start: Optional[int] = None
    deforestation_end: Optional[int] = None
    window_size: int = 2048
    halo: int = 16
    spatial_filter: bool = True
    group_size_filter: int = 11
    group_size_exception: int = 11
    blip_filter: bool = True
    secondary_end_rules: bool = True
    checkpoint_every: int = 25
    window_start: int = 0
    max_windows: Optional[int] = None
    compression: str = "deflate"
    log_level: str = "INFO"
    extra: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.input_dir = Path(self.input_dir)
        self.output_dir = Path(self.output_dir)
        if self.years is not None:
            self.years = tuple(int(y) for y in self.years)

    @property
    def deforestation_dir(self) -> Path:
        return self.output_dir / "deforestation"

    @property
    def secondary_vegetation_dir(self) -> Path:
        return self.output_dir / "secondary_vegetation"

    @property
    def intermediate_dir(self) -> Path:
        return self.output_dir / "intermediate"

    @property
    def reports_dir(self) -> Path:
        return self.output_dir / "reports"

    @property
    def logs_dir(self) -> Path:
        return self.output_dir / "logs"

    def create_output_dirs(self) -> None:
        for path in (
            self.deforestation_dir,
            self.secondary_vegetation_dir,
            self.intermediate_dir,
            self.reports_dir,
            self.logs_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)

    def validate(self) -> None:
        if not self.input_dir.is_dir():
            raise FileNotFoundError(f"input_dir not found: {self.input_dir}")
        if "{year}" not in self.filename_pattern:
            raise ValueError("filename_pattern must contain the '{year}' placeholder")
        if self.window_size <= 0 or self.window_size % 512 != 0:
            raise ValueError("window_size must be a positive multiple of 512")
        if self.halo < 0:
            raise ValueError("halo must be >= 0")
        if self.max_windows is not None and self.max_windows <= 0:
            raise ValueError("max_windows must be positive")
        if self.window_start < 0:
            raise ValueError("window_start must be >= 0")
        if self.group_size_filter < 0 or self.group_size_exception < 0:
            raise ValueError("group size thresholds must be >= 0")

    def to_dict(self) -> dict:
        data = asdict(self)
        for key, value in list(data.items()):
            if isinstance(value, Path):
                data[key] = str(value)
            elif isinstance(value, tuple):
                data[key] = list(value)
        return data

    def summary(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)


def _read_yaml(path: Path) -> dict:
    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError(
            "PyYAML is required to read YAML configuration files. "
            "Install it with 'pip install pyyaml' or use TOML/JSON instead."
        ) from exc
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def load_config_file(path: str | os.PathLike) -> dict:
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".toml":
        import tomllib

        with open(path, "rb") as fh:
            data = tomllib.load(fh)
    elif suffix == ".json":
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    elif suffix in (".yaml", ".yml"):
        data = _read_yaml(path)
    else:
        raise ValueError(f"Unsupported config extension: {suffix}")
    if "run" in data and isinstance(data["run"], dict):
        data = data["run"]
    return data


def merge_dicts(base: dict, override: dict) -> dict:
    merged = dict(base)
    merged.update({k: v for k, v in override.items() if v is not None})
    return merged


def build_config(data: dict) -> RunConfig:
    required = ("input_dir", "output_dir")
    missing = [key for key in required if not data.get(key)]
    if missing:
        raise ValueError(f"Missing required configuration keys: {missing}")
    known = {f.name for f in RunConfig.__dataclass_fields__.values()}
    kwargs = {k: v for k, v in data.items() if k in known and v is not None}
    extra = {k: v for k, v in data.items() if k not in known}
    config = RunConfig(**kwargs, extra=extra)
    config.validate()
    return config
