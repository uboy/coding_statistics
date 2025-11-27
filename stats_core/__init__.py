"""
stats_core
==========

Core package that powers the refactored statistics tooling.  It exposes
high‑level helpers via `stats_core.cli` and is composed of the following
subpackages:

* stats_core.config   – configuration loading, token onboarding.
* stats_core.sources  – adapters for Git/Gerrit/Jira style services.
* stats_core.stats    – aggregation, filtering and consolidation logic.
* stats_core.reports  – report builders that map consolidated data to
                        domain specific outputs (weekly Jira, review stats).
* stats_core.export   – export helpers for Word/Excel/CSV and other formats.

The package is intentionally light-weight at the top level so that
individual modules can be imported without pulling the entire dependency
graph.
"""

from importlib import metadata

__all__ = ["__version__"]


def __getattr__(name: str):
    if name == "__version__":
        try:
            return metadata.version("coding_statistics")
        except metadata.PackageNotFoundError:  # pragma: no cover - local dev
            return "0.0.dev0"
    raise AttributeError(name)

