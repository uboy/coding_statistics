"""
Tests for CodeHub source adapter.
"""

from configparser import ConfigParser
from types import SimpleNamespace

import requests

from stats_core.sources.codehub import CodeHubSource


def test_codehub_source_fetch_records(monkeypatch):
    """Test CodeHub source fetching MRs and commits."""
    cfg = ConfigParser()
    cfg.read_dict(
        {
            "codehub": {
                "codehub-url": "https://codehub.example.com",
                "project": "group/project",
                "per_page": "20",
            }
        }
    )
    source = CodeHubSource(requests.Session(), cfg["codehub"], "codehub")

    mr_stub = {
        "iid": 1,
        "title": "Test MR",
        "web_url": "https://codehub.example.com/group/project/merge_requests/1",
        "author": {"name": "Author"},
        "merge_request_reviewer_list": [{"name": "reviewer1"}],
        "target_branch": "master",
        "state": "merged",
        "created_at": "2025-01-10T12:00:00Z",
        "merged_at": "2025-01-11T12:00:00Z",
    }
    changes_stub = {
        "changes": [
            {"added_lines": 5, "removed_lines": 2},
            {"added_lines": 3, "removed_lines": 1},
        ]
    }
    commit_stub = {
        "id": "abc123",
        "web_url": "https://codehub.example.com/group/project/commit/abc123",
    }
    commit_detail_stub = {
        "stats": {"added_lines": 3, "removed_lines": 1},
        "title": "Fix bug",
        "author_name": "Dev",
        "created_at": "2025-01-09T09:00:00Z",
    }

    monkeypatch.setattr(source, "_iter_merge_requests", lambda *args, **kwargs: iter([mr_stub]))
    monkeypatch.setattr(source, "_request", lambda path, **kwargs: changes_stub if "changes" in path else commit_detail_stub)
    monkeypatch.setattr(source, "_iter_commits", lambda *args, **kwargs: iter([commit_stub]))

    params = SimpleNamespace(start_dt=None, end_dt=None, extra={})
    prs = list(source.fetch_pull_requests(params=params))
    commits = list(source.fetch_commits(params=params))

    assert len(prs) == 1
    assert prs[0].title == "Test MR"
    assert prs[0].additions == 8  # 5 + 3
    assert prs[0].deletions == 3  # 2 + 1
    assert prs[0].reviewers == ("reviewer1",)

    assert len(commits) == 1
    assert commits[0].sha == "abc123"
    assert commits[0].additions == 3


def test_codehub_source_platform_variants(monkeypatch):
    """Test CodeHub source works with different platform variants."""
    cfg = ConfigParser()
    cfg.read_dict(
        {
            "opencodehub": {
                "opencodehub-url": "https://open.codehub.example.com",
                "project": "OpenSourceCenter_CR/group/project",
            }
        }
    )
    source = CodeHubSource(requests.Session(), cfg["opencodehub"], "opencodehub")

    assert source.platform == "opencodehub"
    assert source.base_url == "https://open.codehub.example.com"

