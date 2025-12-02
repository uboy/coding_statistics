"""
Tests for GitHub source adapter.
"""

from configparser import ConfigParser
from types import SimpleNamespace

import requests

from stats_core.sources.github import GitHubSource


def test_github_source_fetch_records(monkeypatch):
    """Test GitHub source fetching PRs and commits."""
    cfg = ConfigParser()
    cfg.read_dict(
        {
            "github": {
                "token": "ghp_test_token",
                "repository": "owner/repo",
                "per_page": "20",
            }
        }
    )
    source = GitHubSource(requests.Session(), cfg["github"])

    pr_stub = {
        "number": 1,
        "title": "Test PR",
        "html_url": "https://github.com/owner/repo/pull/1",
        "user": {"login": "author"},
        "requested_reviewers": [{"login": "reviewer1"}, {"login": "reviewer2"}],
        "base": {"ref": "master"},
        "state": "closed",
        "merged": True,
        "created_at": "2025-01-10T12:00:00Z",
        "merged_at": "2025-01-11T12:00:00Z",
        "additions": 10,
        "deletions": 5,
    }
    commit_stub = {
        "sha": "abc123",
        "html_url": "https://github.com/owner/repo/commit/abc123",
        "commit": {
            "message": "Fix bug",
            "author": {"name": "Dev", "date": "2025-01-09T09:00:00Z"},
        },
        "stats": {"additions": 3, "deletions": 1},
    }

    monkeypatch.setattr(source, "_iter_pull_requests", lambda *args, **kwargs: iter([pr_stub]))
    monkeypatch.setattr(source, "_iter_commits", lambda *args, **kwargs: iter([commit_stub]))

    params = SimpleNamespace(start_dt=None, end_dt=None, extra={})
    prs = list(source.fetch_pull_requests(params=params))
    commits = list(source.fetch_commits(params=params))

    assert len(prs) == 1
    assert prs[0].title == "Test PR"
    assert prs[0].additions == 10
    assert prs[0].deletions == 5
    assert prs[0].reviewers == ("reviewer1", "reviewer2")

    assert len(commits) == 1
    assert commits[0].sha == "abc123"
    assert commits[0].additions == 3


def test_github_source_fetch_from_url(monkeypatch):
    """Test GitHub source fetching records from URL."""
    cfg = ConfigParser()
    cfg.read_dict(
        {
            "github": {
                "token": "ghp_test_token",
                "repository": "owner/repo",
            }
        }
    )
    source = GitHubSource(requests.Session(), cfg["github"])

    pr_stub = {
        "number": 42,
        "title": "PR from URL",
        "html_url": "https://github.com/owner/repo/pull/42",
        "user": {"login": "author"},
        "requested_reviewers": [],
        "base": {"ref": "master"},
        "state": "open",
        "merged": False,
        "created_at": "2025-01-10T12:00:00Z",
        "merged_at": None,
        "additions": 5,
        "deletions": 2,
    }

    def mock_build_pr_record(repo, number, url_override=None):
        return source._build_pr_record(repo, number, url_override=url_override)

    monkeypatch.setattr(source, "_request", lambda path, **kwargs: pr_stub)

    url = "https://github.com/owner/repo/pull/42"
    records = list(source.fetch_records_from_url(url))

    assert len(records) == 1
    assert records[0].title == "PR from URL"
    assert records[0].url == url

