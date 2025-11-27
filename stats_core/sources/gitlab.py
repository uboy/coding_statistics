"""
GitLab adapter.
"""

from __future__ import annotations

from datetime import datetime
from typing import Iterable, Iterator, Any
import logging
import urllib.parse

from requests import Session

from .base import BaseSource, PullRequestRecord, CommitRecord

logger = logging.getLogger(__name__)


class GitLabSource(BaseSource):
    name = "gitlab"

    def __init__(self, session: Session, cfg_section):
        self.session = session
        self.base_url = cfg_section.get("gitlab-url", cfg_section.get("url", "")).rstrip("/")
        if not self.base_url:
            raise ValueError("Config [gitlab] must define gitlab-url.")
        token = cfg_section.get("token")
        if token:
            self.session.headers.setdefault("PRIVATE-TOKEN", token)
        repos = cfg_section.get("repository") or cfg_section.get("project", "")
        self.projects = [repo.strip() for repo in repos.split(",") if repo.strip()]
        if not self.projects:
            raise ValueError("Config [gitlab] must define 'repository=' (project path).")
        self.branch = cfg_section.get("branch")
        self.per_page = cfg_section.getint("per_page", 50)

    def fetch_pull_requests(self, **kwargs) -> Iterable[PullRequestRecord]:
        params = kwargs.get("params")
        start = params.start_dt if params else None
        end = params.end_dt if params else None

        for project in self.projects:
            project_id = urllib.parse.quote(project, safe="")
            for mr in self._iter_merge_requests(project_id, start, end):
                changes = self._request(f"/projects/{project_id}/merge_requests/{mr['iid']}/changes")
                additions = sum(int(change.get("additions", 0)) for change in changes.get("changes", []))
                deletions = sum(int(change.get("deletions", 0)) for change in changes.get("changes", []))
                branch = mr.get("target_branch")
                if self.branch and branch != self.branch:
                    continue
                reviewers = tuple(user.get("name", "") for user in mr.get("reviewed_by", []))
                created_at = _parse_iso(mr.get("created_at"))
                merged_at = _parse_iso(mr.get("merged_at"))
                yield PullRequestRecord(
                    platform=self.name,
                    repository=project,
                    title=mr.get("title", ""),
                    url=mr.get("web_url", ""),
                    author=mr.get("author", {}).get("name", "Unknown"),
                    reviewers=reviewers,
                    created_at=created_at,
                    merged_at=merged_at,
                    additions=additions,
                    deletions=deletions,
                    branch=branch,
                    extra={"state": mr.get("state", "unknown")},
                )

    def fetch_commits(self, **kwargs) -> Iterable[CommitRecord]:
        params = kwargs.get("params")
        start = params.start_dt if params else None
        end = params.end_dt if params else None

        for project in self.projects:
            project_id = urllib.parse.quote(project, safe="")
            for commit in self._iter_commits(project_id, start, end):
                detail = self._request(f"/projects/{project_id}/repository/commits/{commit['id']}")
                stats = detail.get("stats", {})
                author_name = commit.get("author_name") or commit.get("committer_name") or "Unknown"
                created_at = _parse_iso(commit.get("created_at"))
                yield CommitRecord(
                    platform=self.name,
                    repository=project,
                    sha=commit["id"],
                    url=commit.get("web_url", ""),
                    author=author_name,
                    message=commit.get("title", ""),
                    created_at=created_at or datetime.utcnow(),
                    additions=stats.get("additions", 0),
                    deletions=stats.get("deletions", 0),
                )

    # Internal helpers ----------------------------------------------------

    @property
    def api_base(self) -> str:
        return f"{self.base_url}/api/v4"

    def _request(self, path: str, params: dict | None = None) -> Any:
        url = f"{self.api_base}{path}"
        resp = self.session.get(url, params=params, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def _paginate(self, path: str, params: dict | None = None) -> Iterator[Any]:
        page = 1
        while True:
            page_params = dict(params or {})
            page_params.update({"per_page": self.per_page, "page": page})
            data = self._request(path, page_params)
            if not data:
                break
            yield from data
            if len(data) < self.per_page:
                break
            page += 1

    def _iter_merge_requests(
        self,
        project_id: str,
        start: datetime | None,
        end: datetime | None,
    ) -> Iterator[Any]:
        params: dict[str, Any] = {"state": "all", "order_by": "updated_at", "sort": "desc"}
        if start:
            params["updated_after"] = start.isoformat()
        if end:
            params["updated_before"] = end.isoformat()
        path = f"/projects/{project_id}/merge_requests"
        yield from self._paginate(path, params)

    def _iter_commits(
        self,
        project_id: str,
        start: datetime | None,
        end: datetime | None,
    ) -> Iterator[Any]:
        params: dict[str, Any] = {}
        if self.branch:
            params["ref_name"] = self.branch
        if start:
            params["since"] = start.isoformat()
        if end:
            params["until"] = end.isoformat()
        path = f"/projects/{project_id}/repository/commits"
        yield from self._paginate(path, params)


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        logger.warning("Failed to parse datetime %s", value)
        return None

