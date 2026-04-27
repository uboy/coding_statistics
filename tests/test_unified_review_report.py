from configparser import ConfigParser
from pathlib import Path

import pytest

from stats_core.reports import registry
from stats_core.reports.unified_review import UnifiedReviewReport


class RecordingProgress:
    def __init__(self):
        self.totals = []
        self.advances = []

    def set_total(self, total_steps):
        self.totals.append(total_steps)

    def advance(self, n=1):
        self.advances.append(n)

    def create_children(self, **kwargs):
        return []


def test_unified_review_report_word_export(tmp_path, monkeypatch):
    links_file = tmp_path / "links.txt"
    links_file.write_text("dummy\n", encoding="utf-8")

    config = ConfigParser()
    config.read_dict(
        {
            "reporting": {
                "links_file": str(links_file),
                "output_dir": str(tmp_path),
            },
            "gitee": {"gitee-url": "https://gitee.com", "token": "dummy", "repository": "owner/repo"},
        }
    )

    monkeypatch.setattr("stats_core.reports.unified_review.parse_links", lambda _: ["dummy"])
    fake_row = [
        "Name",
        "Login",
        "PR",
        "http://example",
        "merged",
        "2025-01-01",
        "2025-01-02",
        "master",
        "owner/repo",
        10,
        1,
        "reviewer",
    ]
    monkeypatch.setattr("stats_core.reports.unified_review.process_link", lambda *args, **kwargs: fake_row)

    report = UnifiedReviewReport()
    output_formats = ["word"]
    report.run({}, config, output_formats, extra_params={"output_dir": str(tmp_path), "output": "test"})

    assert (tmp_path / "test.docx").exists()


def test_unified_review_parallel_progress_advances_per_link(monkeypatch):
    links = ["link-1", "link-2", "link-3"]
    fake_row = [
        "Name",
        "Login",
        "PR",
        "http://example",
        "merged",
        "2025-01-01",
        "2025-01-02",
        "master",
        "owner/repo",
        10,
        1,
        "reviewer",
    ]
    progress = RecordingProgress()
    config = ConfigParser()

    monkeypatch.setattr("stats_core.reports.unified_review.parse_links", lambda _: links)
    monkeypatch.setattr("stats_core.reports.unified_review.process_link", lambda *args, **kwargs: fake_row)

    rows = UnifiedReviewReport()._rows_from_links(
        links_file="unused.txt",
        config=config,
        start_str=None,
        end_str=None,
        progress=progress,
        extra_params={"parallel_workers": "2"},
    )

    assert rows == [fake_row, fake_row, fake_row]
    assert progress.totals == [5]
    assert progress.advances == [1, 1, 1]

