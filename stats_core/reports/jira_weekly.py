"""
Jira weekly report - coordinates List View, Table View, Epic Progress, and Excel export.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from configparser import ConfigParser
from typing import Any

import pandas as pd

from . import registry
from .jira_utils import (
    fetch_jira_data,
    mark_reassigned_tasks,
    fill_missing_weeks,
    generate_week_headers,
    get_valid_weeks,
    norm_name,
)
from .jira_list_view import add_list_view_to_document
from .jira_table_view import add_table_view_to_document
from .jira_epic_report import generate_epic_report, add_epic_progress_to_document, add_resolved_tasks_section
from ..sources.jira import JiraSource
from ..export import excel as excel_export
from ..utils.members import read_member_list


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


def generate_excel_report(
    data: pd.DataFrame,
    start_date: str,
    end_date: str,
    project: str,
    headers: list[str],
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

    excel_path = Path(f"{output_file}.xlsx")
    grouped_data.to_excel(excel_path)
    print(f"Excel report successfully created: {excel_path}")


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

        # Fetch data
        data = fetch_jira_data(jira_source, project, start_date, end_date)

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

        # Process data
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
        epic_summary = generate_epic_report(data)

        # Generate file suffix
        file_suffix = generate_file_suffix()
        
        # Все отчеты сохраняются в папку reports по умолчанию
        output_dir = extra_params.get("output_dir") or config.get("reporting", "output_dir", fallback="reports")
        output_base = Path(output_dir)
        output_base.mkdir(parents=True, exist_ok=True)
        
        output_file = output_base / f"jira_report_{project}_{start_date}-{end_date}{file_suffix}"

        # Generate Excel report if requested
        if "excel" in output_formats:
            generate_excel_report(data, start_date, end_date, project, headers, output_file)

        # Generate Word report if requested
        if "word" in output_formats:
            from docx import Document

            document = Document()
            document.add_heading(f"JIRA Report: {project} - {start_date}-{end_date}", level=1)

            # Add Table View
            add_table_view_to_document(document, data, jira_url, member_list_file)

            # Add List View
            add_list_view_to_document(document, data, start_date, end_date, jira_url, member_list_file)

            # Add Epic Progress
            add_epic_progress_to_document(document, epic_summary, jira_url)

            # Add Resolved Tasks section
            resolved_tasks = data[data["Status"] == "Resolved"] if not data.empty else pd.DataFrame()
            add_resolved_tasks_section(document, resolved_tasks)

            # Save document
            word_path = Path(f"{output_file}.docx")
            document.save(word_path)
            print(f"Word report successfully created: {word_path}")
