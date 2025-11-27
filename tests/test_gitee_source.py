from configparser import ConfigParser
from types import SimpleNamespace

import requests

from stats_core.sources.gitee import GiteeLikeSource


def test_gitee_source_fetch_records(monkeypatch):
    cfg = ConfigParser()
    cfg.read_dict(
        {
            "gitee": {
                "gitee-url": "https://gitee.com",
                "repository": "owner/repo",
                "per_page": "20",
            }
        }
    )
    source = GiteeLikeSource(requests.Session(), cfg["gitee"], "gitee")

    pr_stub = {"number": 1}
    detail_stub = {
        "title": "Test PR",
        "html_url": "https://gitee.com/owner/repo/pulls/1",
        "user": {"name": "Author", "login": "author"},
        "assignees": [{"login": "reviewer", "accept": True}],
        "base": {"ref": "master"},
        "state": "merged",
        "created_at": "2025-01-10T12:00:00Z",
        "merged_at": "2025-01-11T12:00:00Z",
    }
    commit_stub = {"sha": "abc123", "html_url": "https://gitee.com/owner/repo/commit/abc123"}
    commit_detail_stub = {
        "commit": {"message": "Fix bug", "author": {"name": "Dev", "date": "2025-01-09T09:00:00Z"}},
        "stats": {"additions": 3, "deletions": 1},
    }

    monkeypatch.setattr(source, "_iter_pull_requests", lambda *args, **kwargs: iter([pr_stub]))
    monkeypatch.setattr(source, "_pull_details", lambda *args, **kwargs: (detail_stub, 5, 2))
    monkeypatch.setattr(source, "_iter_commits", lambda *args, **kwargs: iter([commit_stub]))
    monkeypatch.setattr(source, "_commit_detail", lambda *args, **kwargs: commit_detail_stub)

    params = SimpleNamespace(start_dt=None, end_dt=None, extra={})
    prs = list(source.fetch_pull_requests(params=params))
    commits = list(source.fetch_commits(params=params))

    assert len(prs) == 1
    assert prs[0].title == "Test PR"
    assert prs[0].additions == 5
    assert prs[0].reviewers == ("reviewer",)

    assert len(commits) == 1
    assert commits[0].sha == "abc123"
    assert commits[0].additions == 3

