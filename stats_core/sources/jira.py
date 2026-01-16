"""
Jira API adapter for fetching issues and worklogs.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from jira import JIRA
from pathlib import Path


logger = logging.getLogger(__name__)


class JiraSource:
    """Adapter for Jira API to fetch issues and worklogs."""

    def __init__(self, config_section: Any):
        """
        Initialize Jira client from config section.

        Args:
            config_section: ConfigParser section with jira-url, username, password
        """
        self.jira_url = config_section.get("jira-url", config_section.get("url", ""))
        self.username = config_section.get("username", "")
        self.password = config_section.get("password", "")
        
        if not (self.jira_url and self.username and self.password):
            raise ValueError("Jira credentials are not configured in config.ini [jira].")

        jira_options: dict[str, Any] = {"verify": "bundle-ca"} if Path("bundle-ca").exists() else {"verify": True}
        self.jira = JIRA(server=self.jira_url, basic_auth=(self.username, self.password), options=jira_options)

    def get_all_worklogs(self, issue_key: str) -> list[dict[str, Any]]:
        """
        Fetch all work logs for an issue using pagination.

        Args:
            issue_key: Jira issue key (e.g., "ABC-123")

        Returns:
            List of worklog dictionaries
        """
        worklogs = []
        start_at = 0
        while True:
            response = self.jira._session.get(
                f"{self.jira._options['server']}/rest/api/2/issue/{issue_key}/worklog",
                params={"startAt": start_at, "maxResults": 100}
            )
            response.raise_for_status()
            data = response.json()
            worklogs.extend(data.get("worklogs", []))
            if len(worklogs) >= data.get("total", 0):
                break
            start_at += 100
        return worklogs

    def get_all_comments(self, issue_key: str) -> list[dict[str, Any]]:
        """
        Fetch all comments for an issue using pagination.

        Args:
            issue_key: Jira issue key (e.g., "ABC-123")

        Returns:
            List of comment dictionaries
        """
        comments: list[dict[str, Any]] = []
        start_at = 0
        while True:
            response = self.jira._session.get(
                f"{self.jira._options['server']}/rest/api/2/issue/{issue_key}/comment",
                params={"startAt": start_at, "maxResults": 100}
            )
            response.raise_for_status()
            data = response.json()
            comments.extend(data.get("comments", []))
            if len(comments) >= data.get("total", 0):
                break
            start_at += 100
        return comments

    def fetch_issues(self, project: str, start_date: datetime, end_date: datetime) -> list[Any]:
        """
        Fetch all issues updated during the specified period with pagination.

        Args:
            project: Jira project key
            start_date: Start date for filtering
            end_date: End date for filtering

        Returns:
            List of Jira issue objects
        """
        start_at = 0
        max_results = 100
        all_issues = []

        while True:
            jql_query = (
                f"project = {project} "
                f"AND updated >= '{start_date.strftime('%Y-%m-%d')}' "
                f'AND (resolution != "Won\'t Do" OR resolution = Unresolved)'
            )
            issues = self.jira.search_issues(
                jql_query,
                startAt=start_at,
                maxResults=max_results,
                fields=[
                    "key", "summary", "assignee", "resolution", "resolutiondate", "status", "updated",
                    "customfield_10000", "parent", "issuetype", "created"
                ]
            )
            all_issues.extend(issues)
            if len(issues) < max_results:
                break
            start_at += max_results

        return all_issues

    def fetch_epic_names(self, epic_keys: list[str]) -> dict[str, str]:
        """
        Fetch epic names for given epic keys.

        Args:
            epic_keys: List of epic issue keys

        Returns:
            Dictionary mapping epic key to epic name
        """
        if not epic_keys:
            return {}
        
        # Filter out None values
        epic_keys = [k for k in epic_keys if k]
        if not epic_keys:
            return {}

        # Chunk epic keys to avoid JQL length limits
        epic_names = {}
        chunk_size = 50
        for i in range(0, len(epic_keys), chunk_size):
            chunk = epic_keys[i:i + chunk_size]
            epics = self.jira.search_issues(
                f"issuekey in ({', '.join(chunk)})",
                maxResults=1000,
                fields=["key", "summary"]
            )
            epic_names.update({epic.key: epic.fields.summary for epic in epics})
        
        return epic_names

