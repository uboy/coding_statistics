"""
Jira comprehensive report - migrated from legacy jira_ranking_report.py.

Generates a multi-sheet Excel workbook:
- Issues (detailed issue export including description/comments)
- Links (URLs extracted from descriptions/comments)
- Engineer/QA/PM performance sheets (requires members.xlsx)
"""

from __future__ import annotations

import logging
import os
import re
from configparser import ConfigParser
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
from pandas.api.types import is_object_dtype, is_string_dtype
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Alignment, Font, PatternFill

from ..sources.jira import JiraSource
from . import registry

logger = logging.getLogger(__name__)


def build_jql_query(params: dict[str, Any]) -> str:
    """Build JQL query based on provided parameters."""
    if params.get("jql"):
        return str(params["jql"])

    conditions: list[str] = []

    project = params.get("project")
    if project:
        conditions.append(f"project = {project}")

    start_date = params.get("start_date")
    end_date = params.get("end_date")
    if start_date and end_date:
        conditions.append(f"resolved >= '{start_date}' AND resolved <= '{end_date}'")

    version = params.get("version")
    if version:
        conditions.append(f"fixVersion = '{version}'")

    epic = params.get("epic")
    if epic:
        conditions.append(f"'Epic Link' = {epic}")

    if not conditions:
        raise ValueError("Must specify at least one of: project+dates, version, epic, or jql")

    return " AND ".join(conditions) + " ORDER BY created DESC"


def extract_urls_from_text(text: str | None) -> list[str]:
    """Extract all URLs from text."""
    if not text:
        return []
    url_pattern = r'https?://[^\s<>"{}|\\^`\[\]]+'
    return re.findall(url_pattern, text)


def fetch_jira_data(jira, jql_query: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Fetch Jira issues with all details including comments.

    Returns:
        (issues_df, links_df)
    """
    start_at = 0
    max_results = 100
    all_issues: list[Any] = []

    logger.info("Executing JQL: %s", jql_query)

    while True:
        issues = jira.search_issues(
            jql_query,
            startAt=start_at,
            maxResults=max_results,
            fields=[
                "key",
                "summary",
                "assignee",
                "reporter",
                "resolutiondate",
                "created",
                "updated",
                "description",
                "comment",
                "labels",
                "priority",
                "status",
                "resolution",
                "issuetype",
                "timeestimate",
                "timespent",
                "timeoriginalestimate",
                "customfield_10000",  # Epic Link
            ],
            expand="changelog",
        )

        all_issues.extend(issues)

        if len(issues) < max_results:
            break
        start_at += max_results

    logger.info("Fetched %s issues", len(all_issues))

    data: list[dict[str, Any]] = []
    all_links: list[dict[str, str]] = []

    for issue in all_issues:
        key = issue.key
        summary = issue.fields.summary
        assignee = issue.fields.assignee.displayName if issue.fields.assignee else "Unassigned"
        assignee_name = issue.fields.assignee.name if issue.fields.assignee else ""
        reporter = issue.fields.reporter.displayName if issue.fields.reporter else ""
        reporter_name = issue.fields.reporter.name if issue.fields.reporter else ""

        created = issue.fields.created[:10] if issue.fields.created else ""
        resolved = issue.fields.resolutiondate[:10] if issue.fields.resolutiondate else ""

        original_estimate = issue.fields.timeoriginalestimate / 3600 if issue.fields.timeoriginalestimate else 0
        time_spent = issue.fields.timespent / 3600 if issue.fields.timespent else 0
        remaining = issue.fields.timeestimate / 3600 if issue.fields.timeestimate else 0

        description = issue.fields.description or ""

        for link in extract_urls_from_text(description):
            all_links.append({"Issue_Key": key, "Source": "Description", "URL": link})

        comments: list[str] = []
        if hasattr(issue.fields, "comment") and issue.fields.comment.comments:
            for comment in issue.fields.comment.comments:
                comment_text = comment.body
                comment_author = comment.author.displayName if comment.author else "Unknown"
                comment_created = comment.created[:10] if comment.created else ""
                comments.append(f"[{comment_created}] {comment_author}: {comment_text}")

                for link in extract_urls_from_text(comment_text):
                    all_links.append(
                        {
                            "Issue_Key": key,
                            "Source": f"Comment by {comment_author}",
                            "URL": link,
                        }
                    )

        all_comments = "\n---\n".join(comments)

        labels = ", ".join(issue.fields.labels) if issue.fields.labels else ""

        priority = issue.fields.priority.name if issue.fields.priority else ""
        status = issue.fields.status.name if issue.fields.status else ""
        resolution = issue.fields.resolution.name if issue.fields.resolution else ""
        issue_type = issue.fields.issuetype.name if issue.fields.issuetype else ""
        epic_link = getattr(issue.fields, "customfield_10000", "")

        data.append(
            {
                "Issue_Key": key,
                "Summary": summary,
                "Type": issue_type,
                "Status": status,
                "Resolution": resolution,
                "Priority": priority,
                "Assignee": assignee,
                "Assignee_Username": assignee_name,
                "Reporter": reporter,
                "Reporter_Username": reporter_name,
                "Created": created,
                "Resolved": resolved,
                "Original_Estimate_Hours": original_estimate,
                "Time_Spent_Hours": time_spent,
                "Remaining_Hours": remaining,
                "Description": description,
                "Comments": all_comments,
                "Labels": labels,
                "Epic_Link": epic_link,
            }
        )

    return pd.DataFrame(data), pd.DataFrame(all_links)


def read_member_list(member_list_file: str) -> pd.DataFrame:
    """Read team member details from Excel file."""
    if not os.path.exists(member_list_file):
        logger.warning("Member list file %r not found", member_list_file)
        return pd.DataFrame(columns=["name", "email", "username", "role"])

    df = pd.read_excel(member_list_file)
    required_columns = ["name", "username", "role"]
    for col in required_columns:
        if col not in df.columns:
            raise ValueError(f"Member list file must contain '{col}' column")
    return df


def read_code_volume(code_volume_file: str | None) -> pd.DataFrame:
    """Read code volume data from Excel file."""
    if not code_volume_file or not os.path.exists(code_volume_file):
        return pd.DataFrame(columns=["username", "code_volume"])
    return pd.read_excel(code_volume_file)


def calculate_engineer_metrics(
    issues_df: pd.DataFrame, members_df: pd.DataFrame, code_volume_df: pd.DataFrame
) -> pd.DataFrame:
    """Calculate metrics for Engineers."""
    metrics: list[dict[str, Any]] = []
    engineers = members_df[members_df["role"] == "Engineer"]

    for _, engineer in engineers.iterrows():
        username = str(engineer["username"]).lower()
        name = engineer["name"]

        user_issues = issues_df[issues_df["Assignee_Username"].str.lower() == username]
        resolved_issues = user_issues[user_issues["Status"].isin(["Done", "Resolved", "Closed"])]

        code_volume = 0
        if not code_volume_df.empty and "username" in code_volume_df.columns:
            cv_row = code_volume_df[code_volume_df["username"].str.lower() == username]
            if not cv_row.empty:
                code_volume = cv_row.iloc[0].get("code_volume", 0)

        bugs = resolved_issues[resolved_issues["Type"] == "Bug"].shape[0]
        features = resolved_issues[
            resolved_issues["Type"].isin(["Story", "New Feature", "Improvement"])
        ].shape[0]
        code_quality = bugs / features if features > 0 else 0

        doc_tasks = resolved_issues[
            resolved_issues["Labels"].str.contains("documentation", case=False, na=False)
        ].shape[0]

        metrics.append(
            {
                "Name": name,
                "Role": "Engineer",
                "Code_Volume": code_volume,
                "Code_Quality_Score": round(1 / (1 + code_quality), 2) if features > 0 else 1.0,
                "Bugs": bugs,
                "Features": features,
                "Documentation_Tasks": doc_tasks,
                "Outstanding_Contribution": 0,
                "Assistance_Provided": 0,
                "Total_Resolved_Issues": resolved_issues.shape[0],
            }
        )

    return pd.DataFrame(metrics)


def calculate_qa_metrics(issues_df: pd.DataFrame, members_df: pd.DataFrame) -> pd.DataFrame:
    """Calculate metrics for QA Engineers."""
    metrics: list[dict[str, Any]] = []
    qa_engineers = members_df[members_df["role"] == "QA Engineer"]

    for _, qa in qa_engineers.iterrows():
        username = str(qa["username"]).lower()
        name = qa["name"]

        user_issues = issues_df[issues_df["Assignee_Username"].str.lower() == username]
        resolved_issues = user_issues[user_issues["Status"].isin(["Done", "Resolved", "Closed"])]
        test_scenarios = resolved_issues[resolved_issues["Type"].isin(["Test", "Task"])].shape[0]

        bugs_created = issues_df[
            (issues_df["Reporter_Username"].str.lower() == username) & (issues_df["Type"] == "Bug")
        ].shape[0]

        perf_tasks = resolved_issues[
            resolved_issues["Labels"].str.contains("arkoala_perf", case=False, na=False)
        ].shape[0]

        metrics.append(
            {
                "Name": name,
                "Role": "QA Engineer",
                "Test_Scenarios_Executed": test_scenarios,
                "Issues_Raised": bugs_created,
                "Performance_Benchmarks": perf_tasks,
                "Total_Resolved_Issues": resolved_issues.shape[0],
            }
        )

    return pd.DataFrame(metrics)


def calculate_pm_metrics(
    issues_df: pd.DataFrame, members_df: pd.DataFrame, jira, jql_query: str
) -> pd.DataFrame:
    """Calculate metrics for Project Managers."""
    metrics: list[dict[str, Any]] = []
    pms = members_df[members_df["role"] == "Project Manager"]

    epic_count = issues_df[issues_df["Type"] == "Epic"].shape[0]

    for _, pm in pms.iterrows():
        username = str(pm["username"]).lower()
        name = pm["name"]

        total_closed = issues_df[issues_df["Status"].isin(["Done", "Resolved", "Closed"])].shape[0]

        doc_tasks = issues_df[
            issues_df["Status"].isin(["Done", "Resolved", "Closed"])
            & issues_df["Labels"].str.contains("documentation", case=False, na=False)
        ].shape[0]

        metrics.append(
            {
                "Name": name,
                "Role": "Project Manager",
                "Epics_Created": epic_count,
                "Total_Closed_Tasks": total_closed,
                "Documentation_Tasks": doc_tasks,
            }
        )

    return pd.DataFrame(metrics)


def export_to_excel(
    issues_df: pd.DataFrame,
    links_df: pd.DataFrame,
    engineer_metrics: pd.DataFrame,
    qa_metrics: pd.DataFrame,
    pm_metrics: pd.DataFrame,
    output_file: str | Path,
) -> None:
    """Export all data to Excel file with multiple sheets."""
    issues_df = _sanitize_dataframe_for_excel(issues_df)
    links_df = _sanitize_dataframe_for_excel(links_df)
    engineer_metrics = _sanitize_dataframe_for_excel(engineer_metrics)
    qa_metrics = _sanitize_dataframe_for_excel(qa_metrics)
    pm_metrics = _sanitize_dataframe_for_excel(pm_metrics)

    output_path = Path(output_file)
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        issues_df.to_excel(writer, sheet_name="Issues", index=False)

        if not links_df.empty:
            links_df.to_excel(writer, sheet_name="Links", index=False)

        if not engineer_metrics.empty:
            engineer_metrics.to_excel(writer, sheet_name="Engineer_Performance", index=False)

        if not qa_metrics.empty:
            qa_metrics.to_excel(writer, sheet_name="QA_Performance", index=False)

        if not pm_metrics.empty:
            pm_metrics.to_excel(writer, sheet_name="PM_Performance", index=False)

        workbook = writer.book
        for sheet_name in workbook.sheetnames:
            worksheet = workbook[sheet_name]

            for cell in worksheet[1]:
                cell.font = Font(bold=True)
                cell.fill = PatternFill(start_color="CCE5FF", end_color="CCE5FF", fill_type="solid")
                cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

            for column in worksheet.columns:
                max_length = 0
                column_letter = column[0].column_letter
                for cell in column:
                    try:
                        max_length = max(max_length, len(str(cell.value)))
                    except Exception:
                        continue
                worksheet.column_dimensions[column_letter].width = min(max_length + 2, 50)

    logger.info("Excel report created: %s", output_path)


def _sanitize_dataframe_for_excel(df: pd.DataFrame) -> pd.DataFrame:
    """
    Strip illegal control characters that cause openpyxl IllegalCharacterError.
    """
    if df.empty:
        return df
    result = df.copy()
    for column in result.columns:
        series = result[column]
        if not (is_object_dtype(series.dtype) or is_string_dtype(series.dtype)):
            continue
        result[column] = series.map(_sanitize_excel_value)
    return result


def _sanitize_excel_value(value: Any) -> Any:
    if isinstance(value, str):
        return ILLEGAL_CHARACTERS_RE.sub("", value)
    return value


def _first_value(values: list[str | None]) -> str | None:
    for value in values:
        if value is None:
            continue
        normalized = str(value).strip()
        if normalized:
            return normalized
    return None


def _extra_param(extra_params: dict[str, Any], *names: str) -> str | None:
    return _first_value([extra_params.get(name) for name in names])


@registry.register
class JiraComprehensiveReport:
    name = "jira_comprehensive"

    def run(
        self,
        dataset: dict,
        config: ConfigParser,
        output_formats: list[str],
        extra_params: dict | None = None,
    ) -> None:
        extra_params = extra_params or {}

        if "excel" not in output_formats:
            logger.warning("jira_comprehensive supports only Excel output. Skipping.")
            return

        params: dict[str, Any] = {}
        params["project"] = _extra_param(extra_params, "project")
        params["start_date"] = _extra_param(extra_params, "start_date", "start-date", "start")
        params["end_date"] = _extra_param(extra_params, "end_date", "end-date", "end")
        params["version"] = _extra_param(extra_params, "version")
        params["epic"] = _extra_param(extra_params, "epic")
        params["jql"] = _extra_param(extra_params, "jql")
        params["member_list_file"] = _extra_param(
            extra_params, "member_list_file", "member-list-file"
        ) or "members.xlsx"
        params["code_volume_file"] = _extra_param(
            extra_params, "code_volume_file", "code-volume-file"
        )

        jql_query = build_jql_query(params)

        jira_source = JiraSource(config["jira"])
        jira = jira_source.jira

        issues_df, links_df = fetch_jira_data(jira, jql_query)
        if issues_df.empty:
            logger.warning("No issues found matching the query.")
            return

        members_df = read_member_list(params["member_list_file"])
        code_volume_df = read_code_volume(params["code_volume_file"])

        engineer_metrics = pd.DataFrame()
        qa_metrics = pd.DataFrame()
        pm_metrics = pd.DataFrame()

        if not members_df.empty:
            engineer_metrics = calculate_engineer_metrics(issues_df, members_df, code_volume_df)
            qa_metrics = calculate_qa_metrics(issues_df, members_df)
            pm_metrics = calculate_pm_metrics(issues_df, members_df, jira, jql_query)
        else:
            logger.warning("No member list found, skipping team performance calculations.")

        output_dir = _extra_param(extra_params, "output_dir") or config.get(
            "reporting", "output_dir", fallback="reports"
        )
        output_base = Path(str(output_dir))
        output_base.mkdir(parents=True, exist_ok=True)

        output_name = _extra_param(extra_params, "output", "output_file")
        if output_name:
            output_path = Path(output_name)
            if not output_path.is_absolute():
                output_path = output_base / output_path
            if output_path.suffix.lower() != ".xlsx":
                output_path = output_path.with_suffix(".xlsx")
        else:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = output_base / f"jira_comprehensive_report_{timestamp}.xlsx"

        export_to_excel(issues_df, links_df, engineer_metrics, qa_metrics, pm_metrics, output_path)

        logger.info("REPORT SUMMARY: issues=%s links=%s", len(issues_df), len(links_df))
