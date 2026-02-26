"""
Helpers for collecting merged code statistics across Git services.
"""

from __future__ import annotations

import json
import threading
import logging
import os
import re
import urllib.parse
import ssl
from configparser import ConfigParser
from datetime import datetime
from pathlib import Path
from time import sleep
from typing import Iterable, List, Optional, Dict, Any

import requests
from requests.auth import HTTPBasicAuth
from requests.adapters import HTTPAdapter
from urllib3.poolmanager import PoolManager

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_DELAY = 2
class PermissiveSSLAdapter(HTTPAdapter):
    """
    HTTPAdapter that relaxes strict X.509 checks for older / custom CAs on OpenSSL 3.x.
    It still validates against the provided cafile but clears VERIFY_X509_STRICT and enables
    legacy server connect when available.
    """

    def __init__(self, cafile: str, check_hostname: bool = True, permissive_flags: bool = True, **kwargs):
        self._cafile = cafile
        self._check_hostname = check_hostname
        self._permissive_flags = permissive_flags
        super().__init__(**kwargs)

    def init_poolmanager(self, connections, maxsize, block=False, **pool_kwargs):
        ctx = ssl.create_default_context(purpose=ssl.Purpose.SERVER_AUTH)
        ctx.load_verify_locations(cafile=self._cafile)
        if self._permissive_flags:
            if hasattr(ssl, "VERIFY_X509_STRICT"):
                ctx.verify_flags &= ~ssl.VERIFY_X509_STRICT
            # Fall back to default/zero flags if strict not present
            if hasattr(ssl, "VERIFY_DEFAULT"):
                ctx.verify_flags |= ssl.VERIFY_DEFAULT
            else:
                ctx.verify_flags = 0
            if hasattr(ssl, "OP_LEGACY_SERVER_CONNECT"):
                ctx.options |= ssl.OP_LEGACY_SERVER_CONNECT
        ctx.check_hostname = self._check_hostname
        pool_kwargs["ssl_context"] = ctx
        self.poolmanager = PoolManager(
            num_pools=connections, maxsize=maxsize, block=block, **pool_kwargs
        )


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


def init_session(token: Optional[str] = None, proxy_config: Optional[dict] = None, ssl_config: Optional[dict] = None) -> requests.Session:
    """
    Initialize a requests Session with token and proxy support.
    
    Args:
        token: Optional token for Private-Token header (GitLab style)
        proxy_config: Optional proxy config dict with 'http', 'https', 'no_proxy' keys
    """
    session = requests.Session()
    if token:
        session.headers["Private-Token"] = token
    
    # SSL handling: use permissive adapter with bundle-ca when present (helps with OpenSSL 3 strictness)
    check_hostname = True
    if ssl_config is not None:
        check_hostname = ssl_config.get("check_hostname", True)

    if ssl_config and not ssl_config.get("verify", True):
        session.verify = False
        logger.warning("SSL verification is DISABLED (not recommended for production)")
    else:
        bundle_path = os.path.abspath("bundle-ca") if os.path.exists("bundle-ca") else None
        if bundle_path and os.path.isfile(bundle_path):
            try:
                session.mount("https://", PermissiveSSLAdapter(bundle_path, check_hostname=check_hostname, permissive_flags=True))
                session.verify = True  # verification done via adapter context
                logger.info("Using permissive SSL adapter with bundle-ca: %s (check_hostname=%s)", bundle_path, check_hostname)
            except Exception as e:
                logger.warning("Failed to mount permissive SSL adapter, fallback to default verify: %s", e)
                session.verify = bundle_path
        else:
            session.verify = True
            logger.debug("Using default SSL verification (bundle-ca not found)")
    
    # Apply proxy configuration
    if proxy_config:
        # Build proxies dict for requests
        proxies = {}
        if proxy_config.get("http"):
            proxies["http"] = proxy_config["http"]
        if proxy_config.get("https"):
            proxies["https"] = proxy_config["https"]
        
        if proxies:
            session.proxies = proxies
            logger.debug("Proxy configured: %s", {k: v if "password" not in str(v).lower() else "***" for k, v in proxies.items()})
        
        # Handle NO_PROXY
        if proxy_config.get("no_proxy"):
            logger.debug("NO_PROXY configured (will bypass proxy for matching hosts): %s", proxy_config["no_proxy"])
    else:
        # Fallback to environment variables (requests automatically uses these)
        proxy_vars = {
            "HTTP_PROXY": os.environ.get("HTTP_PROXY"),
            "HTTPS_PROXY": os.environ.get("HTTPS_PROXY"),
            "http_proxy": os.environ.get("http_proxy"),
            "https_proxy": os.environ.get("https_proxy"),
            "NO_PROXY": os.environ.get("NO_PROXY"),
            "no_proxy": os.environ.get("no_proxy"),
        }
        active_proxies = {k: v for k, v in proxy_vars.items() if v}
        if active_proxies:
            logger.debug("Proxy from environment variables: %s", {k: v if "password" not in str(v).lower() else "***" for k, v in active_proxies.items()})
    
    logger.debug("Session created: verify=%s, headers=%s, proxies=%s", 
                 session.verify, 
                 {k: v if k.lower() not in ("private-token", "authorization") else "***" for k, v in session.headers.items()},
                 session.proxies if hasattr(session, 'proxies') else "default")
    
    return session


def init_github_session(token: str | None, proxy_config: Optional[dict] = None, ssl_config: Optional[dict] = None) -> requests.Session:
    """
    Initialize a requests Session for GitHub API with token and proxy support.
    
    Args:
        token: GitHub token for Authorization header
        proxy_config: Optional proxy config dict with 'http', 'https', 'no_proxy' keys
    """
    session = requests.Session()
    if token:
        session.headers["Authorization"] = f"token {token}"
    session.headers["Accept"] = "application/vnd.github+json"
    
    # SSL handling: use permissive adapter with bundle-ca when present (helps with OpenSSL 3 strictness)
    check_hostname = True
    if ssl_config is not None:
        check_hostname = ssl_config.get("check_hostname", True)

    if ssl_config and not ssl_config.get("verify", True):
        session.verify = False
        logger.warning("SSL verification is DISABLED for GitHub (not recommended)")
    else:
        bundle_path = os.path.abspath("bundle-ca") if os.path.exists("bundle-ca") else None
        if bundle_path and os.path.isfile(bundle_path):
            try:
                session.mount("https://", PermissiveSSLAdapter(bundle_path, check_hostname=check_hostname, permissive_flags=True))
                session.verify = True
                logger.info("Using permissive SSL adapter with bundle-ca for GitHub: %s (check_hostname=%s)", bundle_path, check_hostname)
            except Exception as e:
                logger.warning("Failed to mount permissive SSL adapter for GitHub, fallback to default verify: %s", e)
                session.verify = bundle_path
        else:
            session.verify = True
            logger.debug("Using default SSL verification for GitHub (bundle-ca not found)")
    
    # Apply proxy configuration (same as init_session)
    if proxy_config:
        proxies = {}
        if proxy_config.get("http"):
            proxies["http"] = proxy_config["http"]
        if proxy_config.get("https"):
            proxies["https"] = proxy_config["https"]
        if proxies:
            session.proxies = proxies
            logger.info("Proxy configured for GitHub: %s", {k: v if "password" not in str(v).lower() else "***" for k, v in proxies.items()})
    
    return session


def make_api_request(
    session: requests.Session,
    url: str,
    auth: Optional[HTTPBasicAuth] = None,
    params: Optional[Dict[str, Any]] = None,
    max_retries: int = MAX_RETRIES,
) -> Optional[Dict[Any, Any]]:
    """
    Make an API request with detailed logging and error handling.
    
    Args:
        session: Requests session with headers/verify configured
        url: Full URL to request
        auth: Optional HTTPBasicAuth for authentication
        params: Optional query parameters dict
        max_retries: Maximum number of retry attempts
        
    Returns:
        Parsed JSON response or None on failure
    """
    params = params or {}
    for attempt in range(max_retries):
        try:
            # Log request details (hide sensitive tokens in params)
            log_params = dict(params)
            if "access_token" in log_params:
                log_params["access_token"] = "***" if log_params["access_token"] else None
            logger.debug(
                "API request [attempt %d/%d]: %s | headers: %s | params: %s",
                attempt + 1,
                max_retries,
                url,
                {k: v if k.lower() not in ("private-token", "authorization") else "***" for k, v in session.headers.items()},
                log_params,
            )
            
            proxies = None
            no_proxy_value = None
            if _proxy_config is not None:
                no_proxy_value = _proxy_config.get("no_proxy")
            if no_proxy_value:
                try:
                    if requests.utils.should_bypass_proxies(url, no_proxy=no_proxy_value):
                        # Disable session proxies for this request. Requests will merge this with
                        # session-level proxies and strip the None values.
                        proxies = {"http": None, "https": None}
                        logger.debug("Bypassing proxy for %s due to NO_PROXY=%s", url, no_proxy_value)
                except Exception as exc:
                    logger.debug("Failed to evaluate NO_PROXY for %s: %s", url, exc)

            resp = session.get(url, auth=auth, params=params, timeout=30, proxies=proxies)
            logger.debug("API response: %s %s | headers: %s", resp.status_code, resp.reason, dict(resp.headers))
            
            resp.raise_for_status()
            text = resp.text
            if text.startswith(")]}'\n"):
                text = text[5:]
            return json.loads(text)
        except requests.exceptions.HTTPError as exc:
            status_code = getattr(exc.response, "status_code", "?")
            response_text = ""
            try:
                if exc.response is not None:
                    response_text = exc.response.text[:500]  # First 500 chars
            except Exception:
                pass
            
            logger.error(
                "HTTP error %s for %s | Response: %s | Headers sent: %s",
                status_code,
                url,
                response_text,
                {k: v if k.lower() not in ("private-token", "authorization") else "***" for k, v in session.headers.items()},
            )
            if exc.response is not None and exc.response.status_code in (401, 404):
                logger.warning("Request failed with %s, stopping retries", status_code)
                return None
        except requests.exceptions.SSLError as exc:
            bundle_ca_exists = os.path.exists("bundle-ca")
            bundle_ca_path = os.path.abspath("bundle-ca") if bundle_ca_exists else None
            logger.error(
                "SSL error for %s: %s | verify=%s | bundle-ca exists: %s | bundle-ca path: %s | current dir: %s",
                url,
                exc,
                session.verify,
                bundle_ca_exists,
                bundle_ca_path,
                os.getcwd(),
            )
            # Log more SSL details if available
            if hasattr(exc, 'args') and exc.args:
                logger.error("SSL error details: %s", exc.args)
        except requests.exceptions.ConnectionError as exc:
            logger.error("Connection error for %s: %s", url, exc)
        except requests.exceptions.Timeout as exc:
            logger.error("Timeout error for %s: %s", url, exc)
        except requests.exceptions.RequestException as exc:
            logger.error("Request exception [attempt %d/%d] for %s: %s", attempt + 1, max_retries, url, exc)
        except json.JSONDecodeError as exc:
            logger.error("JSON parse error for %s: %s | Response text (first 200 chars): %s", url, exc, resp.text[:200] if 'resp' in locals() else "N/A")
            return None
        if attempt < max_retries - 1:
            logger.debug("Retrying after %s seconds...", RETRY_DELAY)
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
    # Gitee API v5 supports token via:
    # 1. Authorization header: "Bearer <token>" or "token <token>"
    # 2. Query parameter: access_token=<token>
    # We'll use query parameter approach (like in gitee.py source) for consistency
    session = init_session(None, proxy_config=_proxy_config, ssl_config=_ssl_config)
    # Note: Token will be passed via params in make_api_request if needed
    # But for now, try without token first (as user indicated params=None works)

    # Support both classic /pulls/ URLs and GitLab-like /merge_requests/ URLs
    pr_match = re.match(
        r"https://(gitee\.com|gitcode\.net|gitcode\.com)/([^/]+)/([^/]+)/(pulls?|merge_requests)/(\d+)",
        url,
    )
    if pr_match:
        _, owner, repo, _, pr_id = pr_match.groups()
        api_url = f"{base_url}/api/v5/repos/{owner}/{repo}/pulls/{pr_id}"
        files_url = f"{api_url}/files"
        # Gitee API: token can be passed via access_token query param or Authorization header
        # Use query param approach (like gitee.py) - add token to params if available
        params = {"access_token": token} if token else None
        pr = make_api_request(session, api_url, params=params)
        if not pr:
            return None
        files = make_api_request(session, files_url, params=params) or []
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
        # Gitee API: token can be passed via access_token query param or Authorization header
        params = {"access_token": token} if token else None
        commit = make_api_request(session, commit_url, params=params)
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
    session = init_session(token, proxy_config=_proxy_config, ssl_config=_ssl_config)
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
    session = init_session(token, proxy_config=_proxy_config, ssl_config=_ssl_config)
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
        project_api_base = f"{base_url}/api/v4/projects/{prefix}{encoded_path}"

        mr_api_urls = [
            f"{project_api_base}/isource/merge_requests/{mr_id}",
            f"{project_api_base}/merge_requests/{mr_id}",
        ]
        changes_api_urls = [
            f"{project_api_base}/isource/merge_requests/{mr_id}/changes",
            f"{project_api_base}/merge_requests/{mr_id}/changes",
        ]

        pr = None
        for api_url in mr_api_urls:
            pr = make_api_request(session, api_url)
            if pr:
                break
        if not pr:
            return None

        if isinstance(pr, dict) and ("added_lines" in pr or "removed_lines" in pr):
            additions = int(pr.get("added_lines") or 0)
            deletions = int(pr.get("removed_lines") or 0)
        else:
            changes = None
            for changes_url in changes_api_urls:
                changes = make_api_request(session, changes_url)
                if changes:
                    break
            changes = changes or {}
            changes_list = changes.get("changes", []) if isinstance(changes, dict) else []
            additions = sum(int(f.get("added_lines", 0)) for f in changes_list)
            deletions = sum(int(f.get("removed_lines", 0)) for f in changes_list)
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
    session = init_session(proxy_config=_proxy_config, ssl_config=_ssl_config)
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
    session = init_github_session(token, proxy_config=_proxy_config, ssl_config=_ssl_config)

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
_cache_lock = threading.Lock()
# Global proxy configuration (set by report)
_proxy_config: Optional[dict] = None
# Global SSL configuration (set by report)
_ssl_config: Optional[dict] = None


def set_cache_manager(cache_manager: Any) -> None:
    """Set the global cache manager for link processing."""
    global _cache_manager
    _cache_manager = cache_manager


def set_proxy_config(proxy_config: Optional[dict]) -> None:
    """Set the global proxy configuration for API requests."""
    global _proxy_config
    _proxy_config = proxy_config


def set_ssl_config(ssl_config: Optional[dict]) -> None:
    """Set the global SSL configuration for API requests."""
    global _ssl_config
    _ssl_config = ssl_config


def process_link(url: str, config: ConfigParser) -> Optional[List]:
    # Check cache first
    if _cache_manager:
        with _cache_lock:
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
        with _cache_lock:
            _cache_manager.set_link_result(url, result)

    return result

