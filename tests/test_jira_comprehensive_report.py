"""
Tests for Jira comprehensive report.
"""

from __future__ import annotations

from configparser import ConfigParser
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pandas as pd
from openpyxl import load_workbook

from stats_core.reports.jira_comprehensive import JiraComprehensiveReport, build_jql_query


def test_build_jql_query_project_dates():
    params = {"project": "ABC", "start_date": "2025-01-01", "end_date": "2025-01-31"}
    assert (
        build_jql_query(params)
        == "project = ABC AND resolved >= '2025-01-01' AND resolved <= '2025-01-31' ORDER BY created DESC"
    )


def _make_issue(
    key: str,
    *,
    summary: str,
    issue_type: str,
    status: str,
    assignee_username: str,
    reporter_username: str,
    description: str = "",
    comment_body: str | None = None,
    labels: list[str] | None = None,
):
    comment = SimpleNamespace(
        comments=(
            [
                SimpleNamespace(
                    body=comment_body,
                    author=SimpleNamespace(displayName="Commenter"),
                    created="2025-01-02T10:00:00.000+0000",
                )
            ]
            if comment_body
            else []
        )
    )
    fields = SimpleNamespace(
        summary=summary,
        assignee=SimpleNamespace(displayName=assignee_username, name=assignee_username),
        reporter=SimpleNamespace(displayName=reporter_username, name=reporter_username),
        resolutiondate="2025-01-10T10:00:00.000+0000",
        created="2025-01-01T10:00:00.000+0000",
        updated="2025-01-11T10:00:00.000+0000",
        description=description,
        comment=comment,
        labels=labels or [],
        priority=SimpleNamespace(name="P1"),
        status=SimpleNamespace(name=status),
        resolution=SimpleNamespace(name="Done"),
        issuetype=SimpleNamespace(name=issue_type),
        timeestimate=0,
        timespent=0,
        timeoriginalestimate=0,
        customfield_10000="EPIC-1",
    )
    return SimpleNamespace(key=key, fields=fields)


@patch("stats_core.reports.jira_comprehensive.JiraSource")
def test_jira_comprehensive_report_run_writes_excel(mock_jira_source_cls, tmp_path: Path):
    issues = [
        _make_issue(
            "ABC-1",
            summary="Bug fix",
            issue_type="Bug",
            status="Done",
            assignee_username="alice",
            reporter_username="bob",
            description="See\x0b https://example.com",
            comment_body="ref\x00 http://example.org",
            labels=["documentation"],
        ),
        _make_issue(
            "ABC-2",
            summary="QA task",
            issue_type="Task",
            status="Resolved",
            assignee_username="bob",
            reporter_username="carol",
        ),
        _make_issue(
            "ABC-3",
            summary="Epic",
            issue_type="Epic",
            status="Closed",
            assignee_username="carol",
            reporter_username="carol",
        ),
    ]

    fake_jira = Mock()
    fake_jira.search_issues.return_value = issues

    fake_source = Mock()
    fake_source.jira = fake_jira
    mock_jira_source_cls.return_value = fake_source

    members_file = tmp_path / "members.xlsx"
    pd.DataFrame(
        [
            {"name": "Alice", "username": "alice", "role": "Engineer"},
            {"name": "Bob", "username": "bob", "role": "QA Engineer"},
            {"name": "Carol", "username": "carol", "role": "Project Manager"},
        ]
    ).to_excel(members_file, index=False)

    code_volume_file = tmp_path / "code_volume.xlsx"
    pd.DataFrame([{"username": "alice", "code_volume": 123}]).to_excel(code_volume_file, index=False)

    config = ConfigParser()
    config.read_dict(
        {
            "jira": {"jira-url": "https://jira.example.com", "username": "u", "password": "p"},
            "reporting": {"output_dir": str(tmp_path)},
        }
    )

    report = JiraComprehensiveReport()
    report.run(
        dataset={},
        config=config,
        output_formats=["excel"],
        extra_params={
            "project": "ABC",
            "start": "2025-01-01",
            "end": "2025-01-31",
            "member_list_file": str(members_file),
            "code_volume_file": str(code_volume_file),
            "output": "out.xlsx",
        },
    )

    expected_jql = (
        "project = ABC AND resolved >= '2025-01-01' AND resolved <= '2025-01-31' ORDER BY created DESC"
    )
    assert fake_jira.search_issues.call_args[0][0] == expected_jql

    out_path = tmp_path / "out.xlsx"
    assert out_path.exists()

    wb = load_workbook(out_path)
    assert "Issues" in wb.sheetnames
    assert "Links" in wb.sheetnames
    assert "Engineer_Performance" in wb.sheetnames
    assert "QA_Performance" in wb.sheetnames
    assert "PM_Performance" in wb.sheetnames

    issues_sheet = wb["Issues"]
    headers = [cell.value for cell in issues_sheet[1]]
    desc_col = headers.index("Description") + 1
    comments_col = headers.index("Comments") + 1
    assert "\x0b" not in str(issues_sheet.cell(row=2, column=desc_col).value)
    assert "\x00" not in str(issues_sheet.cell(row=2, column=comments_col).value)

    links_sheet = wb["Links"]
    # header + at least 2 links (description + comment)
    assert links_sheet.max_row >= 3
