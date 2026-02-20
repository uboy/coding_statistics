from __future__ import annotations

from pathlib import Path


def _normalized(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    return stripped.strip("\"'")


def resolve_existing_or_default(default_rel: str, legacy_rel: str | None = None) -> Path:
    default_path = Path(default_rel)
    if default_path.exists():
        return default_path
    if legacy_rel:
        legacy_path = Path(legacy_rel)
        if legacy_path.exists():
            return legacy_path
    return default_path


def resolve_config_template_path(value: str | None = None) -> Path:
    explicit = _normalized(value)
    if explicit:
        return Path(explicit)
    return Path("configs/config.ini_template")


def resolve_report_input_path(value: str | None, default_rel: str, legacy_rel: str) -> Path:
    explicit = _normalized(value)
    if explicit:
        return Path(explicit)
    return resolve_existing_or_default(default_rel, legacy_rel)


def resolve_links_file_path(value: str | None) -> Path:
    return resolve_report_input_path(value, "report_inputs/input.txt", "input.txt")


def resolve_member_list_path(value: str | None) -> Path:
    return resolve_report_input_path(value, "report_inputs/members.xlsx", "members.xlsx")


def resolve_cache_path(value: str | None) -> Path:
    explicit = _normalized(value)
    if explicit:
        return Path(explicit)
    return resolve_existing_or_default("data/cache/cache.json", "cache.json")
