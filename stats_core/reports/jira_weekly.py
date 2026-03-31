"""
Jira weekly report - coordinates List View, Table View, Epic Progress, and Excel export.
"""

from __future__ import annotations

from datetime import datetime
import logging
from pathlib import Path
from configparser import ConfigParser
from typing import Any

import pandas as pd
from docx import Document

from . import registry
from .jira_comprehensive import build_monthly_summary_df
from .jira_utils import (
    build_developer_activity_df,
    fetch_jira_data,
    fetch_jira_activity_data,
    build_resolved_issues_snapshot,
    mark_reassigned_tasks,
    fill_missing_weeks,
    generate_week_headers,
    get_valid_weeks,
    norm_name,
)
from .jira_list_view import add_list_view_to_document
from .jira_engineer_weekly import add_engineer_weekly_activity_to_document
from .jira_table_view import add_table_view_to_document
from .jira_epic_report import (
    generate_epic_resolved_hierarchy,
    generate_epic_progress_from_worklogs,
    add_epic_progress_to_document,
    add_resolved_tasks_section,
)
from ..sources.jira import JiraSource
from ..utils.members import read_member_list
from ..utils.parallel import parallel_map
from ..utils.progress import NoopProgressManager

logger = logging.getLogger(__name__)

def _parse_bool(value: str | bool | None, default: bool) -> bool:
    """Parse boolean value from string or return default."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return value.lower() in {"1", "true", "yes", "y", "on"}


def generate_file_suffix() -> str:
    """Generate a timestamp-based suffix for file names to ensure uniqueness."""
    now = datetime.now()
    return now.strftime("_%Y%m%d_%H%M")


def _get_progress(extra_params: dict[str, Any], total_steps: int):
    progress = extra_params.get("progress_manager")
    if progress is None:
        progress = NoopProgressManager()
    progress.set_total(total_steps)
    return progress


def _parallel_workers(extra_params: dict[str, Any], default: int = 4) -> int:
    raw = extra_params.get("parallel_workers")
    try:
        value = int(str(raw))
        return max(value, 1)
    except Exception:
        return default


def generate_excel_report(
    data: pd.DataFrame,
    start_date: str,
    end_date: str,
    project: str,
    headers: list[str],
    developer_activity_df: pd.DataFrame,
    output_file: Path,
) -> None:
    """
    Generate an Excel report summarizing the data grouped by assignee and week.

    Args:
        data: DataFrame with Issue_key, Summary, Assignee, Status, Week columns
        start_date: Start date string (YYYY-MM-DD)
        end_date: End date string (YYYY-MM-DD)
        project: Jira project key
        headers: List of week header strings
        output_file: Output file path (without extension)
    """
    data = data.copy()
    data["Formatted"] = data["Status"] + ": " + data["Issue_key"] + " - " + data["Summary"]

    grouped_data = (
        data.groupby(["Assignee", "Week"])["Formatted"]
        .apply("\n".join)
        .unstack(fill_value="")
    )

    grouped_data.columns = headers

    activity_columns = ["Developer", "Issue", "Title", "Logged_Hours", "Worklog", "Comments"]
    if developer_activity_df is None or developer_activity_df.empty:
        developer_activity_export = pd.DataFrame(columns=activity_columns)
    else:
        developer_activity_export = developer_activity_df.copy()
        for column in activity_columns:
            if column not in developer_activity_export.columns:
                developer_activity_export[column] = ""
        developer_activity_export = developer_activity_export[activity_columns + ["Issue_Url"] if "Issue_Url" in developer_activity_export.columns else activity_columns]

    excel_path = Path(f"{output_file}.xlsx")
    with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
        grouped_data.to_excel(writer, sheet_name="Weekly_Grid")
        developer_activity_export[activity_columns].to_excel(writer, sheet_name="Developer_Activity", index=False)

        weekly_sheet = writer.book["Weekly_Grid"]
        activity_sheet = writer.book["Developer_Activity"]
        weekly_sheet.freeze_panes = "B2"
        activity_sheet.freeze_panes = "A2"

        if "Issue_Url" in developer_activity_export.columns:
            issue_col_idx = activity_columns.index("Issue") + 1
            for row_idx, issue_url in enumerate(developer_activity_export["Issue_Url"].tolist(), start=2):
                if not issue_url:
                    continue
                issue_cell = activity_sheet.cell(row=row_idx, column=issue_col_idx)
                issue_cell.hyperlink = str(issue_url)
                issue_cell.style = "Hyperlink"

    logger.info(
        "Excel report successfully created: %s (sheets: %s)",
        excel_path,
        ["Weekly_Grid", "Developer_Activity"],
    )


def _to_weekly_summary_source_df(resolved_issues_df: pd.DataFrame) -> pd.DataFrame:
    if resolved_issues_df.empty:
        return pd.DataFrame(
            columns=[
                "Issue_Key",
                "Summary",
                "Type",
                "Epic_Link",
                "Epic_Name",
                "Epic_Status",
                "Epic_Resolved",
                "Epic_Labels",
                "Resolved",
                "Status",
                "Resolution",
                "Labels",
                "Parent",
                "Parent_Key",
                "Parent_Summary",
                "Description",
                "Last_Comment",
            ]
        )
    summary_df = resolved_issues_df.rename(
        columns={
            "Issue_key": "Issue_Key",
            "Resolution_Date": "Resolved",
        }
    ).copy()
    for column in (
        "Issue_Key",
        "Summary",
        "Type",
        "Epic_Link",
        "Epic_Name",
        "Epic_Status",
        "Epic_Resolved",
        "Epic_Labels",
        "Resolved",
        "Status",
        "Resolution",
        "Labels",
        "Parent",
        "Parent_Key",
        "Parent_Summary",
    ):
        if column not in summary_df.columns:
            summary_df[column] = ""
    if "Parent_Key" in summary_df.columns:
        summary_df["Parent"] = summary_df["Parent"].fillna("").astype(str)
        parent_keys = summary_df["Parent_Key"].fillna("").astype(str)
        empty_parent_mask = summary_df["Parent"].str.strip().eq("")
        summary_df.loc[empty_parent_mask, "Parent"] = parent_keys.loc[empty_parent_mask]
    if "Description" not in summary_df.columns:
        summary_df["Description"] = ""
    if "Last_Comment" not in summary_df.columns:
        summary_df["Last_Comment"] = ""
    return summary_df


def add_summary_section_to_document(document: Document, summary_df: pd.DataFrame) -> None:
    document.add_heading("Summary", level=1)
    if summary_df.empty:
        document.add_paragraph("No summary items for the specified period.")
        return

    sorted_summary = summary_df.copy()
    sorted_summary["_epic_sort"] = sorted_summary["Epic_Name"].fillna("").astype(str).str.casefold()
    sorted_summary = sorted_summary.sort_values(by=["_epic_sort", "Epic_Link"], kind="mergesort")

    for _, row in sorted_summary.iterrows():
        epic_name = str(row.get("Epic_Name") or "Unknown Epic")
        epic_link = str(row.get("Epic_Link") or "").strip()
        heading = f"{epic_name} ({epic_link})" if epic_link else epic_name
        document.add_heading(heading, level=2)

        summary_text = str(row.get("Summary") or "").strip()
        if not summary_text:
            document.add_paragraph("No summary details.")
            continue
        for line in summary_text.splitlines():
            line = line.strip()
            if not line:
                continue
            if line.startswith("- "):
                document.add_paragraph(line[2:], style="List Bullet 2")
            else:
                document.add_paragraph(line)


@registry.register
class JiraWeeklyReport:
    name = "jira_weekly"

    def run(
        self,
        dataset: dict,
        config: ConfigParser,
        output_formats: list[str],
        extra_params: dict | None = None,
    ) -> None:
        extra_params = extra_params or {}
        output_excel = "excel" in output_formats
        output_word = "word" in output_formats
        total_steps = 2 + (1 if output_excel else 0) + (1 if output_word else 0)
        progress = _get_progress(extra_params, total_steps)

        project = extra_params.get("project") or config.get("jira", "project", fallback=None)
        if not project:
            raise ValueError("Project key is required for Jira weekly report. Pass --params project=ABC.")

        start_date = extra_params.get("start") or extra_params.get("start_date")
        end_date = extra_params.get("end") or extra_params.get("end_date")
        if not start_date or not end_date:
            raise ValueError("start_date and end_date must be provided (use --start/--end).")

        include_empty = _parse_bool(extra_params.get("include_empty_weeks"), True)
        member_list_file = extra_params.get("member_list_file") or extra_params.get("members_file")

        # Initialize Jira source
        jira_source = JiraSource(config["jira"])
        jira_url = jira_source.jira_url

        with progress.step("Fetch Jira data"):
            max_workers = _parallel_workers(extra_params)
            if max_workers > 1:
                def _fetch_main():
                    return fetch_jira_data(jira_source, project, start_date, end_date)

                def _fetch_activity():
                    return fetch_jira_activity_data(jira_source, project, start_date, end_date)

                def _fetch_resolved():
                    return build_resolved_issues_snapshot(jira_source, project, start_date, end_date)

                main_df, activity_pair, resolved_issues_df = parallel_map(
                    lambda fn: fn(),
                    [_fetch_main, _fetch_activity, _fetch_resolved],
                    max_workers=min(max_workers, 3),
                    progress_manager=progress,
                    child_label="Jira fetch",
                )
                data = main_df
                worklogs_df, comments_df = activity_pair
            else:
                data = fetch_jira_data(jira_source, project, start_date, end_date)
                worklogs_df, comments_df = fetch_jira_activity_data(jira_source, project, start_date, end_date)
                resolved_issues_df = build_resolved_issues_snapshot(jira_source, project, start_date, end_date)

        # If there is no JIRA data at all, create an empty frame with expected columns
        # so that downstream utilities (fill_missing_weeks, epic reports) work safely.
        if data.empty:
            data = pd.DataFrame(
                columns=[
                    "Issue_key",
                    "Summary",
                    "Assignee",
                    "Final_Assignee",
                    "Status",
                    "Resolution_Date",
                    "Created_Date",
                    "Week",
                    "Epic_Link",
                    "Epic_Name",
                    "Parent_Key",
                    "Parent_Summary",
                    "Type",
                ]
            )

        with progress.step("Process data"):
            start_dt = datetime.strptime(start_date, "%Y-%m-%d").date()
            end_dt = datetime.strptime(end_date, "%Y-%m-%d").date()
            valid_weeks = get_valid_weeks(start_date, end_date)

        # Update the data to include only valid weeks
        if not data.empty:
            data = data[data["Week"].isin(valid_weeks)]

        if member_list_file:
            required_assignees = read_member_list(member_list_file)
        else:
            required_assignees = data["Assignee"].unique().tolist() if not data.empty else []

        if include_empty:
            data = fill_missing_weeks(data, valid_weeks, required_assignees)
            data = mark_reassigned_tasks(data)

        headers = generate_week_headers(valid_weeks, data)
        epic_summary = generate_epic_resolved_hierarchy(resolved_issues_df)
        epic_progress_summary = generate_epic_progress_from_worklogs(worklogs_df)
        weekly_summary_source_df = _to_weekly_summary_source_df(resolved_issues_df)
        weekly_summary_df = build_monthly_summary_df(weekly_summary_source_df, config, extra_params)
        developer_activity_df = pd.DataFrame()

        if output_excel:
            activity_comments_df = comments_df.copy()
            activity_worklogs_df = worklogs_df.copy()
            if member_list_file:
                required_assignees_norm = {norm_name(name) for name in required_assignees}
                if not activity_comments_df.empty:
                    if "CommentAuthor_norm" not in activity_comments_df.columns:
                        activity_comments_df["CommentAuthor_norm"] = activity_comments_df.get("CommentAuthor", "").map(norm_name)
                    activity_comments_df = activity_comments_df[
                        activity_comments_df["CommentAuthor_norm"].isin(required_assignees_norm)
                    ].copy()
                if not activity_worklogs_df.empty:
                    if "Assignee_norm" not in activity_worklogs_df.columns:
                        activity_worklogs_df["Assignee_norm"] = activity_worklogs_df.get("Assignee", "").map(norm_name)
                    activity_worklogs_df = activity_worklogs_df[
                        activity_worklogs_df["Assignee_norm"].isin(required_assignees_norm)
                    ].copy()

            developer_activity_df = build_developer_activity_df(
                activity_comments_df,
                activity_worklogs_df,
                jira_url,
            )
            logger.info(
                "Developer activity sheet rows=%s developers=%s issues=%s total_hours=%.2f",
                len(developer_activity_df.index),
                developer_activity_df["Developer"].nunique() if not developer_activity_df.empty else 0,
                developer_activity_df["Issue"].nunique() if not developer_activity_df.empty else 0,
                float(pd.to_numeric(developer_activity_df.get("Logged_Hours", pd.Series(dtype=float)), errors="coerce").fillna(0).sum()),
            )

        # Generate file suffix
        file_suffix = generate_file_suffix()
        
        # Все отчеты сохраняются в папку reports по умолчанию
        output_dir = extra_params.get("output_dir") or config.get("reporting", "output_dir", fallback="reports")
        output_base = Path(output_dir)
        output_base.mkdir(parents=True, exist_ok=True)
        
        output_file = output_base / f"jira_report_{project}_{start_date}-{end_date}{file_suffix}"

        # Generate Excel report if requested
        if output_excel:
            with progress.step("Export Excel"):
                generate_excel_report(
                    data,
                    start_date,
                    end_date,
                    project,
                    headers,
                    developer_activity_df,
                    output_file,
                )

        # Generate Word report if requested
        if output_word:
            with progress.step("Export Word"):
                document = Document()
                document.add_heading(f"JIRA Report: {project} - {start_date}-{end_date}", level=1)

                # Add Table View
                add_table_view_to_document(document, data, jira_url, member_list_file)

                # Add List View
                add_list_view_to_document(document, data, start_date, end_date, jira_url, member_list_file)

                # Add Engineer Weekly Activity
                add_engineer_weekly_activity_to_document(
                    document,
                    worklogs_df,
                    comments_df,
                    start_date,
                    end_date,
                    jira_url,
                    member_list_file,
                    include_empty=include_empty,
                )

                # Add Epic Progress
                add_epic_progress_to_document(document, epic_summary, jira_url, epic_progress_summary)

                # Add Summary section
                add_summary_section_to_document(document, weekly_summary_df)

                # Add Resolved Tasks section
                add_resolved_tasks_section(document, resolved_issues_df)

                # Save document
                word_path = Path(f"{output_file}.docx")
                document.save(word_path)
                logger.info("Word report successfully created: %s", word_path)
