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


def _comment_body_to_text(body: Any) -> str:
    if body is None:
        return ""
    if isinstance(body, str):
        return body
    if isinstance(body, list):
        return " ".join(_comment_body_to_text(item) for item in body).strip()
    if isinstance(body, dict):
        parts: list[str] = []
        stack = [body]
        while stack:
            node = stack.pop()
            if isinstance(node, dict):
                text_value = node.get("text")
                if isinstance(text_value, str) and text_value:
                    parts.append(text_value)
                content = node.get("content")
                if isinstance(content, list):
                    stack.extend(reversed(content))
            elif isinstance(node, list):
                stack.extend(reversed(node))
        return " ".join(parts).strip()
    return str(body)


_ILLEGAL_EXCEL_CHARS_RE = re.compile(r"[\x00-\x08\x0b-\x0c\x0e-\x1f]")


def _sanitize_excel_text(value: Any) -> str:
    text = _comment_body_to_text(value)
    if not text:
        return ""
    text = str(text).replace("\r\n", "\n").replace("\r", "\n")
    cleaned_lines = [" ".join(line.split()) for line in text.split("\n")]
    cleaned_text = "\n".join(line for line in cleaned_lines if line)
    return _ILLEGAL_EXCEL_CHARS_RE.sub("", cleaned_text).strip()


def _format_hours_value(seconds: int | float | None) -> float:
    if not seconds:
        return 0.0
    return round(float(seconds) / 3600.0, 2)


def _format_hours_label(seconds: int | float | None) -> str:
    hours = _format_hours_value(seconds)
    if hours == 0:
        return "0h"
    return f"{hours:.2f}".rstrip("0").rstrip(".") + "h"


def _empty_developer_activity_df() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "Developer",
            "Issue",
            "Title",
            "Logged_Hours",
            "Worklog",
            "Comments",
            "Issue_Url",
        ]
    )


def build_developer_activity_df(
    comments_df: pd.DataFrame,
    worklogs_df: pd.DataFrame,
    jira_url: str,
) -> pd.DataFrame:
    """Build comment-driven developer activity rows for weekly Excel export."""
    if comments_df is None or comments_df.empty:
        return _empty_developer_activity_df()

    comments_df = comments_df.copy()
    worklogs_df = worklogs_df.copy() if worklogs_df is not None else pd.DataFrame()

    if "CommentAuthor_norm" not in comments_df.columns:
        comments_df["CommentAuthor_norm"] = comments_df.get("CommentAuthor", "").map(norm_name)
    if "Assignee_norm" not in worklogs_df.columns:
        worklogs_df["Assignee_norm"] = worklogs_df.get("Assignee", "").map(norm_name)

    if "Is_Worklog_Comment" in comments_df.columns:
        issue_comments_df = comments_df[~comments_df["Is_Worklog_Comment"].fillna(False).astype(bool)].copy()
    else:
        issue_comments_df = comments_df

    if issue_comments_df.empty:
        return _empty_developer_activity_df()

    sort_columns = [column for column in ("CommentAuthor_norm", "Issue_key", "CommentDate", "CommentId") if column in issue_comments_df.columns]
    if sort_columns:
        issue_comments_df = issue_comments_df.sort_values(by=sort_columns, kind="mergesort")

    rows: list[dict[str, Any]] = []
    grouped = issue_comments_df.groupby(["CommentAuthor_norm", "Issue_key"], sort=True, dropna=False)

    for (developer_norm, issue_key), issue_comments in grouped:
        issue_key = str(issue_key or "").strip()
        developer_norm = str(developer_norm or "").strip()
        if not issue_key or not developer_norm:
            continue

        developer = next(
            (
                str(value).strip()
                for value in issue_comments.get("CommentAuthor", pd.Series(dtype=object)).tolist()
                if str(value).strip()
            ),
            "",
        )
        title = next(
            (
                str(value).strip()
                for value in issue_comments.get("Summary", pd.Series(dtype=object)).tolist()
                if str(value).strip()
            ),
            "",
        )

        comment_lines: list[str] = []
        for _, comment_row in issue_comments.iterrows():
            body = _sanitize_excel_text(comment_row.get("CommentBody", ""))
            if not body:
                continue
            comment_date = str(
                comment_row.get("CommentDateStr")
                or comment_row.get("CommentUpdated")
                or comment_row.get("CommentCreated")
                or ""
            ).strip()
            if comment_date:
                comment_lines.append(f"{comment_date} | {body}")
            else:
                comment_lines.append(body)

        if not comment_lines:
            continue

        issue_worklogs = worklogs_df[
            (worklogs_df.get("Assignee_norm", pd.Series(dtype=object)).fillna("").astype(str) == developer_norm)
            & (worklogs_df.get("Issue_key", pd.Series(dtype=object)).fillna("").astype(str) == issue_key)
        ].copy()

        if not title and not issue_worklogs.empty:
            title = next(
                (
                    str(value).strip()
                    for value in issue_worklogs.get("Summary", pd.Series(dtype=object)).tolist()
                    if str(value).strip()
                ),
                "",
            )

        worklog_lines: list[str] = []
        total_seconds = 0
        if not issue_worklogs.empty:
            worklog_sort_columns = [column for column in ("WorklogDate", "WorklogDateStr") if column in issue_worklogs.columns]
            if worklog_sort_columns:
                issue_worklogs = issue_worklogs.sort_values(by=worklog_sort_columns, kind="mergesort")

            total_seconds = int(pd.to_numeric(issue_worklogs.get("WorklogSeconds", pd.Series(dtype=float)), errors="coerce").fillna(0).sum())

            for _, worklog_row in issue_worklogs.iterrows():
                seconds = int(float(worklog_row.get("WorklogSeconds") or 0))
                date_str = str(worklog_row.get("WorklogDateStr") or "").strip()
                worklog_comment = _sanitize_excel_text(worklog_row.get("WorklogComment", ""))
                parts = [part for part in (date_str, _format_hours_label(seconds), worklog_comment) if part]
                if parts:
                    worklog_lines.append(" | ".join(parts))

        rows.append(
            {
                "Developer": developer,
                "Issue": issue_key,
                "Title": _sanitize_excel_text(title),
                "Logged_Hours": _format_hours_value(total_seconds),
                "Worklog": "\n".join(worklog_lines),
                "Comments": "\n".join(comment_lines),
                "Issue_Url": f"{str(jira_url).rstrip('/')}/browse/{issue_key}" if jira_url else "",
            }
        )

    if not rows:
        return _empty_developer_activity_df()

    result = pd.DataFrame(rows)
    result = result.sort_values(
        by=["Developer", "Issue"],
        key=lambda series: series.fillna("").astype(str).str.casefold(),
        kind="mergesort",
    ).reset_index(drop=True)
    return result


def _extract_last_comment_in_period(
    jira_source: JiraSource,
    issue_key: str,
    start_dt: datetime.date,
    end_dt: datetime.date,
) -> str:
    try:
        comments = jira_source.get_all_comments(issue_key)
    except Exception:
        return ""
    if not isinstance(comments, list):
        return ""

    latest_text = ""
    latest_marker: tuple[datetime.date, int] | None = None
    for idx, comment in enumerate(comments):
        if not isinstance(comment, dict):
            continue
        updated_dt = _parse_jira_date(comment.get("updated"))
        created_dt = _parse_jira_date(comment.get("created"))
        comment_dt = updated_dt or created_dt
        if not comment_dt or not (start_dt <= comment_dt <= end_dt):
            continue
        text = " ".join(_comment_body_to_text(comment.get("body")).split())
        if not text:
            continue
        marker = (comment_dt, idx)
        if latest_marker is None or marker >= latest_marker:
            latest_marker = marker
            latest_text = text
    return latest_text


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


def build_resolved_issues_snapshot(
    jira_source: JiraSource,
    project: str,
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    """
    Build a snapshot of issues resolved within the specified period.

    Args:
        jira_source: JiraSource instance
        project: Jira project key
        start_date: Start date string (YYYY-MM-DD)
        end_date: End date string (YYYY-MM-DD)

    Returns:
        DataFrame with columns: Issue_key, Summary, Resolution_Date, Resolution_Week,
        Epic_Link, Epic_Name, Parent_Key, Parent_Summary, Type

    Note:
        Jira fetch_issues uses updated >= start_date, so resolved issues not updated in the
        period may be missing.
    """
    start_dt = datetime.strptime(start_date, "%Y-%m-%d").date()
    end_dt = datetime.strptime(end_date, "%Y-%m-%d").date()

    all_issues = jira_source.fetch_issues(
        project,
        datetime.combine(start_dt, datetime.min.time()),
        datetime.combine(end_dt, datetime.min.time()),
    )

    epic_keys = list({
        getattr(issue.fields, "customfield_10000", None)
        for issue in all_issues
        if getattr(issue.fields, "customfield_10000", None)
    })
    epic_names = jira_source.fetch_epic_names(epic_keys)

    issue_epic_map: dict[str, str | None] = {}
    issue_summary_map: dict[str, str] = {}
    issue_status_map: dict[str, str] = {}
    issue_resolved_map: dict[str, str] = {}
    issue_labels_map: dict[str, str] = {}
    for issue in all_issues:
        issue_epic_map[issue.key] = getattr(issue.fields, "customfield_10000", None)
        issue_summary_map[issue.key] = issue.fields.summary
        status = issue.fields.status.name if getattr(issue.fields, "status", None) else ""
        issue_status_map[issue.key] = status
        resolved_raw = getattr(issue.fields, "resolutiondate", "") or ""
        issue_resolved_map[issue.key] = str(resolved_raw)[:10] if resolved_raw else ""
        labels_raw = getattr(issue.fields, "labels", None)
        if isinstance(labels_raw, (list, tuple, set)):
            labels_text = ", ".join(str(label) for label in labels_raw if str(label).strip())
        elif isinstance(labels_raw, str):
            labels_text = labels_raw.strip()
        else:
            labels_text = ""
        issue_labels_map[issue.key] = labels_text

    rows: list[dict[str, Any]] = []

    for issue in all_issues:
        resolved_date = issue.fields.resolutiondate
        if not resolved_date:
            continue

        resolution_date = resolved_date.split("T")[0]
        try:
            resolution_dt = datetime.strptime(resolution_date, "%Y-%m-%d").date()
        except Exception:
            continue

        if not (start_dt <= resolution_dt <= end_dt):
            continue

        parent = getattr(issue.fields, "parent", None)
        parent_key = parent.key if parent else ""
        parent_summary = parent.fields.summary if parent else ""
        if not parent_summary and parent_key:
            parent_summary = issue_summary_map.get(parent_key, "")

        epic_link = getattr(issue.fields, "customfield_10000", None)
        if (not epic_link) and parent_key:
            parent_fields = getattr(parent, "fields", None)
            epic_link = getattr(parent_fields, "customfield_10000", None) or issue_epic_map.get(parent_key, "")

        epic_name = epic_names.get(epic_link, "Unknown Epic") if epic_link else "Unknown Epic"
        epic_status = issue_status_map.get(epic_link or "", "")
        epic_resolved = issue_resolved_map.get(epic_link or "", "")
        epic_labels = issue_labels_map.get(epic_link or "", "")

        issue_type = getattr(issue.fields, "issuetype", None)
        issue_type_name = issue_type.name if issue_type else "Unknown"
        status_name = issue.fields.status.name if getattr(issue.fields, "status", None) else ""
        resolution = issue.fields.resolution.name if getattr(issue.fields, "resolution", None) else ""
        description = getattr(issue.fields, "description", "") or ""
        last_comment = _extract_last_comment_in_period(jira_source, issue.key, start_dt, end_dt)
        labels = issue_labels_map.get(issue.key, "")

        rows.append({
            "Issue_key": issue.key,
            "Summary": issue.fields.summary,
            "Status": status_name,
            "Resolution": resolution,
            "Resolution_Date": resolution_date,
            "Resolution_Week": resolution_dt.strftime("%G-W%V"),
            "Epic_Link": epic_link or "",
            "Epic_Name": epic_name,
            "Epic_Status": epic_status,
            "Epic_Resolved": epic_resolved,
            "Epic_Labels": epic_labels,
            "Labels": labels,
            "Parent": parent_key or "",
            "Parent_Key": parent_key or "",
            "Parent_Summary": parent_summary or "",
            "Type": issue_type_name,
            "Description": description,
            "Last_Comment": last_comment,
        })

    return pd.DataFrame(rows)


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

    all_issues = jira_source.fetch_issues(
        project,
        datetime.combine(start_dt, datetime.min.time()),
        datetime.combine(end_dt, datetime.min.time()),
    )

    epic_keys = list({
        getattr(issue.fields, "customfield_10000", None)
        for issue in all_issues
        if getattr(issue.fields, "customfield_10000", None)
    })
    epic_names = jira_source.fetch_epic_names(epic_keys)

    worklog_rows: list[dict[str, Any]] = []
    comment_rows: list[dict[str, Any]] = []
    worklog_comment_rows: list[dict[str, Any]] = []

    for issue in all_issues:
        key = issue.key
        summary = issue.fields.summary
        epic_link = getattr(issue.fields, "customfield_10000", None)
        status = issue.fields.status.name if issue.fields.status else ""
        resolution = issue.fields.resolution.name if issue.fields.resolution else ""
        parent = getattr(issue.fields, "parent", None)
        parent_key = parent.key if parent else ""
        parent_summary = parent.fields.summary if parent else ""
        issue_type = getattr(issue.fields, "issuetype", None)
        issue_type_name = issue_type.name if issue_type else ""

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
                comment_text = _comment_body_to_text(log.get("comment"))
                worklog_rows.append({
                    "Issue_key": key,
                    "Summary": summary,
                    "Assignee": author,
                    "Assignee_norm": norm_name(author),
                    "Week": week,
                    "WorklogSeconds": int(time_spent),
                    "WorklogDate": log_date,
                    "WorklogDateStr": log_date.strftime("%Y-%m-%d"),
                    "WorklogComment": comment_text,
                    "Status": status,
                    "Resolution": resolution,
                    "Epic_Link": epic_link,
                    "Epic_Name": epic_names.get(epic_link, "Unknown Epic"),
                    "Parent_Key": parent_key,
                    "Parent_Summary": parent_summary,
                    "Type": issue_type_name,
                })

                if comment_text and str(comment_text).strip():
                    worklog_comment_rows.append({
                        "Issue_key": key,
                        "Summary": summary,
                        "CommentId": "",
                        "CommentBody": comment_text,
                        "CommentAuthor": author,
                        "CommentAuthor_norm": norm_name(author),
                        "CommentCreated": log_date.strftime("%Y-%m-%d"),
                        "CommentUpdated": log_date.strftime("%Y-%m-%d"),
                        "CommentDate": log_date,
                        "CommentDateStr": log_date.strftime("%Y-%m-%d"),
                        "Week": week,
                        "Status": status,
                        "Resolution": resolution,
                        "Epic_Link": epic_link,
                        "Epic_Name": epic_names.get(epic_link, "Unknown Epic"),
                        "Parent_Key": parent_key,
                        "Parent_Summary": parent_summary,
                        "Type": issue_type_name,
                        "Is_Worklog_Comment": True,
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
                "Status": status,
                "Resolution": resolution,
                "Epic_Link": epic_link,
                "Epic_Name": epic_names.get(epic_link, "Unknown Epic"),
                "Parent_Key": parent_key,
                "Parent_Summary": parent_summary,
                "Type": issue_type_name,
                "Is_Worklog_Comment": False,
            })

    worklogs_df = pd.DataFrame(worklog_rows)
    comments_df = pd.DataFrame(comment_rows + worklog_comment_rows)
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
