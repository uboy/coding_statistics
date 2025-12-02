"""
Tests for GitLab source adapter.
"""

from configparser import ConfigParser
from types import SimpleNamespace

import requests

from stats_core.sources.gitlab import GitLabSource


def test_gitlab_source_fetch_records(monkeypatch):
    """Test GitLab source fetching PRs and commits."""
    cfg = ConfigParser()
    cfg.read_dict(
        {
            "gitlab": {
                "gitlab-url": "https://gitlab.example.com",
                "repository": "group/project",
                "per_page": "20",
            }
        }
    )
    source = GitLabSource(requests.Session(), cfg["gitlab"])

    mr_stub = {
        "iid": 1,
        "title": "Test MR",
        "web_url": "https://gitlab.example.com/group/project/merge_requests/1",
        "author": {"name": "Author"},
        "reviewed_by": [{"name": "reviewer1"}, {"name": "reviewer2"}],
        "target_branch": "master",
        "state": "merged",
        "created_at": "2025-01-10T12:00:00Z",
        "merged_at": "2025-01-11T12:00:00Z",
    }
    changes_stub = {
        "changes": [
            {"additions": 5, "deletions": 2},
            {"additions": 3, "deletions": 1},
        ]
    }
    commit_stub = {
        "id": "abc123",
        "web_url": "https://gitlab.example.com/group/project/commit/abc123",
        "author_name": "Dev",
        "created_at": "2025-01-09T09:00:00Z",
    }
    commit_detail_stub = {
        "stats": {"additions": 3, "deletions": 1},
        "title": "Fix bug",
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
    assert prs[0].reviewers == ("reviewer1", "reviewer2")

    assert len(commits) == 1
    assert commits[0].sha == "abc123"
    assert commits[0].additions == 3


def test_gitlab_source_branch_filtering(monkeypatch):
    """Test GitLab source filters by branch."""
    cfg = ConfigParser()
    cfg.read_dict(
        {
            "gitlab": {
                "gitlab-url": "https://gitlab.example.com",
                "repository": "group/project",
                "branch": "master",
            }
        }
    )
    source = GitLabSource(requests.Session(), cfg["gitlab"])

    mr_master = {"iid": 1, "target_branch": "master", "title": "MR on master"}
    mr_dev = {"iid": 2, "target_branch": "dev", "title": "MR on dev"}

    monkeypatch.setattr(source, "_iter_merge_requests", lambda *args, **kwargs: iter([mr_master, mr_dev]))
    monkeypatch.setattr(source, "_request", lambda path, **kwargs: {"changes": []})

    params = SimpleNamespace(start_dt=None, end_dt=None, extra={})
    prs = list(source.fetch_pull_requests(params=params))

    # Should only include MR on master branch
    assert len(prs) == 1
    assert prs[0].title == "MR on master"

