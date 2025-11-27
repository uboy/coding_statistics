"""
Source adapters for Git/Gerrit style services.

Each module exposes a subclass of :class:`stats_core.sources.base.BaseSource`
that knows how to fetch data from a specific service (Gitee, GitLab, etc.).
"""

from .base import BaseSource, PullRequestRecord, CommitRecord

__all__ = [
    "BaseSource",
    "PullRequestRecord",
    "CommitRecord",
]

