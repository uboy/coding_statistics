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


def register(report_cls):
    """
    Decorator used on report classes.

    It instantiates the class once and stores the instance in the registry,
    so the CLI can later call ``run`` as an instance method.
    """
    instance: Report = report_cls()  # type: ignore[assignment]
    _REGISTRY[instance.name] = instance
    return report_cls


def get(name: str) -> Report:
    return _REGISTRY[name]


def available_reports() -> list[str]:
    return sorted(_REGISTRY.keys())

