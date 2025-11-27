"""
Common base classes and dataclasses for source adapters.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Protocol, runtime_checkable, Mapping, Any


@dataclass(slots=True)
class PullRequestRecord:
    platform: str
    repository: str
    title: str
    url: str
    author: str
    reviewers: tuple[str, ...]
    created_at: datetime
    merged_at: datetime | None
    additions: int
    deletions: int
    branch: str | None = None
    extra: Mapping[str, Any] | None = None


@dataclass(slots=True)
class CommitRecord:
    platform: str
    repository: str
    sha: str
    url: str
    author: str
    message: str
    created_at: datetime
    additions: int
    deletions: int
    extra: Mapping[str, Any] | None = None


@runtime_checkable
class BaseSource(Protocol):
    """
    Interface for all data sources.
    """

    name: str

    def fetch_pull_requests(self, **kwargs) -> Iterable[PullRequestRecord]:
        ...

    def fetch_commits(self, **kwargs) -> Iterable[CommitRecord]:
        ...

    def fetch_records_from_url(self, url: str, **kwargs) -> Iterable[PullRequestRecord | CommitRecord]:
        """
        Optional helper used for link-driven workflows (e.g. unified review stats).
        """
        ...

