"""
Command line entry points for the refactored statistics tooling.

Provides two primary commands:

* ``setup`` – interactively guide the user through config and token setup.
* ``run`` – execute one of the supported reports with the supplied sources.
"""

from __future__ import annotations

import argparse
import pathlib
from typing import Sequence

from . import config as config_utils
from .stats.collector import collect_stats, CollectorParams, SOURCE_BUILDERS
from .reports import registry as report_registry


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stats_main",
        description="Unified statistics toolkit for Git/Jira style services.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    setup_cmd = sub.add_parser("setup", help="Guide through config/token setup.")
    setup_cmd.add_argument("--config", default=str(config_utils.DEFAULT_CONFIG_FILE), help="Path to config.ini.")

    run_cmd = sub.add_parser("run", help="Execute a report.")
    run_cmd.add_argument("--config", default=str(config_utils.DEFAULT_CONFIG_FILE), help="Path to config.ini.")
    run_cmd.add_argument("--report", required=True, choices=report_registry.available_reports())
    run_cmd.add_argument("--sources", nargs="+", help="Optional list of sources to pull from. Defaults to 'jira' for jira_weekly report.")
    run_cmd.add_argument("--start", help="Start date (YYYY-MM-DD)")
    run_cmd.add_argument("--end", help="End date (YYYY-MM-DD)")
    run_cmd.add_argument("--members", help="Path to member list (if applicable).")
    run_cmd.add_argument("--links-file", help="Path to file with explicit links (for review stats).")
    run_cmd.add_argument("--output-formats", nargs="+", default=["excel"])
    run_cmd.add_argument("--params", nargs="*", help="Extra key=value pairs passed to the report.")

    return parser


def parse_key_value_pairs(pairs: Sequence[str] | None) -> dict[str, str]:
    result: dict[str, str] = {}
    if not pairs:
        return result
    for item in pairs:
        if "=" not in item:
            raise ValueError(f"Expected key=value, got {item!r}")
        key, value = item.split("=", 1)
        result[key.strip()] = value.strip()
    return result


def _available_sources(config) -> list[str]:
    return [name for name in SOURCE_BUILDERS.keys() if config.has_section(name)]


def cmd_setup(config_path: pathlib.Path | str) -> None:
    cfg_path = pathlib.Path(config_path)
    if not cfg_path.exists():
        template_path = pathlib.Path("config.ini_template")
        if template_path.exists():
            cfg_path.write_text(template_path.read_text(encoding="utf-8"), encoding="utf-8")
            print(f"Создан {cfg_path} на основе config.ini_template.")
        else:
            cfg_path.write_text("[jira]\nurl=\nusername=\npassword=\n", encoding="utf-8")
            print(f"Создан минимальный {cfg_path}. Заполните секции вручную.")
    config = config_utils.load_config(cfg_path)
    services = ["jira", "gitee", "gitcode", "github", "gitlab", "codehub", "gerrit"]
    missing = config_utils.ensure_tokens(config, services)
    if missing:
        config_utils.interactive_token_setup(config, missing, cfg_path)
    else:
        print("Все необходимые токены уже настроены.")


def cmd_run(args: argparse.Namespace) -> None:
    config = config_utils.load_config(args.config)
    extra_params = parse_key_value_pairs(args.params)
    start = args.start or extra_params.get("start")
    end = args.end or extra_params.get("end")
    if start:
        extra_params["start"] = start
    if end:
        extra_params["end"] = end

    reporting_section = config["reporting"] if config.has_section("reporting") else {}
    links_file = args.links_file or extra_params.get("links_file") or reporting_section.get("links_file")
    if links_file:
        extra_params.setdefault("links_file", links_file)

    # Default to 'jira' for jira_weekly report if no sources specified
    if args.report == "jira_weekly" and not args.sources:
        sources = ["jira"]
    else:
        sources = args.sources or _available_sources(config)
        if not sources:
            sources = []

    if sources:
        missing = config_utils.ensure_tokens(config, sources)
        if missing:
            print("⚠️  Не хватает токенов для следующих сервисов:")
            for service in missing:
                hint = config_utils.TOKEN_HINTS.get(service, "Добавьте необходимые данные в config.ini.")
                print(f"  - [{service}] {hint}")
            raise SystemExit("Заполните токены и повторите команду.")

    collector_params = CollectorParams(
        sources=sources,
        start=start,
        end=end,
        members_file=args.members,
        extra=extra_params,
    )
    dataset = collect_stats(config, collector_params)

    report = report_registry.get(args.report)
    report.run(
        dataset=dataset,
        config=config,
        output_formats=args.output_formats,
        extra_params=extra_params,
    )


def main(argv: Sequence[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "setup":
        cmd_setup(args.config)
    elif args.command == "run":
        cmd_run(args)
    else:  # pragma: no cover - guarded by argparse
        parser.error("Unknown command")

