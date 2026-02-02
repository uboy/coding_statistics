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

from stats_core.reports.jira_comprehensive import (
    JiraComprehensiveReport,
    build_jql_query,
    calculate_engineer_metrics,
)


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
    assignee_display: str,
    assignee_username: str | None,
    reporter_display: str,
    reporter_username: str | None,
    description: str = "",
    comment_body: str | None = None,
    comment_id: str | None = None,
    labels: list[str] | None = None,
    resolution_name: str = "Done",
    epic_link: str | None = "EPIC-1",
    parent_key: str | None = None,
):
    comment = SimpleNamespace(
        comments=(
            [
                SimpleNamespace(
                    body=comment_body,
                    author=SimpleNamespace(displayName="Commenter"),
                    created="2025-01-02T10:00:00.000+0000",
                    id=comment_id,
                )
            ]
            if comment_body
            else []
        )
    )
    parent = SimpleNamespace(key=parent_key) if parent_key else None
    fields = SimpleNamespace(
        summary=summary,
        assignee=SimpleNamespace(displayName=assignee_display, name=assignee_username),
        reporter=SimpleNamespace(displayName=reporter_display, name=reporter_username),
        resolutiondate="2025-01-10T10:00:00.000+0000",
        created="2025-01-01T10:00:00.000+0000",
        updated="2025-01-11T10:00:00.000+0000",
        description=description,
        comment=comment,
        labels=labels or [],
        priority=SimpleNamespace(name="P1"),
        status=SimpleNamespace(name=status),
        resolution=SimpleNamespace(name=resolution_name),
        issuetype=SimpleNamespace(name=issue_type),
        timeestimate=0,
        timespent=0,
        timeoriginalestimate=0,
        customfield_10000=epic_link,
        parent=parent,
    )
    return SimpleNamespace(key=key, fields=fields)


@patch("stats_core.reports.jira_comprehensive.JiraSource")
def test_jira_comprehensive_report_run_writes_excel(mock_jira_source_cls, tmp_path: Path):
    issues = [
        _make_issue(
            "ABC-1",
            summary="Bug fix",
            issue_type="Bug",
            status="Released",
            assignee_display="Alice",
            assignee_username=None,
            reporter_display="Bob",
            reporter_username=None,
            description="See\x0b https://example.com",
            comment_body="Result: fixed issue",
            comment_id="101",
            labels=["documentation"],
        ),
        _make_issue(
            "ABC-2",
            summary="QA task",
            issue_type="Task",
            status="In QA",
            assignee_display="Bob",
            assignee_username=None,
            reporter_display="Carol",
            reporter_username="carol",
            comment_body=(
                "TT_tdev_APIs - number of developed and executed tasks = 2\n"
                "TT_tested_APIs - number of executed tests = 3\n"
                "TT_tested_perf - number of executed performance tests = 1\n"
                "TT_tdev_perf - number of developed benchmark tests = 4"
            ),
            labels=["documentation", "arkoala_perf"],
        ),
        _make_issue(
            "ABC-4",
            summary="Excluded QA task",
            issue_type="Task",
            status="Done",
            assignee_display="Bob",
            assignee_username=None,
            reporter_display="Bob",
            reporter_username=None,
            comment_body="TT_tdev_APIs: 200\nTT_tested_APIs: 300\nTT_tested_perf: 100\nTT_tdev_perf: 400",
            labels=["documentation"],
            resolution_name="Won't Do",
        ),
        _make_issue(
            "ABC-5",
            summary="Excluded invalid resolution",
            issue_type="Bug",
            status="Done",
            assignee_display="Alice",
            assignee_username=None,
            reporter_display="Bob",
            reporter_username=None,
            labels=["documentation"],
            resolution_name="Invalid",
        ),
        _make_issue(
            "ABC-3",
            summary="Epic",
            issue_type="Epic",
            status="Released",
            assignee_display="Carol",
            assignee_username="carol",
            reporter_display="Carol",
            reporter_username="carol",
        ),
        _make_issue(
            "ABC-6",
            summary="Parent Task",
            issue_type="Task",
            status="Released",
            assignee_display="Alice",
            assignee_username="alice",
            reporter_display="Bob",
            reporter_username=None,
            epic_link="EPIC-2",
        ),
        _make_issue(
            "ABC-7",
            summary="Subtask Task",
            issue_type="Sub-task",
            status="Released",
            assignee_display="Alice",
            assignee_username="alice",
            reporter_display="Bob",
            reporter_username=None,
            epic_link=None,
            parent_key="ABC-6",
        ),
    ]

    fake_jira = Mock()
    epic_issues = [
        _make_issue(
            "EPIC-1",
            summary="Epic One",
            issue_type="Epic",
            status="Released",
            assignee_display="Carol",
            assignee_username="carol",
            reporter_display="Carol",
            reporter_username="carol",
        ),
        _make_issue(
            "EPIC-2",
            summary="Epic Two",
            issue_type="Epic",
            status="Released",
            assignee_display="Carol",
            assignee_username="carol",
            reporter_display="Carol",
            reporter_username="carol",
        ),
    ]

    def _search_issues_side_effect(jql_query, *args, **kwargs):
        if "issuekey in" in jql_query:
            return epic_issues
        return issues

    fake_jira.search_issues.side_effect = _search_issues_side_effect

    fake_source = Mock()
    fake_source.jira = fake_jira
    fake_source.get_all_worklogs = Mock(return_value=[])
    mock_jira_source_cls.return_value = fake_source

    members_file = tmp_path / "members.xlsx"
    pd.DataFrame(
        [
            {"name": "Alice", "username": "alice", "role": "engineer"},
            {"name": "Bob", "username": "bob", "role": "test engineer"},
            {"name": "Carol", "username": "carol", "role": "project manager"},
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
    assert any(call.args[0] == expected_jql for call in fake_jira.search_issues.call_args_list)

    out_path = tmp_path / "out.xlsx"
    assert out_path.exists()

    wb = load_workbook(out_path)
    assert "Issues" in wb.sheetnames
    assert "Links" in wb.sheetnames
    assert "Results" in wb.sheetnames
    assert "Engineer_Performance" in wb.sheetnames
    assert "QA_Performance" in wb.sheetnames
    assert "PM_Performance" in wb.sheetnames

    issues_sheet = wb["Issues"]
    headers = [cell.value for cell in issues_sheet[1]]
    desc_col = headers.index("Description") + 1
    comments_col = headers.index("Comments") + 1
    parent_col = headers.index("Parent") + 1
    epic_link_col = headers.index("Epic_Link") + 1
    epic_name_col = headers.index("Epic_Name") + 1
    assert "\x0b" not in str(issues_sheet.cell(row=2, column=desc_col).value)
    assert "\x00" not in str(issues_sheet.cell(row=2, column=comments_col).value)
    issue_key_col = headers.index("Issue_Key") + 1
    subtask_row = None
    for row_idx in range(2, issues_sheet.max_row + 1):
        if issues_sheet.cell(row=row_idx, column=issue_key_col).value == "ABC-7":
            subtask_row = row_idx
            break
    assert subtask_row is not None
    assert issues_sheet.cell(row=subtask_row, column=parent_col).value == "ABC-6"
    assert issues_sheet.cell(row=subtask_row, column=epic_link_col).value == "EPIC-2"
    assert issues_sheet.cell(row=subtask_row, column=epic_name_col).value == "Epic Two"

    links_sheet = wb["Links"]
    # header + at least 2 links (description + comment)
    assert links_sheet.max_row >= 2

    results_sheet = wb["Results"]
    results_headers = [cell.value for cell in results_sheet[1]]
    result_links_col = results_headers.index("Result_Links") + 1
    result_link_value = results_sheet.cell(row=2, column=result_links_col).value
    assert "focusedCommentId=101" in str(result_link_value)

    def _sheet_row(sheet_name: str) -> dict[str, object]:
        sheet = wb[sheet_name]
        headers = [cell.value for cell in sheet[1]]
        values = [sheet.cell(row=2, column=idx + 1).value for idx in range(len(headers))]
        return dict(zip(headers, values))

    engineer_row = _sheet_row("Engineer_Performance")
    assert engineer_row["Bugs"] == 1
    assert engineer_row["Documentation_Tasks"] == 1
    assert engineer_row["Total_Resolved_Issues"] == 3

    qa_row = _sheet_row("QA_Performance")
    assert qa_row["Test_Scenarios_Executed"] == 5
    assert qa_row["Issues_Raised"] == 1
    assert qa_row["Performance_Benchmarks"] == 5
    assert qa_row["Documentation_Tasks"] == 1
    assert "Outstanding_Contribution" in qa_row
    assert qa_row["Outstanding_Contribution"] == 0
    assert qa_row["TT_tdev_APIs"] == 2
    assert qa_row["TT_tested_APIs"] == 3
    assert qa_row["TT_tested_perf"] == 1
    assert qa_row["TT_tdev_perf"] == 4
    assert qa_row["Total_Resolved_Issues"] == 1


def test_calculate_engineer_metrics_uses_members_jira_column():
    issues_df = pd.DataFrame(
        [
            {
                "Issue_Key": "ABC-1",
                "Summary": "Bug fix",
                "Type": "Bug",
                "Status": "Released",
                "Resolution": "Done",
                "Assignee": "Does Not Matter",
                "Assignee_Username": "eWX1025804",
                "Reporter": "Someone",
                "Reporter_Username": "someone",
                "Created": "2025-01-01",
                "Resolved": "2025-01-10",
                "Labels": "",
            }
        ]
    )
    members_df = pd.DataFrame(
        [
            {
                "name": "Evstigneev Roman",
                "username": "wx1025804",
                "Jira": "eWX1025804",
                "role": "engineer",
            }
        ]
    )
    code_volume_df = pd.DataFrame(columns=["username", "code_volume"])

    engineer_metrics = calculate_engineer_metrics(issues_df, members_df, code_volume_df)
    assert engineer_metrics.shape[0] == 1
    row = engineer_metrics.iloc[0].to_dict()
    assert row["Bugs"] == 1
    assert row["Total_Resolved_Issues"] == 1
