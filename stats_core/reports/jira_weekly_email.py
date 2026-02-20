"""
Jira weekly HTML email report with optional Ollama text polishing.
"""

from __future__ import annotations

import difflib
import html
import json
import logging
import re
from configparser import ConfigParser
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import requests
from openpyxl import load_workbook
from openpyxl.utils.datetime import from_excel

from ..sources.jira import JiraSource
from . import registry

logger = logging.getLogger(__name__)


_DONE_VALUES = {"done", "resolved", "closed"}
_REPORT_CLOSED_RESOLUTION_VALUES = {"done", "resolved"}
_IN_PROGRESS_VALUES = {"in progress", "in-progress"}


@dataclass(frozen=True)
class WeekWindow:
    year: int
    week: int
    start: date
    end: date
    key: str


def _bool_value(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _split_csv(value: str | None, default: list[str]) -> list[str]:
    if not value:
        return default
    raw = str(value).strip()
    if len(raw) >= 2 and ((raw[0] == '"' and raw[-1] == '"') or (raw[0] == "'" and raw[-1] == "'")):
        raw = raw[1:-1].strip()
    items: list[str] = []
    for token in raw.split(","):
        cleaned = token.strip()
        if len(cleaned) >= 2 and (
            (cleaned[0] == '"' and cleaned[-1] == '"') or (cleaned[0] == "'" and cleaned[-1] == "'")
        ):
            cleaned = cleaned[1:-1].strip()
        if cleaned:
            items.append(cleaned)
    return [item for item in items if item]


def _normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).strip().split())


def _normalize_html_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _normalize_key(value: Any) -> str:
    return _normalize_text(value).casefold()


def _strip_wrapping_quotes(value: str) -> str:
    cleaned = _normalize_text(value)
    if len(cleaned) >= 2 and ((cleaned[0] == '"' and cleaned[-1] == '"') or (cleaned[0] == "'" and cleaned[-1] == "'")):
        return cleaned[1:-1].strip()
    return cleaned


def _week_key(year: int, week: int) -> str:
    return f"{str(year)[-2:]}\'w{week:02d}"


def resolve_week_window(params: dict[str, Any], now: date | None = None) -> WeekWindow:
    now = now or date.today()
    week_date_value = params.get("week_date") or params.get("date")
    week_value = params.get("week")
    year_value = params.get("year")
    start_value = params.get("start") or params.get("start_date")
    end_value = params.get("end") or params.get("end_date")

    if week_date_value:
        dt = datetime.strptime(str(week_date_value), "%Y-%m-%d").date()
        iso = dt.isocalendar()
        week_start = dt - timedelta(days=dt.weekday())
        week_end = week_start + timedelta(days=6)
        return WeekWindow(
            year=iso.year,
            week=iso.week,
            start=week_start,
            end=week_end,
            key=_week_key(iso.year, iso.week),
        )

    if week_value:
        week_raw = _normalize_text(week_value).replace(" ", "")
        week = 0
        year = now.year

        week_with_year_match = re.fullmatch(r"(?i)(\d{1,2})w(\d{2,4})", week_raw)
        if week_with_year_match:
            week = int(week_with_year_match.group(1))
            year_token = week_with_year_match.group(2)
            if len(year_token) == 2:
                year = 2000 + int(year_token)
            else:
                year = int(year_token)
        else:
            week = int(week_raw)
            year = int(str(year_value)) if year_value is not None else now.year

        week_start = date.fromisocalendar(year, week, 1)
        week_end = week_start + timedelta(days=6)
        return WeekWindow(
            year=year,
            week=week,
            start=week_start,
            end=week_end,
            key=_week_key(year, week),
        )

    if start_value and end_value:
        start_dt = datetime.strptime(str(start_value), "%Y-%m-%d").date()
        end_dt = datetime.strptime(str(end_value), "%Y-%m-%d").date()
        start_iso = start_dt.isocalendar()
        end_iso = end_dt.isocalendar()
        if (start_iso.year, start_iso.week) != (end_iso.year, end_iso.week):
            raise ValueError("start/end must be in the same ISO week for jira_weekly_email.")
        week_start = start_dt - timedelta(days=start_dt.weekday())
        week_end = week_start + timedelta(days=6)
        return WeekWindow(
            year=start_iso.year,
            week=start_iso.week,
            start=week_start,
            end=week_end,
            key=_week_key(start_iso.year, start_iso.week),
        )

    raise ValueError(
        "Provide one selector: week_date=YYYY-MM-DD, or week=<WWwYY|WWwYYYY|WW>, "
        "or start/end in one ISO week."
    )


def _parse_jira_date(value: Any) -> date | None:
    if not value:
        return None
    raw = str(value)
    token = raw.split("T")[0]
    try:
        return datetime.strptime(token, "%Y-%m-%d").date()
    except ValueError:
        return None


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


def _is_finished(status: str, resolution: str) -> bool:
    return _normalize_key(status) in _DONE_VALUES or _normalize_key(resolution) in _DONE_VALUES


def _is_in_progress_status(status: Any) -> bool:
    return _normalize_key(status) in _IN_PROGRESS_VALUES


def _safe_project_key(project: str) -> str:
    normalized = _normalize_text(project)
    if not re.fullmatch(r"[A-Za-z0-9_-]+", normalized):
        raise ValueError("Invalid project key format.")
    return normalized


def _fetch_epic_names(
    jira_source: JiraSource,
    jira,
    all_issues: list[Any],
) -> tuple[dict[str, str], dict[str, str], dict[str, str], dict[str, list[str]], dict[str, dict[str, str]]]:
    issue_epic_map: dict[str, str] = {}
    issue_parent_map: dict[str, str] = {}
    parent_keys_needed: set[str] = set()
    issue_details: dict[str, dict[str, str]] = {}

    for issue in all_issues:
        issue_type = _normalize_key(getattr(getattr(issue.fields, "issuetype", None), "name", ""))
        epic_link = getattr(issue.fields, "customfield_10000", "") or ""
        if not epic_link and issue_type == "epic":
            epic_link = issue.key
        parent = getattr(issue.fields, "parent", None)
        parent_key = parent.key if parent else ""
        issue_epic_map[issue.key] = epic_link
        issue_parent_map[issue.key] = parent_key
        if not epic_link and parent_key:
            parent_keys_needed.add(parent_key)
        issue_details[issue.key] = {
            "summary": _normalize_text(getattr(issue.fields, "summary", "")),
            "status": _normalize_text(getattr(getattr(issue.fields, "status", None), "name", "")),
            "resolution": _normalize_text(getattr(getattr(issue.fields, "resolution", None), "name", "")),
            "labels": [str(label) for label in (getattr(issue.fields, "labels", []) or [])],
        }

    pending_parent_keys = {key for key in parent_keys_needed if key}
    fetched_parent_keys: set[str] = set()
    chunk_size = 50
    while pending_parent_keys:
        chunk = [key for key in list(pending_parent_keys)[:chunk_size] if key not in fetched_parent_keys]
        if not chunk:
            break
        fetched_parent_keys.update(chunk)
        parent_issues = jira.search_issues(
            f"issuekey in ({', '.join(chunk)})",
            maxResults=1000,
            fields=["key", "customfield_10000", "parent", "issuetype", "summary", "status", "resolution", "labels"],
        )
        pending_parent_keys.difference_update(chunk)
        for parent_issue in parent_issues:
            parent_type = _normalize_key(getattr(getattr(parent_issue.fields, "issuetype", None), "name", ""))
            parent_parent = getattr(parent_issue.fields, "parent", None)
            parent_parent_key = parent_parent.key if parent_parent else ""
            parent_epic = getattr(parent_issue.fields, "customfield_10000", "") or ""
            if not parent_epic and parent_type == "epic":
                parent_epic = parent_issue.key

            issue_epic_map[parent_issue.key] = parent_epic
            issue_parent_map[parent_issue.key] = parent_parent_key
            issue_details[parent_issue.key] = {
                "summary": _normalize_text(getattr(parent_issue.fields, "summary", "")),
                "status": _normalize_text(getattr(getattr(parent_issue.fields, "status", None), "name", "")),
                "resolution": _normalize_text(getattr(getattr(parent_issue.fields, "resolution", None), "name", "")),
                "labels": [str(label) for label in (getattr(parent_issue.fields, "labels", []) or [])],
            }
            if not parent_epic and parent_parent_key and parent_parent_key not in fetched_parent_keys:
                pending_parent_keys.add(parent_parent_key)

    def _resolve_epic_for_issue(issue_key: str) -> str:
        visited: set[str] = set()
        current_key = issue_key
        while current_key and current_key not in visited:
            visited.add(current_key)
            epic_key = _normalize_text(issue_epic_map.get(current_key, ""))
            if epic_key:
                return epic_key
            current_key = _normalize_text(issue_parent_map.get(current_key, ""))
        return ""

    for key in list(issue_epic_map.keys()):
        resolved_epic = _resolve_epic_for_issue(key)
        if resolved_epic:
            issue_epic_map[key] = resolved_epic

    epic_keys = list({epic for epic in issue_epic_map.values() if epic})
    epic_names = jira_source.fetch_epic_names(epic_keys)
    epic_labels: dict[str, list[str]] = {}
    if epic_keys:
        chunk_size = 50
        for idx in range(0, len(epic_keys), chunk_size):
            chunk = epic_keys[idx : idx + chunk_size]
            try:
                epic_issues = jira.search_issues(
                    f"issuekey in ({', '.join(chunk)})",
                    maxResults=1000,
                    fields=["key", "labels"],
                )
            except Exception:
                logger.warning("Failed to fetch epic labels for chunk size=%s.", len(chunk))
                continue
            for epic_issue in epic_issues:
                if epic_issue.key not in chunk:
                    continue
                epic_labels[epic_issue.key] = [str(label) for label in (epic_issue.fields.labels or [])]
    return issue_epic_map, issue_parent_map, epic_names, epic_labels, issue_details


def collect_weekly_comment_evidence(
    jira_source: JiraSource,
    project: str,
    week: WeekWindow,
) -> list[dict[str, Any]]:
    jira = jira_source.jira
    project_key = _safe_project_key(project)
    start_value = week.start.strftime("%Y-%m-%d")
    end_exclusive = (week.end + timedelta(days=1)).strftime("%Y-%m-%d")
    jql_query = (
        f"project = {project_key} "
        f"AND updated >= '{start_value}' "
        f"AND updated < '{end_exclusive}' "
        "ORDER BY created DESC"
    )
    logger.info(
        "JIRA QUERY: project=%s week=%s range=[%s..%s] jql=%s fields=%s page_size=%s",
        project,
        week.key,
        start_value,
        week.end.strftime("%Y-%m-%d"),
        jql_query,
        "key,summary,status,resolution,issuetype,labels,priority,customfield_10000,parent,comment",
        100,
    )

    start_at = 0
    max_results = 100
    all_issues: list[Any] = []
    pages = 0
    while True:
        issues = jira.search_issues(
            jql_query,
            startAt=start_at,
            maxResults=max_results,
            fields=[
                "key",
                "summary",
                "status",
                "resolution",
                "issuetype",
                "labels",
                "priority",
                "customfield_10000",
                "parent",
                "comment",
            ],
        )
        pages += 1
        all_issues.extend(issues)
        if len(issues) < max_results:
            break
        start_at += max_results

    if not all_issues:
        logger.info("JIRA FETCH RESULT: project=%s week=%s pages=%s raw_issues=0", project, week.key, pages)
        return []

    issue_epic_map, issue_parent_map, epic_names, epic_labels_map, issue_details = _fetch_epic_names(
        jira_source, jira, all_issues
    )
    summary_map: dict[str, str] = {
        key: _normalize_text((details or {}).get("summary", ""))
        for key, details in issue_details.items()
    }
    status_map: dict[str, str] = {
        key: _normalize_text((details or {}).get("status", ""))
        for key, details in issue_details.items()
    }
    resolution_map: dict[str, str] = {
        key: _normalize_text((details or {}).get("resolution", ""))
        for key, details in issue_details.items()
    }
    labels_map: dict[str, list[str]] = {
        key: [str(label) for label in ((details or {}).get("labels") or [])]
        for key, details in issue_details.items()
    }

    evidence: list[dict[str, Any]] = []
    total_comments_in_week = 0

    for issue in all_issues:
        issue_key = issue.key
        labels = [str(label) for label in (issue.fields.labels or [])]
        priority = issue.fields.priority.name if issue.fields.priority else ""
        status = issue.fields.status.name if issue.fields.status else ""
        resolution = issue.fields.resolution.name if issue.fields.resolution else ""
        issue_type_obj = issue.fields.issuetype if issue.fields.issuetype else None
        issue_type = issue_type_obj.name if issue_type_obj else ""
        issue_is_subtask = bool(getattr(issue_type_obj, "subtask", False))

        epic_link = issue_epic_map.get(issue_key, "")
        parent_key = issue_parent_map.get(issue_key, "")
        if not epic_link and parent_key:
            epic_link = issue_epic_map.get(parent_key, "")
        epic_name = epic_names.get(epic_link, "Unknown Epic") if epic_link else "Unknown Epic"

        comments_in_week_rows: list[tuple[date, int, str]] = []
        comment_block = getattr(getattr(issue.fields, "comment", None), "comments", []) or []
        for comment_idx, comment in enumerate(comment_block):
            created_dt = _parse_jira_date(getattr(comment, "created", ""))
            if not created_dt or not (week.start <= created_dt <= week.end):
                continue
            body_text = _normalize_text(_comment_body_to_text(getattr(comment, "body", "")))
            if body_text:
                comments_in_week_rows.append((created_dt, comment_idx, body_text))

        comments_in_week_rows.sort(key=lambda item: (item[0], item[1]))
        comments_in_week = [item[2] for item in comments_in_week_rows]

        total_comments_in_week += len(comments_in_week)

        parent_finished = False
        if parent_key:
            parent_finished = _is_finished(status_map.get(parent_key, ""), resolution_map.get(parent_key, ""))

        evidence.append(
            {
                "Issue_Key": issue_key,
                "Summary": _normalize_text(issue.fields.summary),
                "Epic_Key": epic_link,
                "Epic_Name": epic_name,
                "Parent_Key": parent_key,
                "Type": issue_type,
                "Status": status,
                "Resolution": resolution,
                "Priority": priority,
                "Labels": labels,
                "Epic_Labels": epic_labels_map.get(epic_link, []),
                "Epic_Labels_Known": epic_link in epic_labels_map,
                "Comments": comments_in_week,
                "Finished": _is_finished(status, resolution),
                "Bug": _normalize_key(issue_type) == "bug",
                "Subtask": issue_is_subtask or _normalize_key(issue_type) in {"sub-task", "subtask"},
                "Parent_Finished": parent_finished,
                "Parent_Summary": summary_map.get(parent_key, ""),
                "Parent_Status": status_map.get(parent_key, ""),
                "Parent_Resolution": resolution_map.get(parent_key, ""),
                "Parent_Labels": labels_map.get(parent_key, []),
            }
        )

    logger.info(
        "JIRA FETCH RESULT: project=%s week=%s pages=%s raw_issues=%s evidence_issues=%s comments_in_week=%s unique_epics=%s",
        project,
        week.key,
        pages,
        len(all_issues),
        len(evidence),
        total_comments_in_week,
        len({item.get('Epic_Key') for item in evidence if _normalize_text(item.get('Epic_Key'))}),
    )
    return evidence

def _first_sentence(text: str) -> str:
    value = _normalize_text(text)
    if not value:
        return ""
    parts = re.split(r"(?<=[.!?])\s+", value)
    sentence = parts[0].strip() if parts else value
    if len(sentence) > 180:
        sentence = sentence[:177].rstrip() + "..."
    if sentence and sentence[-1] not in ".!?":
        sentence += "."
    return sentence


def _comment_hints_joined(comments: Any) -> str:
    values = comments if isinstance(comments, list) else [comments]
    latest_hint = ""
    for value in values:
        hint = _normalize_text(value)
        if not hint:
            continue
        latest_hint = hint
    return latest_hint


def _build_highlight_progress(entry: dict[str, Any], subtasks: list[dict[str, Any]]) -> str:
    if entry.get("Finished"):
        return "Finished this week."

    progress_parts: list[str] = []
    issue_comment = _comment_hints_joined(entry.get("Comments") or [])
    if issue_comment:
        progress_parts.append(issue_comment)

    if not entry.get("Subtask"):
        ordered_subtasks = sorted(
            list(subtasks or []),
            key=lambda item: _normalize_key(item.get("Issue_Key")),
        )
        for subtask in ordered_subtasks:
            subtask_title = _normalize_text(subtask.get("Summary")) or _normalize_text(subtask.get("Issue_Key")) or "Subtask"
            if subtask.get("Finished"):
                progress_parts.append(subtask_title)
                continue

            subtask_comment = _comment_hints_joined(subtask.get("Comments") or [])
            if subtask_comment:
                progress_parts.append(f"{subtask_title}: {subtask_comment}")
            else:
                progress_parts.append(subtask_title)

    if progress_parts:
        return f"Progress: {'; '.join(progress_parts)}"
    return "No progress this week."


def _build_item_text(entry: dict[str, Any], *, mode: str) -> str:
    summary = _normalize_text(entry.get("Summary"))
    issue_key = _normalize_text(entry.get("Issue_Key"))
    comment_hint = _comment_hints_joined(entry.get("Comments") or [])

    if mode == "highlight":
        headline = summary or issue_key or "Task"
        if entry.get("Finished"):
            return f"{headline} - Finished this week."
        if comment_hint:
            return f"{headline} - Progress: {comment_hint}"
        return f"{headline} - No progress this week."

    if mode == "completed":
        return summary or issue_key or "Task"

    if mode == "subtask":
        if summary:
            return summary
        return comment_hint or "Subtask update"

    if mode == "plan":
        return comment_hint

    if mode == "result_progress":
        return summary or issue_key or "Task"

    if mode == "high":
        return summary or comment_hint or "High priority item"

    return comment_hint or summary


def _epic_id(entry: dict[str, Any]) -> str:
    epic_key = _normalize_text(entry.get("Epic_Key"))
    if epic_key:
        return epic_key
    return f"name::{_normalize_text(entry.get('Epic_Name'))}"


def _parse_label_set(value: str | None, default: list[str]) -> set[str]:
    return {_normalize_key(item) for item in _split_csv(value, default)}


def build_report_payload(
    evidence: list[dict[str, Any]],
    week: WeekWindow,
    config: ConfigParser,
    project: str,
    *,
    labels_highlights: set[str],
    labels_report: set[str],
    priority_high_values: set[str],
) -> dict[str, Any]:
    highlights: list[dict[str, str]] = []
    epics: dict[str, dict[str, Any]] = {}
    plans: dict[str, list[dict[str, Any]]] = {}
    plan_index: dict[tuple[str, str], dict[str, Any]] = {}
    subtasks_by_parent: dict[str, list[dict[str, Any]]] = {}
    report_epic_ids: set[str] = set()
    report_all_labels = "@all" in labels_report

    for item in evidence:
        if not item.get("Subtask"):
            continue
        parent_key = _normalize_text(item.get("Parent_Key"))
        if not parent_key:
            continue
        subtasks_by_parent.setdefault(parent_key, []).append(item)

    for entry in evidence:
        # FIX: Exclude low-priority bugs entirely from all processing
        is_bug = bool(entry.get("Bug"))
        priority_key = _normalize_key(entry.get("Priority"))
        if is_bug and priority_key not in priority_high_values:
            continue

        issue_key = _normalize_text(entry.get("Issue_Key"))
        issue_type_key = _normalize_key(entry.get("Type"))
        is_non_bug_task = (not is_bug) and issue_type_key != "epic"
        resolution_key = _normalize_key(entry.get("Resolution"))
        is_in_progress = _is_in_progress_status(entry.get("Status"))
        # Exclude closed issues that are not explicitly Done/Resolved from report sections.
        if entry.get("Finished") and resolution_key not in _REPORT_CLOSED_RESOLUTION_VALUES:
            continue
        labels_norm = {_normalize_key(label) for label in (entry.get("Labels") or [])}
        epic_labels_norm = {_normalize_key(label) for label in (entry.get("Epic_Labels") or [])}
        epic_labels_known = bool(entry.get("Epic_Labels_Known"))
        epic_name = _normalize_text(entry.get("Epic_Name")) or "Unknown Epic"
        epic_key = _normalize_text(entry.get("Epic_Key"))
        epic_identifier = _epic_id(entry)
        issue_report_scope = report_all_labels or bool(labels_norm & labels_report)
        issue_in_report_scope = report_all_labels or bool(epic_labels_norm & labels_report)
        if not issue_in_report_scope and epic_key and not epic_labels_known:
            issue_in_report_scope = bool(labels_norm & labels_report)
        if issue_in_report_scope or issue_report_scope:
            report_epic_ids.add(epic_identifier)

        epic_bucket = epics.setdefault(
            epic_identifier,
            {
                "epic_key": epic_key,
                "epic_name": epic_name,
                "report_items": [],
                "completed_items": [],
                "progress_items": [],
                "parent_subtasks": [],
                "high_priority_items": [],
                "bugs": {"closed": 0, "in_progress": 0},
                "_parent_subtask_map": {},
            },
        )

        if labels_norm & labels_highlights:
            issue_summary = _normalize_text(entry.get("Summary"))
            highlights.append(
                {
                    "issue_key": issue_key,
                    "headline": issue_summary or issue_key or "Task",
                    "comment": _build_highlight_progress(entry, subtasks_by_parent.get(issue_key, [])),
                }
            )

        if entry.get("Bug"):
            # This logic now only runs for high-priority bugs due to the check at the start
            if entry.get("Finished"):
                epic_bucket["bugs"]["closed"] += 1
            else:
                epic_bucket["bugs"]["in_progress"] += 1
        elif entry.get("Finished") and is_non_bug_task:
            if entry.get("Subtask") and _normalize_text(entry.get("Parent_Key")):
                parent_issue_key = _normalize_text(entry.get("Parent_Key"))
                subtask_comment = _comment_hints_joined(entry.get("Comments") or [])
                parent_map = epic_bucket["_parent_subtask_map"]
                parent_group = parent_map.setdefault(
                    parent_issue_key,
                    {
                        "parent_issue_key": parent_issue_key,
                        "parent_text": _normalize_text(entry.get("Parent_Summary"))
                        or _normalize_text(entry.get("Parent_Key"))
                        or "Task",
                        "subtasks": [],
                    },
                )
                parent_group["subtasks"].append(
                    {
                        "issue_key": issue_key,
                        "text": _build_item_text(entry, mode="subtask"),
                        "status": _normalize_text(entry.get("Status")) or _normalize_text(entry.get("Resolution")),
                        "comment": subtask_comment,
                    }
                )
            else:
                completed_item = {
                    "issue_key": issue_key,
                    "text": _build_item_text(entry, mode="completed"),
                    "status": "Finished",
                    "comment": _comment_hints_joined(entry.get("Comments") or []),
                }
                if issue_in_report_scope:
                    epic_bucket["report_items"].append(completed_item)
                else:
                    epic_bucket["completed_items"].append(completed_item)
        elif (
            not entry.get("Finished")
            and is_non_bug_task
            and is_in_progress
        ):
            if entry.get("Subtask"):
                parent_key = _normalize_text(entry.get("Parent_Key"))
                parent_labels_norm = {_normalize_key(label) for label in (entry.get("Parent_Labels") or [])}
                parent_report_scope = report_all_labels or bool(parent_labels_norm & labels_report)
                if parent_key and (parent_report_scope or issue_in_report_scope):
                    report_epic_ids.add(epic_identifier)
                    parent_text = _normalize_text(entry.get("Parent_Summary")) or parent_key
                    subtask_comment = _comment_hints_joined(entry.get("Comments") or [])

                    parent_map = epic_bucket["_parent_subtask_map"]
                    parent_group = parent_map.setdefault(
                        parent_key,
                        {
                            "parent_issue_key": parent_key,
                            "parent_text": parent_text or "Task",
                            "subtasks": [],
                        },
                    )
                    parent_group["subtasks"].append(
                        {
                            "issue_key": issue_key,
                            "text": _normalize_text(entry.get("Summary")) or issue_key,
                            "status": _normalize_text(entry.get("Status")) or _normalize_text(entry.get("Resolution")),
                            "comment": subtask_comment,
                        }
                    )

                    parent_item = plan_index.get((epic_identifier, parent_key))
                    if not parent_item:
                        parent_item = {
                            "issue_key": parent_key,
                            "text": parent_text,
                            "comment": "",
                            "status": "",
                            "subtasks": [],
                        }
                        plans.setdefault(epic_identifier, []).append(parent_item)
                        plan_index[(epic_identifier, parent_key)] = parent_item
                    parent_item["subtasks"].append(
                        {
                            "issue_key": issue_key,
                            "text": _normalize_text(entry.get("Summary")) or issue_key,
                            "status": _normalize_text(entry.get("Status")) or _normalize_text(entry.get("Resolution")),
                            "comment": subtask_comment,
                        }
                    )
            elif issue_report_scope or issue_in_report_scope:
                plan_headline = _normalize_text(entry.get("Summary")) or issue_key
                plan_comment = _build_item_text(entry, mode="plan")
                progress_status = _normalize_text(entry.get("Status")) or "In Progress"
                epic_bucket["progress_items"].append(
                    {
                        "issue_key": issue_key,
                        "text": _build_item_text(entry, mode="result_progress"),
                        "status": progress_status,
                        "comment": plan_comment,
                    }
                )
                existing_item = plan_index.get((epic_identifier, issue_key))
                if existing_item:
                    existing_item["text"] = plan_headline
                    existing_item["comment"] = plan_comment
                    existing_item["status"] = progress_status
                else:
                    parent_plan_item = {
                        "issue_key": issue_key,
                        "text": plan_headline,
                        "comment": plan_comment,
                        "status": progress_status,
                        "subtasks": [],
                    }
                    plans.setdefault(epic_identifier, []).append(parent_plan_item)
                    plan_index[(epic_identifier, issue_key)] = parent_plan_item

        if _normalize_key(entry.get("Priority")) in priority_high_values:
            epic_bucket["high_priority_items"].append(
                {
                    "issue_key": issue_key,
                    "text": _build_item_text(entry, mode="high"),
                }
            )

    epic_entries: list[dict[str, Any]] = []
    for epic_id, epic in epics.items():
        if epic_id not in report_epic_ids:
            continue
        parent_map: dict[str, dict[str, Any]] = epic.pop("_parent_subtask_map", {})
        parent_groups = []
        for _, group in sorted(parent_map.items(), key=lambda item: item[0]):
            group["subtasks"] = sorted(
                list(group.get("subtasks") or []),
                key=lambda item: _normalize_key(item.get("issue_key")),
            )
            parent_groups.append(group)
        epic["parent_subtasks"] = parent_groups
        epic_entries.append(epic)

    if not report_all_labels:
        epic_entries = [epic for epic in epic_entries if _normalize_text(epic.get("epic_key"))]

    epic_entries = sorted(epic_entries, key=lambda item: (_normalize_key(item["epic_name"]), _normalize_key(item["epic_key"])))
    next_week_plans: list[dict[str, Any]] = []
    for epic in epic_entries:
        epic_identifier = epic["epic_key"] if epic["epic_key"] else f"name::{epic['epic_name']}"
        plan_items = plans.get(epic_identifier, [])
        if not plan_items:
            continue
        for plan_item in plan_items:
            subtasks = list(plan_item.get("subtasks") or [])
            if subtasks:
                plan_item["subtasks"] = sorted(
                    subtasks,
                    key=lambda item: _normalize_key(item.get("issue_key")),
                )
        next_week_plans.append(
            {
                "epic_key": epic["epic_key"],
                "epic_name": epic["epic_name"],
                "items": plan_items,
            }
        )

    logger.info(
        "PAYLOAD SUMMARY: project=%s week=%s evidence=%s epics_total=%s epics_in_report=%s highlights=%s report_items=%s completed_items=%s parent_subtasks=%s plans=%s high_priority=%s bugs_closed=%s bugs_in_progress=%s",
        project,
        week.key,
        len(evidence),
        len(epics),
        len(epic_entries),
        len(highlights),
        sum(len(epic.get("report_items") or []) for epic in epic_entries),
        sum(len(epic.get("completed_items") or []) for epic in epic_entries),
        sum(len(epic.get("parent_subtasks") or []) for epic in epic_entries),
        sum(len(item.get("items") or []) for item in next_week_plans),
        sum(len(epic.get("high_priority_items") or []) for epic in epic_entries),
        sum(int((epic.get("bugs") or {}).get("closed") or 0) for epic in epic_entries),
        sum(int((epic.get("bugs") or {}).get("in_progress") or 0) for epic in epic_entries),
    )
    return {
        "meta": {
            "project": project,
            "week_key": week.key,
            "week_start": week.start.strftime("%Y-%m-%d"),
            "week_end": week.end.strftime("%Y-%m-%d"),
        },
        "highlights": highlights,
        "epics": epic_entries,
        "next_week_plans": next_week_plans,
        "vacations": [],
        "titles": {
            "main": config.get("jira_weekly_email", "title_main", fallback="Weekly Report"),
            "highlights": config.get("jira_weekly_email", "chapter_highlights_title", fallback="Highlights"),
            "results": config.get(
                "jira_weekly_email",
                "chapter_results_title",
                fallback="Key Results and Achievements",
            ),
            "plans": config.get("jira_weekly_email", "chapter_next_week_title", fallback="Next Week Plans"),
            "vacations": config.get("jira_weekly_email", "chapter_vacations_title", fallback="Vacations (next 60 days)"),
            "high_priority_subtitle": config.get(
                "jira_weekly_email", "chapter_results_high_priority_subtitle", fallback="High priority items"
            ),
            "bugs_subtitle": config.get(
                "jira_weekly_email", "chapter_results_bugs_subtitle", fallback="Bugs summary"
            ),
            "header_project_info": config.get(
                "jira_weekly_email", "header_project_info_title", fallback="Weekly execution summary"
            ),
            "header_banner_bg_color": config.get(
                "jira_weekly_email", "header_banner_bg_color", fallback="rgb(63,78,0)"
            ),
            "meta_report_period": config.get(
                "jira_weekly_email", "meta_report_period_label", fallback="Report Period"
            ),
            "meta_active_iteration": config.get(
                "jira_weekly_email", "meta_active_iteration_label", fallback="Active iteration"
            ),
            "meta_active_iteration_value": config.get(
                "jira_weekly_email", "meta_active_iteration_value", fallback=""
            ),
            "meta_report_owner": config.get(
                "jira_weekly_email",
                "meta_report_owner_label",
                fallback=config.get("jira_weekly_email", "meta_project_label", fallback="Report Owner"),
            ),
            "meta_report_owner_value": config.get(
                "jira_weekly_email", "meta_report_owner_value", fallback=project
            ),
            "meta_team_member": config.get(
                "jira_weekly_email",
                "meta_team_member_label",
                fallback=config.get("jira_weekly_email", "meta_generated_label", fallback="Team Member"),
            ),
            "meta_team_member_value": config.get(
                "jira_weekly_email", "meta_team_member_value", fallback=""
            ),
            "footer_html": config.get(
                "jira_weekly_email", "footer_html", fallback=""
            ),
        },
    }


def _apply_order_for_items(items: list[dict[str, Any]], order_map: list[str]) -> list[dict[str, Any]]:
    rank = {key: idx for idx, key in enumerate(order_map)}
    return sorted(items, key=lambda item: (rank.get(item.get("issue_key", ""), 10**9), item.get("issue_key", "")))


def apply_previous_order(payload: dict[str, Any], previous_snapshot: dict[str, Any] | None) -> dict[str, Any]:
    if not previous_snapshot:
        return payload

    order = previous_snapshot.get("order") or {}
    epic_order = [str(item) for item in (order.get("epic_order") or [])]
    issue_order_by_epic = order.get("issue_order_by_epic") or {}

    current = dict(payload)
    epics = list(current.get("epics") or [])
    if epic_order:
        epic_rank = {epic_id: idx for idx, epic_id in enumerate(epic_order)}

        def _epic_identifier(epic_entry: dict[str, Any]) -> str:
            epic_key = _normalize_text(epic_entry.get("epic_key"))
            if epic_key:
                return epic_key
            return f"name::{_normalize_text(epic_entry.get('epic_name'))}"

        epics = sorted(
            epics,
            key=lambda item: (
                epic_rank.get(_epic_identifier(item), 10**9),
                _normalize_key(item.get("epic_name")),
            ),
        )

        for epic in epics:
            epic_id = _epic_identifier(epic)
            issue_order = [str(item) for item in (issue_order_by_epic.get(epic_id) or [])]
            if issue_order:
                rank = {key: idx for idx, key in enumerate(issue_order)}
                epic["report_items"] = _apply_order_for_items(list(epic.get("report_items") or []), issue_order)
                epic["completed_items"] = _apply_order_for_items(list(epic.get("completed_items") or []), issue_order)
                epic["progress_items"] = _apply_order_for_items(list(epic.get("progress_items") or []), issue_order)
                epic["high_priority_items"] = _apply_order_for_items(
                    list(epic.get("high_priority_items") or []), issue_order
                )
                parent_subtasks = list(epic.get("parent_subtasks") or [])
                parent_subtasks = sorted(
                    parent_subtasks,
                    key=lambda item: (
                        rank.get(_normalize_text(item.get("parent_issue_key")), 10**9),
                        _normalize_key(item.get("parent_issue_key")),
                    ),
                )
                for group in parent_subtasks:
                    group["subtasks"] = sorted(
                        list(group.get("subtasks") or []),
                        key=lambda item: (
                            rank.get(_normalize_text(item.get("issue_key")), 10**9),
                            _normalize_key(item.get("issue_key")),
                        ),
                    )
                epic["parent_subtasks"] = parent_subtasks

    current["epics"] = epics
    return current


def _collect_text_targets(payload: dict[str, Any]) -> list[tuple[str, str]]:
    targets: list[tuple[str, str]] = []

    # SECTION: Highlights -> only progress/comment (headline/title is never AI-processed)
    for idx, item in enumerate(payload.get("highlights") or []):
        comment = _normalize_text(item.get("comment"))
        if comment:
            targets.append((f"highlights.{idx}.comment", comment))

    # SECTION: Key Results (epics) -> comments from all task levels
    for epic_idx, epic in enumerate(payload.get("epics") or []):
        for section in ("report_items", "completed_items", "progress_items", "high_priority_items"):
            for item_idx, item in enumerate(epic.get(section) or []):
                comment = _normalize_text(item.get("comment"))
                if comment:
                    targets.append((f"epics.{epic_idx}.{section}.{item_idx}.comment", comment))

        for parent_idx, parent_group in enumerate(epic.get("parent_subtasks") or []):
            for subtask_idx, subtask in enumerate(parent_group.get("subtasks") or []):
                comment = _normalize_text(subtask.get("comment"))
                if comment:
                    targets.append(
                        (
                            f"epics.{epic_idx}.parent_subtasks.{parent_idx}.subtasks.{subtask_idx}.comment",
                            comment,
                        )
                    )

    # SECTION: Plans (next_week_plans) -> only comments
    for epic_idx, plan_epic in enumerate(payload.get("next_week_plans") or []):
        for item_idx, item in enumerate(plan_epic.get("items") or []):
            comment = _normalize_text(item.get("comment"))
            if comment:
                targets.append((f"next_week_plans.{epic_idx}.items.{item_idx}.comment", comment))

            for subtask_idx, subtask in enumerate(item.get("subtasks") or []):
                subtask_comment = _normalize_text(subtask.get("comment"))
                if subtask_comment:
                    targets.append(
                        (
                            f"next_week_plans.{epic_idx}.items.{item_idx}.subtasks.{subtask_idx}.comment",
                            subtask_comment,
                        )
                    )
    return targets


def _extract_json_object(text: str) -> dict[str, Any] | None:
    raw = text.strip()
    if not raw:
        return None
    try:
        value = json.loads(raw)
        return value if isinstance(value, dict) else None
    except Exception:
        pass

    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return None
    try:
        value = json.loads(match.group(0))
    except Exception:
        return None
    return value if isinstance(value, dict) else None


def _log_ollama_check_commands(ollama_url: str, model: str, has_api_key: bool) -> None:
    base = ollama_url.rstrip("/")
    logger.error("Ollama API health checks (run in console):")
    logger.error('curl -i "%s/api/tags"', base)
    if has_api_key:
        logger.error('curl -i -H "Authorization: Bearer <OLLAMA_API_KEY>" "%s/api/tags"', base)
        logger.error(
            'curl -i -X POST -H "Content-Type: application/json" -H "Authorization: Bearer <OLLAMA_API_KEY>" "%s/api/generate" -d "{\\"model\\":\\"%s\\",\\"prompt\\":\\"ping\\",\\"stream\\":false}"',
            base,
            model or "<MODEL>",
        )
    else:
        logger.error(
            'curl -i -X POST -H "Content-Type: application/json" "%s/api/generate" -d "{\\"model\\":\\"%s\\",\\"prompt\\":\\"ping\\",\\"stream\\":false}"',
            base,
            model or "<MODEL>",
        )


def _build_rewrite_prompt(targets: list[tuple[str, str]], start_index: int = 1) -> tuple[dict[str, str], str]:
    if not targets:
        return {}, ""

    def _intent_from_path(path: str) -> str:
        if path.startswith("next_week_plans."):
            return "PLAN"
        if path.startswith("highlights."):
            return "HIGHLIGHT"
        return "RESULT"

    prompt_lines = [
        "You are an expert technical writer preparing a formal weekly engineering report for management.",
        "Rewrite each of the following input texts from a developer's raw notes into a polished, professional report entry.",
        "Your task is to convert raw developer notes into a polished summary for a formal engineering report.",
        "Follow these strict rules:",
        "1. Style: Formal, professional, and concise.",
        "2. Language: English.",
        "3. Length: ONE concise sentence. Use a second sentence ONLY if absolutely necessary for clarity. Maximum is 2 sentences.",
        "4. Content and Formatting:",
        "   - For HIGHLIGHT: Rewrite only the progress note for a highlighted task. Task title is handled separately and MUST NOT be repeated in output.",
        "   - For RESULT: Focus on concrete achievements, outcomes, and impact. (Что было сделано и какой результат).",
        "   - For PLAN: Clearly state the next actions or planned work. (Что планируется сделать).",
        "5. Exclusions: REMOVE ALL of the following:",
        "   - Links and URLs (e.g., http://..., www....).",
        "   - Code/repository references (PRs, MRs, commit hashes, file paths, 'see commit', '#123').",
        "   - Jira ticket numbers (e.g., PROJ-123).",
        "   - Conversational filler and noisy prefixes (e.g., 'results:', 'update:', 'details:', 'just a note').",
        "6. Output Format: Return ONLY a valid JSON object mapping the original ID to the rewritten text. Example: {\"t1\":\"Rewritten text for t1.\", \"t2\":\"Rewritten text for t2.\"}",
        "---",
        "Input texts to rewrite:",
    ]
    target_map: dict[str, str] = {}
    for idx, (path, text_value) in enumerate(targets, start=start_index):
        target_id = f"t{idx}"
        target_map[target_id] = path
        prompt_lines.append(f"ID: {target_id} [Intent: {_intent_from_path(path)}] Original: \"{text_value}\"")
    return target_map, "\n".join(prompt_lines)


def _sanitize_ai_text(text: str) -> str:
    cleaned = _normalize_text(text)
    if not cleaned:
        return ""

    # Remove links and repository/file paths regardless of formatting.
    cleaned = re.sub(r"\[[^\]]+\]\([^)]+\)", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"<(?:https?://|www\.|file://)[^>]+>", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"(?:https?://|ftp://|file://|www\.)\S+", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b[a-z0-9.-]+\.[a-z]{2,}(?:/[^\s)\],;]+)+", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\\\\[A-Za-z0-9._$ -]+\\[^\s,;)\]]+", "", cleaned)
    cleaned = re.sub(r"\b[A-Za-z]:\\(?:[^\\/:*?\"<>|\r\n]+\\)*[^\\/:*?\"<>|\s,;)\]]*", "", cleaned)
    cleaned = re.sub(r"(?:(?<=\s)|^)(?:\.\.?/|/)[^\s,;)\]]+", " ", cleaned)
    cleaned = re.sub(r"\b(?:[A-Za-z0-9_.-]+/){1,}[A-Za-z0-9_.-]+\.[A-Za-z0-9]{1,8}\b", "", cleaned)
    cleaned = re.sub(r"\b(?:[A-Za-z0-9_.-]+\\){1,}[A-Za-z0-9_.-]+\.[A-Za-z0-9]{1,8}\b", "", cleaned)
    cleaned = re.sub(r"\b[0-9a-f]{7,40}\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(
        r"(?i)\b(?:pr|mr|pull request|merge request|commit)\b\s*[:#-]?\s*[A-Za-z0-9/_-]*",
        "",
        cleaned,
    )
    cleaned = re.sub(r"(?i)\b(?:results?|status|plan|update|details)\s*:\s*", "", cleaned)
    cleaned = re.sub(r"(?i)\b(?:see|ref(?:erence)?)\s+(?:commit|pr|mr|pull request|merge request|link|url)\b", "", cleaned)
    cleaned = re.sub(
        r"\(\s*(?:https?://|www\.|file://|\\\\|[A-Za-z]:\\|/|\.\./|\./)[^)]*\)",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"\[\s*(?:https?://|www\.|file://|\\\\|[A-Za-z]:\\|/|\.\./|\./)[^\]]*\]",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"\s+([,.;:!?])", r"\1", cleaned)
    cleaned = re.sub(r"[ ]{2,}", " ", cleaned)
    cleaned = _normalize_text(cleaned.strip(" -,:;"))
    if not cleaned:
        return ""

    sentences = [
        part.strip(" -,:;")
        for part in re.split(r"(?<=[.!?])\s+|\s*;\s*", cleaned)
        if part.strip(" -,:;")
    ]
    if not sentences:
        return ""

    limited: list[str] = []
    for sentence in sentences[:2]:
        words = sentence.split()
        if len(words) > 24:
            sentence = " ".join(words[:24]).rstrip(" ,;:-")
            if sentence and sentence[-1] not in ".!?":
                sentence += "."
        limited.append(sentence)
    return _normalize_text(" ".join(limited))


def _apply_rewrite_map(payload: dict[str, Any], target_map: dict[str, str], rewrite_map: dict[str, Any]) -> dict[str, Any]:
    updated = json.loads(json.dumps(payload))
    for target_id, target_path in target_map.items():
        rewritten = _sanitize_ai_text(_normalize_text(rewrite_map.get(target_id)))
        if not rewritten:
            continue
        path_tokens = target_path.split(".")
        cursor: Any = updated
        try:
            for token in path_tokens[:-1]:
                if token.isdigit():
                    cursor = cursor[int(token)]
                else:
                    cursor = cursor[token]
            leaf = path_tokens[-1]
            if leaf.isdigit():
                cursor[int(leaf)] = rewritten
            else:
                cursor[leaf] = rewritten
        except Exception:
            continue
    return updated


def _log_webui_check_commands(api_url: str, model: str, has_api_key: bool, prompt: str = "ping") -> None:
    logger.error("WebUI API health checks (run in console):")
    # Use a truncated prompt to show it's not just 'ping', but avoid massive logs
    display_prompt = prompt if len(prompt) < 200 else (prompt[:200] + "... (truncated)")
    
    json_body = json.dumps({
        "model": model or "<MODEL>",
        "messages": [{"role": "user", "content": display_prompt}],
        "stream": False
    })
    # Escape for shell (simple approach)
    json_body_sh = json_body.replace("'", "'\\''")
    json_body_ps = json_body.replace('"', '\\"')

    if has_api_key:
        logger.error(
            f"curl -i -X POST '{api_url}' -H 'Content-Type: application/json' -H 'Authorization: Bearer <WEBUI_API_KEY>' -d '{json_body_sh}'"
        )
        logger.error(
            f'PowerShell: curl.exe -sS -i -X POST "{api_url}" -H "Content-Type: application/json" -H "Authorization: Bearer <WEBUI_API_KEY>" --data-raw "{json_body_ps}"'
        )
    else:
        logger.error(
            f"curl -i -X POST '{api_url}' -H 'Content-Type: application/json' -d '{json_body_sh}'"
        )
        logger.error(
            f'PowerShell: curl.exe -sS -i -X POST "{api_url}" -H "Content-Type: application/json" --data-raw "{json_body_ps}"'
        )


def _build_webui_api_url(base_url: str, endpoint: str) -> str:
    base = _normalize_text(base_url).rstrip("/")
    ep = _normalize_text(endpoint)
    if not ep:
        return base
    if ep.startswith("http://") or ep.startswith("https://"):
        return ep.rstrip("/")

    ep_path = "/" + ep.lstrip("/")
    if base.endswith(ep_path):
        return base

    parts = urlsplit(base)
    if not parts.scheme or not parts.netloc:
        if not base:
            return ep_path
        return f"{base}/{ep.lstrip('/')}"

    base_path = parts.path.rstrip("/")
    if base_path and ep_path.startswith(base_path + "/"):
        merged_path = ep_path
    elif base_path:
        merged_path = f"{base_path}{ep_path}"
    else:
        merged_path = ep_path
    return urlunsplit((parts.scheme, parts.netloc, merged_path, "", ""))


def rewrite_payload_with_ollama(payload: dict[str, Any], config: ConfigParser, extra_params: dict[str, Any]) -> dict[str, Any]:
    ollama_enabled = _bool_value(
        extra_params.get("ollama_enabled", config.get("ollama", "enabled", fallback="true")),
        True,
    )
    if not ollama_enabled:
        return payload

    model = _normalize_text(extra_params.get("ollama_model") or config.get("ollama", "model", fallback=""))
    if not model:
        logger.warning("Ollama model is not configured; using deterministic text.")
        return payload

    all_targets = _collect_text_targets(payload)
    if not all_targets:
        return payload

    ollama_url = _normalize_text(extra_params.get("ollama_url") or config.get("ollama", "url", fallback="http://localhost:11434"))
    ollama_api_key = _strip_wrapping_quotes(
        _normalize_text(extra_params.get("ollama_api_key") or config.get("ollama", "api_key", fallback=""))
    )
    timeout_seconds = int(
        _normalize_text(extra_params.get("ollama_timeout_seconds") or config.get("ollama", "timeout_seconds", fallback="60"))
        or "60"
    )
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if ollama_api_key:
        headers["Authorization"] = f"Bearer {ollama_api_key}"

    full_rewrite_map: dict[str, Any] = {}
    full_target_map: dict[str, str] = {}
    batch_size = 5

    for i in range(0, len(all_targets), batch_size):
        batch = all_targets[i : i + batch_size]
        target_map, prompt = _build_rewrite_prompt(batch, start_index=i + 1)

        try:
            response = requests.post(
                f"{ollama_url.rstrip('/')}/api/generate",
                headers=headers,
                json={
                    "model": model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "temperature": float(
                            _normalize_text(
                                extra_params.get("ollama_temperature") or config.get("ollama", "temperature", fallback="0.2")
                            )
                            or "0.2"
                        )
                    },
                },
                timeout=timeout_seconds,
            )
            response.raise_for_status()
            response_json = response.json()
            response_text = _normalize_text(response_json.get("response", ""))
            rewrite_map = _extract_json_object(response_text)
            if rewrite_map:
                full_rewrite_map.update(rewrite_map)
                full_target_map.update(target_map)
            else:
                logger.warning("Ollama response is not valid JSON map for batch %s; skipping.", i)
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else "n/a"
            response_text = _normalize_text(exc.response.text if exc.response is not None else "")
            if len(response_text) > 500:
                response_text = response_text[:500] + "..."
            logger.error("Ollama HTTP error: status=%s body=%s", status, response_text or "<empty>")
            _log_ollama_check_commands(ollama_url, model, bool(ollama_api_key))
        except Exception as exc:
            logger.error("Ollama call failed: %s", exc)
            _log_ollama_check_commands(ollama_url, model, bool(ollama_api_key))

    return _apply_rewrite_map(payload, full_target_map, full_rewrite_map)


def rewrite_payload_with_webui(payload: dict[str, Any], config: ConfigParser, extra_params: dict[str, Any]) -> dict[str, Any]:
    webui_section = config["webui"] if config.has_section("webui") else {}
    webui_enabled = _bool_value(
        extra_params.get("webui_enabled")
        or webui_section.get("enabled")
        or config.get("webui", "enabled", fallback="true"),
        True,
    )
    if not webui_enabled:
        return payload

    model = _normalize_text(
        extra_params.get("webui_model")
        or webui_section.get("model")
        or config.get("webui", "model", fallback="")
    )
    if not model:
        logger.warning("WebUI model is not configured; using deterministic text.")
        return payload

    all_targets = _collect_text_targets(payload)
    if not all_targets:
        return payload

    base_url = _normalize_text(
        extra_params.get("webui_url")
        or webui_section.get("url")
        or config.get("webui", "url", fallback="http://localhost:3000")
    )
    endpoint = _normalize_text(
        extra_params.get("webui_endpoint")
        or webui_section.get("endpoint")
        or config.get("webui", "endpoint", fallback="/api/chat/completions")
    )
    api_url = _build_webui_api_url(base_url, endpoint)
    configured_webui_api_key = (
        webui_section.get("api_key")
        if webui_section
        else config.get("webui", "api_key", fallback="")
    )
    webui_api_key = _strip_wrapping_quotes(
        _normalize_text(extra_params.get("webui_api_key") or configured_webui_api_key)
    )
    timeout_seconds = int(
        _normalize_text(
            extra_params.get("webui_timeout_seconds")
            or webui_section.get("timeout_seconds")
            or config.get("webui", "timeout_seconds", fallback="120")
        )
        or "120"
    )
    connect_timeout_seconds = int(
        _normalize_text(
            extra_params.get("webui_connect_timeout_seconds")
            or webui_section.get("connect_timeout_seconds")
            or config.get("webui", "connect_timeout_seconds", fallback="10")
        )
        or "10"
    )
    temperature = float(
        _normalize_text(
            extra_params.get("webui_temperature")
            or webui_section.get("temperature")
            or config.get("webui", "temperature", fallback="0.2")
        )
        or "0.2"
    )
    logger.info(
        "WEBUI CONFIG: enabled=%s url=%s endpoint=%s api_url=%s model=%s api_key_set=%s timeout(connect/read)=%s/%s",
        webui_enabled,
        base_url,
        endpoint,
        api_url,
        model,
        bool(webui_api_key),
        connect_timeout_seconds,
        timeout_seconds,
    )

    headers: dict[str, str] = {"Content-Type": "application/json"}
    if webui_api_key:
        headers["Authorization"] = f"Bearer {webui_api_key}"

    full_rewrite_map: dict[str, Any] = {}
    full_target_map: dict[str, str] = {}
    batch_size = 5

    logger.info("WEBUI REQUEST: api_url=%s total_targets=%s batch_size=%s", api_url, len(all_targets), batch_size)

    for i in range(0, len(all_targets), batch_size):
        batch = all_targets[i : i + batch_size]
        target_map, prompt = _build_rewrite_prompt(batch, start_index=i + 1)

        try:
            response = requests.post(
                api_url,
                headers=headers,
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": "You are an AI assistant that rewrites raw text snippets into formal report entries, returning only a single, valid JSON object with the results."},
                        {"role": "user", "content": prompt},
                    ],
                    "stream": False,
                    "temperature": temperature,
                },
                timeout=(connect_timeout_seconds, timeout_seconds),
            )
            response.raise_for_status()
            response_json = response.json()
            
            response_text = ""
            choices = response_json.get("choices")
            if isinstance(choices, list) and choices:
                first_choice = choices[0] or {}
                message = first_choice.get("message") or {}
                response_text = _normalize_text(message.get("content"))
            if not response_text:
                response_text = _normalize_text(response_json.get("response", ""))

            rewrite_map = _extract_json_object(response_text)
            if rewrite_map:
                full_rewrite_map.update(rewrite_map)
                full_target_map.update(target_map)
            else:
                logger.warning("WebUI response is not valid JSON map for batch %s; skipping.", i)
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else "n/a"
            response_text = _normalize_text(exc.response.text if exc.response is not None else "")
            if len(response_text) > 500:
                response_text = response_text[:500] + "..."
            logger.error("WebUI HTTP error: status=%s body=%s", status, response_text or "<empty>")
            _log_webui_check_commands(api_url, model, bool(webui_api_key), prompt)
        except Exception as exc:
            logger.error("WebUI call failed: %s", exc)
            _log_webui_check_commands(api_url, model, bool(webui_api_key), prompt)

    return _apply_rewrite_map(payload, full_target_map, full_rewrite_map)


def rewrite_payload_with_ai(payload: dict[str, Any], config: ConfigParser, extra_params: dict[str, Any]) -> dict[str, Any]:
    section = config["jira_weekly_email"] if config.has_section("jira_weekly_email") else {}
    provider_raw = _normalize_text(extra_params.get("ai_provider") or section.get("ai_provider"))
    if provider_raw:
        provider = _normalize_key(provider_raw)
    else:
        webui_enabled = _bool_value(
            extra_params.get("webui_enabled", config.get("webui", "enabled", fallback="false")),
            False,
        )
        provider = "webui" if webui_enabled else "ollama"
    if provider == "webui":
        return rewrite_payload_with_webui(payload, config, extra_params)
    if provider not in {"", "ollama"}:
        logger.warning("Unknown ai_provider=%s, falling back to ollama.", provider)
    return rewrite_payload_with_ollama(payload, config, extra_params)


def _snapshot_week_tuple(snapshot: dict[str, Any]) -> tuple[int, int] | None:
    meta = snapshot.get("meta") or {}
    try:
        year = int(meta.get("year"))
        week = int(meta.get("week"))
        return year, week
    except Exception:
        pass

    week_key = _normalize_text(meta.get("week_key"))
    match = re.fullmatch(r"(\d{2,4})'?w(\d{1,2})", week_key, flags=re.IGNORECASE)
    if not match:
        return None
    year_val = int(match.group(1))
    if year_val < 100:
        year_val += 2000
    return year_val, int(match.group(2))


def _previous_week_window(current_week: WeekWindow) -> WeekWindow:
    previous_date = current_week.start - timedelta(days=7)
    previous_iso = previous_date.isocalendar()
    previous_start = previous_date - timedelta(days=previous_date.weekday())
    previous_end = previous_start + timedelta(days=6)
    return WeekWindow(
        year=previous_iso.year,
        week=previous_iso.week,
        start=previous_start,
        end=previous_end,
        key=_week_key(previous_iso.year, previous_iso.week),
    )


def _read_snapshot_json(path: Path) -> dict[str, Any] | None:
    for encoding in ("utf-8", "utf-8-sig"):
        try:
            value = json.loads(path.read_text(encoding=encoding))
        except Exception:
            continue
        if isinstance(value, dict):
            return value
    return None


def load_previous_snapshot(snapshot_dir: Path, project: str, current_week: WeekWindow) -> dict[str, Any] | None:
    previous_week = _previous_week_window(current_week)
    previous_week_compact = previous_week.key.replace("'", "")
    legacy_base = snapshot_dir / "snapshots" / "jira_weekly_email"
    search_dirs = [
        snapshot_dir,
        snapshot_dir / project,
        legacy_base,
        legacy_base / project,
    ]
    previous_candidates = [
        f"jira_weekly_email_{project}_{previous_week.key}.json",
        f"jira_weekly_email_{project}_{previous_week_compact}.json",
        f"{previous_week.key}.json",
        f"{previous_week_compact}.json",
    ]
    previous_candidates_folded = {name.casefold() for name in previous_candidates}
    logger.info(
        "SNAPSHOT SEARCH: previous_week=%s project=%s candidates=%s dirs=%s abs_dirs=%s",
        previous_week.key,
        project,
        ",".join(previous_candidates),
        ",".join(str(path) for path in search_dirs),
        ",".join(str(path.resolve()) for path in search_dirs),
    )

    for directory in search_dirs:
        if not directory.exists():
            continue
        for previous_path in directory.glob("*.json"):
            if previous_path.name.casefold() not in previous_candidates_folded:
                continue
            logger.info("Checking candidate file: %s", previous_path)
            payload = _read_snapshot_json(previous_path)
            if payload is None:
                logger.warning("Failed to read JSON from %s", previous_path)
                continue
            week_tuple = _snapshot_week_tuple(payload)
            target_tuple = (previous_week.year, previous_week.week)
            if week_tuple == target_tuple or week_tuple is None:
                logger.info("Snapshot accepted: %s", previous_path)
                return payload
            logger.warning("Snapshot rejected: %s (week=%s, expected=%s)", previous_path.name, week_tuple, target_tuple)

    if snapshot_dir.exists():
        expected_names = {
            f"jira_weekly_email_{project}_{previous_week.key}.json".casefold(),
            f"jira_weekly_email_{project}_{previous_week_compact}.json".casefold(),
        }
        for candidate_path in snapshot_dir.rglob("*.json"):
            if candidate_path.name.casefold() not in expected_names:
                continue
            payload = _read_snapshot_json(candidate_path)
            if payload is None:
                continue
            week_tuple = _snapshot_week_tuple(payload)
            if week_tuple == (previous_week.year, previous_week.week) or week_tuple is None:
                return payload

    latest_candidate: tuple[tuple[int, int], dict[str, Any]] | None = None
    current_tuple = (current_week.year, current_week.week)
    for directory in search_dirs:
        if not directory.exists():
            continue
        for candidate_path in directory.glob("*.json"):
            payload = _read_snapshot_json(candidate_path)
            if payload is None:
                continue
            week_tuple = _snapshot_week_tuple(payload)
            if not week_tuple or week_tuple >= current_tuple:
                continue
            if latest_candidate is None or week_tuple > latest_candidate[0]:
                latest_candidate = (week_tuple, payload)
    if latest_candidate:
        return latest_candidate[1]
    return None


def _extract_order(payload: dict[str, Any]) -> dict[str, Any]:
    epic_order: list[str] = []
    issue_order_by_epic: dict[str, list[str]] = {}
    for epic in payload.get("epics") or []:
        epic_key = _normalize_text(epic.get("epic_key"))
        epic_name = _normalize_text(epic.get("epic_name"))
        epic_id = epic_key if epic_key else f"name::{epic_name}"
        epic_order.append(epic_id)
        keys: list[str] = []
        for section in ("report_items", "completed_items", "progress_items", "high_priority_items"):
            for item in epic.get(section) or []:
                key = _normalize_text(item.get("issue_key"))
                if key and key not in keys:
                    keys.append(key)
        for group in epic.get("parent_subtasks") or []:
            parent_key = _normalize_text(group.get("parent_issue_key"))
            if parent_key and parent_key not in keys:
                keys.append(parent_key)
            for subtask in group.get("subtasks") or []:
                subtask_key = _normalize_text(subtask.get("issue_key"))
                if subtask_key and subtask_key not in keys:
                    keys.append(subtask_key)
        issue_order_by_epic[epic_id] = keys
    return {"epic_order": epic_order, "issue_order_by_epic": issue_order_by_epic}


def _payload_to_lines(payload: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for item in payload.get("highlights") or []:
        headline = _normalize_text(item.get("headline"))
        comment = _normalize_text(item.get("comment"))
        highlight_line = headline
        if comment:
            highlight_line = f"{headline} - {comment}" if headline else comment
        lines.append(f"HIGHLIGHT {highlight_line} ({item.get('issue_key')})")

    for epic in payload.get("epics") or []:
        lines.append(f"EPIC {epic.get('epic_name')} ({epic.get('epic_key')})")
        for section in ("report_items", "completed_items", "progress_items", "high_priority_items"):
            for item in epic.get(section) or []:
                lines.append(f"{section}:{item.get('issue_key')} {item.get('text')}")
        for group in epic.get("parent_subtasks") or []:
            lines.append(f"parent:{group.get('parent_issue_key')} {group.get('parent_text')}")
            for subtask in group.get("subtasks") or []:
                lines.append(
                    f"subtask:{subtask.get('issue_key')} {subtask.get('text')} status={subtask.get('status')}"
                )
                if _normalize_text(subtask.get("comment")):
                    lines.append(f"subtask_comment:{subtask.get('issue_key')} {subtask.get('comment')}")
        bugs = epic.get("bugs") or {}
        lines.append(f"bugs closed={bugs.get('closed', 0)} in_progress={bugs.get('in_progress', 0)}")

    for epic in payload.get("next_week_plans") or []:
        lines.append(f"PLAN {epic.get('epic_name')} ({epic.get('epic_key')})")
        for item in epic.get("items") or []:
            lines.append(f"plan:{item.get('issue_key')} {item.get('text')}")
            if _normalize_text(item.get("comment")):
                lines.append(f"plan_comment:{item.get('issue_key')} {item.get('comment')}")
            for subtask in item.get("subtasks") or []:
                lines.append(
                    f"plan_subtask:{subtask.get('issue_key')} {subtask.get('text')} status={subtask.get('status')}"
                )
                if _normalize_text(subtask.get("comment")):
                    lines.append(f"plan_subtask_comment:{subtask.get('issue_key')} {subtask.get('comment')}")

    for vacation in payload.get("vacations") or []:
        lines.append(f"VACATION {vacation}")
    return lines


def compute_payload_diff(previous_payload: dict[str, Any] | None, current_payload: dict[str, Any]) -> list[str]:
    if not previous_payload:
        return []
    prev_lines = _payload_to_lines(previous_payload)
    curr_lines = _payload_to_lines(current_payload)
    return list(difflib.ndiff(prev_lines, curr_lines))


def _diff_stats(diff_lines: list[str]) -> dict[str, int]:
    stats = {"added": 0, "removed": 0, "unchanged": 0}
    for line in diff_lines:
        if line.startswith("+ "):
            stats["added"] += 1
        elif line.startswith("- "):
            stats["removed"] += 1
        elif line.startswith("  "):
            stats["unchanged"] += 1
    return stats


def _strikethrough(text: str) -> str:
    return "".join(f"{char}\u0336" for char in text)


def render_console_diff(
    diff_lines: list[str],
    *,
    project: str,
    current_week_key: str,
    previous_week_key: str,
    use_color: bool = True,
) -> None:
    if not diff_lines:
        return

    print(f"[DIFF] {project} {current_week_key} vs {previous_week_key}")
    for line in diff_lines:
        if line.startswith("? "):
            continue
        payload = line[2:]
        if line.startswith("- "):
            old_text = _strikethrough(payload)
            if use_color:
                print(f"  - \x1b[31m{old_text}\x1b[0m")
            else:
                print(f"  - {old_text}")
        elif line.startswith("+ "):
            if use_color:
                print(f"  + \x1b[32m{payload}\x1b[0m")
            else:
                print(f"  + {payload}")
        else:
            if use_color:
                print(f"    \x1b[37m{payload}\x1b[0m")
            else:
                print(f"    {payload}")


def parse_vacations_excel(
    path: Path,
    *,
    sheet: str,
    markers: set[str],
    horizon_start: date,
    horizon_days: int,
) -> list[str]:
    if not path.exists():
        logger.warning("Vacation file not found: %s", path)
        return []

    try:
        workbook = load_workbook(path, data_only=True)
    except Exception as exc:
        logger.error("Vacation file cannot be read: file=%s error=%s", path, exc)
        return []
    if sheet not in workbook.sheetnames:
        logger.warning("Vacation sheet not found: file=%s sheet=%s", path, sheet)
        return []
    ws = workbook[sheet]
    max_col = ws.max_column
    max_row = ws.max_row
    if max_col < 6 or max_row < 5:
        logger.warning("Vacation sheet has unexpected shape: file=%s sheet=%s rows=%s cols=%s", path, sheet, max_row, max_col)
        return []

    marker_set = {_normalize_key(value) for value in markers}
    horizon_end = horizon_start + timedelta(days=horizon_days)
    logger.info(
        "VACATION INPUT: file=%s sheet=%s markers=%s horizon=[%s..%s]",
        path,
        sheet,
        ",".join(sorted(marker_set)),
        horizon_start.strftime("%Y-%m-%d"),
        horizon_end.strftime("%Y-%m-%d"),
    )

    def _coerce_excel_day(raw: Any) -> date | None:
        if isinstance(raw, datetime):
            return raw.date()
        if isinstance(raw, date):
            return raw
        if isinstance(raw, (int, float)):
            try:
                converted = from_excel(raw)
            except Exception:
                return None
            if isinstance(converted, datetime):
                return converted.date()
            if isinstance(converted, date):
                return converted
            return None
        if isinstance(raw, str):
            text = _normalize_text(raw)
            if not text:
                return None
            for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%m/%d/%Y"):
                try:
                    return datetime.strptime(text, fmt).date()
                except ValueError:
                    continue
        return None

    date_by_col: dict[int, date] = {}
    for col in range(6, max_col + 1):
        raw_date = ws.cell(row=3, column=col).value
        parsed_day = _coerce_excel_day(raw_date)
        if parsed_day:
            date_by_col[col] = parsed_day

    vacation_lines: list[str] = []
    marker_hits_total = 0
    marker_hits_in_horizon = 0
    for row in range(5, max_row + 1):
        name = _normalize_text(ws.cell(row=row, column=2).value)
        if not name:
            continue

        selected_dates: list[date] = []
        for col in range(6, max_col + 1):
            marker_raw = ws.cell(row=row, column=col).value
            marker_text = _normalize_key(marker_raw)
            if not marker_text:
                continue
            marker_tokens = [token for token in re.split(r"[,;/\s]+", marker_text) if token]
            if not marker_tokens:
                continue
            if not any(token in marker_set for token in marker_tokens):
                continue
            marker_hits_total += 1
            day = date_by_col.get(col)
            if not day:
                continue
            if horizon_start <= day <= horizon_end:
                selected_dates.append(day)
                marker_hits_in_horizon += 1

        if not selected_dates:
            continue

        selected_dates = sorted(set(selected_dates))
        range_start = selected_dates[0]
        range_end = selected_dates[0]
        for day in selected_dates[1:]:
            if day == range_end + timedelta(days=1):
                range_end = day
                continue
            vacation_lines.append(
                f"{name} vacation {range_start.strftime('%d.%m.%Y')} - {range_end.strftime('%d.%m.%Y')}"
            )
            range_start = day
            range_end = day
        vacation_lines.append(
            f"{name} vacation {range_start.strftime('%d.%m.%Y')} - {range_end.strftime('%d.%m.%Y')}"
        )

    logger.info(
        "VACATION PARSE RESULT: marker_hits=%s marker_hits_in_horizon=%s entries=%s",
        marker_hits_total,
        marker_hits_in_horizon,
        len(vacation_lines),
    )
    return vacation_lines

def render_outlook_html(payload: dict[str, Any]) -> str:
    meta = payload.get("meta") or {}
    titles = payload.get("titles") or {}
    project = html.escape(_normalize_text(meta.get("project")))
    week_key = html.escape(_normalize_text(meta.get("week_key")))

    def _cfg_html(key: str, fallback: str) -> str:
        value = _normalize_html_text(titles.get(key, fallback))
        return value if value else fallback

    report_title = _cfg_html("main", "Weekly Report")
    highlights_title = _cfg_html("highlights", "Highlights")
    results_title = _cfg_html("results", "Key Results and Achievements")
    plans_title = _cfg_html("plans", "Next Week Plans")
    vacations_title = _cfg_html("vacations", "Vacations (next 60 days)")
    high_priority_title = _cfg_html("high_priority_subtitle", "High priority items")
    bugs_title = _cfg_html("bugs_subtitle", "Bugs summary")
    header_project_info = _cfg_html("header_project_info", "Weekly execution summary")
    header_banner_bg_color = html.escape(_normalize_text(titles.get("header_banner_bg_color", "rgb(63,78,0)")))
    meta_report_period = _cfg_html("meta_report_period", "Report Period")
    meta_active_iteration = _cfg_html("meta_active_iteration", "Active iteration")
    meta_active_iteration_value = _cfg_html("meta_active_iteration_value", "")
    meta_report_owner = _cfg_html("meta_report_owner", "Report Owner")
    meta_report_owner_value = _cfg_html(
        "meta_report_owner_value",
        html.escape(_normalize_text(meta.get("project"))),
    )
    meta_team_member = _cfg_html("meta_team_member", "Team Member")
    meta_team_member_value = _cfg_html("meta_team_member_value", "")
    footer_html = str(titles.get("footer_html") or "")

    def _header_date(value: Any) -> str:
        text = _normalize_text(value)
        if not text:
            return ""
        for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
            try:
                parsed = datetime.strptime(text, fmt)
                return parsed.strftime("%Y/%m/%d")
            except ValueError:
                continue
        return text.replace("-", "/")

    period_value = html.escape(f"{_header_date(meta.get('week_start'))} - {_header_date(meta.get('week_end'))}")

    rows: list[str] = []
    rows.append("<!doctype html>")
    rows.append("<html lang='en'>")
    rows.append("<head>")
    rows.append("<meta charset='utf-8' />")
    rows.append("<meta name='viewport' content='width=device-width, initial-scale=1' />")
    rows.append(f"<title>{report_title}</title>")
    rows.append("<style>")
    rows.append("html, body { height:100%; }")
    rows.append("body{margin:0;padding:24px;background:#0b0b0b;font-family:Calibri,'Segoe UI',Arial,sans-serif;color:#ffffff;}")
    rows.append(".sheet,.sheet *{color:#ffffff;}")
    rows.append(".sheet{width:1040px;max-width:100%;margin:0 auto;border:2px solid #ffffff;background:#141414;box-shadow:0 14px 40px rgba(0,0,0,.45);}")
    rows.append(".title{text-align:center;font-weight:700;font-size:20px;letter-spacing:.2px;padding:12px 14px;background:#141414;background-image:linear-gradient(#1f1f1f,#141414);border-bottom:2px solid #ffffff;}")
    rows.append("table{border-collapse:collapse;width:100%;}td{vertical-align:top;}")
    rows.append(".subhead td{border-bottom:1px solid #ffffff;font-size:13px;font-weight:700;padding:8px 10px;text-align:center;}")
    rows.append(".meta td{border-bottom:1px solid #ffffff;border-right:1px solid #ffffff;padding:8px 10px;font-size:13px;line-height:1.2;}")
    rows.append(".meta tr td:last-child{border-right:none;}.meta{border-bottom:2px solid #ffffff;}")
    rows.append(".label{background:rgb(63,78,0);background-image:linear-gradient(rgb(76,92,10),rgb(63,78,0));font-weight:700;width:190px;white-space:nowrap;}")
    rows.append(".value{background:#202020;background-image:linear-gradient(#2a2a2a,#202020);}.label.small{width:140px;}")
    rows.append(".blue-panel{padding:14px 14px 18px;background-color:rgb(23,88,98);background-image:radial-gradient(circle at 38% 20%,rgba(255,255,255,.18) 0%,rgba(255,255,255,0) 35%),linear-gradient(135deg,rgb(32,110,123) 0%,rgb(23,88,98) 48%,rgb(18,70,78) 100%);}")
    rows.append(".content td{padding:8px 12px;font-size:12.6px;line-height:1.25;}")
    rows.append(".content .sec-label{width:190px;font-weight:700;font-size:14pt;padding:8px 10px;background:rgba(0,0,0,.2);}")
    rows.append(".divider{height:1px;background:rgba(255,255,255,.35);margin:10px 0;}")
    rows.append(".muted{color:rgba(255,255,255,.78);}")
    rows.append("ul{margin:6px 0;padding:0;}")
    rows.append(".lvl1 li,.lvl2 li,.lvl3 li,.lvl4 li{list-style:none;margin:3px 0;position:relative;padding-left:18px;}")
    rows.append(".lvl1 li:before{content:'\\25A0';position:absolute;left:0;top:0;font-size:10px;line-height:1.2;color:#ffffff;}")
    rows.append(".lvl2{margin-left:18px;}.lvl2 li:before{content:'\\25C6';position:absolute;left:0;top:0;font-size:12px;line-height:1.2;color:#ffffff;}")
    rows.append(".lvl3{margin-left:36px;}.lvl3 li:before{content:'\\2022';position:absolute;left:0;top:0;font-size:12px;line-height:1.2;color:#ffffff;}")
    rows.append(".lvl4{margin-left:20px;}.lvl4 li:before{content:'\\25E6';position:absolute;left:0;top:0;font-size:12px;line-height:1.2;color:#ffffff;}")
    rows.append("@media print{body{background:#ffffff;padding:0;}.sheet{width:100%;box-shadow:none;}}")
    rows.append("</style>")
    rows.append("</head>")
    rows.append("<body>")
    rows.append("<div class='sheet'>")
    rows.append(f"<div class='title'>{report_title} - {project} - {week_key}</div>")
    rows.append(
        f"<table class='subhead' cellspacing='0' cellpadding='0'><tr><td class='sub-banner' style='background:{header_banner_bg_color};'>{header_project_info}</td></tr></table>"
    )
    rows.append("<table class='meta' cellspacing='0' cellpadding='0'>")
    rows.append(
        "<tr>"
        f"<td class='label'>{meta_active_iteration}</td>"
        f"<td class='value'>{meta_active_iteration_value}</td>"
        f"<td class='label small'>{meta_report_owner}</td>"
        f"<td class='value' style='border-right:none;'>{meta_report_owner_value}</td>"
        "</tr>"
    )
    rows.append(
        "<tr>"
        f"<td class='label'>{meta_report_period}</td>"
        f"<td class='value'>{period_value}</td>"
        f"<td class='label small'>{meta_team_member}</td>"
        f"<td class='value' style='border-right:none;'>{meta_team_member_value}</td>"
        "</tr>"
    )
    rows.append("</table>")
    rows.append("<div class='blue-panel'>")
    rows.append("<table class='content' cellspacing='0' cellpadding='0'>")

    rows.append("<tr>")
    rows.append(f"<td class='sec-label'>{highlights_title}</td><td class='sec-body'><ul class='lvl1'>")
    for item in payload.get("highlights") or []:
        headline = _normalize_text(item.get("headline"))
        comment = _normalize_text(item.get("comment"))
        highlight_text = headline
        if comment:
            highlight_text = f"{headline} - {comment}" if headline else comment
        headline_html = html.escape(highlight_text)
        issue_key = html.escape(_normalize_text(item.get("issue_key")))
        rows.append(f"<li>{headline_html}{f' ({issue_key})' if issue_key else ''}</li>")
    if not (payload.get("highlights") or []):
        rows.append("<li>No highlight updates in this week.</li>")
    rows.append("</ul></td></tr>")

    rows.append("<tr>")
    rows.append(f"<td class='sec-label'>{results_title}</td><td class='sec-body'>")
    for epic_idx, epic in enumerate(payload.get("epics") or []):
        epic_name = html.escape(_normalize_text(epic.get("epic_name")))
        epic_key = html.escape(_normalize_text(epic.get("epic_key")))
        rows.append("<ul class='lvl1'>")
        rows.append(f"<li><b>{epic_name} ({epic_key})</b></li>")
        rows.append("</ul>")
        rows.append("<ul class='lvl2'>")
        for item in (epic.get("report_items") or []) + (epic.get("completed_items") or []) + (epic.get("progress_items") or []):
            text = html.escape(_normalize_text(item.get("text")))
            issue_key = html.escape(_normalize_text(item.get("issue_key")))
            status = html.escape(_normalize_text(item.get("status")))
            comment = html.escape(_normalize_text(item.get("comment")))
            rows.append(f"<li>{text}{f' ({issue_key})' if issue_key else ''}</li>")
            if status or comment:
                rows.append("</ul><ul class='lvl3'>")
                if status:
                    rows.append(f"<li>{status}</li>")
                if comment:
                    rows.append(f"<li>{comment}</li>")
                rows.append("</ul><ul class='lvl2'>")
        for group in epic.get("parent_subtasks") or []:
            parent_issue_key = html.escape(_normalize_text(group.get("parent_issue_key")))
            parent_text = html.escape(_normalize_text(group.get("parent_text")))
            rows.append(f"<li>{parent_text}{f' ({parent_issue_key})' if parent_issue_key else ''}:</li>")
            rows.append("</ul><ul class='lvl3'>")
            for subtask in group.get("subtasks") or []:
                subtask_key = html.escape(_normalize_text(subtask.get("issue_key")))
                subtask_text = html.escape(_normalize_text(subtask.get("text")))
                subtask_status = html.escape(_normalize_text(subtask.get("status")))
                subtask_comment = html.escape(_normalize_text(subtask.get("comment")))
                suffix = f" - {subtask_status}" if subtask_status else ""
                rows.append(f"<li>{subtask_text}{suffix}{f' ({subtask_key})' if subtask_key else ''}</li>")
                if subtask_comment:
                    rows.append("<ul class='lvl4'>")
                    rows.append(f"<li>{subtask_comment}</li>")
                    rows.append("</ul>")
            rows.append("</ul><ul class='lvl2'>")
        if epic.get("high_priority_items"):
            rows.append(f"<li><b>{high_priority_title}</b></li>")
            rows.append("</ul><ul class='lvl3'>")
            for item in epic.get("high_priority_items") or []:
                text = html.escape(_normalize_text(item.get("text")))
                issue_key = html.escape(_normalize_text(item.get("issue_key")))
                rows.append(f"<li>{text}{f' ({issue_key})' if issue_key else ''}</li>")
            rows.append("</ul><ul class='lvl2'>")
        bugs = epic.get("bugs") or {}
        closed_bugs = int(bugs.get("closed", 0))
        in_progress_bugs = int(bugs.get("in_progress", 0))
        if closed_bugs or in_progress_bugs:
            rows.append(
                f"<li><b>{bugs_title}</b>: {closed_bugs} trouble reports/issues are analyzed and closed, "
                f"{in_progress_bugs} currently in progress.</li>"
            )
        rows.append("</ul>")
        if epic_idx < len(payload.get("epics") or []) - 1:
            rows.append("<div class='divider'></div>")
    if not (payload.get("epics") or []):
        rows.append("<p class='muted'>No completed items for selected scope.</p>")
    rows.append("</td></tr>")

    rows.append("<tr>")
    rows.append(f"<td class='sec-label'>{plans_title}</td><td class='sec-body'>")
    for epic in payload.get("next_week_plans") or []:
        epic_name = html.escape(_normalize_text(epic.get("epic_name")))
        epic_key = html.escape(_normalize_text(epic.get("epic_key")))
        rows.append("<ul class='lvl1'>")
        rows.append(f"<li><b>{epic_name} ({epic_key})</b></li>")
        rows.append("</ul>")
        rows.append("<ul class='lvl2'>")
        for item in epic.get("items") or []:
            text = html.escape(_normalize_text(item.get("text")))
            comment = html.escape(_normalize_text(item.get("comment")))
            issue_key = html.escape(_normalize_text(item.get("issue_key")))
            status = html.escape(_normalize_text(item.get("status")))
            rows.append(f"<li>{text}{f' ({issue_key})' if issue_key else ''}</li>")
            if status or comment:
                rows.append("</ul><ul class='lvl3'>")
                if status:
                    rows.append(f"<li>{status}</li>")
                if comment:
                    rows.append(f"<li>{comment}</li>")
                rows.append("</ul><ul class='lvl2'>")
            for subtask in item.get("subtasks") or []:
                subtask_key = html.escape(_normalize_text(subtask.get("issue_key")))
                subtask_text = html.escape(_normalize_text(subtask.get("text")))
                subtask_status = html.escape(_normalize_text(subtask.get("status")))
                subtask_comment = html.escape(_normalize_text(subtask.get("comment")))
                suffix = f" - {subtask_status}" if subtask_status else ""
                rows.append("</ul><ul class='lvl3'>")
                rows.append(f"<li>{subtask_text}{suffix}{f' ({subtask_key})' if subtask_key else ''}</li>")
                if subtask_comment:
                    rows.append("<ul class='lvl4'>")
                    rows.append(f"<li>{subtask_comment}</li>")
                    rows.append("</ul>")
                rows.append("</ul><ul class='lvl2'>")
        rows.append("</ul>")
    if not (payload.get("next_week_plans") or []):
        rows.append("<p class='muted'>No in-progress plans collected for next week.</p>")
    rows.append("</td></tr>")

    rows.append("<tr>")
    rows.append(f"<td class='sec-label'>{vacations_title}</td><td class='sec-body'><ul class='lvl1'>")
    for item in payload.get("vacations") or []:
        rows.append(f"<li>{html.escape(_normalize_text(item))}</li>")
    if not (payload.get("vacations") or []):
        rows.append("<li>No vacations found for the configured horizon.</li>")
    rows.append("</ul></td></tr>")

    rows.append("</table>")
    if footer_html.strip():
        rows.append(f"<div class='footer-html'>{footer_html}</div>")
    rows.append("</div></div></body></html>")
    return "\n".join(rows)


def save_snapshot(path: Path, payload: dict[str, Any], week: WeekWindow) -> None:
    snapshot = {
        "meta": {
            "project": payload.get("meta", {}).get("project", ""),
            "week_key": week.key,
            "year": week.year,
            "week": week.week,
            "generated_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        },
        "order": _extract_order(payload),
        "payload": payload,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")


@registry.register
class JiraWeeklyEmailReport:
    name = "jira_weekly_email"

    def run(
        self,
        dataset: dict,
        config: ConfigParser,
        output_formats: list[str],
        extra_params: dict | None = None,
    ) -> None:
        extra_params = extra_params or {}
        if "html" not in output_formats:
            logger.info("jira_weekly_email outputs HTML only; proceeding with HTML output.")

        section = config["jira_weekly_email"] if config.has_section("jira_weekly_email") else {}
        project = _normalize_text(
            extra_params.get("project")
            or section.get("project")
            or config.get("jira", "project", fallback="")
        )
        if not project:
            raise ValueError("Project key is required for jira_weekly_email. Pass --params project=ABC.")

        week = resolve_week_window(extra_params)

        labels_highlights = _parse_label_set(
            extra_params.get("labels_highlights") or section.get("labels_highlights"),
            ["highlights"],
        )
        labels_report = _parse_label_set(
            extra_params.get("labels_report") or section.get("labels_report"),
            ["report"],
        )
        priority_high_values = _parse_label_set(
            extra_params.get("priority_high_values") or section.get("priority_high_values"),
            ["High", "Highest"],
        )
        logger.info(
            "REPORT PARAMS: project=%s week=%s range=[%s..%s] labels_highlights=%s labels_report=%s priority_high_values=%s",
            project,
            week.key,
            week.start.strftime("%Y-%m-%d"),
            week.end.strftime("%Y-%m-%d"),
            ",".join(sorted(labels_highlights)),
            ",".join(sorted(labels_report)),
            ",".join(sorted(priority_high_values)),
        )

        jira_source = JiraSource(config["jira"])
        evidence = collect_weekly_comment_evidence(jira_source, project, week)
        payload = build_report_payload(
            evidence,
            week,
            config,
            project,
            labels_highlights=labels_highlights,
            labels_report=labels_report,
            priority_high_values=priority_high_values,
        )

        vacation_file = _strip_wrapping_quotes(
            _normalize_text(extra_params.get("vacation_file") or section.get("vacation_file"))
        )
        if vacation_file:
            vacation_sheet = _normalize_text(extra_params.get("vacation_sheet") or section.get("vacation_sheet")) or "Vacations2026"
            vacation_markers = {
                item.strip()
                for item in _split_csv(
                    extra_params.get("vacation_marker_values") or section.get("vacation_marker_values"),
                    ["p", "P"],
                )
            }
            vacation_days_value = (
                _normalize_text(extra_params.get("vacation_horizon_days") or section.get("vacation_horizon_days")) or "60"
            )
            vacation_horizon_days = int(vacation_days_value)
            vacation_horizon_anchor = _normalize_key(
                extra_params.get("vacation_horizon_anchor") or section.get("vacation_horizon_anchor") or "today"
            )
            if vacation_horizon_anchor in {"week", "week_start", "report_week_start"}:
                vacation_horizon_start = week.start
            else:
                vacation_horizon_start = date.today()
            alternate_horizon_start = week.start if vacation_horizon_start != week.start else date.today()
            vacation_path = Path(vacation_file)
            if not vacation_path.is_absolute():
                parent_candidate = (Path.cwd().parent / vacation_path).resolve()
                cwd_candidate = (Path.cwd() / vacation_path).resolve()
                vacation_path = parent_candidate if parent_candidate.exists() else cwd_candidate
            try:
                payload["vacations"] = parse_vacations_excel(
                    vacation_path,
                    sheet=vacation_sheet,
                    markers=vacation_markers,
                    horizon_start=vacation_horizon_start,
                    horizon_days=vacation_horizon_days,
                )
                if not payload.get("vacations"):
                    alternate_vacations = parse_vacations_excel(
                        vacation_path,
                        sheet=vacation_sheet,
                        markers=vacation_markers,
                        horizon_start=alternate_horizon_start,
                        horizon_days=vacation_horizon_days,
                    )
                    if alternate_vacations:
                        payload["vacations"] = alternate_vacations
                        logger.info(
                            "VACATION FALLBACK APPLIED: original_start=%s alternate_start=%s entries=%s",
                            vacation_horizon_start.strftime("%Y-%m-%d"),
                            alternate_horizon_start.strftime("%Y-%m-%d"),
                            len(payload.get("vacations") or []),
                        )
                logger.info(
                    "VACATION RESULT: entries=%s file=%s anchor=%s horizon_start=%s",
                    len(payload.get("vacations") or []),
                    vacation_path,
                    vacation_horizon_anchor,
                    vacation_horizon_start.strftime("%Y-%m-%d"),
                )
            except Exception as exc:
                payload["vacations"] = []
                logger.error("Vacation data read failed: file=%s error=%s", vacation_path, exc)
        else:
            logger.info("VACATION RESULT: skipped (vacation_file is empty).")

        output_dir = _normalize_text(extra_params.get("output_dir") or section.get("output_dir") or config.get("reporting", "output_dir", fallback="reports"))
        output_base = Path(output_dir)
        output_base.mkdir(parents=True, exist_ok=True)
        snapshot_dir = _normalize_text(extra_params.get("snapshot_dir") or section.get("snapshot_dir")) or str(output_base)
        snapshot_base = Path(snapshot_dir).resolve()
        previous_week = _previous_week_window(week)
        logger.info(
            "SNAPSHOT INPUT: dir=%s project=%s current_week=%s previous_week=%s",
            snapshot_base,
            project,
            week.key,
            previous_week.key,
        )

        previous_snapshot = load_previous_snapshot(snapshot_base, project, week)
        previous_payload = previous_snapshot.get("payload") if previous_snapshot else None
        previous_week_key = _normalize_text((previous_snapshot.get("meta") or {}).get("week_key")) if previous_snapshot else ""
        if previous_snapshot:
            logger.info("SNAPSHOT FOUND: previous_week=%s", previous_week_key or previous_week.key)
        else:
            logger.info("SNAPSHOT NOT FOUND: expected_previous_week=%s", previous_week.key)
        payload = apply_previous_order(payload, previous_snapshot)
        payload = rewrite_payload_with_ai(payload, config, extra_params)

        html_text = render_outlook_html(payload)
        output_name = _normalize_text(extra_params.get("output") or extra_params.get("output_file"))
        if output_name:
            output_path = Path(output_name)
            if not output_path.is_absolute():
                output_path = output_base / output_path
            if output_path.suffix.lower() != ".html":
                output_path = output_path.with_suffix(".html")
        else:
            output_path = output_base / f"jira_weekly_email_{project}_{week.key}.html"
        output_path.write_text(html_text, encoding="utf-8")

        snapshot_path = snapshot_base / f"jira_weekly_email_{project}_{week.key}.json"
        save_snapshot(snapshot_path, payload, week)

        diff_lines = compute_payload_diff(previous_payload, payload)
        diff_stats = _diff_stats(diff_lines)
        logger.info(
            "DIFF SUMMARY: previous_week=%s added=%s removed=%s unchanged=%s",
            previous_week_key or "none",
            diff_stats["added"],
            diff_stats["removed"],
            diff_stats["unchanged"],
        )
        if diff_lines and previous_week_key:
            render_console_diff(
                diff_lines,
                project=project,
                current_week_key=week.key,
                previous_week_key=previous_week_key,
                use_color=True,
            )
        elif not previous_week_key:
            logger.info("DIFF SKIPPED: previous week snapshot is missing for week=%s", previous_week.key)

        logger.info(
            "REPORT SUMMARY: project=%s week=%s issues=%s highlights=%s epics=%s plans=%s vacations=%s output=%s",
            project,
            week.key,
            len(evidence),
            len(payload.get("highlights") or []),
            len(payload.get("epics") or []),
            sum(len(item.get("items") or []) for item in (payload.get("next_week_plans") or [])),
            len(payload.get("vacations") or []),
            output_path,
        )
