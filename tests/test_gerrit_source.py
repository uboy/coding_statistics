"""
Tests for Gerrit source adapter.
"""

from configparser import ConfigParser
from types import SimpleNamespace

import requests

from stats_core.sources.gerrit import GerritSource


def test_gerrit_source_fetch_changes(monkeypatch):
    """Test Gerrit source fetching changes (PRs)."""
    cfg = ConfigParser()
    cfg.read_dict(
        {
            "gerrit": {
                "gerrit-url": "https://gerrit.example.com",
                "username": "testuser",
                "password": "testpass",
                "project": "test-project",
            }
        }
    )
    source = GerritSource(requests.Session(), cfg["gerrit"])

    change_stub = {
        "_number": 12345,
        "project": "test-project",
        "subject": "Test change",
        "owner": {"name": "Author"},
        "reviewers": {
            "REVIEWER": [
                {"name": "reviewer1"},
                {"name": "reviewer2"},
            ]
        },
        "branch": "master",
        "status": "MERGED",
        "created": "2025-01-10 12:00:00.000000000",
        "submitted": "2025-01-11 12:00:00.000000000",
        "insertions": 10,
        "deletions": 5,
    }

    def mock_iter_changes(project, start_dt, end_dt):
        return iter([change_stub])

    monkeypatch.setattr(source, "_iter_changes", mock_iter_changes)

    params = SimpleNamespace(start_dt=None, end_dt=None, extra={})
    changes = list(source.fetch_pull_requests(params=params))

    assert len(changes) == 1
    assert changes[0].title == "Test change"
    assert changes[0].additions == 10
    assert changes[0].deletions == 5
    assert changes[0].reviewers == ("reviewer1", "reviewer2")
    assert changes[0].repository == "test-project"
    assert "12345" in changes[0].url


def test_gerrit_source_no_commits(monkeypatch):
    """Test Gerrit source returns empty commits (not supported)."""
    cfg = ConfigParser()
    cfg.read_dict(
        {
            "gerrit": {
                "gerrit-url": "https://gerrit.example.com",
                "username": "testuser",
                "password": "testpass",
            }
        }
    )
    source = GerritSource(requests.Session(), cfg["gerrit"])

    params = SimpleNamespace(start_dt=None, end_dt=None, extra={})
    commits = list(source.fetch_commits(params=params))

    # Gerrit doesn't support commits fetching
    assert len(commits) == 0


def test_gerrit_source_project_filtering(monkeypatch):
    """Test Gerrit source filters by project."""
    cfg = ConfigParser()
    cfg.read_dict(
        {
            "gerrit": {
                "gerrit-url": "https://gerrit.example.com",
                "username": "testuser",
                "password": "testpass",
                "project": "project-a,project-b",
            }
        }
    )
    source = GerritSource(requests.Session(), cfg["gerrit"])

    assert len(source.projects) == 2
    assert "project-a" in source.projects
    assert "project-b" in source.projects

