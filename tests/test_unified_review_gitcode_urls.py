from configparser import ConfigParser

import pytest

from stats_core.reports.unified_review_utils import process_gitee_or_gitcode


class DummySession:
    def __init__(self, response):
        self._response = response
        self.headers = {}
        self.verify = True

    def get(self, url, auth=None, timeout=30):
        class Resp:
            def __init__(self, data):
                self._data = data
                self.status_code = 200

            def raise_for_status(self):
                return None

            @property
            def text(self):
                return self._data

        return Resp(self._response)


@pytest.mark.parametrize(
    "url_path",
    [
        "pulls/123",
        "merge_requests/123",
    ],
)
def test_gitcode_pr_url_variants(monkeypatch, url_path):
    """GitCode URLs with both /pulls/ and /merge_requests/ should be supported."""
    cfg = ConfigParser()
    cfg.read_dict(
        {
            "gitcode": {
                "gitcode-url": "https://gitcode.com",
                "token": "dummy",
            }
        }
    )

    pr_payload = """
    {
        "user": {"name": "Dev", "login": "dev"},
        "title": "Test PR",
        "state": "merged",
        "created_at": "2025-01-01T00:00:00Z",
        "merged_at": "2025-01-02T00:00:00Z",
        "base": {"ref": "master"},
        "assignees": [{"login": "reviewer1", "accept": true}],
        "id": 123
    }
    """
    files_payload = """
    [
        {"additions": 10, "deletions": 2},
        {"additions": 5, "deletions": 1}
    ]
    """

    calls = {"count": 0}

    def fake_make_api_request(session, url, auth=None, max_retries=3):
        calls["count"] += 1
        if url.endswith("/files"):
            return [
                {"additions": 10, "deletions": 2},
                {"additions": 5, "deletions": 1},
            ]
        return {
            "user": {"name": "Dev", "login": "dev"},
            "title": "Test PR",
            "state": "merged",
            "created_at": "2025-01-01T00:00:00Z",
            "merged_at": "2025-01-02T00:00:00Z",
            "base": {"ref": "master"},
            "assignees": [{"login": "reviewer1", "accept": True}],
        }

    monkeypatch.setattr("stats_core.reports.unified_review_utils.make_api_request", fake_make_api_request)

    url = f"https://gitcode.com/owner/repo/{url_path}"
    row = process_gitee_or_gitcode(url, cfg, "gitcode")
    assert row is not None
    assert row[0] == "Dev"
    assert row[1] == "dev"
    assert row[2] == "Test PR"
    assert row[3] == url
    assert row[4] == "merged"
    assert row[8] == "owner/repo"
    # additions + deletions from two files
    assert row[9] == 15
    assert row[10] == 3


