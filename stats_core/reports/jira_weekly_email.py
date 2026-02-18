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

import requests
from openpyxl import load_workbook

from ..sources.jira import JiraSource
from . import registry

logger = logging.getLogger(__name__)


_DONE_VALUES = {"done", "resolved", "closed"}
_TASK_VALUES = {"task", "feature", "improvement", "story", "sub-task", "subtask"}


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
    items = [item.strip() for item in str(value).split(",")]
    return [item for item in items if item]


def _normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).strip().split())


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
        epic_link = getattr(issue.fields, "customfield_10000", "") or ""
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
        }

    missing_parent_keys = [key for key in parent_keys_needed if not issue_epic_map.get(key)]
    if missing_parent_keys:
        chunk_size = 50
        for idx in range(0, len(missing_parent_keys), chunk_size):
            chunk = missing_parent_keys[idx : idx + chunk_size]
            parent_issues = jira.search_issues(
                f"issuekey in ({', '.join(chunk)})",
                maxResults=1000,
                fields=["key", "customfield_10000", "summary", "status", "resolution"],
            )
            for parent_issue in parent_issues:
                parent_epic = getattr(parent_issue.fields, "customfield_10000", "") or ""
                issue_epic_map[parent_issue.key] = parent_epic
                issue_details[parent_issue.key] = {
                    "summary": _normalize_text(getattr(parent_issue.fields, "summary", "")),
                    "status": _normalize_text(getattr(getattr(parent_issue.fields, "status", None), "name", "")),
                    "resolution": _normalize_text(getattr(getattr(parent_issue.fields, "resolution", None), "name", "")),
                }

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

    evidence: list[dict[str, Any]] = []
    total_comments_in_week = 0

    for issue in all_issues:
        issue_key = issue.key
        labels = [str(label) for label in (issue.fields.labels or [])]
        priority = issue.fields.priority.name if issue.fields.priority else ""
        status = issue.fields.status.name if issue.fields.status else ""
        resolution = issue.fields.resolution.name if issue.fields.resolution else ""
        issue_type = issue.fields.issuetype.name if issue.fields.issuetype else ""

        epic_link = issue_epic_map.get(issue_key, "")
        parent_key = issue_parent_map.get(issue_key, "")
        if not epic_link and parent_key:
            epic_link = issue_epic_map.get(parent_key, "")
        epic_name = epic_names.get(epic_link, "Unknown Epic") if epic_link else "Unknown Epic"

        comments_in_week: list[str] = []
        comment_block = getattr(getattr(issue.fields, "comment", None), "comments", []) or []
        for comment in comment_block:
            created_dt = _parse_jira_date(getattr(comment, "created", ""))
            if not created_dt or not (week.start <= created_dt <= week.end):
                continue
            body_text = _normalize_text(_comment_body_to_text(getattr(comment, "body", "")))
            if body_text:
                comments_in_week.append(body_text)

        if not comments_in_week:
            continue
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
                "Subtask": _normalize_key(issue_type) in {"sub-task", "subtask"},
                "Parent_Finished": parent_finished,
                "Parent_Summary": summary_map.get(parent_key, ""),
                "Parent_Status": status_map.get(parent_key, ""),
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


def _build_item_text(entry: dict[str, Any], *, mode: str) -> str:
    summary = _normalize_text(entry.get("Summary"))
    comment_hint = _first_sentence((entry.get("Comments") or [""])[0])

    if mode == "highlight":
        headline = summary or comment_hint or "Progress updated"
        return headline

    if mode == "completed":
        headline = summary or comment_hint or "Task"
        return f"{headline} - Finished"

    if mode == "subtask":
        if summary:
            return summary
        return comment_hint or "Subtask update"

    if mode == "plan":
        return comment_hint or "Work will continue next week."

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
) -> dict[str, Any]:
    highlights: list[dict[str, str]] = []
    epics: dict[str, dict[str, Any]] = {}
    plans: dict[str, list[dict[str, str]]] = {}
    report_epic_ids: set[str] = set()
    report_all_labels = "@all" in labels_report

    for entry in evidence:
        issue_key = _normalize_text(entry.get("Issue_Key"))
        labels_norm = {_normalize_key(label) for label in (entry.get("Labels") or [])}
        epic_labels_norm = {_normalize_key(label) for label in (entry.get("Epic_Labels") or [])}
        epic_labels_known = bool(entry.get("Epic_Labels_Known"))
        epic_name = _normalize_text(entry.get("Epic_Name")) or "Unknown Epic"
        epic_key = _normalize_text(entry.get("Epic_Key"))
        epic_identifier = _epic_id(entry)
        issue_in_report_scope = report_all_labels or bool(epic_labels_norm & labels_report)
        if not issue_in_report_scope and epic_key and not epic_labels_known:
            issue_in_report_scope = bool(labels_norm & labels_report)
        if issue_in_report_scope:
            report_epic_ids.add(epic_identifier)

        epic_bucket = epics.setdefault(
            epic_identifier,
            {
                "epic_key": epic_key,
                "epic_name": epic_name,
                "report_items": [],
                "completed_items": [],
                "parent_subtasks": [],
                "high_priority_items": [],
                "bugs": {"closed": 0, "in_progress": 0},
                "_parent_subtask_map": {},
            },
        )

        if labels_norm & labels_highlights:
            highlights.append(
                {
                    "issue_key": issue_key,
                    "headline": _build_item_text(entry, mode="highlight"),
                }
            )

        if entry.get("Bug"):
            if entry.get("Finished"):
                epic_bucket["bugs"]["closed"] += 1
            else:
                epic_bucket["bugs"]["in_progress"] += 1
        elif entry.get("Finished") and _normalize_key(entry.get("Type")) in _TASK_VALUES:
            if entry.get("Subtask") and _normalize_text(entry.get("Parent_Key")):
                parent_issue_key = _normalize_text(entry.get("Parent_Key"))
                subtask_comment = _first_sentence((entry.get("Comments") or [""])[0])
                summary_key = _normalize_key(_normalize_text(entry.get("Summary")).rstrip(".!?"))
                comment_key = _normalize_key(subtask_comment.rstrip(".!?"))
                if summary_key and summary_key == comment_key:
                    subtask_comment = ""
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
                }
                if issue_in_report_scope:
                    epic_bucket["report_items"].append(completed_item)
                else:
                    epic_bucket["completed_items"].append(completed_item)
        elif (
            not entry.get("Finished")
            and not entry.get("Subtask")
            and _normalize_key(entry.get("Type")) in _TASK_VALUES
        ):
            plan_headline = _normalize_text(entry.get("Summary")) or _normalize_text(entry.get("Issue_Key"))
            plans.setdefault(epic_identifier, []).append(
                {
                    "issue_key": issue_key,
                    "text": plan_headline,
                    "comment": _build_item_text(entry, mode="plan"),
                }
            )

        if _normalize_key(entry.get("Priority")) in {"high", "highest"}:
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

    epic_entries = sorted(epic_entries, key=lambda item: (_normalize_key(item["epic_name"]), _normalize_key(item["epic_key"])))
    next_week_plans: list[dict[str, Any]] = []
    for epic in epic_entries:
        epic_identifier = epic["epic_key"] if epic["epic_key"] else f"name::{epic['epic_name']}"
        plan_items = plans.get(epic_identifier, [])
        if not plan_items:
            continue
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
    for idx, item in enumerate(payload.get("highlights") or []):
        targets.append((f"highlights.{idx}.headline", _normalize_text(item.get("headline"))))

    for epic_idx, epic in enumerate(payload.get("epics") or []):
        for section in ("report_items", "completed_items", "high_priority_items"):
            for item_idx, item in enumerate(epic.get(section) or []):
                targets.append((f"epics.{epic_idx}.{section}.{item_idx}.text", _normalize_text(item.get("text"))))
        for parent_idx, parent_group in enumerate(epic.get("parent_subtasks") or []):
            targets.append(
                (
                    f"epics.{epic_idx}.parent_subtasks.{parent_idx}.parent_text",
                    _normalize_text(parent_group.get("parent_text")),
                )
            )
            for subtask_idx, subtask in enumerate(parent_group.get("subtasks") or []):
                targets.append(
                    (
                        f"epics.{epic_idx}.parent_subtasks.{parent_idx}.subtasks.{subtask_idx}.text",
                        _normalize_text(subtask.get("text")),
                    )
                )
                targets.append(
                    (
                        f"epics.{epic_idx}.parent_subtasks.{parent_idx}.subtasks.{subtask_idx}.comment",
                        _normalize_text(subtask.get("comment")),
                    )
                )

    for epic_idx, plan_epic in enumerate(payload.get("next_week_plans") or []):
        for item_idx, item in enumerate(plan_epic.get("items") or []):
            targets.append((f"plans.{epic_idx}.items.{item_idx}.text", _normalize_text(item.get("text"))))
            targets.append((f"plans.{epic_idx}.items.{item_idx}.comment", _normalize_text(item.get("comment"))))
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

    targets = _collect_text_targets(payload)
    if not targets:
        return payload

    prompt_lines = [
        "Rewrite each value to concise business style with at most 1-2 sentences.",
        "Preserve meaning and keep references intact.",
        "Return only JSON object: {\"id\":\"rewritten text\", ...}.",
        "IDs:",
    ]
    target_map: dict[str, str] = {}
    for idx, (path, text_value) in enumerate(targets, start=1):
        target_id = f"t{idx}"
        target_map[target_id] = path
        prompt_lines.append(f"{target_id}: {text_value}")
    prompt = "\n".join(prompt_lines)

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
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else "n/a"
        response_text = _normalize_text(exc.response.text if exc.response is not None else "")
        if len(response_text) > 500:
            response_text = response_text[:500] + "..."
        logger.error("Ollama HTTP error: status=%s body=%s", status, response_text or "<empty>")
        _log_ollama_check_commands(ollama_url, model, bool(ollama_api_key))
        logger.warning("Ollama call failed; using deterministic text.")
        return payload
    except Exception as exc:
        logger.error("Ollama call failed: %s", exc)
        _log_ollama_check_commands(ollama_url, model, bool(ollama_api_key))
        logger.warning("Ollama call failed; using deterministic text.")
        return payload

    response_text = _normalize_text(response_json.get("response", ""))
    rewrite_map = _extract_json_object(response_text)
    if not rewrite_map:
        logger.warning("Ollama response is not valid JSON map; using deterministic text.")
        return payload

    updated = json.loads(json.dumps(payload))

    for target_id, target_path in target_map.items():
        rewritten = _normalize_text(rewrite_map.get(target_id))
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


def _snapshot_week_tuple(snapshot: dict[str, Any]) -> tuple[int, int] | None:
    meta = snapshot.get("meta") or {}
    try:
        year = int(meta.get("year"))
        week = int(meta.get("week"))
    except Exception:
        return None
    return year, week


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


def load_previous_snapshot(snapshot_dir: Path, project: str, current_week: WeekWindow) -> dict[str, Any] | None:
    project_dir = snapshot_dir / project
    if not project_dir.exists():
        return None

    previous_week = _previous_week_window(current_week)
    previous_path = project_dir / f"{previous_week.key}.json"
    if not previous_path.exists():
        return None
    try:
        payload = json.loads(previous_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    week_tuple = _snapshot_week_tuple(payload)
    if week_tuple != (previous_week.year, previous_week.week):
        return None
    return payload


def _extract_order(payload: dict[str, Any]) -> dict[str, Any]:
    epic_order: list[str] = []
    issue_order_by_epic: dict[str, list[str]] = {}
    for epic in payload.get("epics") or []:
        epic_key = _normalize_text(epic.get("epic_key"))
        epic_name = _normalize_text(epic.get("epic_name"))
        epic_id = epic_key if epic_key else f"name::{epic_name}"
        epic_order.append(epic_id)
        keys: list[str] = []
        for section in ("report_items", "completed_items", "high_priority_items"):
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
        lines.append(f"HIGHLIGHT {item.get('headline')} ({item.get('issue_key')})")

    for epic in payload.get("epics") or []:
        lines.append(f"EPIC {epic.get('epic_name')} ({epic.get('epic_key')})")
        for section in ("report_items", "completed_items", "high_priority_items"):
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

    date_by_col: dict[int, date] = {}
    for col in range(6, max_col + 1):
        raw_date = ws.cell(row=3, column=col).value
        if isinstance(raw_date, datetime):
            date_by_col[col] = raw_date.date()
        elif isinstance(raw_date, date):
            date_by_col[col] = raw_date

    vacation_lines: list[str] = []
    for row in range(5, max_row + 1):
        name = _normalize_text(ws.cell(row=row, column=2).value)
        if not name:
            continue

        selected_dates: list[date] = []
        for col in range(6, max_col + 1):
            marker_raw = ws.cell(row=row, column=col).value
            marker = _normalize_key(marker_raw)
            if not marker or marker not in marker_set:
                continue
            day = date_by_col.get(col)
            if not day:
                continue
            if horizon_start <= day <= horizon_end:
                selected_dates.append(day)

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

    return vacation_lines

def render_outlook_html(payload: dict[str, Any]) -> str:
    meta = payload.get("meta") or {}
    titles = payload.get("titles") or {}
    project = html.escape(_normalize_text(meta.get("project")))
    week_key = html.escape(_normalize_text(meta.get("week_key")))
    week_start = html.escape(_normalize_text(meta.get("week_start")))
    week_end = html.escape(_normalize_text(meta.get("week_end")))

    rows: list[str] = []
    rows.append("<html>")
    rows.append('<body style="font-family: Calibri, Arial, sans-serif; font-size:14px; color:#1f2937;">')
    rows.append(f"<h2>{html.escape(_normalize_text(titles.get('main', 'Weekly Report')))} - {project} - {week_key}</h2>")
    rows.append(f"<p>Period: {week_start} to {week_end}</p>")

    rows.append(f"<h3>1. {html.escape(_normalize_text(titles.get('highlights', 'Highlights')))}</h3>")
    rows.append("<ul>")
    for item in payload.get("highlights") or []:
        headline = html.escape(_normalize_text(item.get("headline")))
        issue_key = html.escape(_normalize_text(item.get("issue_key")))
        rows.append(f"<li>{headline} ({issue_key})</li>")
    if not (payload.get("highlights") or []):
        rows.append("<li>No highlight updates in this week.</li>")
    rows.append("</ul>")

    rows.append(f"<h3>2. {html.escape(_normalize_text(titles.get('results', 'Key Results and Achievements')))}</h3>")
    high_priority_title = html.escape(_normalize_text(titles.get("high_priority_subtitle", "High priority items")))
    bugs_title = html.escape(_normalize_text(titles.get("bugs_subtitle", "Bugs summary")))
    rows.append("<ul style='margin:0 0 0 16px; padding-left:16px;'>")
    for epic in payload.get("epics") or []:
        epic_name = html.escape(_normalize_text(epic.get("epic_name")))
        epic_key = html.escape(_normalize_text(epic.get("epic_key")))
        rows.append(f"<li><b>Epic: {epic_name} ({epic_key})</b>")
        rows.append("<ul style='margin:6px 0 10px 16px; padding-left:16px;'>")
        if epic.get("report_items"):
            for item in epic.get("report_items") or []:
                text = html.escape(_normalize_text(item.get("text")))
                issue_key = html.escape(_normalize_text(item.get("issue_key")))
                rows.append(f"<li>({issue_key}) {text}</li>")
        if epic.get("completed_items"):
            for item in epic.get("completed_items") or []:
                text = html.escape(_normalize_text(item.get("text")))
                issue_key = html.escape(_normalize_text(item.get("issue_key")))
                rows.append(f"<li>({issue_key}) {text}</li>")
        if epic.get("parent_subtasks"):
            for group in epic.get("parent_subtasks") or []:
                parent_issue_key = html.escape(_normalize_text(group.get("parent_issue_key")))
                parent_text = html.escape(_normalize_text(group.get("parent_text")))
                rows.append(f"<li>({parent_issue_key}) {parent_text}:")
                rows.append("<ul style='margin:6px 0 6px 16px; padding-left:16px;'>")
                for subtask in group.get("subtasks") or []:
                    subtask_key = html.escape(_normalize_text(subtask.get("issue_key")))
                    subtask_text = html.escape(_normalize_text(subtask.get("text")))
                    subtask_status = html.escape(_normalize_text(subtask.get("status")))
                    subtask_comment = html.escape(_normalize_text(subtask.get("comment")))
                    if subtask_status:
                        rows.append(f"<li>({subtask_key}) {subtask_text} - {subtask_status}")
                    else:
                        rows.append(f"<li>({subtask_key}) {subtask_text}")
                    if subtask_comment:
                        rows.append("<ul style='margin:4px 0 4px 16px; padding-left:16px;'>")
                        rows.append(f"<li>Comment: {subtask_comment}</li>")
                        rows.append("</ul>")
                    rows.append("</li>")
                rows.append("</ul>")
                rows.append("</li>")
        if epic.get("high_priority_items"):
            rows.append(f"<li><b>{high_priority_title}</b>")
            rows.append("<ul style='margin:6px 0 6px 16px; padding-left:16px;'>")
            for item in epic.get("high_priority_items") or []:
                text = html.escape(_normalize_text(item.get("text")))
                issue_key = html.escape(_normalize_text(item.get("issue_key")))
                rows.append(f"<li>({issue_key}) {text}</li>")
            rows.append("</ul>")
            rows.append("</li>")
        bugs = epic.get("bugs") or {}
        closed_bugs = int(bugs.get("closed", 0))
        in_progress_bugs = int(bugs.get("in_progress", 0))
        if closed_bugs or in_progress_bugs:
            rows.append(
                "<li><b>"
                f"{bugs_title}"
                "</b>: "
                f"{closed_bugs} trouble reports/issues are analyzed and closed, "
                f"{in_progress_bugs} currently in progress."
                "</li>"
            )
        rows.append("</ul>")
        rows.append("</li>")
    rows.append("</ul>")

    rows.append(f"<h3>3. {html.escape(_normalize_text(titles.get('plans', 'Next Week Plans')))}</h3>")
    for epic in payload.get("next_week_plans") or []:
        epic_name = html.escape(_normalize_text(epic.get("epic_name")))
        epic_key = html.escape(_normalize_text(epic.get("epic_key")))
        rows.append(f"<h4>Epic: {epic_name} ({epic_key})</h4>")
        rows.append("<ul>")
        for item in epic.get("items") or []:
            text = html.escape(_normalize_text(item.get("text")))
            comment = html.escape(_normalize_text(item.get("comment")))
            issue_key = html.escape(_normalize_text(item.get("issue_key")))
            rows.append(f"<li>({issue_key}) {text}")
            if comment:
                rows.append("<ul style='margin:4px 0 4px 16px; padding-left:16px;'>")
                rows.append(f"<li>{comment}</li>")
                rows.append("</ul>")
            rows.append("</li>")
        rows.append("</ul>")
    if not (payload.get("next_week_plans") or []):
        rows.append("<p>No in-progress plans collected for next week.</p>")

    rows.append(f"<h3>4. {html.escape(_normalize_text(titles.get('vacations', 'Vacations (next 60 days)')))}</h3>")
    rows.append("<ul>")
    for item in payload.get("vacations") or []:
        rows.append(f"<li>{html.escape(_normalize_text(item))}</li>")
    if not (payload.get("vacations") or []):
        rows.append("<li>No vacations found for the configured horizon.</li>")
    rows.append("</ul>")

    rows.append("</body>")
    rows.append("</html>")
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
        logger.info(
            "REPORT PARAMS: project=%s week=%s range=[%s..%s] labels_highlights=%s labels_report=%s",
            project,
            week.key,
            week.start.strftime("%Y-%m-%d"),
            week.end.strftime("%Y-%m-%d"),
            ",".join(sorted(labels_highlights)),
            ",".join(sorted(labels_report)),
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
                    horizon_start=week.start,
                    horizon_days=vacation_horizon_days,
                )
                logger.info("VACATION RESULT: entries=%s file=%s", len(payload.get("vacations") or []), vacation_path)
            except Exception as exc:
                payload["vacations"] = []
                logger.error("Vacation data read failed: file=%s error=%s", vacation_path, exc)
        else:
            logger.info("VACATION RESULT: skipped (vacation_file is empty).")

        output_dir = _normalize_text(extra_params.get("output_dir") or section.get("output_dir") or config.get("reporting", "output_dir", fallback="reports"))
        output_base = Path(output_dir)
        output_base.mkdir(parents=True, exist_ok=True)
        snapshot_dir = _normalize_text(extra_params.get("snapshot_dir") or section.get("snapshot_dir")) or str(
            output_base / "snapshots" / "jira_weekly_email"
        )
        snapshot_base = Path(snapshot_dir)
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
        if previous_snapshot:
            logger.info("SNAPSHOT FOUND: previous_week=%s", previous_week.key)
        else:
            logger.info("SNAPSHOT NOT FOUND: expected_previous_week=%s", previous_week.key)
        payload = apply_previous_order(payload, previous_snapshot)
        payload = rewrite_payload_with_ollama(payload, config, extra_params)
        payload = apply_previous_order(payload, previous_snapshot)

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

        snapshot_path = snapshot_base / project / f"{week.key}.json"
        save_snapshot(snapshot_path, payload, week)

        diff_lines = compute_payload_diff(previous_payload, payload)
        diff_stats = _diff_stats(diff_lines)
        previous_week_key = previous_week.key if previous_snapshot else ""
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
