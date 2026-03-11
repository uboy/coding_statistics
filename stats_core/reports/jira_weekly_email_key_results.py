from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


def _normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).replace("\r", " ").replace("\n", " ").split())


def _normalize_key(value: Any) -> str:
    return _normalize_text(value).casefold()


def _ensure_terminal_punctuation(text: str) -> str:
    value = _normalize_text(text)
    if not value:
        return ""
    if value[-1] not in ".!?":
        value += "."
    return value


def _dedupe_points(points: list[str]) -> list[str]:
    unique_points: list[str] = []
    seen: set[str] = set()
    for point in points:
        cleaned = _ensure_terminal_punctuation(point)
        marker = _normalize_key(cleaned)
        if not marker or marker in seen:
            continue
        seen.add(marker)
        unique_points.append(cleaned)
    return unique_points


def _truncate_words(text: str, max_words: int = 12) -> str:
    words = _normalize_text(text).split()
    if not words:
        return ""
    if len(words) <= max_words:
        return " ".join(words)
    truncated = " ".join(words[:max_words]).rstrip(" ,;:-")
    if truncated and truncated[-1] not in ".!?":
        truncated += "..."
    return truncated


def _limit_points(points: list[str], *, max_items: int = 2, max_words_per_item: int = 12) -> str:
    if not points:
        return ""
    compact = [_truncate_words(item, max_words=max_words_per_item) for item in points[:max_items]]
    compact = [item for item in compact if item]
    return "; ".join(compact)


def classify_progress_points(points: list[str]) -> dict[str, list[str]]:
    done: list[str] = []
    plan: list[str] = []
    risk: list[str] = []
    dependency: list[str] = []
    misc: list[str] = []
    for point in points:
        marker = _normalize_key(point)
        if not marker:
            continue
        if re.search(
            r"\b(done|completed|fixed|merged|implemented|released|resolved|verified|tested|closed|prepared|delivered)\b",
            marker,
        ):
            done.append(point)
            continue
        if re.search(
            r"\b(next|plan|will|todo|to do|continue|prepare|scheduled|pending|need to|going to|target)\b",
            marker,
        ):
            plan.append(point)
            continue
        if re.search(r"\b(block|blocked|issue|problem|risk|fail|failed|unstable|delay|stuck|timeout|hold)\b", marker):
            risk.append(point)
            continue
        if re.search(r"\b(depend|dependency|waiting|await|requires|need from|external|review|approval)\b", marker):
            dependency.append(point)
            continue
        misc.append(point)
    return {"done": done, "plan": plan, "risk": risk, "dependency": dependency, "misc": misc}


def _flatten_unique(point_groups: list[list[str]]) -> list[str]:
    merged: list[str] = []
    for group in point_groups:
        merged.extend(group or [])
    return _dedupe_points(merged)


def _fallback_note(*, status: str, resolution: str, finished: bool, in_progress: bool, blocked: bool, comments_count: int) -> str:
    if finished:
        return "Marked completed."
    if blocked:
        return "Blocked."
    if in_progress:
        return _ensure_terminal_punctuation(status or resolution or "In progress")
    if status or resolution:
        return _ensure_terminal_punctuation(status or resolution)
    if comments_count > 0:
        return "Updated this week."
    return "No textual update."


@dataclass
class SubtaskWeeklyUpdate:
    issue_key: str
    summary: str
    status: str
    resolution: str
    finished: bool
    in_progress: bool
    blocked: bool
    comments_count: int
    done_points: list[str] = field(default_factory=list)
    progress_points: list[str] = field(default_factory=list)
    risk_points: list[str] = field(default_factory=list)
    dependency_points: list[str] = field(default_factory=list)
    plan_points: list[str] = field(default_factory=list)
    fallback_note: str = ""

    @property
    def is_active(self) -> bool:
        return bool(
            self.comments_count
            or self.done_points
            or self.progress_points
            or self.risk_points
            or self.dependency_points
            or self.plan_points
            or self.finished
            or self.in_progress
            or self.blocked
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "issue_key": self.issue_key,
            "summary": self.summary,
            "status": self.status,
            "resolution": self.resolution,
            "finished": self.finished,
            "in_progress": self.in_progress,
            "blocked": self.blocked,
            "comments_count": self.comments_count,
            "done_points": list(self.done_points),
            "progress_points": list(self.progress_points),
            "risk_points": list(self.risk_points),
            "dependency_points": list(self.dependency_points),
            "plan_points": list(self.plan_points),
            "fallback_note": self.fallback_note,
        }


@dataclass
class FeatureWeeklyProgress:
    feature_key: str
    feature_name: str
    closed_tasks: int
    in_progress_tasks: int
    blocked_tasks: int
    comments_count: int
    parent_done_points: list[str] = field(default_factory=list)
    parent_progress_points: list[str] = field(default_factory=list)
    parent_risk_points: list[str] = field(default_factory=list)
    parent_dependency_points: list[str] = field(default_factory=list)
    parent_plan_points: list[str] = field(default_factory=list)
    active_subtasks: list[SubtaskWeeklyUpdate] = field(default_factory=list)

    @property
    def has_active_subtasks(self) -> bool:
        return bool(self.active_subtasks)


def build_feature_progress(feature: dict[str, Any]) -> FeatureWeeklyProgress:
    parent_points = _dedupe_points(list(feature.get("parent_points") or []))
    parent_classified = classify_progress_points(parent_points)

    ordered_keys: list[str] = []
    for key in feature.get("subtask_issue_keys") or []:
        normalized = _normalize_text(key)
        if normalized and normalized not in ordered_keys:
            ordered_keys.append(normalized)
    for key in (feature.get("subtask_updates") or {}).keys():
        normalized = _normalize_text(key)
        if normalized and normalized not in ordered_keys:
            ordered_keys.append(normalized)

    updates: list[SubtaskWeeklyUpdate] = []
    updates_map = feature.get("subtask_updates") or {}
    for issue_key in ordered_keys:
        raw = updates_map.get(issue_key) or {}
        points = _dedupe_points(list(raw.get("points") or []))
        classified = classify_progress_points(points)
        update = SubtaskWeeklyUpdate(
            issue_key=_normalize_text(raw.get("issue_key") or issue_key),
            summary=_normalize_text(raw.get("summary")),
            status=_normalize_text(raw.get("status")),
            resolution=_normalize_text(raw.get("resolution")),
            finished=bool(raw.get("finished")),
            in_progress=bool(raw.get("in_progress")),
            blocked=bool(raw.get("blocked")),
            comments_count=int(raw.get("comments_count") or 0),
            done_points=classified["done"],
            progress_points=classified["misc"],
            risk_points=classified["risk"],
            dependency_points=classified["dependency"],
            plan_points=classified["plan"],
            fallback_note=_normalize_text(raw.get("fallback_note"))
            or _fallback_note(
                status=_normalize_text(raw.get("status")),
                resolution=_normalize_text(raw.get("resolution")),
                finished=bool(raw.get("finished")),
                in_progress=bool(raw.get("in_progress")),
                blocked=bool(raw.get("blocked")),
                comments_count=int(raw.get("comments_count") or 0),
            ),
        )
        if update.is_active:
            updates.append(update)

    return FeatureWeeklyProgress(
        feature_key=_normalize_text(feature.get("feature_key")),
        feature_name=_normalize_text(feature.get("feature_name")),
        closed_tasks=int(feature.get("closed_tasks") or 0),
        in_progress_tasks=int(feature.get("in_progress_tasks") or 0),
        blocked_tasks=int(feature.get("blocked_tasks") or 0),
        comments_count=int(feature.get("comments_count") or 0),
        parent_done_points=parent_classified["done"],
        parent_progress_points=parent_classified["misc"],
        parent_risk_points=parent_classified["risk"],
        parent_dependency_points=parent_classified["dependency"],
        parent_plan_points=parent_classified["plan"],
        active_subtasks=updates,
    )


def has_feature_result_activity(progress: FeatureWeeklyProgress) -> bool:
    return bool(
        progress.closed_tasks > 0
        or progress.comments_count > 0
        or progress.parent_done_points
        or progress.parent_progress_points
        or progress.parent_risk_points
        or progress.parent_dependency_points
        or progress.parent_plan_points
        or progress.active_subtasks
    )


def _build_status_lead(progress: FeatureWeeklyProgress) -> str:
    if progress.blocked_tasks > 0 and progress.in_progress_tasks <= 0 and progress.closed_tasks <= 0:
        return "Blocked."
    if progress.in_progress_tasks > 0 and progress.closed_tasks <= 0:
        return "In progress."
    if progress.closed_tasks > 0 and progress.in_progress_tasks <= 0:
        return "Completed."
    return ""


def _build_parent_result_sentence(progress: FeatureWeeklyProgress) -> str:
    parts: list[str] = []
    done_part = _limit_points(progress.parent_done_points, max_items=2, max_words_per_item=12)
    progress_part = _limit_points(progress.parent_progress_points, max_items=1, max_words_per_item=14)
    plan_part = _limit_points(progress.parent_plan_points, max_items=2, max_words_per_item=12)
    risk_part = _limit_points(progress.parent_risk_points, max_items=1, max_words_per_item=14)
    dependency_part = _limit_points(progress.parent_dependency_points, max_items=1, max_words_per_item=14)

    if done_part:
        parts.append(f"Done: {done_part}")
    if progress_part:
        parts.append(f"Progress: {progress_part}")
    if plan_part:
        parts.append(f"Next: {plan_part}")
    if risk_part:
        parts.append(f"Risk: {risk_part}")
    elif progress.blocked_tasks > 0 and not progress.active_subtasks and has_feature_result_activity(progress):
        parts.append("Blocked; requires follow-up")
    if dependency_part:
        parts.append(f"Depends on: {dependency_part}")

    if not parts:
        return ""
    return _ensure_terminal_punctuation("; ".join(parts))


def _build_parent_plan_sentence(progress: FeatureWeeklyProgress) -> str:
    parts: list[str] = []
    plan_part = _limit_points(progress.parent_plan_points, max_items=2, max_words_per_item=12)
    progress_part = _limit_points(progress.parent_progress_points, max_items=1, max_words_per_item=14)
    risk_part = _limit_points(progress.parent_risk_points, max_items=1, max_words_per_item=14)
    dependency_part = _limit_points(progress.parent_dependency_points, max_items=1, max_words_per_item=14)

    if plan_part:
        parts.append(f"Next: {plan_part}")
    elif progress_part:
        parts.append(f"Progress: {progress_part}")
    if risk_part:
        parts.append(f"Risk: {risk_part}")
    if dependency_part:
        parts.append(f"Depends on: {dependency_part}")

    if not parts:
        return ""
    return _ensure_terminal_punctuation("; ".join(parts))


def _build_named_subtask_sentences(
    progress: FeatureWeeklyProgress,
    *,
    mode: str = "result",
    max_items: int = 3,
) -> list[str]:
    sentences: list[str] = []
    for item in progress.active_subtasks[:max_items]:
        parts: list[str] = []
        done_part = _limit_points(item.done_points, max_items=2, max_words_per_item=12)
        progress_part = _limit_points(item.progress_points, max_items=1, max_words_per_item=14)
        plan_part = _limit_points(item.plan_points, max_items=1, max_words_per_item=14)
        risk_part = _limit_points(item.risk_points, max_items=1, max_words_per_item=14)
        dependency_part = _limit_points(item.dependency_points, max_items=1, max_words_per_item=14)

        if mode == "plan":
            if plan_part:
                parts.append(f"Next: {plan_part}")
            elif progress_part:
                parts.append(f"Progress: {progress_part}")
            if risk_part:
                parts.append(f"Risk: {risk_part}")
            if dependency_part:
                parts.append(f"Depends on: {dependency_part}")
        else:
            if done_part:
                parts.append(f"Done: {done_part}")
            if progress_part:
                parts.append(f"Progress: {progress_part}")
            if plan_part:
                parts.append(f"Next: {plan_part}")
            if risk_part:
                parts.append(f"Risk: {risk_part}")
            if dependency_part:
                parts.append(f"Depends on: {dependency_part}")

        if not parts and item.fallback_note:
            parts.append(item.fallback_note.rstrip("."))
        if not parts:
            continue

        label = item.summary or item.issue_key or "Subtask"
        sentences.append(_ensure_terminal_punctuation(f"{label}: {'; '.join(parts)}"))

    remaining = len(progress.active_subtasks) - len(sentences)
    if remaining > 0:
        sentences.append(f"+{remaining} more subtasks updated.")
    return sentences


def build_feature_result_summary(progress: FeatureWeeklyProgress) -> str:
    sentences: list[str] = []
    lead = _build_status_lead(progress)
    if lead:
        sentences.append(lead)

    parent_sentence = _build_parent_result_sentence(progress)
    if parent_sentence:
        sentences.append(parent_sentence)

    sentences.extend(_build_named_subtask_sentences(progress, mode="result"))

    if not sentences:
        if progress.blocked_tasks > 0:
            return "Blocked."
        if progress.closed_tasks > 0:
            return "Completed."
        if progress.in_progress_tasks > 0:
            return "In progress."
        if progress.comments_count > 0 or progress.active_subtasks:
            return "Updated this week."
        return ""

    return " ".join(_ensure_terminal_punctuation(sentence) for sentence in sentences if sentence)


def build_feature_plan_summary(progress: FeatureWeeklyProgress) -> str:
    sentences: list[str] = []
    parent_sentence = _build_parent_plan_sentence(progress)
    if parent_sentence:
        sentences.append(parent_sentence)

    sentences.extend(_build_named_subtask_sentences(progress, mode="plan"))

    if not sentences:
        return ""
    return " ".join(_ensure_terminal_punctuation(sentence) for sentence in sentences if sentence)


def build_feature_aggregate_input(progress: FeatureWeeklyProgress, *, mode: str = "result") -> str:
    summary = build_feature_plan_summary(progress) if mode == "plan" else build_feature_result_summary(progress)
    prefix = "Next week:" if mode == "plan" else "Weekly progress:"
    text = f"Feature: {progress.feature_name or progress.feature_key}. {prefix} {summary or 'In progress.'}"
    words = text.split()
    if len(words) > 90:
        text = " ".join(words[:90]).rstrip(".,;:") + "."
    return text
