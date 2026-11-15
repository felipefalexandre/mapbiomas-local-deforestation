from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

from .audit import write_audit_report
from .config import RunConfig, build_config, load_config_file, merge_dicts
from .deforestation import run_deforestation
from .preflight import format_report, preflight, write_preflight_report
from .qa import format_qa, qa_products
from .secondary_vegetation import run_secondary_products

LOGGER = logging.getLogger("mapbiomas_local")


def add_common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", type=Path, help="TOML, JSON or YAML configuration file")
    parser.add_argument("--input-dir", type=Path, help="Directory with annual MapBiomas rasters")
    parser.add_argument(
        "--filename-pattern",
        help="Filename pattern with a {year} placeholder (default: mapbiomas_col11_{year}.tif)",
    )
    parser.add_argument("--output-dir", type=Path, help="Output directory")
    parser.add_argument("--years", nargs="+", type=int, help="Explicit year subset")
    parser.add_argument("--deforestation-start", type=int)
    parser.add_argument("--deforestation-end", type=int)
    parser.add_argument("--window-size", type=int, help="Window size (multiple of 512)")
    parser.add_argument("--halo", type=int, help="Halo in pixels for the spatial filter")
    parser.add_argument("--group-size-filter", type=int, help="Maximum patch size in pixels")
    parser.add_argument("--group-size-exception", type=int, help="Maximum patch size for last year")
    parser.add_argument("--max-windows", type=int, help="Limit number of windows (sampling)")
    parser.add_argument("--window-start", type=int, help="Skip the first N windows (sampling)")
    parser.add_argument("--checkpoint-every", type=int)
    parser.add_argument("--compression", help="GeoTIFF compression (default: deflate)")
    parser.add_argument(
        "--spatial-filter",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Apply the 8-connected minimum patch filter",
    )
    parser.add_argument(
        "--blip-filter",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Apply the one-year vegetation blip filter",
    )
    parser.add_argument(
        "--secondary-end-rules",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Apply anchored end-of-series rules",
    )
    parser.add_argument("--log-level", default=None, choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    parser.add_argument("--no-progress", action="store_true", help="Disable progress bars")
    parser.add_argument("--force", action="store_true", help="Ignore checkpoints")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mapbiomas-local",
        description="Local processing of MapBiomas Collection 11 deforestation and secondary vegetation",
    )
    parser.add_argument("--version", action="version", version="mapbiomas-local 0.1.0")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run the full pipeline")
    add_common_arguments(run_parser)
    run_parser.add_argument(
        "--steps",
        nargs="+",
        choices=["audit", "deforestation", "secondary"],
        default=["deforestation"],
    )
    run_parser.add_argument("--write-audit", action="store_true", help="Write audit reports first")

    for name, help_text in (
        ("audit", "Audit annual rasters"),
        ("preflight", "Validate inputs before processing"),
        ("deforestation", "Build annual deforestation transition maps"),
        ("secondary", "Build secondary vegetation age and deforestation frequency"),
        ("qa", "Check consistency of the generated products"),
    ):
        sub = subparsers.add_parser(name, help=help_text)
        add_common_arguments(sub)
        if name in ("audit", "preflight"):
            sub.add_argument("--blocks", type=int, default=12, help="Native blocks per raster")
        if name == "preflight":
            sub.add_argument("--deep", action="store_true", help="Read every block (slow)")
        if name == "qa":
            sub.add_argument(
                "--sample-blocks",
                type=int,
                default=200,
                help="Blocks sampled per file; use 0 for a full scan",
            )
    return parser


def namespace_overrides(args: argparse.Namespace) -> dict:
    skip = {
        "command",
        "config",
        "steps",
        "write_audit",
        "no_progress",
        "force",
        "blocks",
        "deep",
        "sample_blocks",
    }
    overrides = {}
    for key, value in vars(args).items():
        if key in skip or value is None:
            continue
        overrides[key] = value
    return overrides


def build_runtime_config(args: argparse.Namespace) -> RunConfig:
    data = {}
    if getattr(args, "config", None):
        data = load_config_file(args.config)
    merged = merge_dicts(data, namespace_overrides(args))
    return build_config(merged)


def configure_logging(config: RunConfig, log_level: str | None = None) -> Path:
    config.logs_dir.mkdir(parents=True, exist_ok=True)
    level = getattr(logging, (log_level or config.log_level).upper(), logging.INFO)
    log_path = config.logs_dir / f"run_{time.strftime('%Y%m%d_%H%M%S')}.log"
    handlers = [logging.StreamHandler(sys.stdout), logging.FileHandler(log_path, encoding="utf-8")]
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
        force=True,
    )
    return log_path


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        config = build_runtime_config(args)
    except Exception as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2
    log_path = configure_logging(config, getattr(args, "log_level", None))
    LOGGER.info("Configuration:\n%s", config.summary())
    LOGGER.info("Log file: %s", log_path)
    progress = not getattr(args, "no_progress", False)
    force = getattr(args, "force", False)

    try:
        command = args.command
        if command == "audit":
            products = write_audit_report(config, n_blocks=args.blocks)
            LOGGER.info("Audit written to %s and %s", products["json"], products["markdown"])
        elif command == "preflight":
            report = preflight(
                config,
                start=config.deforestation_start,
                end=config.deforestation_end,
                n_blocks=args.blocks,
                deep=args.deep,
            )
            write_preflight_report(config, report)
            print(format_report(report))
            if not report["ok"]:
                return 3
        elif command == "deforestation":
            summary = run_deforestation(config, progress=progress, force=force)
            LOGGER.info("Deforestation summary: %s", summary)
        elif command == "secondary":
            summary = run_secondary_products(config, progress=progress)
            LOGGER.info("Secondary products: %s", summary)
        elif command == "qa":
            report = qa_products(
                config,
                progress=progress,
                sample_blocks=args.sample_blocks or None,
            )
            print(format_qa(report))
            if not report["ok"]:
                return 4
        elif command == "run":
            steps = list(args.steps)
            if args.write_audit and "audit" not in steps:
                steps.insert(0, "audit")
            if "audit" in steps:
                write_audit_report(config, n_blocks=getattr(args, "blocks", 12))
            if "deforestation" in steps:
                run_deforestation(config, progress=progress, force=force)
            if "secondary" in steps:
                run_secondary_products(config, progress=progress)
        else:
            parser.error(f"unknown command: {command}")
    except Exception as exc:
        LOGGER.exception("processing failed: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
