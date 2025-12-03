"""
Shared utilities for Jira reports.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any

import pandas as pd

from ..sources.jira import JiraSource


def norm_name(name: str) -> str:
    """Normalize name for comparison (lowercase, single spaces)."""
    if not isinstance(name, str):
        return ""
    return re.sub(r"\s+", " ", name).strip().casefold()


def fetch_jira_data(
    jira_source: JiraSource,
    project: str,
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    """
    Fetch data from JIRA and filter by date range and resolution status.

    Returns:
        DataFrame with columns: Issue_key, Summary, Assignee, Status, Resolution_Date,
        Week, Epic_Link, Epic_Name, Parent_Key, Parent_Summary, Type, Created_Date
    """
    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")

    all_issues = jira_source.fetch_issues(project, start_dt, end_dt)

    epic_keys = list({
        getattr(issue.fields, "customfield_10000", None)
        for issue in all_issues
        if getattr(issue.fields, "customfield_10000", None)
    })
    epic_names = jira_source.fetch_epic_names(epic_keys)

    data = []
    for issue in all_issues:
        key = issue.key
        summary = issue.fields.summary

        # финальный assignee на момент выгрузки
        assignee = issue.fields.assignee.displayName if issue.fields.assignee else "Unassigned"

        resolved_date = issue.fields.resolutiondate
        created_date = getattr(issue.fields, "created", None)
        created_date_str = created_date.split("T")[0] if created_date else ""

        epic_link = getattr(issue.fields, "customfield_10000", None)

        parent = getattr(issue.fields, "parent", None)
        parent_key = parent.key if parent else None
        parent_summary = parent.fields.summary if parent else None

        issue_type = getattr(issue.fields, "issuetype", None)
        issue_type_name = issue_type.name if issue_type else "Unknown"

        worklogs = jira_source.get_all_worklogs(key)

        worklog_by_week: dict[str, set[str]] = {}
        for log in worklogs:
            try:
                author = log["author"]["displayName"]
                log_date = datetime.strptime(log["started"].split("T")[0], "%Y-%m-%d")

                if start_dt <= log_date <= end_dt:
                    week = log_date.strftime("%G-W%V")
                    worklog_by_week.setdefault(week, set()).add(author)
            except Exception:
                continue

        # --- Resolved: только финальному assignee ---
        resolved_week = None
        resolution_date_str = ""
        if resolved_date:
            resolution_date_str = resolved_date.split("T")[0]
            resolved_date_dt = datetime.strptime(resolution_date_str, "%Y-%m-%d")
            if start_dt <= resolved_date_dt <= end_dt:
                resolved_week = resolved_date_dt.strftime("%G-W%V")
                data.append({
                    "Issue_key": key,
                    "Summary": summary,
                    "Assignee": assignee,  # Resolved только финальному assignee
                    "Status": "Resolved",
                    "Resolution_Date": resolution_date_str,
                    "Created_Date": created_date_str,
                    "Week": resolved_week,
                    "Epic_Link": epic_link,
                    "Epic_Name": epic_names.get(epic_link, "Unknown Epic"),
                    "Parent_Key": parent_key,
                    "Parent_Summary": parent_summary,
                    "Type": issue_type_name,
                })

        # --- In progress: по worklog авторам, всегда (независимо от resolved_date) ---
        for log_week, authors_in_week in worklog_by_week.items():
            for author in authors_in_week:
                # В неделю резолва финальному исполнителю не ставим In progress (у него будет Resolved)
                if resolved_week and log_week == resolved_week and author == assignee:
                    continue

                data.append({
                    "Issue_key": key,
                    "Summary": summary,
                    "Assignee": author,
                    "Status": "In progress",
                    "Resolution_Date": "",
                    "Created_Date": created_date_str,
                    "Week": log_week,
                    "Epic_Link": epic_link,
                    "Epic_Name": epic_names.get(epic_link, "Unknown Epic"),
                    "Parent_Key": parent_key,
                    "Parent_Summary": parent_summary,
                    "Type": issue_type_name,
                })

    df = pd.DataFrame(data)
    if not df.empty:
        df = df.drop_duplicates(subset=["Issue_key", "Assignee", "Week", "Status"], keep="last")
    return df


def mark_reassigned_tasks(df: pd.DataFrame) -> pd.DataFrame:
    """
    Mark tasks that were reassigned (final assignee is not in worklog authors).

    Args:
        df: DataFrame with Issue_key, Assignee columns

    Returns:
        DataFrame with added Reassigned column
    """
    # собираем всех worklog-авторов для каждой задачи
    worklog_authors = (
        df[df["Status"] == "In progress"]
        .groupby("Issue_key")["Assignee"]
        .unique()
        .to_dict()
    )

    # финальный исполнитель задачи
    final_assignee = (
        df[df["Status"] == "Resolved"]
        .groupby("Issue_key")["Assignee"]
        .last()
        .to_dict()
    )

    # формируем флаг reassigned
    reassigned_map = {}
    for issue, authors in worklog_authors.items():
        final = final_assignee.get(issue)
        reassigned_map[issue] = final not in authors

    # Добавляем в DataFrame столбец:
    df = df.copy()
    df["Reassigned"] = df["Issue_key"].map(reassigned_map).fillna(False)
    return df


def fill_missing_weeks(
    data: pd.DataFrame,
    valid_weeks: list[str],
    required_assignees: list[str],
) -> pd.DataFrame:
    """
    Добавляет фиктивные строки в датафрейм для каждого assignee и недели,
    если у него нет активности. Сопоставление делаем по нормализованным именам.

    Args:
        data: DataFrame with Assignee, Week columns
        valid_weeks: List of week strings (e.g., ["2025-W01", "2025-W02"])
        required_assignees: List of assignee names to ensure presence

    Returns:
        DataFrame with filler rows added
    """
    data = data.copy()
    data["Assignee_norm"] = data["Assignee"].map(norm_name)

    required_assignees_norm = [(a, norm_name(a)) for a in required_assignees]

    existing_keys = set(zip(data["Assignee_norm"], data["Week"]))
    filler_rows = []

    for assignee_display, assignee_norm in required_assignees_norm:
        for week in valid_weeks:
            if (assignee_norm, week) not in existing_keys:
                year, week_num = map(int, week.split("-W"))
                week_start = pd.Timestamp.fromisocalendar(year, week_num, 1)
                resolution_date = week_start.strftime("%Y-%m-%d")

                filler_rows.append({
                    "Issue_key": "",
                    "Summary": "",
                    "Assignee": assignee_display,
                    "Assignee_norm": assignee_norm,
                    "Status": "",
                    "Resolution_Date": resolution_date,
                    "Created_Date": "",
                    "Week": week,
                    "Epic_Link": "",
                    "Epic_Name": "",
                    "Parent_Key": "",
                    "Parent_Summary": "",
                    "Type": ""
                })

    if filler_rows:
        data = pd.concat([data, pd.DataFrame(filler_rows)], ignore_index=True)

    return data


def generate_week_headers(valid_weeks: list[str], data: pd.DataFrame) -> list[str]:
    """
    Generate table headers with week ranges for the report.
    Include only weeks with existing JIRA data and that have passed.

    Args:
        valid_weeks: List of week strings
        data: DataFrame with Week column

    Returns:
        List of header strings like "2025-W01(01/01-07/01)"
    """
    headers = []
    unique_weeks_with_data = set(data["Week"])

    for week in valid_weeks:
        if week in unique_weeks_with_data:
            year, week_num = map(int, week.split("-W"))
            week_start = pd.Timestamp.fromisocalendar(year, week_num, 1)
            week_end = week_start + timedelta(days=6)
            # Exclude future weeks
            if week_start <= datetime.now():
                headers.append(f"{week}({week_start.strftime('%d/%m')}-{week_end.strftime('%d/%m')})")
    return headers


def get_valid_weeks(start_date: str, end_date: str) -> list[str]:
    """
    Get list of valid week strings (ISO format) for date range.

    Args:
        start_date: Start date string (YYYY-MM-DD)
        end_date: End date string (YYYY-MM-DD)

    Returns:
        List of week strings like ["2025-W01", "2025-W02"]
    """
    start_dt = datetime.strptime(start_date, "%Y-%m-%d").date()
    start_monday = start_dt - timedelta(days=start_dt.weekday())
    end_dt = datetime.strptime(end_date, "%Y-%m-%d").date()
    valid_weeks = pd.date_range(start=start_monday, end=end_dt, freq='W-MON').strftime("%G-W%V").tolist()
    return valid_weeks


def is_empty_task(summary: Any, status: Any) -> bool:
    """Определяет, является ли строка пустой (нет задачи и нет worklog)."""
    return (
        (not isinstance(summary, str) or summary.strip() == "") and
        (not isinstance(status, str) or status.strip() == "")
    )

