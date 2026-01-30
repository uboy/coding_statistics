"""
Tests for Jira epic resolved hierarchy and resolved tasks rendering.
"""

from unittest.mock import Mock

import pandas as pd
from docx import Document

from stats_core.reports.jira_epic_report import (
    generate_epic_resolved_hierarchy,
    add_resolved_tasks_section,
)
from stats_core.reports.jira_utils import build_resolved_issues_snapshot
from stats_core.sources.jira import JiraSource


def _make_issue(
    key: str,
    summary: str,
    resolution_date: str | None,
    epic_link: str | None = None,
    parent: Mock | None = None,
    issue_type: str = "Task",
) -> Mock:
    issue = Mock()
    issue.key = key
    issue.fields.summary = summary
    issue.fields.resolutiondate = resolution_date
    issue.fields.customfield_10000 = epic_link
    issue.fields.parent = parent
    issue.fields.issuetype = Mock(name=issue_type)
    return issue


def test_build_resolved_snapshot_includes_subtasks_and_parent_meta():
    mock_jira_source = Mock(spec=JiraSource)
    parent_issue = _make_issue(
        "PARENT-1",
        "Parent Task",
        "2025-01-15T10:00:00.000+0000",
        epic_link="EPIC-1",
        parent=None,
        issue_type="Task",
    )
    subtask_issue = _make_issue(
        "SUB-1",
        "Subtask Task",
        "2025-01-16T10:00:00.000+0000",
        epic_link=None,
        parent=parent_issue,
        issue_type="Sub-task",
    )

    mock_jira_source.fetch_issues = Mock(return_value=[parent_issue, subtask_issue])
    mock_jira_source.fetch_epic_names = Mock(return_value={"EPIC-1": "Epic One"})

    resolved_df = build_resolved_issues_snapshot(
        mock_jira_source,
        "TEST",
        "2025-01-13",
        "2025-01-19",
    )

    assert set(resolved_df["Issue_key"]) == {"PARENT-1", "SUB-1"}
    subtask_row = resolved_df[resolved_df["Issue_key"] == "SUB-1"].iloc[0]
    assert subtask_row["Parent_Key"] == "PARENT-1"
    assert subtask_row["Epic_Link"] == "EPIC-1"
    assert subtask_row["Epic_Name"] == "Epic One"


def test_generate_epic_resolved_hierarchy_groups_subtasks():
    resolved_df = pd.DataFrame(
        [
            {
                "Issue_key": "PARENT-1",
                "Summary": "Parent Task",
                "Resolution_Date": "2025-01-15",
                "Resolution_Week": "2025-W03",
                "Epic_Link": "EPIC-1",
                "Epic_Name": "Epic One",
                "Parent_Key": "",
                "Parent_Summary": "",
                "Type": "Task",
            },
            {
                "Issue_key": "SUB-1",
                "Summary": "Subtask One",
                "Resolution_Date": "2025-01-16",
                "Resolution_Week": "2025-W03",
                "Epic_Link": "",
                "Epic_Name": "",
                "Parent_Key": "PARENT-1",
                "Parent_Summary": "Parent Task",
                "Type": "Sub-task",
            },
            {
                "Issue_key": "SUB-2",
                "Summary": "Subtask Two",
                "Resolution_Date": "2025-01-17",
                "Resolution_Week": "2025-W03",
                "Epic_Link": "",
                "Epic_Name": "",
                "Parent_Key": "PARENT-1",
                "Parent_Summary": "Parent Task",
                "Type": "Sub-task",
            },
        ]
    )

    summary = generate_epic_resolved_hierarchy(resolved_df)
    assert len(summary) == 1
    epic = summary[0]
    assert epic["Epic"] == "Epic One"
    assert len(epic["Parents"]) == 1
    parent = epic["Parents"][0]
    assert parent["Parent_Key"] == "PARENT-1"
    assert len(parent["Subtasks"]) == 2


def test_generate_epic_resolved_hierarchy_subtask_only_adds_parent_bucket():
    resolved_df = pd.DataFrame(
        [
            {
                "Issue_key": "SUB-1",
                "Summary": "Subtask Only",
                "Resolution_Date": "2025-01-16",
                "Resolution_Week": "2025-W03",
                "Epic_Link": "EPIC-1",
                "Epic_Name": "Epic One",
                "Parent_Key": "PARENT-2",
                "Parent_Summary": "Parent Missing",
                "Type": "Sub-task",
            },
        ]
    )

    summary = generate_epic_resolved_hierarchy(resolved_df)
    assert len(summary) == 1
    parent = summary[0]["Parents"][0]
    assert parent["Parent_Key"] == "PARENT-2"
    assert len(parent["Subtasks"]) == 1


def test_add_resolved_tasks_section_groups_weeks_and_subtasks():
    resolved_df = pd.DataFrame(
        [
            {
                "Issue_key": "PARENT-1",
                "Summary": "Parent Task",
                "Resolution_Date": "2025-01-15",
                "Resolution_Week": "2025-W03",
                "Epic_Link": "EPIC-1",
                "Epic_Name": "Epic One",
                "Parent_Key": "",
                "Parent_Summary": "",
                "Type": "Task",
            },
            {
                "Issue_key": "SUB-2",
                "Summary": "Subtask Week 4",
                "Resolution_Date": "2025-01-22",
                "Resolution_Week": "2025-W04",
                "Epic_Link": "EPIC-1",
                "Epic_Name": "Epic One",
                "Parent_Key": "PARENT-1",
                "Parent_Summary": "Parent Task",
                "Type": "Sub-task",
            },
            {
                "Issue_key": "SUB-3",
                "Summary": "Subtask Week 3",
                "Resolution_Date": "2025-01-16",
                "Resolution_Week": "2025-W03",
                "Epic_Link": "EPIC-1",
                "Epic_Name": "Epic One",
                "Parent_Key": "PARENT-1",
                "Parent_Summary": "Parent Task",
                "Type": "Sub-task",
            },
        ]
    )

    document = Document()
    add_resolved_tasks_section(document, resolved_df)

    texts = [paragraph.text for paragraph in document.paragraphs]
    assert any("Week 2025-W03" in text for text in texts)
    assert any("Week 2025-W04" in text for text in texts)
    assert texts.count("PARENT-1: Parent Task") >= 2
    assert "SUB-2: Subtask Week 4" in texts
    assert "SUB-3: Subtask Week 3" in texts
