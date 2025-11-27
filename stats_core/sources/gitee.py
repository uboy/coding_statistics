"""
Gitee/GitCode/GitCode.com adapters using /api/v5 endpoints.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable, Iterator, Any
import logging

from requests import Session

from .base import BaseSource, PullRequestRecord, CommitRecord

logger = logging.getLogger(__name__)


class GiteeLikeSource(BaseSource):
    """
    Adapter for APIs compatible with ``/api/v5`` (Gitee, gitcode.net/.com).
    """

    name = "gitee"

    def __init__(self, session: Session, cfg_section, platform: str):
        self.session = session
        self.platform = platform
        self.cfg = cfg_section
        self.base_url = cfg_section.get(f"{platform}-url", cfg_section.get("url", "https://gitee.com")).rstrip("/")
        self.token = cfg_section.get("token")
        repos = cfg_section.get("repository", "")
        self.repositories = [repo.strip() for repo in repos.split(",") if repo.strip()]
        if not self.repositories:
            raise ValueError(f"Секция [{platform}] должна содержать список repository.")
        self.branch = cfg_section.get("branch")
        self.per_page = cfg_section.getint("per_page", 50)

    # BaseSource API ------------------------------------------------------

    def fetch_pull_requests(self, **kwargs) -> Iterable[PullRequestRecord]:
        params = kwargs.get("params")
        start = params.start_dt if params else None
        end = params.end_dt if params else None

        for repo in self.repositories:
            owner, name = repo.split("/", 1)
            for pr_item in self._iter_pull_requests(owner, name, start, end):
                detail, additions, deletions = self._pull_details(owner, name, pr_item["number"])
                branch = detail.get("base", {}).get("ref")
                if self.branch and branch != self.branch:
                    continue
                reviewers = tuple(
                    reviewer.get("login") or reviewer.get("name", "")
                    for reviewer in detail.get("assignees", [])
                    if reviewer.get("accept", True)
                )
                created_at = self._parse_dt(detail.get("created_at"))
                merged_at = self._parse_dt(detail.get("merged_at"))

                yield PullRequestRecord(
                    platform=self.platform,
                    repository=repo,
                    title=detail.get("title", ""),
                    url=detail.get("html_url", ""),
                    author=detail.get("user", {}).get("name") or detail.get("user", {}).get("login", "Unknown"),
                    reviewers=reviewers,
                    created_at=created_at,
                    merged_at=merged_at,
                    additions=additions,
                    deletions=deletions,
                    branch=branch,
                    extra={
                        "state": detail.get("state", "unknown"),
                        "login": detail.get("user", {}).get("login", ""),
                    },
                )

    def fetch_commits(self, **kwargs) -> Iterable[CommitRecord]:
        params = kwargs.get("params")
        start = params.start_dt if params else None
        end = params.end_dt if params else None
        branch_filter = self.branch or (params.extra.get("branch") if params and params.extra else None)

        for repo in self.repositories:
            owner, name = repo.split("/", 1)
            for commit_item in self._iter_commits(owner, name, branch_filter, start, end):
                detail = self._commit_detail(owner, name, commit_item["sha"])
                commit = detail.get("commit", {})
                author = commit.get("author", {})
                created_at = self._parse_dt(author.get("date"))
                stats = detail.get("stats", {})
                yield CommitRecord(
                    platform=self.platform,
                    repository=repo,
                    sha=commit_item["sha"],
                    url=commit_item.get("html_url", detail.get("html_url", "")),
                    author=author.get("name", "Unknown"),
                    message=commit.get("message", ""),
                    created_at=created_at or datetime.utcnow(),
                    additions=stats.get("additions", 0),
                    deletions=stats.get("deletions", 0),
                )

    # Internal helpers ----------------------------------------------------

    def _request(self, path: str, params: dict | None = None) -> Any:
        url = f"{self.base_url}{path}"
        params = dict(params or {})
        if self.token:
            params.setdefault("access_token", self.token)
        resp = self.session.get(url, params=params, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def _paginate(self, path: str, params: dict | None = None) -> Iterator[Any]:
        base_params = dict(params or {})
        page = 1
        while True:
            page_params = base_params | {"page": page, "per_page": self.per_page}
            data = self._request(path, page_params)
            if not data:
                break
            yield from data
            if len(data) < self.per_page:
                break
            page += 1

    def _iter_pull_requests(
        self,
        owner: str,
        repo: str,
        start: datetime | None,
        end: datetime | None,
    ) -> Iterator[Any]:
        params: dict[str, Any] = {"state": "all", "sort": "updated", "direction": "desc"}
        if start:
            params["since"] = start.isoformat()
        if end:
            params["before"] = end.isoformat()
        path = f"/api/v5/repos/{owner}/{repo}/pulls"
        yield from self._paginate(path, params)

    def _pull_details(self, owner: str, repo: str, number: int):
        detail = self._request(f"/api/v5/repos/{owner}/{repo}/pulls/{number}")
        files = self._request(f"/api/v5/repos/{owner}/{repo}/pulls/{number}/files") or []
        additions = sum(int(file.get("additions", 0)) for file in files)
        deletions = sum(int(file.get("deletions", 0)) for file in files)
        return detail, additions, deletions

    def _iter_commits(
        self,
        owner: str,
        repo: str,
        branch: str | None,
        start: datetime | None,
        end: datetime | None,
    ) -> Iterator[Any]:
        params: dict[str, Any] = {}
        if branch:
            params["sha"] = branch
        if start:
            params["since"] = start.isoformat()
        if end:
            params["until"] = end.isoformat()
        path = f"/api/v5/repos/{owner}/{repo}/commits"
        yield from self._paginate(path, params)

    def _commit_detail(self, owner: str, repo: str, sha: str) -> dict:
        return self._request(f"/api/v5/repos/{owner}/{repo}/commits/{sha}")

    @staticmethod
    def _parse_dt(value: str | None) -> datetime | None:
        if not value:
            return None
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            logger.warning("Failed to parse datetime %s", value)
            return None


# Support for collect_from_links ------------------------------------------------
PR_URL_RE = re.compile(
    r"https://(gitee\.com|gitcode\.(?:net|com))/([^/]+)/([^/]+)/pull(?:s)?/(\d+)",
    re.IGNORECASE,
)
COMMIT_URL_RE = re.compile(
    r"https://(gitee\.com|gitcode\.(?:net|com))/([^/]+)/([^/]+)/commit/([0-9a-fA-F]+)",
    re.IGNORECASE,
)


def fetch_records_from_url(self, url: str, **_) -> Iterable[PullRequestRecord | CommitRecord]:  # type: ignore[misc]
    match = PR_URL_RE.match(url)
    if match:
        _, owner, repo, pr_id = match.groups()
        detail, additions, deletions = self._pull_details(owner, repo, int(pr_id))
        created_at = self._parse_dt(detail.get("created_at"))
        merged_at = self._parse_dt(detail.get("merged_at"))
        reviewers = tuple(
            reviewer.get("login") or reviewer.get("name", "")
            for reviewer in detail.get("assignees", [])
            if reviewer.get("accept", True)
        )
        return [
            PullRequestRecord(
                platform=self.platform,
                repository=f"{owner}/{repo}",
                title=detail.get("title", ""),
                url=url,
                author=detail.get("user", {}).get("name") or detail.get("user", {}).get("login", "Unknown"),
                reviewers=reviewers,
                created_at=created_at,
                merged_at=merged_at,
                additions=additions,
                deletions=deletions,
                branch=detail.get("base", {}).get("ref"),
                extra={"state": detail.get("state", "unknown")},
            )
        ]

    match = COMMIT_URL_RE.match(url)
    if match:
        _, owner, repo, sha = match.groups()
        detail = self._commit_detail(owner, repo, sha)
        commit = detail.get("commit", {})
        author = commit.get("author", {})
        created_at = self._parse_dt(author.get("date"))
        stats = detail.get("stats", {})
        return [
            CommitRecord(
                platform=self.platform,
                repository=f"{owner}/{repo}",
                sha=sha,
                url=url,
                author=author.get("name", "Unknown"),
                message=commit.get("message", ""),
                created_at=created_at or datetime.utcnow(),
                additions=stats.get("additions", 0),
                deletions=stats.get("deletions", 0),
            )
        ]

    return []


GiteeLikeSource.fetch_records_from_url = fetch_records_from_url  # type: ignore[attr-defined]


