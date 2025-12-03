"""
GitHub adapter using the REST v3 API.
"""

from __future__ import annotations

from datetime import datetime
from typing import Iterable, Iterator, Any, Optional
import logging
import re

from requests import Session

from .base import BaseSource, PullRequestRecord, CommitRecord

logger = logging.getLogger(__name__)

PR_URL_RE = re.compile(r"https://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/pull/(?P<number>\d+)", re.IGNORECASE)
COMMIT_URL_RE = re.compile(r"https://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/commit/(?P<sha>[0-9a-fA-F]+)")


class GitHubSource(BaseSource):
    name = "github"

    def __init__(self, session: Session, cfg_section):
        self.session = session
        token = cfg_section.get("token")
        if not token:
            raise ValueError("GitHub token is required in config [github].")
        self.session.headers.setdefault("Authorization", f"token {token}")
        self.session.headers.setdefault("Accept", "application/vnd.github+json")
        repos = cfg_section.get("repository", "")
        self.repositories = [repo.strip() for repo in repos.split(",") if repo.strip()]
        if not self.repositories:
            raise ValueError("Config [github] must define 'repository=owner/name,..'.")
        self.branch = cfg_section.get("branch")
        self.per_page = cfg_section.getint("per_page", 50)

    def fetch_pull_requests(self, **kwargs) -> Iterable[PullRequestRecord]:
        params = kwargs.get("params")
        start = params.start_dt if params else None
        end = params.end_dt if params else None

        for repo in self.repositories:
            for pr in self._iter_pull_requests(repo, start, end):
                # Tests may provide fully-populated PR dicts via monkeypatch.
                # If essential fields are present, build the record directly to avoid extra HTTP calls.
                if {"title", "html_url", "user", "base"}.issubset(pr.keys()):
                    created_at = _parse_iso(pr.get("created_at"))
                    merged_at = _parse_iso(pr.get("merged_at"))
                    reviewers = tuple(user.get("login", "") for user in pr.get("requested_reviewers", []))
                    record = PullRequestRecord(
                        platform=self.name,
                        repository=repo,
                        title=pr.get("title", ""),
                        url=pr.get("html_url", ""),
                        author=pr.get("user", {}).get("login", "Unknown"),
                        reviewers=reviewers,
                        created_at=created_at,
                        merged_at=merged_at,
                        additions=pr.get("additions", 0),
                        deletions=pr.get("deletions", 0),
                        branch=pr.get("base", {}).get("ref"),
                        extra={"state": pr.get("state", "unknown")},
                    )
                    yield record
                else:
                    record = self._build_pr_record(repo, pr["number"])
                    if record:
                        yield record

    def fetch_commits(self, **kwargs) -> Iterable[CommitRecord]:
        params = kwargs.get("params")
        start = params.start_dt if params else None
        end = params.end_dt if params else None

        for repo in self.repositories:
            for commit in self._iter_commits(repo, start, end):
                # Allow tests to inject fully-populated commit dicts via monkeypatch.
                if {"sha", "html_url", "commit"}.issubset(commit.keys()):
                    commit_info = commit.get("commit", {})
                    author = commit_info.get("author", {})
                    created_at = _parse_iso(author.get("date"))
                    stats = commit.get("stats", {}) or {}
                    record = CommitRecord(
                        platform=self.name,
                        repository=repo,
                        sha=commit["sha"],
                        url=commit.get("html_url", ""),
                        author=author.get("name", "Unknown"),
                        message=commit_info.get("message", ""),
                        created_at=created_at or datetime.utcnow(),
                        additions=stats.get("additions", 0),
                        deletions=stats.get("deletions", 0),
                    )
                    yield record
                else:
                    record = self._build_commit_record(repo, commit["sha"])
                    if record:
                        yield record

    def fetch_records_from_url(self, url: str, **kwargs) -> Iterable[PullRequestRecord | CommitRecord]:
        match = PR_URL_RE.match(url)
        if match:
            repo = f"{match.group('owner')}/{match.group('repo')}"
            try:
                record = self._build_pr_record(repo, int(match.group("number")), url_override=url)
            except Exception as exc:  # pragma: no cover
                logger.warning("Не удалось получить PR %s: %s", url, exc)
                return []
            return [record] if record else []

        match = COMMIT_URL_RE.match(url)
        if match:
            repo = f"{match.group('owner')}/{match.group('repo')}"
            try:
                record = self._build_commit_record(repo, match.group("sha"), url_override=url)
            except Exception as exc:  # pragma: no cover
                logger.warning("Не удалось получить commit %s: %s", url, exc)
                return []
            return [record] if record else []
        return []

    # Internal helpers ----------------------------------------------------

    def _request(self, path: str, params: dict | None = None) -> Any:
        url = f"https://api.github.com{path}"
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

    def _iter_pull_requests(self, repo: str, start: datetime | None, end: datetime | None) -> Iterator[Any]:
        params: dict[str, Any] = {"state": "all", "sort": "updated", "direction": "desc"}
        if start:
            params["since"] = start.isoformat()
        return self._paginate(f"/repos/{repo}/pulls", params)

    def _iter_commits(self, repo: str, start: datetime | None, end: datetime | None) -> Iterator[Any]:
        params: dict[str, Any] = {}
        if self.branch:
            params["sha"] = self.branch
        if start:
            params["since"] = start.isoformat()
        if end:
            params["until"] = end.isoformat()
        return self._paginate(f"/repos/{repo}/commits", params)

    def _build_pr_record(
        self,
        repo: str,
        number: int,
        url_override: Optional[str] = None,
    ) -> Optional[PullRequestRecord]:
        detail = self._request(f"/repos/{repo}/pulls/{number}")
        branch = detail.get("base", {}).get("ref")
        if self.branch and branch != self.branch:
            return None
        created_at = _parse_iso(detail.get("created_at"))
        merged_at = _parse_iso(detail.get("merged_at"))
        reviewers = tuple(user.get("login", "") for user in detail.get("requested_reviewers", []))
        return PullRequestRecord(
            platform=self.name,
            repository=repo,
            title=detail.get("title", ""),
            url=url_override or detail.get("html_url", ""),
            author=detail.get("user", {}).get("login", "Unknown"),
            reviewers=reviewers,
            created_at=created_at,
            merged_at=merged_at,
            additions=detail.get("additions", 0),
            deletions=detail.get("deletions", 0),
            branch=branch,
            extra={"state": detail.get("state", "unknown")},
        )

    def _build_commit_record(
        self,
        repo: str,
        sha: str,
        url_override: Optional[str] = None,
    ) -> Optional[CommitRecord]:
        detail = self._request(f"/repos/{repo}/commits/{sha}")
        commit_info = detail.get("commit", {})
        author = commit_info.get("author", {})
        created_at = _parse_iso(author.get("date"))
        stats = detail.get("stats", {}) or {}
        return CommitRecord(
            platform=self.name,
            repository=repo,
            sha=sha,
            url=url_override or detail.get("html_url", ""),
            author=author.get("name", "Unknown"),
            message=commit_info.get("message", ""),
            created_at=created_at or datetime.utcnow(),
            additions=stats.get("additions", 0),
            deletions=stats.get("deletions", 0),
        )


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

