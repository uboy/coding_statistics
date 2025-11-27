"""
Simple report registry used by the CLI.
"""

from __future__ import annotations

from typing import Callable, Dict, Protocol

from configparser import ConfigParser


class Report(Protocol):
    name: str

    def run(
        self,
        dataset: dict,
        config: ConfigParser,
        output_formats: list[str],
        extra_params: dict | None = None,
    ) -> None:
        ...


_REGISTRY: Dict[str, Report] = {}


def register(report: Report) -> Report:
    _REGISTRY[report.name] = report
    return report


def get(name: str) -> Report:
    return _REGISTRY[name]


def available_reports() -> list[str]:
    return sorted(_REGISTRY.keys())

