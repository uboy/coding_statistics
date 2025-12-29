"""
CodeHub/OpenCodeHub adapters (GitLab-compatible API).
"""

from __future__ import annotations

from datetime import datetime
from typing import Iterable, Iterator, Any
import logging
import urllib.parse

import requests
from requests import Session

from .base import BaseSource, PullRequestRecord, CommitRecord

logger = logging.getLogger(__name__)


class CodeHubSource(BaseSource):
    name = "codehub"

    def __init__(self, session: Session, cfg_section, platform: str):
        self.session = session
        self.platform = platform
        self.base_url = cfg_section.get(f"{platform}-url", cfg_section.get("codehub-url", cfg_section.get("url", ""))).rstrip("/")
        if not self.base_url:
            raise ValueError(f"Config [{platform}] must define codehub-url/url.")
        token = cfg_section.get("token")
        if token:
            self.session.headers.setdefault("Private-Token", token)
        repos = cfg_section.get("project") or cfg_section.get("repository", "")
        self.projects = [repo.strip() for repo in repos.split(",") if repo.strip()]
        if not self.projects:
            raise ValueError(f"Config [{platform}] must define 'project='.")
        self.branch = cfg_section.get("branch")
        self.per_page = cfg_section.getint("per_page", 50)

    def fetch_pull_requests(self, **kwargs) -> Iterable[PullRequestRecord]:
        params = kwargs.get("params")
        start = params.start_dt if params else None
        end = params.end_dt if params else None

        for project in self.projects:
            project_id = urllib.parse.quote(project, safe="")
            for mr in self._iter_merge_requests(project_id, start, end):
                additions, deletions, used_direct_stats = _extract_mr_line_stats(mr)
                if not used_direct_stats:
                    changes = self._fetch_mr_changes(project_id, mr["iid"])
                    changes_list = changes.get("changes", []) if isinstance(changes, dict) else []
                    additions = sum(_coerce_int(change.get("added_lines", 0)) for change in changes_list)
                    deletions = sum(_coerce_int(change.get("removed_lines", 0)) for change in changes_list)
                branch = mr.get("target_branch")
                if self.branch and branch != self.branch:
                    continue
                reviewers = tuple(user.get("name", "") for user in mr.get("merge_request_reviewer_list", []))
                created_at = _parse_iso(mr.get("created_at"))
                merged_at = _parse_iso(mr.get("merged_at"))
                yield PullRequestRecord(
                    platform=self.platform,
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
                author_name = detail.get("author_name") or detail.get("committer_name") or "Unknown"
                created_at = _parse_iso(detail.get("created_at"))
                yield CommitRecord(
                    platform=self.platform,
                    repository=project,
                    sha=commit["id"],
                    url=commit.get("web_url", ""),
                    author=author_name,
                    message=detail.get("title", ""),
                    created_at=created_at or datetime.utcnow(),
                    additions=stats.get("added_lines", 0),
                    deletions=stats.get("removed_lines", 0),
                )

    @property
    def api_base(self) -> str:
        return f"{self.base_url}/api/v4"

    def _mr_changes_paths(self, project_id: str, mr_iid: str | int) -> list[str]:
        paths = [
            f"/projects/{project_id}/isource/merge_requests/{mr_iid}/changes",
            f"/projects/{project_id}/merge_requests/{mr_iid}/changes",
        ]
        return paths

    def _fetch_mr_changes(self, project_id: str, mr_iid: str | int) -> Any:
        """
        Fetch MR changes using a platform-appropriate endpoint.

        For some CodeHub variants (notably OpenCodeHub) the "changes" endpoint
        lives under /merge_requests instead of /isource/merge_requests.
        """
        last_404: Exception | None = None
        for path in self._mr_changes_paths(project_id, mr_iid):
            try:
                return self._request(path)
            except requests.exceptions.HTTPError as exc:
                status = getattr(getattr(exc, "response", None), "status_code", None)
                if status in {404, 410}:
                    last_404 = exc
                    continue
                raise
        if last_404:
            raise last_404
        raise RuntimeError(f"Unable to fetch merge request changes for project={project_id} iid={mr_iid}")

    def _request(self, path: str, params: dict | None = None) -> Any:
        url = f"{self.api_base}{path}"
        
        # Log request details (hide token)
        logger.debug(
            "CodeHub API request: %s | headers: %s | params: %s",
            url,
            {k: v if k.lower() not in ("private-token", "authorization") else "***" for k, v in self.session.headers.items()},
            params or {},
        )
        
        try:
            resp = self.session.get(url, params=params, timeout=30)
            logger.debug("CodeHub API response: %s %s", resp.status_code, resp.reason)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            response_text = ""
            if hasattr(exc, "response") and exc.response is not None:
                try:
                    response_text = exc.response.text[:500]
                except Exception:
                    pass
            logger.error(
                "CodeHub API error for %s | params: %s | error: %s | response: %s",
                url,
                params or {},
                exc,
                response_text,
            )
            raise

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
        path = f"/projects/{project_id}/isource/merge_requests"
        yield from self._paginate(path, params)

    def _iter_commits(
        self,
        project_id: str,
        start: datetime | None,
        end: datetime | None,
    ) -> Iterator[Any]:
        params: dict[str, Any] = {}
        if self.branch:
            params["ref"] = self.branch
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


def _coerce_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _extract_mr_line_stats(mr: Any) -> tuple[int, int, bool]:
    """
    Return (additions, deletions, used_direct_stats).

    Some CodeHub instances include aggregate line stats directly in the MR payload
    as 'added_lines' and 'removed_lines', so the /changes endpoint is optional.
    """
    if isinstance(mr, dict) and ("added_lines" in mr or "removed_lines" in mr):
        return _coerce_int(mr.get("added_lines", 0)), _coerce_int(mr.get("removed_lines", 0)), True
    return 0, 0, False

