from jira import JIRA
from configparser import ConfigParser
import pandas as pd
from datetime import datetime, timedelta
import argparse
import codecs
import os

# Configuration constants
CONFIG_FILE = "config.ini"
CONFIG_SECTION = "jira"
CONFIG_URL = "jira-url"
CONFIG_USERNAME = "username"
CONFIG_PASSWORD = "password"

def parse_arguments_and_config():
    parser = argparse.ArgumentParser(description="Generate JIRA monthly report with extended filtering.")
    parser.add_argument("-c", "--config", default=CONFIG_FILE, help="Path to config file.")
    parser.add_argument("-u", "--username", help="JIRA username.")
    parser.add_argument("-p", "--password", help="JIRA password.")
    parser.add_argument("-l", "--url", help="JIRA base URL.")
    parser.add_argument("-proj", "--project", required=True, help="JIRA project key.")
    parser.add_argument("-m", "--month", required=True, help="Month in YYYY-MM format (e.g., 2024-11).")
    args = parser.parse_args()

    config = ConfigParser(allow_no_value=False, comment_prefixes=('#', ';'), inline_comment_prefixes='#')
    config.read_file(codecs.open(args.config, 'r', encoding='utf-8-sig'))

    jira_url = args.url or config.get(CONFIG_SECTION, CONFIG_URL, fallback=None)
    jira_username = args.username or config.get(CONFIG_SECTION, CONFIG_USERNAME, fallback=None)
    jira_password = args.password or config.get(CONFIG_SECTION, CONFIG_PASSWORD, fallback=None)

    if not jira_url or not jira_username or not jira_password:
        raise ValueError("JIRA URL, username, and password must be specified either as arguments or in the config file.")

    return jira_url, jira_username, jira_password, args.project, args.month

def get_all_worklogs(jira, issue_key):
    """Fetch all work logs for an issue using pagination."""
    worklogs = []
    start_at = 0
    while True:
        response = jira._session.get(
            f"{jira._options['server']}/rest/api/2/issue/{issue_key}/worklog",
            params={"startAt": start_at, "maxResults": 100}
        )
        response.raise_for_status()
        data = response.json()
        worklogs.extend(data.get("worklogs", []))
        if len(worklogs) >= data.get("total", 0):
            break
        start_at += 100
    return worklogs

def fetch_jira_data(jira, project, month):
    # Determine the first and last day of the specified month
    start_date = datetime.strptime(month, "%Y-%m")
    end_date = (start_date.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    start_date_str = start_date.strftime("%Y-%m-%d")
    end_date_str = end_date.strftime("%Y-%m-%d")

    # JQL query for fetching issues (tasks and subtasks)
    jql_query = f"project = {project}"  # No date filter to include all relevant tasks
    issues = jira.search_issues(jql_query, maxResults=1000, fields=["key", "assignee", "resolutiondate", "updated"])

    data = []
    for issue in issues:
        key = issue.key
        assignee = issue.fields.assignee.displayName if issue.fields.assignee else "Unassigned"
        resolved_date = issue.fields.resolutiondate

        # Fetch all work logs for the issue
        worklogs = get_all_worklogs(jira, key)
        worklog_dates = set()
        for log in worklogs:
            try:
                log_date = datetime.strptime(log["started"].split("T")[0], "%Y-%m-%d")
                if start_date <= log_date <= end_date:
                    worklog_dates.add(log_date)
            except Exception:
                continue

        # Determine resolved week
        resolved_week = None
        if resolved_date:
            resolved_date_dt = datetime.strptime(resolved_date.split("T")[0], "%Y-%m-%d")
            if start_date <= resolved_date_dt <= end_date:
                resolved_week = resolved_date_dt.strftime("%G-W%V")
                data.append({
                    "Issue key": key,
                    "Assignee": assignee,
                    "Status": "Resolved",
                    "Week": resolved_week
                })

        # Add "In progress" for unique weeks, excluding resolved week
        for log_date in worklog_dates:
            log_week = log_date.strftime("%G-W%V")
            if log_week != resolved_week:
                if not any(d["Issue key"] == key and d["Week"] == log_week for d in data):
                    data.append({
                        "Issue key": key,
                        "Assignee": assignee,
                        "Status": "In progress",
                        "Week": log_week
                    })

    return pd.DataFrame(data)

def generate_week_headers(valid_weeks):
    """Generate headers with week ranges for the report."""
    headers = []
    for week in valid_weeks:
        year, week_num = map(int, week.split("-W"))
        week_start = pd.Timestamp.fromisocalendar(year, week_num, 1)  # Start of the week (Monday)
        week_end = week_start + timedelta(days=6)  # End of the week (Sunday)
        headers.append(f"{week}({week_start.strftime('%d/%m')}-{week_end.strftime('%d/%m')})")
    return headers

def generate_report(data, month, project):
    # Ensure only data within the specified month or overlapping weeks
    start_date = datetime.strptime(month, "%Y-%m")
    end_date = (start_date.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)

    # Include weeks overlapping with the month
    valid_weeks = pd.date_range(start=start_date - timedelta(days=7), end=end_date, freq='W-MON').strftime("%G-W%V").tolist()

    # Filter data to include only relevant weeks
    data = data[data["Week"].isin(valid_weeks)]

    # Generate headers with week ranges
    headers = generate_week_headers(valid_weeks)

    # Group by Assignee and Week
    grouped_data = data.groupby(["Assignee", "Week"]).apply(
        lambda x: "\n".join(f"{row['Status']}: {row['Issue key']}" for _, row in x.iterrows())
    ).unstack(fill_value="")

    # Rename columns to include week ranges
    grouped_data.columns = headers

    # Save to Excel
    output_file = f"jira_report_{project}_{month}.xlsx"
    grouped_data.to_excel(output_file)
    print(f"Report successfully created: {output_file}")

def main():
    jira_url, jira_username, jira_password, project, month = parse_arguments_and_config()

    # Add options for JIRA connection if bundle-ca file exists
    jira_options = {"verify": "bundle-ca"} if os.path.exists("bundle-ca") else {}
    jira = JIRA(server=jira_url, basic_auth=(jira_username, jira_password), options=jira_options)

    # Fetch data
    data = fetch_jira_data(jira, project, month)

    # Generate and save report
    generate_report(data, month, project)

if __name__ == "__main__":
    main()
