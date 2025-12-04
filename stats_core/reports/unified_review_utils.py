"""
Helpers for collecting merged code statistics across Git services.
"""

from __future__ import annotations

import json
import logging
import os
import re
import urllib.parse
from configparser import ConfigParser
from datetime import datetime
from pathlib import Path
from time import sleep
from typing import Iterable, List, Optional, Dict, Any

import requests
from requests.auth import HTTPBasicAuth

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_DELAY = 2

HEADERS = [
    "Name",
    "Login",
    "PR_Name",
    "PR_URL",
    "PR_State",
    "PR_Created_Date",
    "PR_Merged_Date",
    "branch",
    "Repo",
    "Additions",
    "Deletions",
    "Reviewers",
]


def parse_links(file_path: str) -> List[str]:
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Input file '{file_path}' not found.")
    with path.open("r", encoding="utf-8") as fh:
        return [line.strip() for line in fh if line.strip()]


def init_session(token: Optional[str] = None) -> requests.Session:
    session = requests.Session()
    if token:
        session.headers["Private-Token"] = token
    session.verify = "bundle-ca" if os.path.exists("bundle-ca") else True
    return session


def init_github_session(token: str | None) -> requests.Session:
    session = requests.Session()
    if token:
        session.headers["Authorization"] = f"token {token}"
    session.headers["Accept"] = "application/vnd.github+json"
    return session


def make_api_request(
    session: requests.Session,
    url: str,
    auth: Optional[HTTPBasicAuth] = None,
    max_retries: int = MAX_RETRIES,
) -> Optional[Dict[Any, Any]]:
    for attempt in range(max_retries):
        try:
            resp = session.get(url, auth=auth, timeout=30)
            resp.raise_for_status()
            text = resp.text
            if text.startswith(")]}'\n"):
                text = text[5:]
            return json.loads(text)
        except requests.exceptions.HTTPError as exc:
            logger.warning("HTTP error %s for %s", getattr(exc.response, "status_code", "?"), url)
            if exc.response is not None and exc.response.status_code in (401, 404):
                return None
        except requests.exceptions.RequestException as exc:
            logger.warning("Attempt %s/%s failed for %s: %s", attempt + 1, max_retries, url, exc)
        except json.JSONDecodeError as exc:
            logger.error("JSON parse error for %s: %s", url, exc)
            return None
        if attempt < max_retries - 1:
            sleep(RETRY_DELAY)
    logger.error("Failed to fetch data after %s attempts: %s", max_retries, url)
    return None


def safe_get(data: Dict, *keys, default=0):
    for key in keys:
        if isinstance(data, dict):
            data = data.get(key, {})
        else:
            return default
    return data if data != {} else default


# Gitee / GitCode (.net / .com)
def process_gitee_or_gitcode(url: str, config: ConfigParser, platform: str) -> Optional[List]:
    base_url = config.get(platform, f"{platform}-url", fallback=config.get(platform, "url", fallback=""))
    if not base_url:
        logger.error("Base URL for %s is not configured.", platform)
        return None
    token = config.get(platform, "token", fallback=None)
    session = init_session(token)

    # Support both classic /pulls/ URLs and GitLab-like /merge_requests/ URLs
    pr_match = re.match(
        r"https://(gitee\.com|gitcode\.net|gitcode\.com)/([^/]+)/([^/]+)/(pulls?|merge_requests)/(\d+)",
        url,
    )
    if pr_match:
        _, owner, repo, _, pr_id = pr_match.groups()
        api_url = f"{base_url}/api/v5/repos/{owner}/{repo}/pulls/{pr_id}"
        files_url = f"{api_url}/files"
        pr = make_api_request(session, api_url)
        if not pr:
            return None
        files = make_api_request(session, files_url) or []
        additions = sum(int(f.get("additions", 0)) for f in files)
        deletions = sum(int(f.get("deletions", 0)) for f in files)
        reviewers = ", ".join([r["login"] for r in pr.get("assignees", []) if r.get("accept", True)])
        return [
            safe_get(pr, "user", "name", default="Unknown"),
            safe_get(pr, "user", "login", default="Unknown"),
            pr.get("title", "No title"),
            url,
            pr.get("state", "unknown"),
            pr.get("created_at", ""),
            pr.get("merged_at", ""),
            safe_get(pr, "base", "ref", default=""),
            f"{owner}/{repo}",
            additions,
            deletions,
            reviewers,
        ]

    commit_match = re.match(r"https://(gitee\.com|gitcode\.net|gitcode\.com)/([^/]+)/([^/]+)/commit/([0-9a-fA-F]+)", url)
    if commit_match:
        _, owner, repo, sha = commit_match.groups()
        commit_url = f"{base_url}/api/v5/repos/{owner}/{repo}/commits/{sha}"
        commit = make_api_request(session, commit_url)
        if not commit:
            return None
        additions = safe_get(commit, "stats", "additions")
        deletions = safe_get(commit, "stats", "deletions")
        return [
            safe_get(commit, "author", "name", default="Unknown"),
            safe_get(commit, "author", "name", default="Unknown"),
            safe_get(commit, "commit", "message", default="").splitlines()[0],
            url,
            "committed",
            safe_get(commit, "commit", "author", "date", default=""),
            "",
            "",
            f"{owner}/{repo}",
            additions,
            deletions,
            "",
        ]
    logger.warning("URL does not match gitee/gitcode patterns: %s", url)
    return None


# GitLab
def process_gitlab(url: str, config: ConfigParser) -> Optional[List]:
    base_url = config.get("gitlab", "gitlab-url", fallback=config.get("gitlab", "url", fallback=""))
    token = config.get("gitlab", "token", fallback=None)
    session = init_session(token)
    cleaned = url.replace("#/", "")
    match = re.match(r"https://([^/]+)/([^/]+/[^/]+)/merge_requests/(\d+)", cleaned)
    if not match:
        logger.warning("URL does not match GitLab pattern: %s", url)
        return None
    domain, repo_path, mr_id = match.groups()
    encoded_path = urllib.parse.quote(repo_path, safe="")
    api_url = f"{base_url}/api/v4/projects/{encoded_path}/merge_requests/{mr_id}"
    changes_url = f"{api_url}/changes"
    pr = make_api_request(session, api_url)
    if not pr:
        return None
    changes = make_api_request(session, changes_url) or {}
    additions = sum(f.get("additions", 0) for f in changes.get("changes", []))
    deletions = sum(f.get("deletions", 0) for f in changes.get("changes", []))
    reviewers = pr.get("reviewed_by", [])
    reviewer_names = ", ".join([r["name"] for r in reviewers]) if reviewers else ""
    return [
        safe_get(pr, "author", "name", default="Unknown"),
        safe_get(pr, "author", "username", default="Unknown"),
        pr.get("title", "No title"),
        url,
        pr.get("state", "unknown"),
        pr.get("created_at", ""),
        pr.get("merged_at", ""),
        pr.get("target_branch", ""),
        repo_path,
        additions,
        deletions,
        reviewer_names,
    ]


# CodeHub variants
def process_codehub(url: str, config: ConfigParser, platform: str) -> Optional[List]:
    base_url = config.get(platform, f"{platform}-url", fallback=config.get(platform, "url", fallback=""))
    token = config.get(platform, "token", fallback=None)
    session = init_session(token)
    url_clean = url.replace("#/", "")
    patterns = {
        "opencodehub": {
            "mr": r"https://([^/]+)/OpenSourceCenter_CR/([^/]+/[^/]+)/-/change_requests/(\d+)",
            "commit": r"https://([^/]+)/OpenSourceCenter_CR/([^/]+/[^/]+)/-/commit/([0-9A-Fa-f]+)",
            "prefix": "OpenSourceCenter_CR%2F",
        },
        "codehub-y": {
            "mr": r"https://([^/]+)/([^/]+/[^/]+)/merge_requests/(\d+)",
            "commit": r"https://([^/]+)/([^/]+/[^/]+)/files/commit/([0-9A-Fa-f]+)",
            "prefix": "",
        },
        "cr-y.codehub": {
            "mr": r"https://([^/]+)/(.*)/-/change_requests/(\d+)",
            "commit": r"https://([^/]+)/(.*)/files/commit/([0-9A-Fa-f]+)",
            "prefix": "",
        },
        "codehub": {
            "mr": r"https://([^/]+)/([^/]+/[^/]+)/merge_requests/(\d+)",
            "commit": r"https://([^/]+)/([^/]+/[^/]+)/files/commit/([0-9A-Fa-f]+)",
            "prefix": "",
        },
    }
    pattern_config = patterns.get(platform, patterns["codehub"])
    mr_match = re.match(pattern_config["mr"], url_clean)
    commit_match = re.match(pattern_config["commit"], url_clean)
    prefix = pattern_config["prefix"]

    if mr_match:
        domain, repo_path, mr_id = mr_match.groups()
        encoded_path = urllib.parse.quote(repo_path, safe="")
        api_url = f"{base_url}/api/v4/projects/{prefix}{encoded_path}/isource/merge_requests/{mr_id}"
        changes_url = f"{api_url}/changes"
        pr = make_api_request(session, api_url)
        if not pr:
            return None
        changes = make_api_request(session, changes_url) or {}
        additions = sum(int(f.get("added_lines", 0)) for f in changes.get("changes", []))
        deletions = sum(int(f.get("removed_lines", 0)) for f in changes.get("changes", []))
        reviewers = pr.get("merge_request_reviewer_list", [])
        reviewer_names = ", ".join([r["name"] for r in reviewers]) if reviewers else ""
        return [
            safe_get(pr, "author", "name", default="Unknown"),
            safe_get(pr, "author", "username", default="Unknown"),
            pr.get("title", "No title"),
            url,
            pr.get("state", "unknown"),
            pr.get("created_at", ""),
            pr.get("merged_at", ""),
            pr.get("target_branch", ""),
            repo_path,
            additions,
            deletions,
            reviewer_names,
        ]

    if commit_match:
        domain, repo_path, commit_id = commit_match.groups()
        encoded_path = urllib.parse.quote(repo_path, safe="")
        api_url = f"{base_url}/api/v4/projects/{prefix}{encoded_path}/repository/commits/{commit_id}"
        commit = make_api_request(session, api_url)
        if not commit:
            return None
        additions = safe_get(commit, "stats", "additions")
        deletions = safe_get(commit, "stats", "deletions")
        return [
            commit.get("author_name", "Unknown"),
            commit.get("author_name", "Unknown"),
            commit.get("title", "No title"),
            url,
            "committed",
            commit.get("created_at", ""),
            "",
            "",
            repo_path,
            additions,
            deletions,
            "",
        ]

    logger.warning("URL does not match CodeHub patterns: %s", url)
    return None


# Gerrit
def process_gerrit(url: str, config: ConfigParser) -> Optional[List]:
    match = re.match(r"https?://([^/#]+)/.*/(\d+)/?", url)
    if not match:
        logger.warning("URL does not match Gerrit pattern: %s", url)
        return None
    domain, change_id = match.groups()
    base_url = config.get("gerrit", "gerrit-url", fallback=config.get("gerrit", "url", fallback=""))
    username = config.get("gerrit", "username", fallback=None)
    password = config.get("gerrit", "password", fallback=None)
    if not base_url or not username or not password:
        logger.error("Gerrit credentials are missing in config.")
        return None
    session = init_session()
    auth = HTTPBasicAuth(username, password)
    api_url = f"{base_url}/a/changes/{change_id}/detail"
    data = make_api_request(session, api_url, auth=auth)
    if not data:
        return None
    owner = data.get("owner", {})
    revisions = list(data.get("revisions", {}).values())
    if revisions:
        insertions = revisions[0].get("insertions", 0)
        deletions = revisions[0].get("deletions", 0)
    else:
        insertions = deletions = 0
    reviewers = data.get("reviewers", {}).get("REVIEWER", [])
    owner_name = owner.get("name", "Unknown")
    reviewer_names = ", ".join([r.get("name") for r in reviewers if r.get("name") != owner_name])
    return [
        owner_name,
        owner.get("username", "Unknown"),
        data.get("subject", "No subject"),
        url,
        data.get("status", "unknown").lower(),
        data.get("created", ""),
        data.get("submitted", ""),
        data.get("branch", ""),
        data.get("project", ""),
        insertions,
        deletions,
        reviewer_names,
    ]


# GitHub
def process_github(url: str, config: ConfigParser) -> Optional[List]:
    token = config.get("github", "token", fallback=None)
    if not token:
        logger.error("GitHub token not configured.")
        return None
    session = init_github_session(token)

    pr_match = re.match(r"https://github\.com/([^/]+)/([^/]+)/pull/(\d+)", url)
    if pr_match:
        owner, repo, pr_id = pr_match.groups()
        api_url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_id}"
        pr = make_api_request(session, api_url)
        if not pr:
            return None
        additions = pr.get("additions", 0)
        deletions = pr.get("deletions", 0)
        reviewers = pr.get("requested_reviewers", [])
        reviewer_names = ", ".join([r.get("login") for r in reviewers]) if reviewers else ""
        return [
            safe_get(pr, "user", "login", default="Unknown"),
            safe_get(pr, "user", "login", default="Unknown"),
            pr.get("title", "No title"),
            url,
            pr.get("state", "unknown"),
            pr.get("created_at", ""),
            pr.get("merged_at", ""),
            pr.get("base", {}).get("ref", ""),
            f"{owner}/{repo}",
            additions,
            deletions,
            reviewer_names,
        ]

    commit_match = re.match(r"https://github\.com/([^/]+)/([^/]+)/commit/([0-9a-fA-F]+)", url)
    if commit_match:
        owner, repo, sha = commit_match.groups()
        commit_url = f"https://api.github.com/repos/{owner}/{repo}/commits/{sha}"
        commit = make_api_request(session, commit_url)
        if not commit:
            return None
        stats = commit.get("stats", {})
        additions = stats.get("additions", 0)
        deletions = stats.get("deletions", 0)
        return [
            safe_get(commit, "commit", "author", "name", default="Unknown"),
            safe_get(commit, "author", "login", default="Unknown"),
            safe_get(commit, "commit", "message", default="").splitlines()[0],
            url,
            "committed",
            safe_get(commit, "commit", "author", "date", default=""),
            "",
            "",
            f"{owner}/{repo}",
            additions,
            deletions,
            "",
        ]
    logger.warning("URL does not match GitHub pattern: %s", url)
    return None


# Global cache manager instance (set by report)
_cache_manager: Optional[Any] = None


def set_cache_manager(cache_manager: Any) -> None:
    """Set the global cache manager for link processing."""
    global _cache_manager
    _cache_manager = cache_manager


def process_link(url: str, config: ConfigParser) -> Optional[List]:
    # Check cache first
    if _cache_manager:
        cached = _cache_manager.get_link_result(url)
        if cached is not None:
            return cached

    # Process link
    result = None
    if "gitee.com" in url:
        result = process_gitee_or_gitcode(url, config, "gitee")
    elif "gitcode.net" in url or "gitcode.com" in url:
        result = process_gitee_or_gitcode(url, config, "gitcode")
    elif "github.com" in url:
        result = process_github(url, config)
    elif "gitlab" in url:
        result = process_gitlab(url, config)
    elif "open.codehub" in url:
        result = process_codehub(url, config, "opencodehub")
    elif "codehub-y" in url:
        result = process_codehub(url, config, "codehub-y")
    elif "cr-y.codehub" in url:
        result = process_codehub(url, config, "cr-y.codehub")
    elif "codehub" in url:
        result = process_codehub(url, config, "codehub")
    elif "gerrit" in url or "mgit" in url:
        result = process_gerrit(url, config)
    else:
        logger.warning("Unknown platform in URL: %s", url)

    # Cache result if successful
    if result and _cache_manager:
        _cache_manager.set_link_result(url, result)

    return result

