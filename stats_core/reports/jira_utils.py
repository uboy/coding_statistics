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
    Build a per-week snapshot for each issue using worklogs and resolution dates.

    For every worklog inside the period we emit an "In progress" row (one per author per
    week). If the issue was resolved inside the period we also emit a "Resolved" row for
    each worklog author in the resolution week. This makes sure tasks with logged time
    appear in weekly reports even if they are still open.

    Args:
        jira_source: JiraSource instance
        project: Jira project key
        start_date: Start date string (YYYY-MM-DD)
        end_date: End date string (YYYY-MM-DD)

    Returns:
        DataFrame with columns: Issue_key, Summary, Assignee, Status, Resolution_Date,
        Week, Epic_Link, Epic_Name, Parent_Key, Parent_Summary, Type, Created_Date
    """
    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")

    all_issues = jira_source.fetch_issues(project, start_dt, end_dt)

    # Fetch all epic names
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
        jira_assignee = issue.fields.assignee.displayName if issue.fields.assignee else "Unassigned"
        resolved_date = issue.fields.resolutiondate
        created_date = getattr(issue.fields, "created", None)
        epic_link = getattr(issue.fields, "customfield_10000", None)
        parent = getattr(issue.fields, "parent", None)
        parent_key = parent.key if parent else None
        parent_summary = parent.fields.summary if parent else None

        worklogs = jira_source.get_all_worklogs(key)
        # собираем всех авторов worklog и авторов по неделям
        worklog_authors = set()
        worklog_by_week = {}

        for log in worklogs:
            try:
                author = log["author"]["displayName"]
                log_date = datetime.strptime(log["started"].split("T")[0], "%Y-%m-%d")

                if start_dt <= log_date <= end_dt:
                    week = log_date.strftime("%G-W%V")
                    worklog_authors.add(author)
                    worklog_by_week.setdefault(week, set()).add(author)
            except Exception:
                continue

        resolution_date = resolved_date.split("T")[0] if resolved_date else ""
        created_date_str = created_date.split("T")[0] if created_date else ""
        issue_type = getattr(issue.fields, "issuetype", None)
        issue_type_name = issue_type.name if issue_type else "Unknown"

        resolved_week = None
        if resolved_date:
            resolved_date_dt = datetime.strptime(resolution_date, "%Y-%m-%d")
            if start_dt <= resolved_date_dt <= end_dt:
                resolved_week = resolved_date_dt.strftime("%G-W%V")

        for author in worklog_authors:
            if resolved_week:
                data.append({
                    "Issue_key": key,
                    "Summary": summary,
                    "Assignee": author,  # assignee = worklog author
                    "Final_Assignee": jira_assignee,
                    "Status": "Resolved",
                    "Resolution_Date": resolution_date,
                    "Created_Date": created_date_str,
                    "Week": resolved_week,
                    "Epic_Link": epic_link,
                    "Epic_Name": epic_names.get(epic_link, "Unknown Epic"),
                    "Parent_Key": parent_key,
                    "Parent_Summary": parent_summary,
                    "Type": issue_type_name
                })

        for log_week, authors_in_week in worklog_by_week.items():
            if resolved_week and log_week == resolved_week:
                continue
            for author in authors_in_week:
                data.append({
                    "Issue_key": key,
                    "Summary": summary,
                    "Assignee": author,  # assignee = worklog author
                    "Final_Assignee": jira_assignee,
                    "Status": "In progress",
                    "Resolution_Date": resolution_date if resolved_week else "",
                    "Created_Date": created_date_str,
                    "Week": log_week,
                    "Epic_Link": epic_link,
                    "Epic_Name": epic_names.get(epic_link, "Unknown Epic"),
                    "Parent_Key": parent_key,
                    "Parent_Summary": parent_summary,
                    "Type": issue_type_name
                })

    df = pd.DataFrame(data)
    if not df.empty:
        df = df.drop_duplicates(subset=["Issue_key", "Assignee", "Week", "Status"], keep="last")
    return df


def fetch_jira_activity_data(
    jira_source: JiraSource,
    project: str,
    start_date: str,
    end_date: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Fetch per-week worklogs and comments for activity reporting.

    Returns:
        (worklogs_df, comments_df)
    """
    start_dt = datetime.strptime(start_date, "%Y-%m-%d").date()
    end_dt = datetime.strptime(end_date, "%Y-%m-%d").date()

    all_issues = jira_source.fetch_issues(project, datetime.combine(start_dt, datetime.min.time()),
                                          datetime.combine(end_dt, datetime.min.time()))

    worklog_rows: list[dict[str, Any]] = []
    comment_rows: list[dict[str, Any]] = []

    for issue in all_issues:
        key = issue.key
        summary = issue.fields.summary

        worklogs = jira_source.get_all_worklogs(key)
        for log in worklogs:
            try:
                author = log.get("author", {}).get("displayName", "")
                log_date = datetime.strptime(log["started"].split("T")[0], "%Y-%m-%d").date()
            except Exception:
                continue

            if start_dt <= log_date <= end_dt:
                week = log_date.strftime("%G-W%V")
                time_spent = log.get("timeSpentSeconds") or 0
                worklog_rows.append({
                    "Issue_key": key,
                    "Summary": summary,
                    "Assignee": author,
                    "Assignee_norm": norm_name(author),
                    "Week": week,
                    "WorklogSeconds": int(time_spent),
                })

        comments = jira_source.get_all_comments(key)
        for comment in comments:
            author = comment.get("author", {}).get("displayName", "")
            created = comment.get("created")
            updated = comment.get("updated")
            created_dt = _parse_jira_date(created)
            updated_dt = _parse_jira_date(updated)

            comment_dt = None
            if updated_dt and start_dt <= updated_dt <= end_dt:
                comment_dt = updated_dt
            elif created_dt and start_dt <= created_dt <= end_dt:
                comment_dt = created_dt

            if comment_dt is None:
                continue

            week = comment_dt.strftime("%G-W%V")
            comment_rows.append({
                "Issue_key": key,
                "Summary": summary,
                "CommentId": comment.get("id", ""),
                "CommentBody": comment.get("body", ""),
                "CommentAuthor": author,
                "CommentAuthor_norm": norm_name(author),
                "CommentCreated": created.split("T")[0] if created else "",
                "CommentUpdated": updated.split("T")[0] if updated else "",
                "CommentDate": comment_dt,
                "CommentDateStr": comment_dt.strftime("%Y-%m-%d"),
                "Week": week,
            })

    worklogs_df = pd.DataFrame(worklog_rows)
    comments_df = pd.DataFrame(comment_rows)
    return worklogs_df, comments_df


def _parse_jira_date(value: str | None) -> datetime.date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value.split("T")[0], "%Y-%m-%d").date()
    except Exception:
        return None


def mark_reassigned_tasks(df: pd.DataFrame) -> pd.DataFrame:
    """
    Mark tasks that were reassigned.

    Логика:
      - собираем всех worklog-авторов (поле Assignee) для каждой Issue_key;
      - берём финального исполнителя из Jira (поле Final_Assignee);
      - считаем задачу переназначенной, если финальный исполнитель НЕ логировал время.
    """
    df = df.copy()

    # If required columns are missing (e.g. completely empty input from fetch_jira_data),
    # there is nothing to mark – return DataFrame with a False flag.
    for col in ("Issue_key", "Assignee", "Final_Assignee"):
        if col not in df.columns:
            df["Reassigned"] = False
            return df

    # Игнорируем заполнители без ключа задачи
    real_issues = df[df["Issue_key"] != ""]
    if real_issues.empty:
        df["Reassigned"] = False
        return df

    worklog_authors = (
        real_issues.groupby("Issue_key")["Assignee"]
        .unique()
        .to_dict()
    )

    final_assignee = (
        real_issues.groupby("Issue_key")["Final_Assignee"]
        .last()
        .to_dict()
    )

    reassigned_map: dict[str, bool] = {}
    for issue, authors in worklog_authors.items():
        final = final_assignee.get(issue)
        # Если финальный исполнитель отсутствует или пустой — считаем, что не переназначено
        if final is None or str(final).strip() == "":
            reassigned_map[issue] = False
        else:
            reassigned_map[issue] = final not in authors

    reassigned_series = df["Issue_key"].map(reassigned_map)
    reassigned_series = reassigned_series.infer_objects(copy=False).fillna(False)
    df["Reassigned"] = reassigned_series.astype(bool)
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

    # Ensure required columns exist even for empty DataFrames
    if "Assignee" not in data.columns:
        data["Assignee"] = ""
    if "Week" not in data.columns:
        data["Week"] = ""

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
