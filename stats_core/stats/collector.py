"""
High level data collection orchestrator.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Sequence, Any

from configparser import ConfigParser
import requests

from ..sources import base as source_base
from ..sources import gitee, gitlab, github, codehub, gerrit, jira


@dataclass(slots=True)
class CollectorParams:
    sources: Sequence[str]
    start: str | None = None
    end: str | None = None
    members_file: str | None = None
    extra: dict[str, Any] | None = None

    @property
    def start_dt(self) -> datetime | None:
        if not self.start:
            return None
        dt = datetime.fromisoformat(self.start)
        # Normalise to UTC-aware for consistent comparison with API timestamps
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        return dt

    @property
    def end_dt(self) -> datetime | None:
        if not self.end:
            return None
        dt = datetime.fromisoformat(self.end)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        return dt


SOURCE_BUILDERS: dict[str, Any] = {
    "gitee": gitee.GiteeLikeSource,
    "gitcode": gitee.GiteeLikeSource,
    "github": github.GitHubSource,
    "gitlab": gitlab.GitLabSource,
    "codehub": codehub.CodeHubSource,
    "codehub-y": codehub.CodeHubSource,
    "cr-y.codehub": codehub.CodeHubSource,
    "opencodehub": codehub.CodeHubSource,
    "gerrit": gerrit.GerritSource,
    "jira": jira.JiraSource
}


def build_source(config: ConfigParser, name: str) -> source_base.BaseSource:
    session = requests.Session()
    cfg = config[name]
    builder = SOURCE_BUILDERS[name]

    if name in {"gitee", "gitcode"}:
        return builder(session, cfg, name)
    if name in {"codehub", "codehub-y", "cr-y.codehub", "opencodehub"}:
        return builder(session, cfg, name)
    if name == "github":
        return builder(session, cfg)
    if name == "gitlab":
        return builder(session, cfg)
    if name == "gerrit":
        return builder(session, cfg)
    if name == "jira":
        return builder(cfg)
    raise ValueError(f"Unknown source {name}")


def collect_stats(config: ConfigParser, params: CollectorParams) -> dict[str, list]:
    """
    Fetch data from the requested sources. For now this returns a dict with
    two keys ``pull_requests`` and ``commits`` to keep the implementation
    straightforward.  Later iterations can introduce richer data structures.
    """
    from ..config import create_cache_manager
    from ..sources import utils as source_utils

    # Initialize cache manager and set it for API requests
    cache_manager = create_cache_manager(config)
    source_utils.set_cache_manager(cache_manager)

    pull_requests: list[source_base.PullRequestRecord] = []
    commits: list[source_base.CommitRecord] = []
    start_dt = params.start_dt
    end_dt = params.end_dt

    sources = {name: build_source(config, name) for name in params.sources}

    for source in sources.values():
        pull_requests.extend(source.fetch_pull_requests(params=params))
        commits.extend(source.fetch_commits(params=params))

    pull_requests = _filter_pull_requests(pull_requests, start_dt, end_dt)
    commits = _filter_commits(commits, start_dt, end_dt)

    # Save cache after collection
    cache_manager.save()

    return {
        "pull_requests": pull_requests,
        "commits": commits,
    }


def _filter_pull_requests(
    records: Sequence[source_base.PullRequestRecord],
    start: datetime | None,
    end: datetime | None,
) -> list[source_base.PullRequestRecord]:
    if not start and not end:
        return list(records)
    filtered: list[source_base.PullRequestRecord] = []
    for record in records:
        ts = record.merged_at or record.created_at
        if _within_range(ts, start, end):
            filtered.append(record)
    return filtered


def _filter_commits(
    records: Sequence[source_base.CommitRecord],
    start: datetime | None,
    end: datetime | None,
) -> list[source_base.CommitRecord]:
    if not start and not end:
        return list(records)
    filtered: list[source_base.CommitRecord] = []
    for record in records:
        if _within_range(record.created_at, start, end):
            filtered.append(record)
    return filtered


def _within_range(
    value: datetime | None,
    start: datetime | None,
    end: datetime | None,
) -> bool:
    # Normalise all datetimes to naive UTC to avoid offset-aware/naive comparison issues
    def _norm(dt: datetime | None) -> datetime | None:
        if not dt:
            return None
        if dt.tzinfo is not None:
            return dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt

    value = _norm(value)
    start = _norm(start)
    end = _norm(end)

    if not value:
        return not start and not end
    if start and value < start:
        return False
    if end and value > end:
        return False
    return True

