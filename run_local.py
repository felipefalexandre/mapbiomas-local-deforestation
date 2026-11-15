from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from mapbiomas_local.cli import configure_logging  # noqa: E402
from mapbiomas_local.config import RunConfig  # noqa: E402
from mapbiomas_local.deforestation import run_deforestation  # noqa: E402
from mapbiomas_local.preflight import (  # noqa: E402
    REQUIRED_YEARS,
    format_report,
    preflight,
    write_preflight_report,
)
from mapbiomas_local.qa import format_qa, qa_products  # noqa: E402
from mapbiomas_local.raster_io import discover_years  # noqa: E402
from mapbiomas_local.secondary_vegetation import run_secondary_products  # noqa: E402

BANNER = """
====================================================================
 mapbiomas-local
 Desmatamento e vegetacao secundaria - Colecao 11 do MapBiomas
====================================================================
Este programa le os GeoTIFFs anuais da Colecao 11 que voce ja tem
no computador, verifica a integridade dos arquivos e gera a serie
anual de desmatamento (classes 0-7).

Nao e necessario Google Earth Engine. Tudo roda localmente.
====================================================================
"""


def ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    try:
        raw = input(f"{prompt}{suffix}: ").strip()
    except EOFError:
        print()
        raise SystemExit("entrada interrompida pelo usuario")
    return raw or str(default)


def ask_path(prompt: str, default: str = "", must_exist: bool = False) -> Path:
    while True:
        raw = ask(prompt, default).strip('"').strip("'")
        path = Path(raw).expanduser()
        if must_exist and not path.is_dir():
            print(f"  pasta nao encontrada: {path}")
            continue
        return path.resolve()


def ask_year(prompt: str, default: int) -> int:
    while True:
        raw = ask(prompt, str(default))
        try:
            return int(raw)
        except ValueError:
            print("  informe um ano valido, por exemplo 2004")


def ask_yes(prompt: str, default: bool = True) -> bool:
    raw = ask(prompt, "S" if default else "n").strip().lower()
    return raw in ("s", "sim", "y", "yes", "")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Assistente local para gerar a serie de desmatamento do MapBiomas"
    )
    parser.add_argument("--input-dir", type=Path, help="Pasta com os rasters anuais")
    parser.add_argument(
        "--filename-pattern",
        default="mapbiomas_col11_{year}.tif",
        help="Padrao do nome dos arquivos (use {year})",
    )
    parser.add_argument("--output-dir", type=Path, default=Path("outputs"))
    parser.add_argument("--start", type=int, help="Primeiro ano da serie")
    parser.add_argument("--end", type=int, help="Ultimo ano da serie")
    parser.add_argument("--yes", action="store_true", help="Nao faz perguntas (modo script)")
    parser.add_argument("--deep-check", action="store_true", help="Le todos os blocos na verificacao")
    parser.add_argument("--no-secondary", action="store_true", help="Nao gera idade/frequencia")
    parser.add_argument("--force", action="store_true", help="Reprocessa tudo")
    parser.add_argument("--no-progress", action="store_true", help="Sem barras de progresso")
    parser.add_argument("--window-start", type=int, default=0, help="Pula as primeiras N janelas")
    parser.add_argument("--max-windows", type=int, help="Limita o numero de janelas (teste)")
    parser.add_argument(
        "--sample-blocks",
        type=int,
        default=200,
        help="Blocos por arquivo no controle de qualidade (0 = tudo)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    args = parse_args(argv)
    print(BANNER)

    if args.input_dir:
        input_dir = args.input_dir.expanduser().resolve()
        if not input_dir.is_dir():
            print(f"Erro: pasta de entrada nao encontrada: {input_dir}")
            return 2
    else:
        input_dir = ask_path(
            "Pasta onde estao os rasters anuais da Colecao 11",
            must_exist=True,
        )

    pattern = args.filename_pattern
    if not args.input_dir and not args.yes:
        pattern = ask("Padrao do nome dos arquivos (use {year})", pattern)

    output_dir = (args.output_dir or Path("outputs")).expanduser().resolve()
    if not args.yes and not args.output_dir:
        output_dir = ask_path("Pasta de saida", str(output_dir))

    base_config = RunConfig(
        input_dir=input_dir,
        output_dir=output_dir,
        filename_pattern=pattern,
    )
    base_config.create_output_dirs()
    log_path = configure_logging(base_config, "INFO")
    print(f"Log: {log_path}\n")

    try:
        available = sorted(discover_years(input_dir, pattern))
    except Exception as exc:
        print(f"Erro ao localizar os rasters: {exc}")
        return 2
    print(f"Anos encontrados ({len(available)}): {available[0]}..{available[-1]}")
    if len(available) < REQUIRED_YEARS:
        print(
            f"Erro: o metodo exige pelo menos {REQUIRED_YEARS} anos; "
            f"foram encontrados {len(available)}."
        )
        return 2

    if args.start is not None and args.end is not None:
        start, end = args.start, args.end
    elif args.yes:
        start, end = available[0], available[-1]
    else:
        start = ask_year("Ano inicial da analise", available[0])
        end = ask_year("Ano final da analise", available[-1])
    if start > end:
        print("Erro: o ano inicial e maior que o ano final.")
        return 2

    deep = args.deep_check
    if not args.yes and not deep:
        deep = ask_yes(
            "Fazer verificacao completa, lendo todos os blocos de todos os anos?",
            default=False,
        )
    print("\nVerificando os arquivos (isso pode levar alguns minutos)...")
    report = preflight(
        base_config,
        start=start,
        end=end,
        n_blocks=24 if deep else 12,
        deep=deep,
    )
    write_preflight_report(base_config, report)
    print(format_report(report))

    if not report["ok"]:
        print("\nCorrija os problemas acima e execute novamente.")
        return 3

    selected = report["selected_years"]
    if report["missing_years"]:
        print(
            f"\nAtencao: faltam os anos {report['missing_years']} no periodo solicitado "
            f"({start}-{end})."
        )
        if not args.yes and not ask_yes(
            f"Continuar usando apenas os anos disponiveis ({selected[0]}-{selected[-1]})?",
            default=True,
        ):
            return 0
    if len(selected) < REQUIRED_YEARS:
        print(f"Erro: restaram apenas {len(selected)} anos; o minimo e {REQUIRED_YEARS}.")
        return 2
    if selected != list(range(start, end + 1)):
        print(f"Serie efetiva: {selected[0]}-{selected[-1]} ({len(selected)} anos)")

    if not args.yes and not ask_yes(
        f"\nIniciar o processamento de {len(selected)} anos? Isso pode levar horas.",
        default=True,
    ):
        return 0

    config = RunConfig(
        input_dir=input_dir,
        output_dir=output_dir,
        filename_pattern=pattern,
        years=selected,
        window_start=args.window_start,
        max_windows=args.max_windows,
    )
    started = time.time()
    try:
        print("\n[1/2] Gerando a serie anual de desmatamento...")
        summary = run_deforestation(
            config, progress=not args.no_progress, force=args.force
        )
    except Exception as exc:
        print(f"\nErro no processamento: {exc}")
        print(f"Detalhes no log: {log_path}")
        return 1

    if not args.no_secondary:
        print("\n[2/2] Gerando idade da vegetacao secundaria e frequencia...")
        try:
            run_secondary_products(config, progress=not args.no_progress)
        except Exception as exc:
            print(f"Aviso: produtos secundarios falharam: {exc}")

    elapsed = time.time() - started
    print("\nControle de qualidade dos produtos...")
    qa = qa_products(
        config,
        progress=not args.no_progress,
        sample_blocks=args.sample_blocks or None,
    )
    print(format_qa(qa))

    print("\n" + "=" * 68)
    print("CONCLUIDO")
    print("=" * 68)
    print(f"Tempo total: {elapsed / 3600:.2f} h")
    print(f"Serie: {summary['years'][0]}-{summary['years'][-1]}")
    print(f"Produtos: {config.deforestation_dir}")
    print(f"Relatorios: {config.reports_dir}")
    print(f"Log: {log_path}")
    print(
        "\nOs dois primeiros anos sao aquecimento. "
        f"Use a serie a partir de {summary['recommended_start']}."
    )
    if qa["ok"]:
        print("Os produtos passaram no controle de qualidade.")
    else:
        print("ATENCAO: o controle de qualidade encontrou problemas; veja o relatorio.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
