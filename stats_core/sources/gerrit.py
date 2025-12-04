"""
Gerrit adapter built on top of the REST API.
"""

from __future__ import annotations

import json
import logging
import re
import urllib.parse
from datetime import datetime
from typing import Iterable, Iterator, Any, Sequence

from requests import Session

from .base import BaseSource, PullRequestRecord, CommitRecord

logger = logging.getLogger(__name__)
GERRIT_PREFIX = ")]}'\n"
CHANGE_URL_RE = re.compile(r"/c/[^+]+/\+/(\d+)")


class GerritSource(BaseSource):
    name = "gerrit"

    def __init__(self, session: Session, cfg_section):
        self.session = session
        self.base_url = cfg_section.get("gerrit-url", cfg_section.get("url", "")).rstrip("/")
        if not self.base_url:
            raise ValueError("Config [gerrit] must define gerrit-url/url.")
        username = cfg_section.get("username")
        password = cfg_section.get("password")
        if not username or not password:
            raise ValueError("Config [gerrit] must define username/password.")
        self.session.auth = (username, password)
        projects = cfg_section.get("project", "")
        self.projects = [p.strip() for p in projects.split(",") if p.strip()]
        self.verify = cfg_section.getboolean("verify", True)
        self.session.verify = self.verify
        self.extra_query = cfg_section.get("query")
        self.page_size = cfg_section.getint("page_size", 200)

    def fetch_pull_requests(self, **kwargs) -> Iterable[PullRequestRecord]:
        params = kwargs.get("params")
        start_dt = params.start_dt if params else None
        end_dt = params.end_dt if params else None
        projects = self.projects or params.extra.get("projects", []) if params and params.extra else self.projects
        if not projects:
            projects = [None]

        for project in projects:
            for change in self._iter_changes(project, start_dt, end_dt):
                created_at = _parse_iso(change.get("created"))
                merged_at = _parse_iso(change.get("submitted"))
                reviewers = tuple(
                    reviewer.get("name", "")
                    for reviewer in change.get("reviewers", {}).get("REVIEWER", [])
                    if reviewer.get("name")
                )
                yield PullRequestRecord(
                    platform=self.name,
                    repository=change.get("project", project or ""),
                    title=change.get("subject", ""),
                    url=f"{self.base_url}/c/{change.get('project')}/+/{change.get('_number')}",
                    author=change.get("owner", {}).get("name", "Unknown"),
                    reviewers=reviewers,
                    created_at=created_at,
                    merged_at=merged_at,
                    additions=change.get("insertions", 0),
                    deletions=change.get("deletions", 0),
                    branch=change.get("branch"),
                    extra={"state": change.get("status", "").lower()},
                )

    def fetch_commits(self, **kwargs) -> Iterable[CommitRecord]:
        return []

    # Internal helpers ----------------------------------------------------

    def _iter_changes(
        self,
        project: str | None,
        start_dt: datetime | None,
        end_dt: datetime | None,
    ) -> Iterator[dict]:
        query_parts: list[str] = []
        if project:
            query_parts.append(f"project:{project}")
        if start_dt:
            query_parts.append(f"after:{start_dt.date().isoformat()}")
        if end_dt:
            query_parts.append(f"before:{end_dt.date().isoformat()}")
        if self.extra_query:
            query_parts.append(f"({self.extra_query})")
        query = " ".join(query_parts) if query_parts else "status:merged"

        start = 0
        while True:
            params = {
                "q": query,
                "n": self.page_size,
                "start": start,
                "o": ["DETAILED_ACCOUNTS"],
            }
            data = self._request("/a/changes/", params=params)
            if not data:
                break
            for change in data:
                yield change
            if not data[-1].get("_more_changes"):
                break
            start += self.page_size

    def _request(self, path: str, params: dict | None = None) -> list[dict]:
        url = f"{self.base_url}{path}"
        
        # Log request details (hide credentials)
        logger.debug(
            "Gerrit API request: %s | headers: %s | params: %s",
            url,
            {k: v if k.lower() not in ("private-token", "authorization") else "***" for k, v in self.session.headers.items()},
            params or {},
        )
        
        try:
            resp = self.session.get(url, params=params, timeout=30)
            logger.debug("Gerrit API response: %s %s", resp.status_code, resp.reason)
            resp.raise_for_status()
            text = resp.text
            if text.startswith(GERRIT_PREFIX):
                text = text[len(GERRIT_PREFIX) :]
            return json.loads(text)
        except Exception as exc:
            response_text = ""
            if hasattr(exc, "response") and exc.response is not None:
                try:
                    response_text = exc.response.text[:500]
                except Exception:
                    pass
            logger.error(
                "Gerrit API error for %s | params: %s | error: %s | response: %s",
                url,
                params or {},
                exc,
                response_text,
            )
            raise


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

