from jira import JIRA
from configparser import ConfigParser
import pandas as pd
from datetime import datetime
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
    parser = argparse.ArgumentParser(description="Generate JIRA monthly report with refined statuses.")
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

def fetch_jira_data(jira, project, month):
    start_date = datetime.strptime(month, "%Y-%m")
    end_date = (start_date.replace(day=28) + pd.DateOffset(days=4)).replace(day=1) - pd.DateOffset(days=1)
    start_date_str = start_date.strftime("%Y-%m-%d")
    end_date_str = end_date.strftime("%Y-%m-%d")

    jql_query = f"project = {project} AND updated >= {start_date_str} AND updated <= {end_date_str}"
    issues = jira.search_issues(jql_query, maxResults=1000, fields=["key", "assignee", "resolutiondate", "worklog"])

    data = []
    for issue in issues:
        key = issue.key
        assignee = issue.fields.assignee.displayName if issue.fields.assignee else "Unassigned"
        resolved_date = issue.fields.resolutiondate

        # Worklogs processing
        worklog_dates = set()
        if issue.fields.worklog and issue.fields.worklog.worklogs:
            for log in issue.fields.worklog.worklogs:
                log_date = datetime.strptime(log.started.split("T")[0], "%Y-%m-%d")
                worklog_dates.add(log_date)

        # Add resolved task status
        if resolved_date:
            resolved_week = datetime.strptime(resolved_date.split("T")[0], "%Y-%m-%d")
            data.append({
                "Issue key": key,
                "Assignee": assignee,
                "Status": "Resolved",
                "Date": resolved_week
            })
        else:
            # Add in-progress status only if the task was not resolved
            for log_date in worklog_dates:
                data.append({
                    "Issue key": key,
                    "Assignee": assignee,
                    "Status": "In progress",
                    "Date": log_date
                })

    return pd.DataFrame(data)

def generate_report(data, month, project):
    start_date = datetime.strptime(month, "%Y-%m")
    end_date = (start_date.replace(day=28) + pd.DateOffset(days=4)).replace(day=1) - pd.DateOffset(days=1)

    # Filter data to include only weeks within the specified month
    data = data[(data["Date"] >= start_date) & (data["Date"] <= end_date)]

    # Add week column
    data["Week"] = data["Date"].dt.strftime("%Y-W%U")
    data["Assignee"] = data["Assignee"].fillna("Unassigned")

    # Keep only unique statuses per task per week
    data = data.drop_duplicates(subset=["Issue key", "Week"])

    # Group by Assignee and Week
    grouped_data = data.groupby(["Assignee", "Week"]).apply(
        lambda x: "\n".join(f"{row['Status']}: {row['Issue key']}" for _, row in x.iterrows())
    ).unstack(fill_value="")

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
