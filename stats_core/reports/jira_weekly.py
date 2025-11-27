"""
Jira weekly report – proxy to the existing implementation while the new
architecture is fleshed out.
"""

from __future__ import annotations

from configparser import ConfigParser
from pathlib import Path
from typing import Any

from jira import JIRA

from . import registry
from jira_weekly_report import (
    fetch_jira_data,
    generate_report,
)


def _parse_bool(value: str | bool | None, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return value.lower() in {"1", "true", "yes", "y", "on"}


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
        pr_stat_file = extra_params.get("pr_stat_file")

        jira_cfg = config["jira"]
        jira_url = jira_cfg.get("jira-url", jira_cfg.get("url"))
        jira_username = jira_cfg.get("username")
        jira_password = jira_cfg.get("password")
        if not (jira_url and jira_username and jira_password):
            raise ValueError("Jira credentials are not configured in config.ini [jira].")

        jira_options: dict[str, Any] = {"verify": "bundle-ca"} if Path("bundle-ca").exists() else {"verify": True}
        jira_client = JIRA(server=jira_url, basic_auth=(jira_username, jira_password), options=jira_options)

        data = fetch_jira_data(jira_client, project, start_date, end_date)
        generate_report(
            data,
            start_date,
            end_date,
            project,
            jira_url,
            include_empty,
            member_list_file,
            pr_stat_file,
        )

