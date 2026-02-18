from __future__ import annotations

from configparser import ConfigParser
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from openpyxl import Workbook

from stats_core.reports.jira_weekly_email import (
    JiraWeeklyEmailReport,
    parse_vacations_excel,
    resolve_week_window,
)


def _make_issue(
    key: str,
    *,
    summary: str,
    issue_type: str,
    status: str,
    resolution: str,
    labels: list[str],
    priority: str,
    epic_link: str = "EPIC-1",
    parent_key: str | None = None,
    comment_created: str = "2026-03-03T10:00:00.000+0000",
    comment_body: str = "Weekly update",
):
    parent = SimpleNamespace(key=parent_key) if parent_key else None
    comment = SimpleNamespace(
        comments=[
            SimpleNamespace(
                body=comment_body,
                created=comment_created,
                id=f"c-{key}",
            )
        ]
    )
    fields = SimpleNamespace(
        summary=summary,
        status=SimpleNamespace(name=status),
        resolution=SimpleNamespace(name=resolution) if resolution else None,
        issuetype=SimpleNamespace(name=issue_type),
        labels=labels,
        priority=SimpleNamespace(name=priority) if priority else None,
        customfield_10000=epic_link,
        parent=parent,
        comment=comment,
    )
    return SimpleNamespace(key=key, fields=fields)


def _make_epic_issue(key: str, summary: str, labels: list[str]):
    fields = SimpleNamespace(summary=summary, labels=labels)
    return SimpleNamespace(key=key, fields=fields)


def _make_parent_issue(
    key: str,
    *,
    summary: str,
    status: str = "In Progress",
    resolution: str = "",
    epic_link: str = "EPIC-1",
):
    fields = SimpleNamespace(
        summary=summary,
        status=SimpleNamespace(name=status) if status else None,
        resolution=SimpleNamespace(name=resolution) if resolution else None,
        customfield_10000=epic_link,
    )
    return SimpleNamespace(key=key, fields=fields)


def test_resolve_week_window_from_week_defaults_year():
    week = resolve_week_window({"week": "8"}, now=date(2026, 2, 18))
    assert week.year == 2026
    assert week.week == 8
    assert week.key == "26'w08"
    assert week.start == date(2026, 2, 16)
    assert week.end == date(2026, 2, 22)


def test_resolve_week_window_from_compact_week_and_year():
    week = resolve_week_window({"week": "08w26"}, now=date(2025, 1, 1))
    assert week.year == 2026
    assert week.week == 8
    assert week.key == "26'w08"
    assert week.start == date(2026, 2, 16)
    assert week.end == date(2026, 2, 22)


def test_parse_vacations_excel_sheet_format(tmp_path: Path):
    path = tmp_path / "vac.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = "Vacations2026"
    ws.cell(row=3, column=2).value = "Name"
    ws.cell(row=3, column=6).value = datetime(2026, 3, 1)
    ws.cell(row=3, column=7).value = datetime(2026, 3, 2)
    ws.cell(row=3, column=8).value = datetime(2026, 3, 3)
    ws.cell(row=3, column=9).value = datetime(2026, 4, 20)  # outside horizon
    ws.cell(row=5, column=2).value = "Denis Mazur"
    ws.cell(row=5, column=6).value = "p"
    ws.cell(row=5, column=7).value = "P"
    ws.cell(row=5, column=8).value = "p"
    ws.cell(row=5, column=9).value = "p"
    wb.save(path)

    lines = parse_vacations_excel(
        path,
        sheet="Vacations2026",
        markers={"p", "P"},
        horizon_start=date(2026, 2, 20),
        horizon_days=30,
    )
    assert lines == ["Denis Mazur vacation 01.03.2026 - 03.03.2026"]


@patch("stats_core.reports.jira_weekly_email.JiraSource")
def test_jira_weekly_email_report_run_html_snapshot_and_diff(mock_jira_source_cls, tmp_path: Path, capsys):
    issues_week_10 = [
        _make_issue(
            "ABC-1",
            summary="Feature delivery",
            issue_type="Feature",
            status="Done",
            resolution="Done",
            labels=["shine", "reportx"],
            priority="High",
            comment_body="Feature finalized and merged.",
        ),
        _make_issue(
            "ABC-2",
            summary="Parent task",
            issue_type="Task",
            status="In Progress",
            resolution="",
            labels=[],
            priority="Highest",
            comment_body="Work in progress for next week.",
        ),
        _make_issue(
            "ABC-3",
            summary="Bug fix",
            issue_type="Bug",
            status="Done",
            resolution="Done",
            labels=[],
            priority="Medium",
            comment_body="Bug resolved.",
        ),
        _make_issue(
            "ABC-4",
            summary="Subtask done",
            issue_type="Sub-task",
            status="Done",
            resolution="Done",
            labels=[],
            priority="Medium",
            parent_key="ABC-2",
            comment_body="Subtask completed.",
        ),
        _make_issue(
            "ABC-6",
            summary="Other epic task",
            issue_type="Task",
            status="Done",
            resolution="Done",
            labels=[],
            priority="Medium",
            epic_link="EPIC-2",
            comment_body="Completed in non-report epic.",
        ),
    ]
    issues_week_11 = issues_week_10 + [
        _make_issue(
            "ABC-5",
            summary="New improvement",
            issue_type="Improvement",
            status="Done",
            resolution="Done",
            labels=["reportx"],
            priority="Medium",
            comment_created="2026-03-10T10:00:00.000+0000",
            comment_body="Improvement closed.",
        )
    ]

    def _fake_search_issues(jql, *args, **kwargs):
        if "issuekey in (" in str(jql):
            return [
                _make_epic_issue("EPIC-1", "Epic One", ["reportx"]),
                _make_epic_issue("EPIC-2", "Epic Two", []),
            ]
        if "updated < '2026-03-09'" in str(jql):
            return issues_week_10
        if "updated < '2026-03-16'" in str(jql):
            return issues_week_11
        return []

    fake_jira = Mock()
    fake_jira.search_issues.side_effect = _fake_search_issues

    fake_source = Mock()
    fake_source.jira = fake_jira
    fake_source.fetch_epic_names.return_value = {"EPIC-1": "Epic One", "EPIC-2": "Epic Two"}
    mock_jira_source_cls.return_value = fake_source

    config = ConfigParser()
    config.read_dict(
        {
            "jira": {"jira-url": "https://jira.example.com", "username": "u", "password": "p"},
            "reporting": {"output_dir": str(tmp_path)},
            "ollama": {"enabled": "false"},
            "jira_weekly_email": {
                "labels_highlights": "highlights",
                "labels_report": "report",
            },
        }
    )

    report = JiraWeeklyEmailReport()
    report.run(
        dataset={},
        config=config,
        output_formats=["excel"],  # report forces html output mode
        extra_params={
            "project": "ABC",
            "week_date": "2026-03-03",
            "labels_highlights": "shine",
            "labels_report": "reportx",
            "output_dir": str(tmp_path),
        },
    )
    report.run(
        dataset={},
        config=config,
        output_formats=["html"],
        extra_params={
            "project": "ABC",
            "week_date": "2026-03-10",
            "labels_highlights": "shine",
            "labels_report": "reportx",
            "output_dir": str(tmp_path),
        },
    )

    out = capsys.readouterr().out
    assert "[DIFF] ABC" in out
    assert "\x1b[32m" in out
    assert "\x1b[31m" in out or "\x1b[37m" in out

    week10_path = tmp_path / "jira_weekly_email_ABC_26'w10.html"
    assert week10_path.exists()
    week10_text = week10_path.read_text(encoding="utf-8")
    assert "(ABC-1)" in week10_text
    assert "Report items" not in week10_text
    assert "Feature delivery - Finished" in week10_text
    assert "Task completion:" not in week10_text
    assert "(ABC-2) Parent task:" in week10_text
    assert "(ABC-4) Subtask done - Done" in week10_text
    assert "Comment: Subtask completed." in week10_text
    assert "High priority focus:" not in week10_text
    assert "Work in progress for next week." in week10_text
    assert "Plan: Work in progress for next week." not in week10_text
    assert "Continue implementation:" not in week10_text
    assert "Other completed work" not in week10_text
    assert "Epic Two" not in week10_text

    html_path = tmp_path / "jira_weekly_email_ABC_26'w11.html"
    assert html_path.exists()
    text = html_path.read_text(encoding="utf-8")
    assert "1. Highlights" in text
    assert "2. Key Results and Achievements" in text
    assert "(ABC-5)" in text
    assert "[ABC-5]" not in text
    assert "Changes vs Previous Week" not in text

    snapshot_path = tmp_path / "snapshots" / "jira_weekly_email" / "ABC" / "26'w11.json"
    assert snapshot_path.exists()


@patch("stats_core.reports.jira_weekly_email.JiraSource")
def test_jira_weekly_email_omits_empty_high_priority_and_bugs(mock_jira_source_cls, tmp_path: Path):
    issues = [
        _make_issue(
            "ABC-10",
            summary="Report task done",
            issue_type="Task",
            status="Done",
            resolution="Done",
            labels=["reportx"],
            priority="Medium",
            comment_body="Done this week.",
        )
    ]

    fake_jira = Mock()
    fake_jira.search_issues.return_value = issues
    fake_source = Mock()
    fake_source.jira = fake_jira
    fake_source.fetch_epic_names.return_value = {"EPIC-1": "Epic One"}
    mock_jira_source_cls.return_value = fake_source

    config = ConfigParser()
    config.read_dict(
        {
            "jira": {"jira-url": "https://jira.example.com", "username": "u", "password": "p"},
            "reporting": {"output_dir": str(tmp_path)},
            "ollama": {"enabled": "false"},
            "jira_weekly_email": {"labels_report": "reportx"},
        }
    )

    report = JiraWeeklyEmailReport()
    report.run(
        dataset={},
        config=config,
        output_formats=["html"],
        extra_params={
            "project": "ABC",
            "week_date": "2026-03-03",
            "labels_report": "reportx",
            "output_dir": str(tmp_path),
        },
    )

    html_path = tmp_path / "jira_weekly_email_ABC_26'w10.html"
    text = html_path.read_text(encoding="utf-8")
    assert "High priority items" not in text
    assert "Bugs summary" not in text


@patch("stats_core.reports.jira_weekly_email.JiraSource")
def test_jira_weekly_email_labels_report_all_includes_any_labels(mock_jira_source_cls, tmp_path: Path):
    issues = [
        _make_issue(
            "ABC-20",
            summary="Done in epic one",
            issue_type="Task",
            status="Done",
            resolution="Done",
            labels=["foo"],
            priority="Medium",
            epic_link="EPIC-1",
            comment_body="Done.",
        ),
        _make_issue(
            "ABC-21",
            summary="Done in epic two",
            issue_type="Task",
            status="Done",
            resolution="Done",
            labels=[],
            priority="Medium",
            epic_link="EPIC-2",
            comment_body="Done.",
        ),
    ]

    fake_jira = Mock()
    fake_jira.search_issues.return_value = issues
    fake_source = Mock()
    fake_source.jira = fake_jira
    fake_source.fetch_epic_names.return_value = {"EPIC-1": "Epic One", "EPIC-2": "Epic Two"}
    mock_jira_source_cls.return_value = fake_source

    config = ConfigParser()
    config.read_dict(
        {
            "jira": {"jira-url": "https://jira.example.com", "username": "u", "password": "p"},
            "reporting": {"output_dir": str(tmp_path)},
            "ollama": {"enabled": "false"},
            "jira_weekly_email": {"labels_report": "@all"},
        }
    )

    report = JiraWeeklyEmailReport()
    report.run(
        dataset={},
        config=config,
        output_formats=["html"],
        extra_params={
            "project": "ABC",
            "week_date": "2026-03-03",
            "labels_report": "@all",
            "output_dir": str(tmp_path),
        },
    )

    html_path = tmp_path / "jira_weekly_email_ABC_26'w10.html"
    text = html_path.read_text(encoding="utf-8")
    assert "Epic: Epic One (EPIC-1)" in text
    assert "Epic: Epic Two (EPIC-2)" in text


@patch("stats_core.reports.jira_weekly_email.JiraSource")
def test_jira_weekly_email_includes_epic_by_epic_label_not_issue_label(mock_jira_source_cls, tmp_path: Path):
    issues = [
        _make_issue(
            "ABC-30",
            summary="Done work",
            issue_type="Task",
            status="Done",
            resolution="Done",
            labels=[],
            priority="Medium",
            epic_link="EPIC-9",
            comment_body="Done.",
        ),
    ]

    fake_jira = Mock()

    def _fake_search_issues(jql, *args, **kwargs):
        if "issuekey in (" in str(jql):
            return [_make_epic_issue("EPIC-9", "Epic Nine", ["reportx"])]
        return issues

    fake_jira.search_issues.side_effect = _fake_search_issues
    fake_source = Mock()
    fake_source.jira = fake_jira
    fake_source.fetch_epic_names.return_value = {"EPIC-9": "Epic Nine"}
    mock_jira_source_cls.return_value = fake_source

    config = ConfigParser()
    config.read_dict(
        {
            "jira": {"jira-url": "https://jira.example.com", "username": "u", "password": "p"},
            "reporting": {"output_dir": str(tmp_path)},
            "ollama": {"enabled": "false"},
            "jira_weekly_email": {"labels_report": "reportx"},
        }
    )

    report = JiraWeeklyEmailReport()
    report.run(
        dataset={},
        config=config,
        output_formats=["html"],
        extra_params={
            "project": "ABC",
            "week_date": "2026-03-03",
            "labels_report": "reportx",
            "output_dir": str(tmp_path),
        },
    )

    html_path = tmp_path / "jira_weekly_email_ABC_26'w10.html"
    text = html_path.read_text(encoding="utf-8")
    assert "Epic: Epic Nine (EPIC-9)" in text


@patch("stats_core.reports.jira_weekly_email.JiraSource")
def test_jira_weekly_email_uses_parent_summary_when_parent_not_in_main_query(mock_jira_source_cls, tmp_path: Path):
    issues = [
        _make_issue(
            "ABC-40",
            summary="Subtask delivered",
            issue_type="Sub-task",
            status="Done",
            resolution="Done",
            labels=[],
            priority="Medium",
            epic_link="",
            parent_key="ABC-41",
            comment_body="Subtask delivered.",
        ),
    ]

    fake_jira = Mock()

    def _fake_search_issues(jql, *args, **kwargs):
        jql_text = str(jql)
        if "issuekey in (ABC-41)" in jql_text:
            return [_make_parent_issue("ABC-41", summary="Parent headline", epic_link="EPIC-1")]
        if "issuekey in (EPIC-1)" in jql_text:
            return [_make_epic_issue("EPIC-1", "Epic One", ["reportx"])]
        return issues

    fake_jira.search_issues.side_effect = _fake_search_issues
    fake_source = Mock()
    fake_source.jira = fake_jira
    fake_source.fetch_epic_names.return_value = {"EPIC-1": "Epic One"}
    mock_jira_source_cls.return_value = fake_source

    config = ConfigParser()
    config.read_dict(
        {
            "jira": {"jira-url": "https://jira.example.com", "username": "u", "password": "p"},
            "reporting": {"output_dir": str(tmp_path)},
            "ollama": {"enabled": "false"},
            "jira_weekly_email": {"labels_report": "reportx"},
        }
    )

    report = JiraWeeklyEmailReport()
    report.run(
        dataset={},
        config=config,
        output_formats=["html"],
        extra_params={
            "project": "ABC",
            "week_date": "2026-03-03",
            "labels_report": "reportx",
            "output_dir": str(tmp_path),
        },
    )

    html_path = tmp_path / "jira_weekly_email_ABC_26'w10.html"
    text = html_path.read_text(encoding="utf-8")
    assert "(ABC-41) Parent headline:" in text
    assert "(ABC-41) Parent task:" not in text


@patch("stats_core.reports.jira_weekly_email.JiraSource")
def test_jira_weekly_email_vacation_file_accepts_quoted_absolute_path(mock_jira_source_cls, tmp_path: Path):
    path = tmp_path / "vacations.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = "Vacations2026"
    ws.cell(row=3, column=2).value = "Name"
    ws.cell(row=3, column=6).value = datetime(2026, 3, 1)
    ws.cell(row=3, column=7).value = datetime(2026, 3, 2)
    ws.cell(row=5, column=2).value = "Denis Mazur"
    ws.cell(row=5, column=6).value = "p"
    ws.cell(row=5, column=7).value = "p"
    wb.save(path)

    issues = [
        _make_issue(
            "ABC-50",
            summary="Done report item",
            issue_type="Task",
            status="Done",
            resolution="Done",
            labels=[],
            priority="Medium",
            epic_link="EPIC-1",
            comment_body="Done.",
        ),
    ]
    fake_jira = Mock()

    def _fake_search_issues(jql, *args, **kwargs):
        if "issuekey in (EPIC-1)" in str(jql):
            return [_make_epic_issue("EPIC-1", "Epic One", ["reportx"])]
        return issues

    fake_jira.search_issues.side_effect = _fake_search_issues
    fake_source = Mock()
    fake_source.jira = fake_jira
    fake_source.fetch_epic_names.return_value = {"EPIC-1": "Epic One"}
    mock_jira_source_cls.return_value = fake_source

    config = ConfigParser()
    config.read_dict(
        {
            "jira": {"jira-url": "https://jira.example.com", "username": "u", "password": "p"},
            "reporting": {"output_dir": str(tmp_path)},
            "ollama": {"enabled": "false"},
            "jira_weekly_email": {"labels_report": "reportx"},
        }
    )

    report = JiraWeeklyEmailReport()
    report.run(
        dataset={},
        config=config,
        output_formats=["html"],
        extra_params={
            "project": "ABC",
            "week_date": "2026-03-03",
            "labels_report": "reportx",
            "vacation_file": f"\"{path}\"",
            "vacation_sheet": "Vacations2026",
            "vacation_horizon_days": "30",
            "output_dir": str(tmp_path),
        },
    )

    html_path = tmp_path / "jira_weekly_email_ABC_26'w10.html"
    text = html_path.read_text(encoding="utf-8")
    assert "Denis Mazur vacation 02.03.2026 - 02.03.2026" in text


@patch("stats_core.reports.jira_weekly_email.JiraSource")
def test_jira_weekly_email_closed_subtask_not_added_to_plans(mock_jira_source_cls, tmp_path: Path):
    issues = [
        _make_issue(
            "ABC-60",
            summary="Closed subtask",
            issue_type="Sub-task",
            status="Done",
            resolution="Done",
            labels=[],
            priority="Medium",
            epic_link="",
            parent_key="ABC-61",
            comment_body="Subtask is done.",
        ),
    ]
    fake_jira = Mock()

    def _fake_search_issues(jql, *args, **kwargs):
        jql_text = str(jql)
        if "issuekey in (ABC-61)" in jql_text:
            return [_make_parent_issue("ABC-61", summary="Open parent", status="In Progress", epic_link="EPIC-1")]
        if "issuekey in (EPIC-1)" in jql_text:
            return [_make_epic_issue("EPIC-1", "Epic One", ["reportx"])]
        return issues

    fake_jira.search_issues.side_effect = _fake_search_issues
    fake_source = Mock()
    fake_source.jira = fake_jira
    fake_source.fetch_epic_names.return_value = {"EPIC-1": "Epic One"}
    mock_jira_source_cls.return_value = fake_source

    config = ConfigParser()
    config.read_dict(
        {
            "jira": {"jira-url": "https://jira.example.com", "username": "u", "password": "p"},
            "reporting": {"output_dir": str(tmp_path)},
            "ollama": {"enabled": "false"},
            "jira_weekly_email": {"labels_report": "reportx"},
        }
    )

    report = JiraWeeklyEmailReport()
    report.run(
        dataset={},
        config=config,
        output_formats=["html"],
        extra_params={
            "project": "ABC",
            "week_date": "2026-03-03",
            "labels_report": "reportx",
            "output_dir": str(tmp_path),
        },
    )

    html_path = tmp_path / "jira_weekly_email_ABC_26'w10.html"
    text = html_path.read_text(encoding="utf-8")
    assert "(ABC-60) Closed subtask - Done" in text
    assert "No in-progress plans collected for next week." in text
