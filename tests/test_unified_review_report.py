from configparser import ConfigParser
from pathlib import Path

import pytest

from stats_core.reports import registry
from stats_core.reports.unified_review import UnifiedReviewReport


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

