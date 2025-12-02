"""
Jira Epic Progress report - resolved tasks grouped by epics.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
from docx import Document

from ..export.word import _apply_paragraph_style


def generate_epic_report(data: pd.DataFrame) -> list[dict[str, Any]]:
    """
    Generate a summary of resolved tasks grouped by epics.

    Args:
        data: DataFrame with Status, Epic_Link, Epic_Name, Issue_key, Summary columns

    Returns:
        List of dictionaries with Epic name and Tasks list
    """
    epic_data = data[data["Status"] == "Resolved"].dropna(subset=["Epic_Link"])
    grouped = epic_data.groupby("Epic_Link")

    epic_summary = []
    for epic, tasks in grouped:
        task_details = [
            {
                "Task_Key": row["Issue_key"],
                "Task_Summary": row["Summary"]
            }
            for _, row in tasks.iterrows()
        ]
        epic_summary.append({"Epic": tasks.iloc[0]["Epic_Name"], "Tasks": task_details})

    return epic_summary


def add_epic_progress_to_document(
    document: Document,
    epic_summary: list[dict[str, Any]],
    jira_url: str,
) -> None:
    """
    Add Epic Progress section to Word document.

    Args:
        document: Word document to add section to
        epic_summary: List of epic dictionaries from generate_epic_report
        jira_url: Base Jira URL for hyperlinks
    """
    document.add_heading("Epic Progress", level=2)
    if epic_summary:
        for epic in epic_summary:
            document.add_heading(epic["Epic"], level=3)
            for task in epic["Tasks"]:
                paragraph = document.add_paragraph(
                    f"{task['Task_Key']}: {task['Task_Summary']}",
                    style="List Bullet 2"
                )
                _apply_paragraph_style(paragraph.paragraphs, font_name="Calibri (Body)", font_size=10)
    else:
        document.add_paragraph("No resolved tasks for open epics during the specified period.")


def add_resolved_tasks_section(
    document: Document,
    resolved_tasks: pd.DataFrame,
) -> None:
    """
    Add a section to the Word document for resolved tasks, grouped by week and parent tasks.

    Args:
        document: Word document to add section to
        resolved_tasks: DataFrame with Status="Resolved" and Resolution_Date, Week columns
    """
    document.add_heading("Resolved Tasks", level=2)
    if resolved_tasks.empty:
        document.add_paragraph("No resolved tasks during the specified period.")
        return

    # Group tasks by week
    resolved_tasks = resolved_tasks.copy()
    resolved_tasks.loc[:, "Resolution_Week"] = pd.to_datetime(resolved_tasks["Resolution_Date"]).dt.strftime("%G-W%V")

    from datetime import timedelta
    for week, tasks in resolved_tasks.groupby("Resolution_Week"):
        year, week_num = map(int, week.split("-W"))
        week_start = pd.Timestamp.fromisocalendar(year, week_num, 1)
        week_end = week_start + timedelta(days=6)
        week_header = f"Week {week} ({week_start.strftime('%d/%m')} - {week_end.strftime('%d/%m')})"
        document.add_heading(week_header, level=3)

        for _, task in tasks[tasks["Type"] != "Sub-task"].iterrows():
            paragraph = document.add_paragraph(style="Normal")
            document.add_paragraph(f"{task['Issue_key']}: {task['Summary']}", style="List Bullet 2")
            _apply_paragraph_style(paragraph.paragraphs, font_name="Calibri (Body)", font_size=10)

            # List subtasks under parent task
            subtasks = tasks[tasks["Parent_Key"] == task["Issue_key"]]
            for _, subtask in subtasks.iterrows():
                document.add_paragraph(f"{subtask['Issue_key']}: {subtask['Summary']}", style="List Bullet 3")

