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


_DONE_STATUSES = {"done", "resolved", "closed"}

_TT_COUNTER_PATTERNS: dict[str, re.Pattern[str]] = {
    # Accept counters written as:
    # - "TT_tdev_APIs = 2" (any spaces around "=")
    # - "TT_tdev_APIs: 2"
    # - "TT_tdev_APIs - 2"
    # - "TT_tdev_APIs - some explanation = 2"
    "TT_tdev_APIs": re.compile(r"\bTT_tdev_APIs\b[^\n\r]*?(?:[:=]\s*|\s-\s*)(\d+)", re.IGNORECASE),
    "TT_tested_APIs": re.compile(r"\bTT_tested_APIs\b[^\n\r]*?(?:[:=]\s*|\s-\s*)(\d+)", re.IGNORECASE),
    "TT_tested_perf": re.compile(r"\bTT_tested_perf\b[^\n\r]*?(?:[:=]\s*|\s-\s*)(\d+)", re.IGNORECASE),
    "TT_tdev_perf": re.compile(r"\bTT_tdev_perf\b[^\n\r]*?(?:[:=]\s*|\s-\s*)(\d+)", re.IGNORECASE),
}

_OUTSTANDING_CONTRIBUTION_PATTERN = re.compile(r"outstanding[_ -]?contribution", re.IGNORECASE)


def _normalize_text(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    return " ".join(str(value).strip().split()).casefold()


def _jira_user_identifier(user: Any | None) -> str:
    """
    Jira user identifiers differ between Server/DC and Cloud.

    Prefer the legacy username when available, then fall back to other stable IDs.
    """
    if not user:
        return ""
    for attr in ("name", "key", "accountId"):
        candidate = getattr(user, attr, None)
        if candidate:
            return str(candidate)
    return ""


def _resolved_mask(issues_df: pd.DataFrame) -> pd.Series:
    resolved_value = issues_df.get("Resolved")
    if resolved_value is None:
        resolved_value = pd.Series([""] * len(issues_df), index=issues_df.index)
    resolved_by_date = (
        resolved_value.fillna("").astype(str).str.strip().ne("")
    )

    status_value = issues_df.get("Status")
    if status_value is None:
        status_value = pd.Series([""] * len(issues_df), index=issues_df.index)
    status_norm = status_value.fillna("").astype(str).map(_normalize_text)
    resolved_by_status = status_norm.isin(_DONE_STATUSES)

    return resolved_by_date | resolved_by_status


def _countable_mask(issues_df: pd.DataFrame) -> pd.Series:
    resolution_value = issues_df.get("Resolution")
    if resolution_value is None:
        return pd.Series([True] * len(issues_df), index=issues_df.index)

    resolution_norm = resolution_value.fillna("").astype(str).map(_normalize_text)
    excluded = (
        resolution_norm.str.contains(r"won['’]t do", regex=True, na=False)
        | resolution_norm.str.contains("wont do", regex=False, na=False)
        | resolution_norm.str.contains("invalid", regex=False, na=False)
    )
    return ~excluded


def _extract_tt_counters(text: Any) -> dict[str, int]:
    if text is None:
        return {key: 0 for key in _TT_COUNTER_PATTERNS}
    try:
        if pd.isna(text):
            return {key: 0 for key in _TT_COUNTER_PATTERNS}
    except Exception:
        pass

    payload = str(text)
    payload = (
        payload.replace("\u00a0", " ")
        .replace("\uff1a", ":")  # fullwidth colon
        .replace("\uff1d", "=")  # fullwidth equals
        .replace("\u2013", "-")  # en-dash
        .replace("\u2014", "-")  # em-dash
        .replace("\u2212", "-")  # minus sign
    )
    payload = re.sub(r"\s+", " ", payload)
    counters: dict[str, int] = {}
    for key, pattern in _TT_COUNTER_PATTERNS.items():
        matches = pattern.findall(payload)
        counters[key] = sum(int(match) for match in matches) if matches else 0
    return counters


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
        assignee_name = _jira_user_identifier(issue.fields.assignee)
        reporter = issue.fields.reporter.displayName if issue.fields.reporter else ""
        reporter_name = _jira_user_identifier(issue.fields.reporter)

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
    member_role_norm = members_df.get(
        "role", pd.Series([""] * len(members_df), index=members_df.index)
    ).map(_normalize_text)
    engineers = members_df[member_role_norm.isin({"engineer", "huawei"})]

    jira_column = next(
        (
            col
            for col in members_df.columns
            if _normalize_text(col) in {"jira", "jira username", "jira_user", "jira account"}
        ),
        None,
    )

    assignee_username_value = issues_df.get(
        "Assignee_Username", pd.Series([""] * len(issues_df), index=issues_df.index)
    )
    assignee_username_norm = assignee_username_value.fillna("").astype(str).map(_normalize_text)

    assignee_value = issues_df.get("Assignee", pd.Series([""] * len(issues_df), index=issues_df.index))
    assignee_name_norm = assignee_value.fillna("").astype(str).map(_normalize_text)
    status_resolved_mask = _resolved_mask(issues_df)
    countable_mask = _countable_mask(issues_df)
    labels_value = issues_df.get("Labels")
    labels_norm = (
        labels_value.fillna("").astype(str)
        if labels_value is not None
        else pd.Series([""] * len(issues_df), index=issues_df.index)
    )

    for _, engineer in engineers.iterrows():
        username = str(engineer.get("username", "")).strip()
        username_norm = _normalize_text(username)
        name = engineer.get("name", "")
        name_norm = _normalize_text(name)

        jira_username_raw = engineer.get(jira_column, "") if jira_column else ""
        jira_username = _first_value([jira_username_raw, username]) or ""
        jira_username_norm = _normalize_text(jira_username)

        identifier_candidates = {jira_username_norm, username_norm} - {""}

        user_mask = assignee_username_norm.isin(identifier_candidates)
        if name_norm:
            user_mask = user_mask | (assignee_name_norm == name_norm)

        user_issues = issues_df[user_mask & countable_mask]
        resolved_issues = user_issues[status_resolved_mask.loc[user_issues.index]]

        code_volume = 0
        if not code_volume_df.empty and "username" in code_volume_df.columns:
            cv_row = code_volume_df[code_volume_df["username"].fillna("").astype(str).map(_normalize_text) == username_norm]
            if not cv_row.empty:
                code_volume = cv_row.iloc[0].get("code_volume", 0)

        bugs = resolved_issues[resolved_issues["Type"] == "Bug"].shape[0]
        features = resolved_issues[
            resolved_issues["Type"].isin(["Story", "New Feature", "Improvement"])
        ].shape[0]
        code_quality = bugs / features if features > 0 else 0

        doc_tasks = labels_norm.loc[resolved_issues.index].str.contains("documentation", case=False, na=False).sum()

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
    member_role_norm = members_df.get(
        "role", pd.Series([""] * len(members_df), index=members_df.index)
    ).map(_normalize_text)
    qa_engineers = members_df[member_role_norm.isin({"qa engineer", "test engineer", "tester", "qa"})]

    jira_column = next(
        (
            col
            for col in members_df.columns
            if _normalize_text(col) in {"jira", "jira username", "jira_user", "jira account"}
        ),
        None,
    )

    assignee_username_value = issues_df.get(
        "Assignee_Username", pd.Series([""] * len(issues_df), index=issues_df.index)
    )
    assignee_username_norm = assignee_username_value.fillna("").astype(str).map(_normalize_text)

    assignee_value = issues_df.get("Assignee", pd.Series([""] * len(issues_df), index=issues_df.index))
    assignee_name_norm = assignee_value.fillna("").astype(str).map(_normalize_text)

    reporter_username_value = issues_df.get(
        "Reporter_Username", pd.Series([""] * len(issues_df), index=issues_df.index)
    )
    reporter_username_norm = reporter_username_value.fillna("").astype(str).map(_normalize_text)

    reporter_value = issues_df.get("Reporter", pd.Series([""] * len(issues_df), index=issues_df.index))
    reporter_name_norm = reporter_value.fillna("").astype(str).map(_normalize_text)
    status_resolved_mask = _resolved_mask(issues_df)
    countable_mask = _countable_mask(issues_df)
    labels_value = issues_df.get("Labels")
    labels_norm = (
        labels_value.fillna("").astype(str)
        if labels_value is not None
        else pd.Series([""] * len(issues_df), index=issues_df.index)
    )
    summary_value = issues_df.get("Summary", pd.Series([""] * len(issues_df), index=issues_df.index))
    summary_norm = summary_value.fillna("").astype(str)

    for _, qa in qa_engineers.iterrows():
        username = str(qa.get("username", "")).strip()
        username_norm = _normalize_text(username)
        name = qa.get("name", "")
        name_norm = _normalize_text(name)

        jira_username_raw = qa.get(jira_column, "") if jira_column else ""
        jira_username = _first_value([jira_username_raw, username]) or ""
        jira_username_norm = _normalize_text(jira_username)
        identifier_candidates = {jira_username_norm, username_norm} - {""}

        user_mask = assignee_username_norm.isin(identifier_candidates)
        if name_norm:
            user_mask = user_mask | (assignee_name_norm == name_norm)

        user_issues = issues_df[user_mask & countable_mask]
        resolved_issues = user_issues[status_resolved_mask.loc[user_issues.index]]
        tt_totals = {key: 0 for key in _TT_COUNTER_PATTERNS}
        for payload in resolved_issues.get("Comments", pd.Series([], dtype=object)).fillna("").astype(str):
            counters = _extract_tt_counters(payload)
            for key in tt_totals:
                tt_totals[key] += counters.get(key, 0)

        test_scenarios = tt_totals["TT_tdev_APIs"] + tt_totals["TT_tested_APIs"]
        perf_tasks = tt_totals["TT_tested_perf"] + tt_totals["TT_tdev_perf"]

        reporter_mask = reporter_username_norm.isin(identifier_candidates)
        if name_norm:
            reporter_mask = reporter_mask | (reporter_name_norm == name_norm)
        bugs_created = issues_df[(reporter_mask & countable_mask) & (issues_df["Type"] == "Bug")].shape[0]

        doc_tasks = labels_norm.loc[resolved_issues.index].str.contains("documentation", case=False, na=False).sum()
        outstanding_tasks = (
            labels_norm.loc[resolved_issues.index].str.contains(
                _OUTSTANDING_CONTRIBUTION_PATTERN, regex=True, na=False
            )
            | summary_norm.loc[resolved_issues.index].str.contains(
                _OUTSTANDING_CONTRIBUTION_PATTERN, regex=True, na=False
            )
        ).sum()

        metrics.append(
            {
                "Name": name,
                "Role": "QA Engineer",
                "Test_Scenarios_Executed": test_scenarios,
                "Issues_Raised": bugs_created,
                "Performance_Benchmarks": perf_tasks,
                "Documentation_Tasks": doc_tasks,
                "TT_tdev_APIs": tt_totals["TT_tdev_APIs"],
                "TT_tested_APIs": tt_totals["TT_tested_APIs"],
                "TT_tested_perf": tt_totals["TT_tested_perf"],
                "TT_tdev_perf": tt_totals["TT_tdev_perf"],
                "Outstanding_Contribution": int(outstanding_tasks),
                "Total_Resolved_Issues": resolved_issues.shape[0],
            }
        )

    return pd.DataFrame(metrics)


def calculate_pm_metrics(
    issues_df: pd.DataFrame, members_df: pd.DataFrame, jira, jql_query: str
) -> pd.DataFrame:
    """Calculate metrics for Project Managers."""
    metrics: list[dict[str, Any]] = []
    member_role_norm = members_df.get(
        "role", pd.Series([""] * len(members_df), index=members_df.index)
    ).map(_normalize_text)
    pms = members_df[member_role_norm.isin({"project manager", "pm"})]

    epic_count = issues_df[issues_df["Type"] == "Epic"].shape[0]
    resolved_issues_mask = _resolved_mask(issues_df)
    countable_mask = _countable_mask(issues_df)
    resolved_countable_mask = resolved_issues_mask & countable_mask

    for _, pm in pms.iterrows():
        name = pm["name"]

        total_closed = int(resolved_countable_mask.sum())

        labels_value = issues_df.get("Labels")
        labels_norm = (
            labels_value.fillna("").astype(str)
            if labels_value is not None
            else pd.Series([""] * len(issues_df), index=issues_df.index)
        )
        doc_tasks = labels_norm[resolved_countable_mask].str.contains("documentation", case=False, na=False).sum()

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
        try:
            if pd.isna(value):
                continue
        except Exception:
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
